"""Benchmark: Relay (graph) vs vector baselines, plus ablations, component metrics and external checks.

python -m eval.run_eval --tenant pml [--phases main,components,ood,locomo,ksweep,variance,ablations]
python -m eval.run_eval --report      # rebuild results.md from results.json

Fairness: for each question every system uses the same answer model and prompt; questions alternate between
two models (per-model breakdown reported). Resumable: answers are cached on disk and finished rows are skipped.
Do not reload the tenant between runs: new fact ids change the prompts and miss the cache.
"""
import argparse
import json
import math
import os
import re
import statistics
import time
from pathlib import Path

import numpy as np

from relay import db, embed, llm, retrieve
from relay.memory import norm, to_date

HERE = Path(__file__).parent
DATA = HERE.parent / "data"
RESULTS = HERE / "results.json"
# Answer models, alternating by question index. Override: RELAY_EVAL_MODELS="a,b" (keeps per-question fairness).
MODELS = [m.strip() for m in os.environ.get("RELAY_EVAL_MODELS", "openai/gpt-oss-120b,qwen/qwen3.8-27b").split(",")]

SYSTEMS = {  # name: (kind, setting, k, description)
    "FULL": ("relay", "full", None, "Relay: graph expansion + two clocks + conflict ranking"),
    "B1": ("vector", True, 10, "Vector store: customer-filtered, top-10, dated, newest first"),
    "B1_k20": ("vector", True, 20, "B1 with top-20"),
    "B1_k50": ("vector", True, 50, "B1 with top-50"),
    "A1": ("relay", "no_temporal", None, "Relay without the two clocks (history unlabelled)"),
    "A2": ("relay", "no_hops", None, "Relay without multi-hop expansion"),
    "B0": ("vector", False, 10, "B1 without dates or recency ordering"),
}
PHASE_SYSTEMS = {"main": ["FULL", "B1"], "ksweep": ["B1_k20", "B1_k50"], "ablations": ["A1", "A2", "B0"]}


class QuotaExhausted(Exception):
    pass


# ---------------------------------------------------------------- statistics

def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def abstention(rows):
    """Positive class = 'should refuse'. Hallucination = should refuse but answered."""
    pred = [bool(r["unknown"] or not [v for v in r["values"] if norm(v)]) for r in rows]
    exp = [r["expect_unknown"] for r in rows]
    tp = sum(p and e for p, e in zip(pred, exp))
    fp = sum(p and not e for p, e in zip(pred, exp))
    fn = sum(e and not p for p, e in zip(pred, exp))
    return {"precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "hallucinations": fn, "false_refusals": fp, "should_refuse": tp + fn}


def pairwise_resolution(mentions):
    """mentions: [(gold_cluster, predicted_entity)]. Precision/recall over mention pairs merged into one entity."""
    tp = fp = fn = 0
    for i in range(len(mentions)):
        for j in range(i + 1, len(mentions)):
            same_gold, same_pred = mentions[i][0] == mentions[j][0], mentions[i][1] == mentions[j][1]
            tp += same_gold and same_pred
            fp += same_pred and not same_gold
            fn += same_gold and not same_pred
    return {"precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None, "pairs_merged": tp + fp, "gold_pairs": tp + fn}


# ---------------------------------------------------------------- systems

class VectorStore:
    """The standard baseline: every episode the agents wrote, embedded, with a customer metadata filter."""

    def __init__(self, tenant, customers):
        rows = db.run(tenant, "episodes", "MATCH (ep:Episode) RETURN ep.episode_id, ep.text, ep.recorded_at, ep.customer",
                      ro=True)
        self.ids, self.texts, self.at, self.cust = (list(x) for x in zip(*rows)) if rows else ([], [], [], [])
        m = np.array(embed.embed(self.texts)) if self.texts else np.zeros((0, 1))
        self.m = m / np.linalg.norm(m, axis=1, keepdims=True) if len(m) else m
        firsts = {}
        for c in customers:
            firsts.setdefault(c.split()[0], []).append(c)
        self.names = {c: c for c in customers} | {f: cs[0] for f, cs in firsts.items() if len(cs) == 1}

    def customer_in(self, question):
        q = " " + " ".join(re.sub(r"[^a-z0-9\- ]", " ", question.lower()).split()) + " "
        hits = [c for n, c in sorted(self.names.items(), key=lambda x: -len(x[0])) if f" {n} " in q]
        return hits[0] if hits else None

    def lines(self, question, dated, k=10):
        c = self.customer_in(question)
        idx = [i for i, cu in enumerate(self.cust) if c is None or cu == c]
        if not idx:  # an empty graph, or nothing about that customer: nothing to retrieve
            return []
        qv = np.array(embed.embed_one(question))
        sims = self.m[idx] @ (qv / np.linalg.norm(qv))
        top = [idx[j] for j in np.argsort(-sims)[:k]]
        if dated:
            top.sort(key=lambda i: self.at[i], reverse=True)
            return [f"[{self.ids[i]}] {to_date(self.at[i])} | {self.texts[i]}" for i in top]
        return [f"[{self.ids[i]}] {self.texts[i]}" for i in top]


def _match(pred, gold):
    p, g = norm(pred), norm(gold)
    return bool(p) and (p == g or g in p or (len(p) >= 3 and p in g))


def score(q, a):
    if a.get("error"):
        return False
    vals = [v for v in a["values"] if norm(v)]
    if q["expect_unknown"]:
        return bool(a["unknown"] or not vals)
    if a["unknown"] or not vals:
        return False
    if q["expect_conflict"]:
        return bool(a["conflict"]) and _match(vals[0], q["gold"][0])
    return (all(any(_match(v, g) for v in vals) for g in q["gold"])
            and all(any(_match(v, g) for g in q["gold"]) for v in vals))


def evidence(q, lines):
    ctx = " ".join(lines).lower()
    return None if q["expect_unknown"] else all(g in ctx for g in q["gold"])


FAILED = {"answer": "", "values": [], "cited_ids": [], "conflict": False, "unknown": False, "error": True}


def _is_daily(msg):
    msg = msg.lower()
    return "per day" in msg or "(tpd)" in msg or "(rpd)" in msg


def answer(question, lines, model, cache=True):
    """Pinned-model answer with backoff. cache=False re-asks the model (determinism check)."""
    import groq
    import httpx
    bad = 0
    for _ in range(30):
        try:
            if cache:
                return llm.answer(question, lines, model=model)
            user = "Memory:\n" + ("\n".join(lines) if lines else "(empty)") + f"\n\nQuestion: {question}"
            return json.loads(llm._call(model, [{"role": "system", "content": llm.ANSWER_SYSTEM},
                                                {"role": "user", "content": user}], llm.ANSWER_SCHEMA, "answer"))
        except (groq.BadRequestError, httpx.HTTPStatusError, json.JSONDecodeError, llm.SchemaFailure):
            bad += 1  # strict decoding failure / rejected request: counted as a wrong answer
            if bad == 3:
                return FAILED
        except (groq.RateLimitError, llm.Unavailable) as e:
            if _is_daily(str(e)):
                raise QuotaExhausted(f"{model}: {str(e)[:160]}") from e
            time.sleep(20)
    raise QuotaExhausted(f"{model}: rate limited for too long")


def model_for(q):
    return MODELS[q["i"] % len(MODELS)]


def round_robin(questions):
    """Stratified order: one question of each type in turn. Prefixes of it are stratified subsets."""
    by = {}
    for q in questions:
        by.setdefault(q["type"], []).append(q)
    out, k = [], 0
    while any(k < len(v) for v in by.values()):
        out += [v[k] for t, v in sorted(by.items()) if k < len(v)]
        k += 1
    return out


def context(name, q, tenant, store):
    kind, setting, k, _ = SYSTEMS[name]
    t = time.perf_counter()
    gate = False
    if kind == "relay":
        r = retrieve.recall(tenant, q["question"], mode=setting)
        lines, known = r["lines"], {f["fact_id"] for f in r["facts"]}
        # the same pre-model abstention as retrieve.ask (the product's answer path): an unknown name, or a question
        # whose relation isn't on file for the subject it names, is refused without asking the model
        gate = bool(r["unknown"] and not r["facts"]) or bool(retrieve.ungrounded(q["question"], r))
    else:
        lines = store.lines(q["question"], setting, k)
        known = {ln[1:ln.index("]")] for ln in lines}
    return lines, known, (time.perf_counter() - t) * 1000, gate


def run_system(name, questions, tenant, store, results, exhausted):
    sysres = results["systems"].setdefault(name, {"rows": []})
    run_id = results.setdefault("run_id", time.strftime("run-%Y%m%d-%H%M%S"))  # one id per results file / run
    done = {r["i"] for r in sysres["rows"]}
    pending = []
    for q in questions:
        if q["i"] in done:
            continue
        m = model_for(q)
        if m in exhausted:
            pending.append(q["i"])
            continue
        lines, known, ms, gate = context(name, q, tenant, store)
        try:
            a = {"answer": "unknown", "values": [], "cited_ids": [], "conflict": False, "unknown": True} if gate                 else answer(q["question"], lines, m)
        except QuotaExhausted as e:
            print(f"quota: {e}")
            exhausted.add(m)
            pending.append(q["i"])
            continue
        sysres["rows"].append({
            "i": q["i"], "question_id": f"q{q['i']:03}", "system_name": name, "run_id": run_id, "type": q["type"], "question": q["question"], "gold": q["gold"], "model": m,
            "expect_unknown": q["expect_unknown"], "collision": q.get("collision", False),
            "values": a["values"], "conflict": a["conflict"], "unknown": a["unknown"], "answer": a["answer"],
            "cited_ids": [c for c in a["cited_ids"] if c in known], "correct": score(q, a),
            "error": bool(a.get("error")), "evidence": evidence(q, lines), "retrieval_ms": round(ms, 1),
            "context_lines": len(lines)})
        r = sysres["rows"][-1]
        print(f"{name:6} q{q['i']:03} {'OK ' if r['correct'] else 'BAD'} {q['type']:12} {m[:12]:12} "
              f"{q['question'][:50]:50} -> {a['values']}", flush=True)
        if len(sysres["rows"]) % 10 == 0:
            save(results)
    sysres["rows"].sort(key=lambda r: r["i"])
    sysres["n_target"] = len(questions)
    sysres["pending"] = pending
    sysres["summary"] = summarize(sysres["rows"])
    save(results)


def run_variance(questions, tenant, results, exhausted, runs=3):
    var = results.setdefault("variance", {"system": "FULL", "runs": [[] for _ in range(runs)]})
    for run in range(runs):
        done = {r["i"] for r in var["runs"][run]}
        for q in questions:
            m = model_for(q)
            if q["i"] in done or m in exhausted:
                continue
            lines, _, _, _ = context("FULL", q, tenant, None)
            try:
                a = answer(q["question"], lines, m, cache=False)
            except QuotaExhausted as e:
                print(f"quota: {e}")
                exhausted.add(m)
                continue
            var["runs"][run].append({"i": q["i"], "question_id": f"q{q['i']:03}", "run_id": f"variance-{run}",
                                     "model": m, "correct": score(q, a), "values": a["values"]})
            print(f"variance run{run} q{q['i']:03} {'OK ' if var['runs'][run][-1]['correct'] else 'BAD'}", flush=True)
        save(results)
    common = set.intersection(*[{r["i"] for r in run} for run in var["runs"]]) if all(var["runs"]) else set()
    accs = [sum(r["correct"] for r in run if r["i"] in common) / len(common) for run in var["runs"]] if common else []
    flips = sum(len({tuple(sorted(norm(v) for v in r["values"])) for run in var["runs"] for r in run if r["i"] == i}) > 1
                for i in common)
    var["summary"] = {"n": len(common), "accuracy_per_run": [round(a, 4) for a in accs],
                      "stdev": round(statistics.pstdev(accs), 4) if accs else None,
                      "questions_with_changed_answer": flips, "target_n": len(questions)}
    save(results)


# ---------------------------------------------------------------- summaries

def agg(rs):
    k, n = sum(r["correct"] for r in rs), len(rs)
    ev = [r["evidence"] for r in rs if r["evidence"] is not None]
    return {"n": n, "accuracy": round(k / n, 4) if n else None, "ci95": wilson(k, n),
            "evidence_recall": round(sum(ev) / len(ev), 4) if ev else None}


def summarize(rows):
    lat = sorted(r["retrieval_ms"] for r in rows)
    return {"overall": agg(rows),
            "by_type": {t: agg([r for r in rows if r["type"] == t]) for t in sorted({r["type"] for r in rows})},
            "by_model": {m: agg([r for r in rows if r["model"] == m]) for m in sorted({r["model"] for r in rows})},
            "collision_questions": agg([r for r in rows if r.get("collision")]),
            "abstention": abstention(rows),
            "retrieval_ms": {"p50": round(statistics.median(lat), 1),
                             "p95": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)} if lat else None,
            "avg_context_lines": round(sum(r["context_lines"] for r in rows) / len(rows), 1) if rows else None}


def common_acc(results, a, b, subset=None):
    ra = {r["i"]: r["correct"] for r in results["systems"].get(a, {}).get("rows", [])}
    rb = {r["i"]: r["correct"] for r in results["systems"].get(b, {}).get("rows", [])}
    ids = sorted(set(ra) & set(rb) & (subset if subset is not None else set(ra)))
    return ids, ra, rb


def pct(x):
    return "-" if x is None else f"{x:.0%}"


def ci(a):
    return f"{pct(a['accuracy'])} [{pct(a['ci95'][0])}–{pct(a['ci95'][1])}]" if a and a["n"] else "-"


def write_md(results):
    S = results["systems"]
    # the models the run actually used, from results.json, so the report is the same on any machine (MODELS comes
    # from this machine's keys and routes); natural order, groq6 before groq10
    natural = lambda m: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", m)]
    models = sorted({m for s in S.values() for m in (s.get("summary") or {}).get("by_model", {})}, key=natural) or MODELS
    out = ["# Relay benchmark", "",
           f"Tenant `{results.get('tenant')}`: {results.get('dataset', '')}. Answer models alternate per question "
           f"({', '.join(f'`{m}`' for m in models)}); for each question every system uses the same model and prompt. "
           "Intervals are 95% Wilson.", ""]
    if "FULL" in S and "B1" in S:
        ids, rf, rb = common_acc(results, "FULL", "B1")
        kf, kb, n = sum(rf[i] for i in ids), sum(rb[i] for i in ids), len(ids)
        out += ["## Headline", "",
                f"On the {n} questions both systems answered: **Relay {kf / n:.0%}** [{pct(wilson(kf, n)[0])}–{pct(wilson(kf, n)[1])}] "
                f"vs **vector baseline (B1) {kb / n:.0%}** [{pct(wilson(kb, n)[0])}–{pct(wilson(kb, n)[1])}].", ""] if n else []
        out += ["## Gap decomposition by question type (directional: ~16–18 questions per type, wide intervals)", "",
                "| Type | n | Relay | B1 vector | Δ |", "|---|---|---|---|---|"]
        for t in sorted({r["type"] for r in S["FULL"]["rows"]}):
            tid = [i for i in ids if any(r["i"] == i and r["type"] == t for r in S["FULL"]["rows"])]
            if not tid:
                continue
            a = agg([{"correct": rf[i], "evidence": None} for i in tid])
            b = agg([{"correct": rb[i], "evidence": None} for i in tid])
            out.append(f"| {t} | {len(tid)} | {ci(a)} | {ci(b)} | {(a['accuracy'] - b['accuracy']) * 100:+.0f} pts |")
        out += ["", "Simple recall (`current`, `handoff`) is where a good vector store should stay competitive; "
                "the gap should come from updates over time, disagreement, multi-hop and abstention.", ""]
    out += ["## All systems", "", "| System | What it is | Questions | Accuracy [95% CI] | Evidence recall | Retrieval p50 / p95 ms |",
            "|---|---|---|---|---|---|"]
    for s, (_, _, _, desc) in SYSTEMS.items():
        if s in S and S[s].get("summary") and S[s]["summary"].get("retrieval_ms"):  # a system with no answered rows yet has none
            sm = S[s]["summary"]
            out.append(f"| {s} | {desc} | {sm['overall']['n']}/{S[s].get('n_target', '?')} | {ci(sm['overall'])} | "
                       f"{pct(sm['overall']['evidence_recall'])} | {sm['retrieval_ms']['p50']} / {sm['retrieval_ms']['p95']} |")
    sub = set(results.get("subset", []))
    if sub and any(s in S for s in ["B1_k20", "B1_k50"]):
        out += ["", "## Baseline k-sensitivity (stratified subset)", "", "| System | n | Accuracy [95% CI] |", "|---|---|---|"]
        for s in ["B1", "B1_k20", "B1_k50", "FULL"]:
            rows = [r for r in S.get(s, {}).get("rows", []) if r["i"] in sub]
            if rows:
                out.append(f"| {s} | {len(rows)} | {ci(agg(rows))} |")
    if sub and any(s in S for s in ["A1", "A2", "B0"]):
        out += ["", "## Ablations (stratified subset)", "", "| System | n | Accuracy [95% CI] |", "|---|---|---|"]
        for s in ["FULL", "A1", "A2", "B1", "B0"]:
            rows = [r for r in S.get(s, {}).get("rows", []) if r["i"] in sub]
            if rows:
                out.append(f"| {s} | {len(rows)} | {ci(agg(rows))} |")
    out += ["", "## Abstention (should-refuse questions)", "",
            "| System | Precision | Recall | Hallucinated answers | False refusals |", "|---|---|---|---|---|"]
    for s in S:
        ab = S[s].get("summary", {}).get("abstention")
        if ab and ab["should_refuse"]:
            out.append(f"| {s} | {pct(ab['precision'])} | {pct(ab['recall'])} | {ab['hallucinations']} | {ab['false_refusals']} |")
    out += ["", "## Per answer model", "", "| System | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for s in S:
        bm = S[s].get("summary", {}).get("by_model", {})
        if bm:
            out.append(f"| {s} | " + " | ".join(ci(bm.get(m)) if bm.get(m) else "-" for m in models) + " |")
    comp = results.get("components")
    if comp:
        ex, pn, er, ch = comp["extraction"], comp["predicate_normalization"], comp["entity_resolution"], comp["contradiction"]
        out += ["", "## Component metrics (no LLM; measured on the loaded graph)", "",
                f"- **Extraction recall** (in-distribution templates): {ex['recovered']}/{ex['planted']} planted facts = {pct(ex['recall'])}.",
                f"- **Predicate normalization**: of extracted facts whose object matches a planted value, "
                f"{pct(pn['accuracy'])} carry the planted predicate ({pn['correct']}/{pn['n']}). Extraction is constrained to a "
                "fixed predicate enum at write time (strict JSON schema), so paraphrases cannot create new predicates.",
                f"- **Entity resolution, issue aliases** (pairs of mentions of the same problem merged into one entity): "
                f"precision {pct(er['issue_aliases']['precision'])}, recall {pct(er['issue_aliases']['recall'])} "
                f"({er['issue_aliases']['gold_pairs']} gold pairs).",
                f"- **Typos** normalised to the existing entity: {er['typos']['ok']}/{er['typos']['n']}.",
                f"- **Name collisions** kept apart (e.g. alice rao / alice roy, each with only their own facts): "
                f"{er['collisions']['kept_apart']}/{er['collisions']['n']} pairs.", "",
                "| Contradiction case | What must happen | Correct | Excluding extraction misses |", "|---|---|---|---|"]
        what = {"change": "old value retired, new one current", "unchanged": "re-statement corroborates, no new fact",
                "multi": "new item added, earlier items stay", "cross_agent": "both agents' claims stay current"}
        for case, v in ch.items():
            out.append(f"| {case} | {what.get(case, '')} | {v['correct']}/{v['n']} ({pct(v['accuracy'])}) | "
                       f"{v['correct']}/{v['n'] - v['extraction_miss']} |")
    ood = results.get("ood")
    if ood:
        out += ["", "## Out-of-distribution extraction", "",
                f"Customer messages written by a different model ({ood['writer']}) in its own style, for {ood['n']} planted "
                f"facts. Extraction recall: **{pct(ood['recall'])}** [{pct(ood['ci95'][0])}–{pct(ood['ci95'][1])}]; "
                f"predicate accuracy where the value was found: {pct(ood['predicate_accuracy'])}. "
                f"In-distribution recall for comparison: {pct(comp['extraction']['recall']) if comp else '-'}."]
    loc = results.get("locomo")
    if loc:
        out += ["", "## External check: LoCoMo", "",
                f"Conversation `{loc['conversation']}` ({loc['turns']} turns from {loc['sessions']} sessions), "
                f"{loc['n']} of its own questions whose evidence lies in the ingested sessions. "
                f"Relay used a general personal-life predicate registry. Metric: token F1 (LoCoMo's standard) and "
                f"refusal accuracy on adversarial questions. License: {loc['license']}.", "",
                "| System | n | Mean F1 | F1 ≥ 0.5 | Adversarial refused |", "|---|---|---|---|---|"]
        for s, v in loc["systems"].items():
            out.append(f"| {s} | {v['n']} | {v['f1']:.2f} | {pct(v['f1_ge_half'])} | {v['adversarial_refused']} |")
        out += ["", "Noisy by construction (one conversation, extraction tuned on support chats); reported as the one "
                "datapoint not built on our own data."]
    var = results.get("variance", {}).get("summary")
    if var and var["n"]:
        out += ["", "## Determinism", "",
                f"Answers run at temperature 0. {var['n']} questions re-asked {len(var['accuracy_per_run'])}× with the cache "
                f"bypassed: accuracy per run {', '.join(pct(a) for a in var['accuracy_per_run'])} "
                f"(stdev {var['stdev'] * 100:.1f} pts); {var['questions_with_changed_answer']} questions changed answer across runs."]
    pend = {s: len(v.get("pending", [])) for s, v in S.items() if v.get("pending")}
    if pend or results.get("todo"):
        out += ["", "## Still queued (daily LLM quota)", ""] + [f"- {s}: {n} questions" for s, n in pend.items()] \
            + [f"- {t}" for t in results.get("todo", [])] + ["", f"Resume: `{results.get('resume')}`"]
    (HERE / "results.md").write_text("\n".join(out) + "\n", encoding="utf-8")


def save(results):
    RESULTS.write_text(json.dumps(results, indent=1))
    write_md(results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="pml-bench")  # kept apart from the demo tenant 'pml'; protected in the API
    ap.add_argument("--phases", default="main,components,ood,locomo,ksweep,variance,ablations")
    ap.add_argument("--report", action="store_true", help="only rebuild results.md from results.json")
    args = ap.parse_args()
    if args.report:
        write_md(json.loads(RESULTS.read_text()))
        return print((HERE / "results.md").read_text(encoding="utf-8"))
    questions = json.loads((DATA / "questions.json").read_text())
    scenario = json.loads((DATA / "scenario.json").read_text())
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    if results.get("tenant") != args.tenant:
        results = {"systems": {}}  # results from another dataset/tenant are not comparable
    rr = round_robin(questions)
    turns = sum(e["type"] == "turn" for e in scenario["events"])
    results |= {"tenant": args.tenant, "subset": [q["i"] for q in rr[:63]], "todo": [],
                "dataset": f"{len(scenario['customers'])} customers, {turns} customer turns, {len(questions)} questions",
                "resume": f"python -m eval.run_eval --tenant {args.tenant} --phases {args.phases}"}
    subset = [q for q in questions if q["i"] in set(results["subset"])]
    store, exhausted = None, set()
    for phase in args.phases.split(","):
        print(f"=== phase {phase}", flush=True)
        if phase in PHASE_SYSTEMS:
            for name in PHASE_SYSTEMS[phase]:
                if SYSTEMS[name][0] == "vector" and store is None:
                    store = VectorStore(args.tenant, scenario["customers"])
                run_system(name, questions if phase == "main" else subset, args.tenant, store, results, exhausted)
        elif phase == "components":
            from eval import components
            results["components"] = components.measure(args.tenant)
        elif phase == "ood":
            from eval import ood
            results["ood"] = ood.measure() or results.get("ood")
            if not results["ood"] or results["ood"].get("partial"):
                results["todo"].append("out-of-distribution extraction (partial)")
        elif phase == "locomo":
            from eval import locomo
            loc = locomo.measure(exhausted)
            results["locomo"] = loc
            if loc.get("partial"):
                results["todo"].append("LoCoMo (partial)")
        elif phase == "variance":
            run_variance(round_robin(questions)[:40], args.tenant, results, exhausted)
            if results["variance"]["summary"]["n"] < 40:
                results["todo"].append("determinism re-runs (partial)")
        save(results)
    print((HERE / "results.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
