"""Open facts, plans vs wants, planned moves, orders. Part A needs no LLM; part B replays the conversation that
went wrong. Run: python -m tests.test_open_facts"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import converse, db, memory, orders, registry as R, retrieve

T = "test-open"
c = TestClient(app)


def facts(name):
    return {(p, o) for _, p, o, active, *_ in retrieve.history(T, name) if active}


def part_a():
    assert R.open_name("Works From Home") == "open:works_from_home" and R.rel_type("open:works_from_home") == "WORKS_FROM_HOME"
    assert R.rel_type("open:lives_in") == "HAS_LIVES_IN"  # never collides with a core edge type
    assert memory.catalogue_plan("the Fiber 1000 plan") == "fiber 1000" and memory.catalogue_plan("Fiber 200") is None
    memory.remember(T, agent="intake", session_id="m-1", customer="Meera Iyer", at="2026-10-13T10:00:00+05:30",
                    text="works from home, lives in HSR Layout",
                    facts=[("meera iyer", "open:works_from_home", "yes"), ("meera iyer", "lives_in", "hsr layout")])
    assert db.run(T, "open edge", "MATCH (:Customer {name_key:'meera iyer'})-[r:WORKS_FROM_HOME]->(v) RETURN v.name_key",
                  ro=True) == [["yes"]]
    assert memory.open_predicate(T, "works_from_home") == "open:works_from_home"
    o = orders.place(T, customer="meera iyer", plan="fiber 1000", at="2026-10-13T10:05:00+05:30")
    assert o["status"] == "pending" and o["install_at"] == "hsr layout" and o["covered"]
    again = orders.place(T, customer="meera iyer", plan="fiber 300", at="2026-10-13T10:06:00+05:30")
    assert again["order_id"] == o["order_id"] and again["plan"] == "fiber 300", "one open order per customer"
    notes, _, iso = converse.customer_notes(T, "meera iyer")
    assert any("NOT on this plan" in n for n in notes) and iso == "IN", notes
    assert ("on_plan", "fiber 300") not in facts("meera iyer")
    done = c.post(f"/api/tenants/{T}/orders/{o['order_id']}/install").json()
    assert done["status"] == "installed" and ("on_plan", "fiber 300") in facts("meera iyer")


def part_b():
    sid, lines = None, ["so i live in chennai currently",
                        "im planning to move to blr by next month",
                        "what plans do you have for 2000 rupees",
                        "i work from home and my house has thick concrete walls",
                        "ill buy Fiber 1000, i am in koramangala now",
                        "Which plan am I on?"]
    for i, text in enumerate(lines):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Tharun", "text": text, "session_id": sid,
                                                    "at": f"2026-10-13T23:{17 + i}:00+05:30"}).json()
        sid = r["session_id"]
        print(f"{text!r:55} -> {[(x['predicate'], x['object'], x['status']) for x in r['learned']]}  orders={r['orders']}")
    now = facts("tharun")
    print("current facts:", sorted(now))
    assert ("lives_in", "koramangala") in now, now
    assert not any(p == "moving_to" for p, _ in now), "the planned move happened, so it is retired"
    assert not any(p == "on_plan" for p, _ in now), "saying 'I'll buy' must not put them on a plan"
    assert any(p == "budget" and "2000" in o for p, o in now), now
    assert any(R.is_open(p) for p, _ in now), "open facts captured"
    assert orders.for_customer(T, "tharun")[0]["plan"] == "fiber 1000"


if __name__ == "__main__":
    db.reset(T)
    part_a()
    print("part A ok")
    part_b()
    db.graph(T).delete()
    print("test_open_facts: all checks passed")
