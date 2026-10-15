"""Recall: abstains on people memory doesn't hold, links typos, answers nameless questions, takes <= 2 round trips,
and ranks like the old five-query implementation. No LLM calls. Run: python -m tests.test_recall"""
import time
from relay.retrieve import _pvec  # open predicates must rank, not crash (eval found KeyError on open:<attr>)
assert _pvec("open:favourite_colour").shape == _pvec("lives_in").shape

import numpy as np

from relay import agents, db, embed, memory, queries as Q, retrieve

T = "test-recall"
AT = "2026-10-01T10:00:00+05:30"


def say(agent, customer, text, facts, at=AT, speaker="customer"):
    memory.remember(T, agent=agent, session_id=f"s-{customer or 'feed'}", customer=customer, text=text, at=at,
                    facts=facts, speaker=speaker)


# ---------------------------------------------------------------- the old read path (reference for parity)
OLD_KNOWN = "MATCH (e:Entity) WHERE e.type IN ['customer', 'ticket', 'city', 'outage', 'plan', 'router'] RETURN e.name_key, e.type"
OLD_FUZZY = "CALL db.idx.fulltext.queryNodes('Customer', $q) YIELD node, score RETURN node.name_key, score ORDER BY score DESC LIMIT 5"
# the old vector query, with the same name tie-break the new one has (equal distances came back in storage order)
OLD_VECTOR = """CALL db.idx.vector.queryNodes('Episode', 'embedding', $k, vecf32($qvec)) YIELD node AS ep, score
MATCH (ep)-[:MENTIONS]->(e:Entity) RETURN e.name_key AS key, e.type, min(score) AS dist ORDER BY dist ASC, key ASC LIMIT $limit"""
OLD_SALIENCE = "MATCH (e:Entity) WHERE e.name_key IN $keys AND e.salience IS NOT NULL RETURN e.name_key, e.salience"


def old_recall(question, mode="full", k=8, log=None):
    cfg = retrieve.MODES[mode]
    qvec = embed.embed_one(question)
    q = f" {' '.join(retrieve._words(question))} "
    rows = db.run(T, "known entities", OLD_KNOWN, log=log, ro=True)
    linked = [key for key, _ in rows if f" {key} " in q]
    first = {}
    for key, t in rows:
        if t == "customer":
            first.setdefault(key.split()[0], []).append(key)
    linked += [ks[0] for n, ks in first.items() if len(ks) == 1 and f" {n} " in q and ks[0] not in linked]
    if not any(t == "customer" for key, t in rows if key in linked):
        words = retrieve._fuzzy_words(q.split())
        if words:
            fz = db.run(T, "fuzzy", OLD_FUZZY, {"q": "|".join(f"%{w}%" for w in words)}, log, ro=True)
            linked += [x for x in retrieve._fuzzy_pick(fz, words) if x not in linked]
    linked.sort(key=len, reverse=True)
    vrows = db.run(T, "vector seeds", OLD_VECTOR, {"qvec": qvec, "k": k, "limit": 8}, log, ro=True)
    if linked:
        extra = [key for key, typ, _ in vrows if typ != "customer" and key not in linked][:3]
        seeds, dist = linked + extra, {s: 0 for s in linked} | {s: 1 for s in extra}
    else:
        seeds = [key for key, _, _ in vrows][:5]
        dist = {s: 0 for s in seeds}
    rows = db.run(T, "retrieve", Q.retrieve_facts(cfg["hops"]), {"seeds": seeds, "max_entities": 100, "max_facts": 400},
                  log, ro=True)
    facts = [dict(zip(retrieve.FIELDS[:13], r)) for r in rows]
    if cfg["temporal"]:
        retrieve._annotate_conflicts(facts)
    changed = True
    while changed:
        changed = False
        for f in facts:
            for a, b in ((f["subject"], f["object"]), (f["object"], f["subject"])):
                if a in dist and dist.get(b, 99) > dist[a] + 1:
                    dist[b], changed = dist[a] + 1, True
    qn = np.array(qvec) / np.linalg.norm(qvec)
    pv = retrieve._predicate_vecs()
    keys = list({x for f in facts for x in (f["subject"], f["object"])})
    sal = dict(db.run(T, "salience", OLD_SALIENCE, {"keys": keys}, log, ro=True)) if keys else {}
    top = max(sal.values(), default=0) or 1
    imp = lambda f: max(sal.get(f["subject"], 0), sal.get(f["object"], 0)) / top
    facts.sort(key=lambda f: (min(dist.get(f["subject"], 9), dist.get(f["object"], 9)),
                              -(float(pv[f["predicate"]] @ qn) + retrieve.SALIENCE_WEIGHT * imp(f)),
                              not f["active"], f["recorded_at"]))
    facts = facts[:retrieve.MAX_LINES]
    return {"seeds": seeds, "facts": facts, "lines": [retrieve.fmt(f, cfg["temporal"]) for f in facts]}


def main():
    db.reset(T)
    try:
        run()
    finally:
        db.graph(T).delete()


def run():
    say("intake", "alice rao", "I live in Mumbai", [("alice rao", "lives_in", "mumbai")], at="2026-09-01")
    say("intake", "alice rao", "I moved to Pune", [("alice rao", "lives_in", "pune")], at="2026-09-12")
    say("intake", "alice rao", "I'm on Fiber 300", [("alice rao", "on_plan", "fiber 300")])
    say("resolver", "alice rao", "Billing: fiber 100", [("alice rao", "on_plan", "fiber 100")], speaker="tool:billing")
    say("intake", "alice rao", "My router is a PML Hub 6", [("alice rao", "has_router", "pml hub 6")])
    say("intake", "alina rao", "I live in Mumbai, on Fiber 100", [("alina rao", "lives_in", "mumbai"),
                                                                 ("alina rao", "on_plan", "fiber 100")])
    say("intake", "bob menon", "Pune here, fiber 100", [("bob menon", "lives_in", "pune"), ("bob menon", "on_plan", "fiber 100")])
    say("resolver", None, "Outage feed: fiber cut near baner affects pune", [("fiber cut near baner", "affects", "pune")],
        speaker="tool:outage")
    for c in ("alice rao", "alina rao", "bob menon"):
        db.run(T, "profile", Q.PROFILE, {"c": c, "name": c.title(), "at": 1, "at_dt": None})
    agents.consolidate(T)  # PageRank salience, so the salience nudge is exercised

    # unknown person: no facts, no substitute, and ask() abstains without a model call
    for q in ("where does kevin live?", "Which plan is Kevin on?", "what's kevin's router?", "tell me about kevin",
              "what is the status of pml-9999-zzzz?"):
        r = retrieve.recall(T, q)
        assert r["facts"] == [] and r["unknown"], (q, r["seeds"], r["unknown"])
    a = retrieve.ask(T, "where does kevin live?")
    assert a["unknown"] and not a["values"] and not a["cited_ids"] and "Kevin" in a["answer"], a

    # known person: their facts first; the conflict and the superseded city are annotated
    r = retrieve.recall(T, "where does alice rao live?")
    assert not r["unknown"] and r["facts"][0]["subject"] == "alice rao" and r["facts"][0]["predicate"] == "lives_in", r["lines"][:3]
    assert r["facts"][0]["object"] == "pune" and r["facts"][0]["active"]
    plan = [ln for ln in retrieve.recall(T, "Which plan is Alice Rao on?")["lines"] if "| on_plan |" in ln and "alice" in ln]
    assert any("CONFLICT: PREFERRED" in ln and "fiber 300" in ln for ln in plan), plan

    # similar names: each links to the right person; a typo links; a unique first name links
    assert retrieve.detect_entities(T, "where does alina rao live?") == ["alina rao"]
    assert retrieve.detect_entities(T, "where does alise rao live?") == ["alice rao"], "one typo"
    assert retrieve.detect_entities(T, "what plan is bob menn on?") == ["bob menon"], "typo in the surname"
    assert retrieve.detect_entities(T, "where does bob live?") == ["bob menon"], "unique first name"
    r = retrieve.recall(T, "where does alise rao live?")
    assert not r["unknown"] and r["facts"][0]["subject"] == "alice rao", r["lines"][:2]

    # nameless questions keep using vector seeds (and ordinary/city/plan words are not names)
    for q in ("who lives in Pune?", "which plan has the most customers?", "Is there an outage in Pune?",
              "Which customers are on Fiber 100?", "Who lives in Delhi?"):
        r = retrieve.recall(T, q)
        assert not r["unknown"] and r["facts"], (q, r["unknown"])

    # a customer in chat only ever sees their own memory, whoever they ask about
    mine = retrieve.customer_facts(T, "alice rao")
    assert mine and all(f["subject"] == "alice rao" or f["predicate"] == "affects" for f in mine), mine

    # round trips, latency and parity with the old implementation
    questions = ["where does alice rao live?", "Which plan is Alice Rao on?", "where does alise rao live?",
                 "who lives in Pune?", "which plan has the most customers?", "Which outage might affect Bob Menon?",
                 "What router does alina rao have?", "Is there an outage in Pune?"]
    retrieve.recall(T, questions[0])  # warm
    new_ms, old_ms, new_n, old_n = [], [], [], []
    for q in questions:
        for mode in retrieve.MODES:
            log, t = [], time.perf_counter()
            new = retrieve.recall(T, q, mode=mode, log=log)
            new_ms.append((time.perf_counter() - t) * 1000)
            new_n.append(len(log))
            assert len(log) <= 2, (q, [x["name"] for x in log])
            log, t = [], time.perf_counter()
            old = old_recall(q, mode=mode, log=log)
            old_ms.append((time.perf_counter() - t) * 1000)
            old_n.append(len(log))
            assert new["seeds"] == old["seeds"], (q, mode, new["seeds"], old["seeds"])
            assert new["lines"] == old["lines"], (q, mode, new["lines"], old["lines"])
    print(f"recall: old {max(old_n)} round trips, {np.median(old_ms):.0f} ms median; "
          f"new {max(new_n)} round trips, {np.median(new_ms):.0f} ms median ({len(new_ms)} recalls each)")


if __name__ == "__main__":
    main()
    print("test_recall: all checks passed")
