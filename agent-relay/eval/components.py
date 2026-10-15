"""Component metrics measured on the loaded graph (no LLM): extraction, predicate normalization,
entity resolution, contradiction handling. Needs `python -m data.load --tenant <t>` first."""
import json
from pathlib import Path

from relay import retrieve
from relay.memory import norm

DATA = Path(__file__).resolve().parent.parent / "data"


def _match(a, b):
    a, b = norm(a), norm(b)
    return bool(a) and bool(b) and (a == b or b in a or a in b)


def measure(tenant):
    from eval.run_eval import pairwise_resolution
    events = json.loads((DATA / "scenario.json").read_text())["events"]
    report = json.loads((DATA / "load_report.json").read_text())
    gold = json.loads((DATA / "gold.json").read_text())
    rep = report["events"]
    assert len(rep) == len(events), "load_report does not match scenario.json: reload the tenant"

    # predicate normalization: extracted facts whose object matches a planted value carry the planted predicate?
    pn = {"n": 0, "correct": 0}
    for ev, r in zip(events, rep):
        if ev["type"] != "turn":
            continue
        for pred, obj in ev["expect"]:
            preds = [p for _, p, o in r["got"] if obj and _match(o, obj)]
            if preds:
                pn["n"] += 1
                pn["correct"] += pred in preds
    pn["accuracy"] = round(pn["correct"] / pn["n"], 4) if pn["n"] else None

    # entity resolution: issue phrasings of one problem -> one entity; different problems -> different entities
    mentions, typos = [], {"n": 0, "ok": 0, "failures": []}
    for ev, r in zip(events, rep):
        for plant in ev.get("plants", []):
            if plant["kind"] == "issue":
                stored = [o for _, p, o in r["got"] if p == "reported_issue"]
                if stored:
                    mentions.append((plant["cluster"], stored[0]))
            if plant.get("typo"):
                typos["n"] += 1
                stored = [o for _, p, o in r["got"] if p == plant["pred"]]
                if stored and stored[0] == plant["value"]:
                    typos["ok"] += 1
                else:
                    typos["failures"].append({"text": ev["text"], "stored": stored})
    hist = {}

    def history(c):
        if c not in hist:
            hist[c] = [dict(zip(["fact_id", "pred", "obj", "active", "vf", "vt", "rec", "exp", "by", "agents"], row))
                       for row in retrieve.history(tenant, c)]
        return hist[c]

    final = {(f["customer"], f["pred"]): f["value"] for f in gold["facts"] if f["pred"] == "lives_in"}
    kept = 0
    for a, b in gold["collisions"]:
        ok = all({f["obj"] for f in history(c) if f["pred"] == "lives_in" and f["active"]} == {final[(c, "lives_in")]}
                 for c in (a, b))
        kept += ok
    resolution = {"issue_aliases": {**pairwise_resolution(mentions), "mentions": len(mentions),
                                    "entities": len({m[1] for m in mentions}), "clusters": len({m[0] for m in mentions})},
                  "typos": typos, "collisions": {"n": len(gold["collisions"]), "kept_apart": kept}}

    # contradiction handling, per planted case, on the final graph state
    cases = {}
    for ch in gold["changes"]:
        fs = [f for f in history(ch["customer"]) if f["pred"] == ch["pred"]]
        has = lambda v, active=None, by=None: any(_match(f["obj"], v) and (active is None or f["active"] == active)
                                                  and (by is None or f["by"] == by) for f in fs)
        if ch["case"] == "change":
            miss = not has(ch["new"])
            ok = has(ch["new"], True) and has(ch["old"], False) and not has(ch["old"], True)
        elif ch["case"] == "unchanged":
            miss = False
            active_intake = [f for f in fs if f["active"] and f["by"] == "intake"]
            ok = len(active_intake) == 1 and _match(active_intake[0]["obj"], ch["new"])
        elif ch["case"] == "multi":
            miss = not has(ch["new"])
            ok = has(ch["new"], True) and (ch["old"] is None or has(ch["old"], True))
        else:  # cross_agent: customer told intake one plan, billing tool says another; both must stay current
            miss = not has(ch["old"], by="resolver") or not has(ch["new"], by="intake")
            ok = has(ch["new"], True, "intake") and has(ch["old"], True, "resolver")
        c = cases.setdefault(ch["case"], {"n": 0, "correct": 0, "extraction_miss": 0})
        c["n"] += 1
        c["correct"] += ok
        c["extraction_miss"] += miss and not ok
    for c in cases.values():
        c["accuracy"] = round(c["correct"] / c["n"], 4)
    s = report["summary"]
    return {"extraction": {"planted": s["planted"], "recovered": s["recovered"],
                           "recall": round(s["recovered"] / s["planted"], 4), "extra_facts": s["extra_facts"],
                           "load_errors": len(s["errors"])},
            "predicate_normalization": pn, "entity_resolution": resolution, "contradiction": cases}


if __name__ == "__main__":
    import sys
    print(json.dumps(measure(sys.argv[1] if len(sys.argv) > 1 else "pml"), indent=1))
