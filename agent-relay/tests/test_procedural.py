"""Procedural memory as a graph: ordered procedure paths, decided-from-the-graph, failures learned, merges not duplicates,
and the resolver never reading chaos:<tenant>. No LLM: the model is made unavailable, so the rule engine is the fallback.
Run: python -m tests.test_procedural"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, lab, llm, memory, procedural

T = "test-procedural"
c = TestClient(app)


def put(name, ticket=None):
    facts = [(name.lower(), "lives_in", "baner")]
    if ticket:
        facts += [(name.lower(), "has_ticket", ticket), (ticket, "ticket_about", "no internet"),
                  (ticket, "has_status", "open")]
    memory.remember(T, agent="intake", session_id=f"{name.split()[0].lower()}-s1", customer=name, at=lab._ms(),
                    text=f"{name} lives in Baner", facts=facts)


def case(customer, said, ticket=None):
    run = lab.Run(T, customer, ticket, None, said, picked=True)
    run.followup = True  # the faults are set up by the test; don't let the world add a matching one
    lab.investigate(run)
    return run.data


def q(query, params=None):
    return db.graph(T).ro_query(query, params or {}).result_set


def test_all():
    db.reset(T)
    lab.reset(T)
    lab.STEP_PAUSE = 0
    lab.DELAY["send_payment_link"] = 0.2

    def no_model(*a, **k):  # quota: the rule engine stands in for the model
        raise RuntimeError("model unavailable in this test")
    llm.chat_json = no_model

    # the resolver's procedural queries must never touch chaos:<tenant>
    graphs, inside = [], [False]
    cl = db.client()
    real_select = cl.select_graph
    cl.select_graph = lambda name: (graphs.append(name) if inside[0] else None) or real_select(name)
    for fn in ("suggest", "record", "failed"):
        real = getattr(procedural, fn)

        def wrapped(*a, _real=real, **k):
            inside[0] = True
            try:
                return _real(*a, **k)
            finally:
                inside[0] = False
        setattr(procedural, fn, wrapped)

    for name, tk in (("Asha Rao", "tst-1"), ("Bina Rao", "tst-2"), ("Chetan Rao", None), ("Dev Rao", "tst-4")):
        put(name, tk)
    lab.ensure(T)

    # 1. first frozen box: nothing in procedural memory yet; the rules fix it; the path is written after verifying
    lab.inject(T, "frozen_box", "asha rao", complain=False)
    a = case("asha rao", "My internet isn't working at all", "tst-1")
    assert a["status"] == "resolved", a["status"]
    assert any(s["title"].startswith("Procedural memory: no past procedure") for s in a["steps"])
    procs = {p["signature"]: p for p in procedural.procedures(T)}
    assert procs["reads:box"]["steps"] == ["remote_reboot"] and procs["reads:box"]["successes"] == 1, procs
    assert procs["reads:box"]["tickets"] == ["tst-1"] and procs["reads:box"]["places"], procs["reads:box"]

    # 2. second frozen box on the same street cabinet: procedural memory decides, in no more attempts
    lab.inject(T, "frozen_box", "bina rao", complain=False)
    b = case("bina rao", "Nothing is loading", "tst-2")
    marker = [s for s in b["steps"] if "Procedural memory: restart the box remotely fixed this 1 time (1 nearby) — taking it"
              in s["title"]]
    assert marker and marker[0]["kind"] == "memory" and marker[0]["cypher"], [s["title"] for s in b["steps"]]
    assert b["diagnosis"]["by"] == "procedural memory" and b["diagnosis"]["agrees"], b["diagnosis"]
    assert b["status"] == "resolved" and len(b["actions"]) <= len(a["actions"]), (b["status"], b["actions"])
    assert b["verdict"]["correct"] and b["verdict"]["fixed"], b["verdict"]  # graded against the hidden truth
    # merged, not duplicated
    assert q("MATCH (p:Procedure {signature:'reads:box'}) WHERE p.actions = ['remote_reboot'] "
             "RETURN count(p), max(p.successes)") == [[1, 2]]
    assert q("MATCH (p:Procedure {signature:'reads:box'})-[:FIRST]->(s:ProcStep) WHERE p.actions = ['remote_reboot'] "
             "RETURN count(s)") == [[1]]
    assert q("MATCH (p:Procedure {signature:'reads:box'})-[w:WORKED_AT]->() WHERE p.actions = ['remote_reboot'] "
             "RETURN count(w), max(w.times)") == [[1, 2]]

    # 3. a box restart can't fix (stuck, not frozen): memory's pick fails and the graph counts the failure
    lab._q(T, "test: stuck box", "MATCH (o:Ont {customer:'chetan rao'}) SET o.box_state='stuck'")
    ch = case("chetan rao", "Internet is down")
    assert any(s["title"] == "Procedural memory was wrong here: failure recorded" for s in ch["steps"])
    assert ch["status"] == "unresolved", ch["status"]
    assert q("MATCH (p:Procedure {signature:'reads:box'}) WHERE p.actions = ['remote_reboot'] "
             "RETURN p.successes, p.failures") == [[2, 1]]
    lab._q(T, "test: unstick", "MATCH (o:Ont {customer:'chetan rao'}) SET o.box_state='online'")

    # 4. two faults at once: an ordered two-step path, FIRST then NEXT {order:1}
    lab.inject(T, "frozen_box", "dev rao", complain=False)
    lab.inject(T, "payment_failed", "dev rao", complain=False)
    d = case("dev rao", "My internet stopped", "tst-4")
    assert d["status"] == "resolved" and d["actions"] == ["remote_reboot", "send_payment_link"], (d["status"], d["actions"])
    chain = q("MATCH (p:Procedure {signature:'reads:account,reads:box'})-[:FIRST]->(a:ProcStep)-[n:NEXT]->(b:ProcStep) "
              "RETURN a.action, n.order, b.action, p.successes, p.failures")
    assert chain == [["remote_reboot", 1, "send_payment_link", 1, 0]], chain

    # 5. the API returns the ordered steps with counters
    out = c.get(f"/api/tenants/{T}/procedural").json()["procedures"]
    two = next(p for p in out if p["signature"] == "reads:account,reads:box")
    assert two["steps"] == ["remote_reboot", "send_payment_link"] and two["successes"] == 1, two

    # 6. never chaos: from inside the procedural module, and not in its source
    assert graphs and all(g == f"mem:{T}" for g in graphs), set(graphs)
    assert "chaos" not in open(procedural.__file__, encoding="utf-8").read().replace("chaos:<tenant>", "")

    cl.select_graph = real_select
    db.graph(T).delete()
    try:
        lab._chaos(T).delete()
    except Exception:
        pass
    print("test_procedural: all checks passed")


if __name__ == "__main__":
    test_all()
