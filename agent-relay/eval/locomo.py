"""External check on LoCoMo (Maharana et al., 2024; CC BY-NC 4.0, github.com/snap-research/locomo).

One public conversation is ingested into tenant `life-locomo` (general personal-life predicate registry) and
answered by Relay (FULL) and the vector baseline (B1) on its own QA. Downloaded at run time, not redistributed.
"""
import json
import re
import string
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from data.load import with_retry
from relay import db, llm, memory

DIR = Path(__file__).resolve().parent.parent / "data" / "locomo"
URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
TENANT, CONV, MAX_TURNS, MAX_Q = "life-locomo", 0, 150, 60
LICENSE = "CC BY-NC 4.0 (snap-research/locomo); downloaded at run time, not redistributed"
CATEGORY = {1: "multi_hop", 2: "temporal", 3: "open_domain", 4: "single_hop", 5: "adversarial"}


def data():
    path = DIR / "locomo10.json"
    if not path.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(httpx.get(URL, timeout=60, follow_redirects=True).content)
    return json.loads(path.read_text(encoding="utf-8"))[CONV]


def sessions(conv):
    c, out, turns = conv["conversation"], [], 0
    n = 1
    while f"session_{n}" in c and turns < MAX_TURNS:
        when = datetime.strptime(c[f"session_{n}_date_time"], "%I:%M %p on %d %B, %Y")
        out.append((n, when, c[f"session_{n}"]))
        turns += len(c[f"session_{n}"])
        n += 1
    return out


def ingest(conv):
    marker = DIR / f"loaded_{TENANT}.json"
    sess = sessions(conv)
    if marker.exists():
        return sess
    db.reset(TENANT)
    for n, when, turns in sess:
        for j, t in enumerate(turns):
            with_retry(lambda: memory.ingest_turn(TENANT, agent="intake", session_id=f"locomo-s{n}",
                                                  customer=t["speaker"], text=t["text"], at=when + timedelta(minutes=j)))
        print(f"locomo: ingested session {n} ({len(turns)} turns)", flush=True)
    marker.write_text(json.dumps({"sessions": len(sess), "turns": sum(len(t) for _, _, t in sess)}))
    return sess


def _norm_tokens(s):
    s = str(s).lower()
    s = "".join(ch for ch in s if ch not in string.punctuation)
    s = re.sub(r"\b(a|an|the|and)\b", " ", s)
    return s.split()


def token_f1(pred, gold):
    p, g = _norm_tokens(pred), _norm_tokens(gold)
    common = sum((Counter(p) & Counter(g)).values())
    if not p or not g or not common:
        return 0.0
    prec, rec = common / len(p), common / len(g)
    return 2 * prec * rec / (prec + rec)


def questions(conv, n_sessions):
    ok = []
    for qa in conv["qa"]:
        ev = qa.get("evidence") or []
        sess = [int(m.group(1)) for e in ev for m in [re.match(r"D(\d+):", e)] if m]
        if sess and max(sess) <= n_sessions:
            ok.append(qa)
    by = {}
    for qa in ok:
        by.setdefault(qa["category"], []).append(qa)
    out, k = [], 0
    while len(out) < MAX_Q and any(k < len(v) for v in by.values()):
        out += [v[k] for _, v in sorted(by.items()) if k < len(v)]
        k += 1
    return out[:MAX_Q]


def measure(exhausted=None):
    from eval.run_eval import MODELS, QuotaExhausted, VectorStore, answer
    from relay import retrieve
    exhausted = exhausted if exhausted is not None else set()
    conv = data()
    try:
        sess = ingest(conv)
    except llm.Unavailable as e:
        print(f"locomo: ingest stopped, {str(e)[:120]}")
        return {"partial": True, "stage": "ingest", "license": LICENSE}
    qs = questions(conv, len(sess))
    store = VectorStore(TENANT, [])
    cache = DIR / "answers.json"
    rows = json.loads(cache.read_text()) if cache.exists() else {}
    partial = False
    for i, qa in enumerate(qs):
        m = MODELS[i % len(MODELS)]
        for system in ["FULL", "B1"]:
            k = f"{system}:{i}"
            if k in rows:
                continue
            if m in exhausted:
                partial = True
                continue
            lines = (retrieve.recall(TENANT, qa["question"])["lines"] if system == "FULL"
                     else store.lines(qa["question"], True, 10))
            try:
                a = answer(qa["question"], lines, m)
            except QuotaExhausted as e:
                print(f"locomo quota: {e}")
                exhausted.add(m)
                partial = True
                continue
            adversarial = qa["category"] == 5
            pred = " ".join(a["values"]) if a["values"] else a["answer"]
            refused = bool(a["unknown"] or not a["values"])
            rows[k] = {"system": system, "category": CATEGORY[qa["category"]], "question": qa["question"],
                       "gold": qa.get("answer", qa.get("adversarial_answer")), "pred": pred, "model": m,
                       "adversarial": adversarial, "refused": refused,
                       "f1": None if adversarial else round(token_f1(pred, qa["answer"]), 4)}
            print(f"locomo {system:4} q{i:02} {CATEGORY[qa['category']]:11} f1={rows[k]['f1']} {pred[:50]!r}", flush=True)
            cache.write_text(json.dumps(rows, indent=1))
    systems = {}
    for system in ["FULL", "B1"]:
        rs = [r for r in rows.values() if r["system"] == system]
        f1 = [r["f1"] for r in rs if r["f1"] is not None]
        adv = [r for r in rs if r["adversarial"]]
        by = {}
        for r in rs:
            if r["f1"] is not None:
                by.setdefault(r["category"], []).append(r["f1"])
        systems[system] = {"n": len(rs), "f1": round(sum(f1) / len(f1), 4) if f1 else 0.0,
                           "f1_ge_half": round(sum(x >= 0.5 for x in f1) / len(f1), 4) if f1 else None,
                           "adversarial_refused": f"{sum(r['refused'] for r in adv)}/{len(adv)}",
                           "f1_by_category": {c: round(sum(v) / len(v), 3) for c, v in by.items()}}
    return {"conversation": conv.get("sample_id", CONV), "sessions": len(sess), "turns": sum(len(t) for _, _, t in sess),
            "n": len(qs), "systems": systems, "partial": partial, "license": LICENSE}
