"""'Who has worked on this before?' as a traversal. Run: python -m tests.test_experts"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import agents, db, experts, memory

T = "test-experts"


def ticket(customer, tid, issue, router, at):
    memory.remember(T, agent="intake", session_id=f"{tid}-s", customer=customer, at=at, text=f"{customer}: {issue}",
                    facts=[(customer, "lives_in", "baner"), (customer, "has_router", router), (customer, "has_ticket", tid),
                           (tid, "ticket_about", issue), (tid, "has_status", "open")])


def test_all():
    db.reset(T)
    ticket("asha rao", "pml-4001", "router keeps rebooting", "pml hub 6 pro", "2026-10-01T10:00:00+05:30")
    ticket("dev joshi", "pml-4002", "router reboots at night", "pml hub 6 pro", "2026-10-02T10:00:00+05:30")
    res = agents.Resolver()
    t1 = res.pick_up(T, ticket="pml-4001", at="2026-10-01T11:00:00+05:30")["technician"]
    res.try_fix(T, ticket="pml-4001", fix="firmware update", worked=True, at="2026-10-01T12:00:00+05:30")
    res.pick_up(T, ticket="pml-4002", at="2026-10-02T11:00:00+05:30")
    assert t1 in experts.technicians("in")["pune"], t1  # Baner is in Pune
    out = TestClient(app).get(f"/api/tenants/{T}/experts", params={"topic": "Hub 6 Pro reboots"}).json()
    assert out and out[0]["technician"] == t1 and out[0]["resolved"] == 1, out
    assert sum(e["tickets"] for e in out) == 2
    assert TestClient(app).get(f"/api/tenants/{T}/experts", params={"topic": "billing dispute"}).json() == []
    rows = db.run(T, "browser", "MATCH (:Ticket)-[:WORKED_BY]->(t:Technician) RETURN count(t)", ro=True)
    assert rows[0][0] == 2
    db.graph(T).delete()
    print("test_experts: all checks passed")


if __name__ == "__main__":
    test_all()
