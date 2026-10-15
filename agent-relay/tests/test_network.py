"""Network graph + NOC agent: a failure finds affected customers by traversal and warns them first.
Run: python -m tests.test_network"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, events, memory, retrieve, sharing

T = "test-network"
c = TestClient(app)


def put(name, place, at):
    memory.remember(T, agent="intake", session_id=f"{name.split()[0].lower()}-s1", customer=name, at=at,
                    text=f"{name} lives in {place}", facts=[(name.lower(), "lives_in", place)])


def test_all():
    db.reset(T)
    got = []
    off = events.subscribe(T, got.append)
    put("Asha Rao", "baner", "2026-10-01T10:00:00+05:30")
    put("Vikram Das", "pune", "2026-10-01T10:05:00+05:30")       # city only -> first Pune area (Baner)
    put("Neha Shah", "andheri", "2026-10-01T10:10:00+05:30")     # Mumbai, dual-homed
    put("Omar Ali", "madurai", "2026-10-01T10:15:00+05:30")      # outside coverage: no line

    net = c.get(f"/api/tenants/{T}/network").json()
    by_id = {n["id"]: n for n in net["nodes"]}
    assert by_id["olt-pune-baner"]["customers"] == 2 and by_id["olt-mumbai-andheri"]["customers"] == 1
    assert by_id["pop-pune"]["betweenness"] > by_id["olt-pune-baner"]["betweenness"], "POPs are more critical than OLTs"

    # Core West fails: Pune is single-homed and goes dark, Mumbai survives via Core South
    r = c.post(f"/api/tenants/{T}/network/core-west/fail").json()
    hit = {a["customer"] for a in r["affected"]}
    assert hit == {"asha rao", "vikram das"}, r
    asha = next(a for a in r["affected"] if a["customer"] == "asha rao")
    assert asha["path"] == ["e:asha rao", "olt-pune-baner", "pop-pune", "core-west"], asha["path"]
    assert any(e["type"] == "outage_detected" for e in got)
    msgs = [e["data"] for e in got if e["type"] == "message" and e["data"]["speaker"] == "noc" and e["data"]["customer"]]
    assert {m["customer"] for m in msgs} == {"asha rao", "vikram das"} and "no need to call" in msgs[0]["text"]
    # the outage is shared memory now: the resolver's view of Asha includes it
    assert any(f["predicate"] == "affects" and f["object"] == "baner" for f in retrieve.customer_facts(T, "asha rao"))
    assert any(f["predicate"] == "affects" and f["object"] == "pune" for f in retrieve.customer_facts(T, "vikram das"))
    # the NOC used facts intake wrote
    assert {"from": "intake", "to": "noc", "facts": 2} in sharing.summary(T)["flows"]

    r = c.post(f"/api/tenants/{T}/network/core-west/restore").json()
    assert set(r["notified"]) == {"asha rao", "vikram das"}
    assert not any(f["predicate"] == "affects" and f["active"] for f in retrieve.customer_facts(T, "asha rao"))

    # moving out of coverage drops the line
    put("Asha Rao", "madurai", "2026-10-02T10:00:00+05:30")
    assert {n["id"]: n for n in c.get(f"/api/tenants/{T}/network").json()["nodes"]}["olt-pune-baner"]["customers"] == 1
    off()
    db.graph(T).delete()
    print("test_network: all checks passed")


if __name__ == "__main__":
    test_all()
