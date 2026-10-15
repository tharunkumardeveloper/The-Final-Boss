"""Worldwide company knowledge lives in each region's graph and connects to customer memory.
Run: python -m tests.test_kb"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import config, db, kb

T = "test-kb"
config.ROUTES["reply"] = ["allam-2-7b"] + [m for m in config.ROUTES["reply"] if m != "allam-2-7b"]
c = TestClient(app)


def test_all():
    db.reset(T)
    cat = c.get(f"/api/tenants/{T}/kb").json()
    assert cat["region"] == "in" and cat["currency"] == "INR"
    assert [p["price"] for p in cat["plans"]] == [649, 949, 1399, 1799], [p["price"] for p in cat["plans"]]
    assert {"Baner", "Kothrud"} <= set(next(x for x in cat["coverage"] if x["key"] == "pune")["areas"])
    assert any("₹949" in t for t in kb.relevant(T, "How much is Fiber 300?"))
    assert any("Baner" in t for t in kb.relevant(T, "Do you cover Baner?"))
    assert kb.covered_city("baner") and kb.covered_city("hsr layout bangalore") and not kb.covered_city("madurai")
    # another region's prices come from that region's graph, in local currency
    assert any("£37.99" in t for t in kb.relevant("pml-eu", "How much is Fiber 300?", iso="GB"))

    # customer memory points at the same plan node that holds the prices; places are normalised to the catalogue
    r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Nikhil Rao", "text": "Hi, I'm on Fiber 300 at HSR Layout, Bangalore.",
                                                "at": "2026-10-10T10:00:00+05:30"}).json()
    rows = db.run(T, "plan link", "MATCH (:Customer {name_key:'nikhil rao'})-[:ON_PLAN]->(p:Plan)-[pr:PRICED_IN]->"
                  "(:Country {iso:'IN'}) RETURN p.name_key, pr.amount", ro=True)
    assert rows == [["fiber 300", 949]], (rows, r["learned"])
    assert db.run(T, "place", "MATCH (:Customer {name_key:'nikhil rao'})-[:LIVES_IN]->(a:Area)-[:IN_CITY]->(c:City) "
                  "RETURN a.name_key, c.name_key", ro=True) == [["hsr layout", "bengaluru"]]

    r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Nikhil Rao", "text": "How much does Fiber 1000 cost?",
                                                "session_id": r["session_id"], "at": "2026-10-10T10:02:00+05:30"}).json()
    assert "1399" in r["reply"].replace(",", ""), r["reply"]
    assert any(e["name"].startswith("kb:") for e in r["cypher"]), "KB lookup should show in the Cypher log"
    db.graph(T).delete()
    print("test_kb: all checks passed")


if __name__ == "__main__":
    test_all()
