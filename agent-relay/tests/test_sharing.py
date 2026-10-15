"""Knowledge crossing between agents is recorded and measured. Run: python -m tests.test_sharing"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import agents, db, events, memory, sharing

T = "test-sharing"


def test_all():
    db.reset(T)
    got = []
    off = events.subscribe(T, got.append)
    memory.remember(T, agent="intake", session_id="s1", customer="Ravi Kumar", at="2026-10-01T10:00:00+05:30",
                    text="Ravi lives in Pune; wifi drops", facts=[("ravi kumar", "lives_in", "pune"),
                                                               ("ravi kumar", "has_ticket", "pml-3001"),
                                                               ("pml-3001", "ticket_about", "wifi drops"),
                                                               ("pml-3001", "has_status", "open")])
    agents.Resolver().pick_up(T, ticket="pml-3001", at="2026-10-01T11:00:00+05:30")
    s = sharing.summary(T)
    res = next(a for a in s["agents"] if a["agent"] == "resolver")
    assert res["consulted_from_others"] >= 1 and res["reuse_pct"] > 0, s
    assert {"from": "intake", "to": "resolver", "facts": 1} in s["flows"], s["flows"]
    assert s["top_shared"][0]["sentence"].startswith("Ravi Kumar lives in Pune"), s["top_shared"]
    assert any(e["type"] == "consulted" and e["data"]["writers"].get("intake") for e in got)
    # repeated use counts, it doesn't duplicate the edge
    agents.Resolver().pick_up(T, ticket="pml-3001", at="2026-10-01T12:00:00+05:30")
    assert sharing.summary(T)["top_shared"][0]["uses"] == 2
    assert TestClient(app).get(f"/api/tenants/{T}/sharing").json()["flows"][0]["to"] == "resolver"
    off()
    db.graph(T).delete()
    print("test_sharing: all checks passed")


if __name__ == "__main__":
    test_all()
