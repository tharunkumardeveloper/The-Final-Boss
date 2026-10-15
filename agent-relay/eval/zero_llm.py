"""Zero-LLM metrics: everything scored from saved data and read-only graph queries, no model calls.

python -m eval.zero_llm [--report eval/load_report_bench.json] [--graph pml-bench] [--results eval/results.json]
-> eval/components.json + eval/components.md

- extraction / predicate normalisation / issue-alias resolution / typos: from a load report (per-turn extracted triples)
- name collisions / contradiction handling: read-only history queries on the loaded benchmark graph (--graph)
- benchmark: paired bootstrap CI and exact McNemar for Relay vs B1, abstention P/R, gap decomposition of misses
"""
import argparse
import json
import math
import random
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from eval.run_eval import wilson

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def git_state():
    import os
    if os.environ.get("RELAY_EVAL_PROVENANCE"):  # running from a clean snapshot outside the repo
        return {"snapshot": os.environ["RELAY_EVAL_PROVENANCE"]}
    run = lambda *a: subprocess.run(["git", *a], cwd=HERE.parent, capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "relay_retrieve_dirty": bool(run("status", "--short", "relay/retrieve.py")),
            "relay_dirty": run("status", "--short", "relay/").splitlines()}


# ---------------------------------------------------------------- from a load report (no graph, no LLM)

def offline(report_path):
    events = json.loads((DATA / "scenario.json").read_text())["events"]
    rep = json.loads(Path(report_path).read_text())
    assert len(rep["events"]) == len(events), "report does not match scenario.json"
    turns = [(e, r) for e, r in zip(events, rep["events"]) if e["type"] == "turn"]
    planted = sum(len(r["expect"]) for _, r in turns)
    missed = Counter(p for _, r in turns for p, _ in r["missed"])
    by_pred = Counter(p for _, r in turns for p, _ in r["expect"])
    out = {"extraction_recall": rate(planted - sum(missed.values()), planted),
           "extraction_misses_by_predicate": {p: f"{missed[p]}/{by_pred[p]}" for p in sorted(missed, key=lambda p: -missed[p])},
           "extra_facts": rep["summary"]["extra_facts"], "load_errors": len(rep["summary"]["errors"])}
    # the rest reuses components.measure's offline parts by running it with history stubbed out
    return out


def components(report_path, graph):
    """components.measure on a copy of the data dir holding this report. graph=None: no graph parts."""
    from eval import components as C
    from relay import retrieve
    tmp = Path(tempfile.mkdtemp())
    for f in ("scenario.json", "gold.json"):
        shutil.copy(DATA / f, tmp / f)
    shutil.copy(report_path, tmp / "load_report.json")
    C.DATA, hist = tmp, retrieve.history
    if graph is None:
        retrieve.history = lambda tenant, c: []
    try:
        m = C.measure(graph or "none")
    finally:
        retrieve.history = hist
    pn = m["predicate_normalization"]
    m["predicate_normalization"] |= {"ci95": wilson(pn["correct"], pn["n"])}
    if graph is None:
        m.pop("contradiction")
        m["entity_resolution"].pop("collisions")
    else:
        col = m["entity_resolution"]["collisions"]
        col["ci95"] = wilson(col["kept_apart"], col["n"])
        for v in m["contradiction"].values():
            v["ci95"] = wilson(v["correct"], v["n"])
        tot = m["contradiction"]
        k, n = sum(v["correct"] for v in tot.values()), sum(v["n"] for v in tot.values())
        miss = sum(v["extraction_miss"] for v in tot.values())
        m["contradiction_overall"] = {**rate(k, n), "excluding_extraction_misses": rate(k, n - miss)}
    return m


# ---------------------------------------------------------------- benchmark rows (no LLM)

def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired(rf, rb, ids, iters=10000, seed=0):
    rnd = random.Random(seed)
    diffs = []
    for _ in range(iters):
        s = [rnd.choice(ids) for _ in ids]
        diffs.append(sum(rf[i] - rb[i] for i in s) / len(s))
    diffs.sort()
    b = sum(rf[i] and not rb[i] for i in ids)
    c = sum(rb[i] and not rf[i] for i in ids)
    return {"n": len(ids), "relay": rate(sum(rf[i] for i in ids), len(ids)), "b1": rate(sum(rb[i] for i in ids), len(ids)),
            "diff": round(sum(rf[i] - rb[i] for i in ids) / len(ids), 4),
            "diff_ci95_bootstrap": [round(diffs[int(iters * .025)], 4), round(diffs[int(iters * .975)], 4)],
            "relay_only_correct": b, "b1_only_correct": c, "mcnemar_exact_p": mcnemar_exact(b, c)}


def why(r):
    """Why one answer is wrong."""
    if r["error"]:
        return "model error (schema/request failure)"
    vals = [v for v in r["values"] if v.strip()]
    if r["expect_unknown"]:
        return "answered a should-refuse question (hallucination)"
    if r["evidence"] is False:
        return "retrieval: gold value not in context" + (" -> refused" if r["unknown"] or not vals else " -> wrong answer")
    if r["unknown"] or not vals:
        return "gold in context but model refused"
    if r["type"] == "disagreement" and not r["conflict"]:
        return "gold in context, conflict not flagged"
    return "gold in context, wrong/incomplete value chosen"


def bench(results_path):
    res = json.loads(Path(results_path).read_text())
    S = res.get("systems", {})
    out = {"tenant": res.get("tenant"), "dataset": res.get("dataset"), "run_id": res.get("run_id"),
           "provenance": res.get("provenance"), "systems": {}}
    for s, v in S.items():
        rows = v["rows"]
        if not rows:
            continue
        ab = [r for r in rows]
        pred = [bool(r["unknown"] or not [x for x in r["values"] if x.strip()]) for r in ab]
        exp = [r["expect_unknown"] for r in ab]
        tp = sum(p and e for p, e in zip(pred, exp))
        fp = sum(p and not e for p, e in zip(pred, exp))
        fn = sum(e and not p for p, e in zip(pred, exp))
        out["systems"][s] = {
            "accuracy": rate(sum(r["correct"] for r in rows), len(rows)),
            "abstention": {"precision": rate(tp, tp + fp), "recall": rate(tp, tp + fn), "should_refuse": tp + fn},
            "misses": dict(Counter(why(r) for r in rows if not r["correct"]).most_common()),
            "by_model": {mm: rate(sum(r["correct"] for r in rows if r["model"].split(":")[-1] == mm),
                                  sum(r["model"].split(":")[-1] == mm for r in rows))
                         for mm in sorted({r["model"].split(":")[-1] for r in rows})},
            "misses_by_type": dict(Counter(r["type"] for r in rows if not r["correct"]).most_common())}
    if "FULL" in S and "B1" in S:
        rf = {r["i"]: int(r["correct"]) for r in S["FULL"]["rows"]}
        rb = {r["i"]: int(r["correct"]) for r in S["B1"]["rows"]}
        ids = sorted(set(rf) & set(rb))
        if ids:
            out["paired"] = paired(rf, rb, ids)
            types = {r["i"]: r["type"] for r in S["FULL"]["rows"]}
            out["by_type"] = {t: paired(rf, rb, [i for i in ids if types[i] == t], iters=2000)
                              for t in sorted({types[i] for i in ids})}
    return out


def small_set():
    """The 74-question run: only aggregates survive (per-question rows were overwritten). Wilson CIs and the
    McNemar bound that holds for every pairing consistent with the aggregates (42/46 vs 20/46 head-to-head)."""
    worst = max(mcnemar_exact(b, b - 22) for b in range(22, 27))  # Relay-only minus B1-only = 22; Relay wrong <= 4
    return {"relay": rate(69, 74), "b1": rate(20, 46), "head_to_head_relay": rate(42, 46),
            "head_to_head_b1": rate(20, 46), "mcnemar_p_worst_case": worst,
            "note": "aggregates from README/PROGRESS; per-question rows not kept, so no bootstrap"}


def write_md(m):
    p = lambda r: "-" if not r or r.get("rate") is None else f"{r['rate']:.1%} ({r['k']}/{r['n']}) [{r['ci95'][0]:.0%}–{r['ci95'][1]:.0%}]"
    L = ["# Component and zero-LLM metrics", "",
         "Generated by `python -m eval.zero_llm`. Wilson 95% intervals unless noted. All data synthetic, built from our "
         "own templates (in-distribution); treat as engineering checks, not external validity.", ""]
    for label, c in m.get("components", {}).items():
        src = c.pop("_source", {})
        L += [f"## Components: {label}", "", f"Source: {src}", ""]
        ex = c["extraction"]
        L += [f"- Extraction recall: {p(rate(ex['recovered'], ex['planted']))}; extra facts {ex['extra_facts']}, load errors {ex['load_errors']}"]
        pn = c["predicate_normalization"]
        L += [f"- Predicate normalisation (extracted fact with the planted value carries the planted predicate): {p(rate(pn['correct'], pn['n']))}"]
        ia = c["entity_resolution"]["issue_aliases"]
        L += [f"- Entity resolution, issue paraphrases ({ia['mentions']} mentions, {ia['clusters']} gold clusters -> "
              f"{ia['entities']} entities): pairwise precision {ia['precision']}, recall {ia['recall']} ({ia['gold_pairs']} gold pairs)"]
        ty = c["entity_resolution"]["typos"]
        L += [f"- Typos mapped to the existing entity: {p(rate(ty['ok'], ty['n']))}"]
        col = c["entity_resolution"].get("collisions")
        if col:
            L += [f"- Name collisions kept apart (both customers hold exactly their own current city): {p(rate(col['kept_apart'], col['n']))}"]
        if "contradiction" in c:
            L += ["", "| Contradiction case | Correct [CI] | Excluding extraction misses |", "|---|---|---|"]
            for case, v in c["contradiction"].items():
                L.append(f"| {case} | {p(rate(v['correct'], v['n']))} | {v['correct']}/{v['n'] - v['extraction_miss']} |")
            o = c["contradiction_overall"]
            L.append(f"| **all** | {p(o)} | {p(o['excluding_extraction_misses'])} |")
        if c.get("misses_by_predicate"):
            L += ["", f"Extraction misses by predicate: {c['misses_by_predicate']}"]
        L += [""]
    for label, b in m.get("bench", {}).items():
        L += [f"## Benchmark: {label}", "", f"Tenant `{b['tenant']}`, {b['dataset']}, run `{b['run_id']}`. Provenance: {b.get('provenance')}", ""]
        if "paired" in b:
            pr = b["paired"]
            L += [f"Head-to-head on {pr['n']} questions: Relay {p(pr['relay'])} vs B1 {p(pr['b1'])}; difference "
                  f"{pr['diff']:+.1%}, paired bootstrap 95% CI [{pr['diff_ci95_bootstrap'][0]:+.1%}, {pr['diff_ci95_bootstrap'][1]:+.1%}]; "
                  f"Relay-only correct {pr['relay_only_correct']}, B1-only {pr['b1_only_correct']}, exact McNemar p = {pr['mcnemar_exact_p']:.2g}", "",
                  "| Type | n | Relay | B1 | Δ [bootstrap CI] |", "|---|---|---|---|---|"]
            for t, v in b["by_type"].items():
                L.append(f"| {t} | {v['n']} | {p(v['relay'])} | {p(v['b1'])} | {v['diff']:+.0%} [{v['diff_ci95_bootstrap'][0]:+.0%}, {v['diff_ci95_bootstrap'][1]:+.0%}] |")
            L += [""]
        for s, v in b["systems"].items():
            a = v["abstention"]
            L += [f"**{s}**: accuracy {p(v['accuracy'])}. Abstention ({a['should_refuse']} should-refuse): precision {p(a['precision'])}, recall {p(a['recall'])}.",
                  "", "Why misses happen: " + "; ".join(f"{k}: {n}" for k, n in v["misses"].items()),
                  "", "By answer model (all API keys pooled): " + "; ".join(f"{k} {p(r)}" for k, r in v["by_model"].items()), ""]
    s = m.get("small_set")
    if s:
        L += ["## Small set (74 questions, earlier run)", "",
              f"Relay {p(s['relay'])}; B1 {p(s['b1'])}; head-to-head Relay {p(s['head_to_head_relay'])} vs B1 {p(s['head_to_head_b1'])}. "
              f"Exact McNemar p ≤ {s['mcnemar_p_worst_case']:.1g} for any pairing consistent with these counts. {s['note']}.", ""]
    if m.get("fix_log"):  # one engine fix at a time, each re-scored on the metric it should move
        L += ["## Fix log", "", "| # | Fix | Metric | Before | After | n | Graph / answers |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['id']} | {r['fix']} | {r['metric']} | {r['before']} | {r['after']} | {r['n']} | {r['state']} |"
              for r in m["fix_log"]] + [""]
    L += m.get("notes", [])
    L += ["## Provenance", "", "```", json.dumps(m["git"], indent=1), "```"]
    (HERE / "components.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="append", default=[], help="label=path to a load report")
    ap.add_argument("--graph", default=None, help="tenant to read history from for the LAST report")
    ap.add_argument("--results", action="append", default=[], help="label=path to a results.json")
    a = ap.parse_args()
    out_path = HERE / "components.json"
    m = json.loads(out_path.read_text()) if out_path.exists() else {}
    m["git"] = git_state()
    m["small_set"] = small_set()
    for i, spec in enumerate(a.report):
        label, path = spec.split("=", 1)
        g = a.graph if i == len(a.report) - 1 else None
        c = components(path, g)
        c["misses_by_predicate"] = offline(path)["extraction_misses_by_predicate"]
        c["_source"] = {"report": path, "graph": g, **git_state()}
        m.setdefault("components", {})[label] = c
    for spec in a.results:
        label, path = spec.split("=", 1)
        m.setdefault("bench", {})[label] = bench(path)
    out_path.write_text(json.dumps(m, indent=1))
    write_md(json.loads(json.dumps(m)))
    print((HERE / "components.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
