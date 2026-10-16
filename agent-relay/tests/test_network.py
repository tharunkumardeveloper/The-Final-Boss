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



def blast_radius_decides():
    """The resolver calls the catalogue's affected_by tool before acting on an upstream fault; its answer sets priority."""
    from relay import lab, memory
    T = "test-blast-radius"
    db.reset(T)
    try:
        for c in ("alice rao", "bob menon"):
            memory.remember(T, agent="intake", session_id=f"s-{c}", customer=c, at="2026-10-15T10:00:00+05:30", text="t",
                            facts=[(c, "lives_in", "mumbai")])
        lab.ensure(T)
        m = lab.measure(T, "alice rao")
        steps = []

        class Run:
            tenant, customer, ticket = T, "alice rao", None
            def step(self, *a, **k):
                steps.append((a, k))
        others = lab._blast_radius(Run(), "dispatch_cable_crew", m)
        assert others == ["bob menon"], others
        (kind, title, detail, *_), kw = steps[0]
        assert kind == "think" and "Blast radius: 2 customers" in title and "affected_by(node=" in detail
        assert kw["data"]["priority"] == "high" and kw["data"]["tool"] == "affected_by"
        assert lab._blast_radius(Run(), "remote_reboot", m) is None, "a fault inside one home has no blast radius"
    finally:
        db.graph(T).delete()
        try:
            db.client().select_graph("chaos:" + T).delete()
        except Exception:
            pass


if __name__ == "__main__":
    test_all()
    blast_radius_decides()
    print("blast radius: checks passed")
