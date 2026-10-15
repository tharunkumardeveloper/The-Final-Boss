"""The answer contract and the tool catalogue against a live FalkorDB, with no LLM calls.
Run: python -m tests.test_contract"""
from relay import db, memory, retrieve, tools_catalog as TC

T = "test-contract"
DEV = "dev kumar"


def remember(agent, text, at, facts, speaker="customer", customer=DEV):
    return memory.remember(T, agent=agent, session_id="s-contract", customer=customer, text=text, at=at,
                           facts=facts, speaker=speaker)


def fake_answer(r, *preds):
    """What the answer model would cite, chosen by predicate, so the contract is tested without a model call."""
    return {"cited_ids": [f["fact_id"] for f in r["facts"] if f["predicate"] in preds and f["active"]],
            "unknown": not preds}


def test_all():
    db.reset(T)
    remember("intake", "I live in Chennai", "2026-09-01", [(DEV, "lives_in", "chennai")])
    remember("intake", "We moved to Madurai on the 10th", "2026-09-12", [(DEV, "lives_in", "madurai", "2026-09-10")])
    remember("noc", "Outage: fibre cut in Madurai", "2026-09-13", [("fibre cut madurai", "affects", "madurai")],
             speaker="tool:noc")
    remember("intake", "I'm on Fiber 300", "2026-09-04", [(DEV, "on_plan", "fiber 300")])
    remember("resolver", "Billing says fiber 100", "2026-09-05", [(DEV, "on_plan", "fiber 100")], speaker="tool:billing")

    # memory: one fact about the asked entity, with when it went on file and who wrote it
    r = retrieve.recall(T, "Where does Dev Kumar live?")
    c = retrieve.contract(r, fake_answer(r, "lives_in"))
    assert c["outcome"] == "memory", c
    assert [(h["from"], h["rel"], h["to"]) for h in c["paths"][0]] == [(DEV, "LIVES_IN", "madurai")], c
    assert c["learned"][0]["by"] == ["intake"] and c["learned"][0]["at"] == "2026-09-12", c

    # path: the outage reaches Dev through his city; the hops come back in the order recall walked them
    r = retrieve.recall(T, "Which outage might affect Dev Kumar?")
    c = retrieve.contract(r, fake_answer(r, "affects"))
    assert c["outcome"] == "path", c
    assert [(h["from"], h["rel"], h["to"]) for h in c["paths"][0]] == [
        (DEV, "LIVES_IN", "madurai"), ("fibre cut madurai", "AFFECTS", "madurai")], c
    assert c["paths"][0][0]["since"] == "2026-09-10" and c["paths"][0][1]["by"] == ["noc"], c

    # not_in_graph: Dev is known, nothing of the asked kind connects him ("not modelled", not "nothing")
    r = retrieve.recall(T, "Which router does Dev Kumar have?")
    c = retrieve.contract(r, fake_answer(r))
    assert c["outcome"] == "not_in_graph" and DEV in c["note"], c

    # unknown_entity: a name the graph doesn't hold; recall stops after name lookup and ask never calls the model
    log = []
    a = retrieve.ask(T, "Where does Zed Quinlan live?", log=log)
    assert a["outcome"] == "unknown_entity" and a["unknown"] and not a["paths"], a
    assert [q["name"] for q in log] == ["recall: link"], log

    # tools: two clocks
    now = TC.call(T, "facts_at", {"name": DEV, "at": "now"})
    then = TC.call(T, "facts_at", {"name": DEV, "at": "2026-09-05"})
    city = lambda out: [x["object"] for x in out["result"] if x["predicate"] == "lives_in"]
    assert city(now) == ["madurai"] and city(then) == ["chennai"], (now, then)
    assert then["paths"][0][0]["by"] and then["extra"]["at"] == "2026-09-05", then
    # system clock on the 11th: true in the world = madurai, still on file = chennai
    gap = TC.call(T, "facts_at", {"name": DEV, "at": "2026-09-11"})
    assert city(gap) == ["madurai"] and [b["value"] for b in gap["extra"]["belief"] if b["predicate"] == "lives_in"] == ["chennai"], gap

    # tools: disagreement, trust ranked (intake 0.9 over resolver 0.6), both writers kept
    cl = TC.call(T, "claims", {"name": "dev  KUMAR", "predicate": "on_plan"})
    assert [(x["value"], x["agents"], x["preferred"]) for x in cl["result"]] == [
        ("fiber 300", ["intake"], True), ("fiber 100", ["resolver"], False)], cl
    assert cl["extra"]["disputed"], cl

    # tools: a typo of a known customer resolves; an unknown name runs no tool query (only the name lookups)
    assert TC.call(T, "recall_customer", {"name": "dev kumr"})["outcome"] in ("memory", "path")
    log = []
    u = TC.call(T, "recall_customer", {"name": "zed quinlan"}, log)
    assert u["outcome"] == "unknown_entity" and u["rows"] == 0, u
    assert {q["name"] for q in log} <= {"tool: resolve name", "fuzzy customers"}, log
    assert "customer memory" not in u["queries"], u

    # tools: arg validation happens before any query; depth is capped at 4
    for bad in ({"node": "pop-x", "depth": 9}, {"node": "pop-x", "depth": 0}, {"node": "pop-x"},
                {"node": "pop-x", "depth": 1, "cypher": "MATCH (n) DETACH DELETE n"}):
        log = []
        try:
            TC.call(T, "affected_by", bad, log)
            raise AssertionError(f"accepted {bad}")
        except TC.BadArg:
            assert log == [], log
    try:
        TC.call(T, "claims", {"name": DEV, "predicate": "favourite_colour"})
        raise AssertionError("accepted an unknown predicate")
    except TC.BadArg:
        pass

    # tools: blast radius, depth 1 vs depth 2, each row with its path
    db.graph(T).query("""
        CREATE (p:NetNode:Pop:Up {node_id:'pop-test', label:'Test POP'}),
               (o:NetNode:Olt:Up {node_id:'olt-test', label:'Test OLT'})-[:UPLINK]->(p)
        WITH o MATCH (c:Entity {name_key:$c}) CREATE (c)-[:CONNECTED_VIA]->(o)""", {"c": DEV})
    d1 = TC.call(T, "affected_by", {"node": "pop-test", "depth": 1})
    d2 = TC.call(T, "affected_by", {"node": "pop-test", "depth": "2"})
    assert [r["id"] for r in d1["result"]] == ["olt-test"] and d1["extra"]["customers"] == 0, d1
    assert d2["extra"]["customers"] == 1 and d2["outcome"] == "path", d2
    assert [(h["from"], h["rel"], h["to"]) for h in d2["paths"][-1]] == [
        (DEV, "CONNECTED_VIA", "Test OLT"), ("Test OLT", "UPLINK", "Test POP")], d2["paths"]
    assert TC.call(T, "affected_by", {"node": "pop-nowhere", "depth": 2})["outcome"] == "unknown_entity"

    # every call is recorded with tool, args, ms, rows, outcome
    calls = TC.recent(T)
    assert calls[0]["tool"] == "affected_by" and {"tool", "args", "ms", "rows", "outcome"} <= set(calls[0]), calls[0]
    assert any(c["outcome"] == "unknown_entity" and c["tool"] == "recall_customer" for c in calls)

    # the customer chat's "how I know": only this customer's facts, only ones on file before the reply's turn
    how = retrieve.grounding(T, DEV, "Your line in Madurai is affected.", memory.to_ms("2026-09-20"))
    assert [(h["rel"], h["to"]) for h in how] == [("LIVES_IN", "madurai")], how
    assert retrieve.grounding(T, DEV, "Your line in Madurai is affected.", memory.to_ms("2026-09-11")) == []
    assert retrieve.grounding(T, "zed quinlan", "Madurai", memory.to_ms("2026-09-20")) == []


if __name__ == "__main__":
    try:
        test_all()
        print("test_contract: all checks passed")
    finally:
        for g in (db.key(T), f"chaos:{T}"):
            if g in db.client().list_graphs():
                db.client().select_graph(g).delete()
