"""API end to end against live FalkorDB + LLMs (cached after the first run). Run: python -m tests.test_api"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, sim

T = "api-test"


def test_api():
    c = TestClient(app)
    assert c.get("/health").json()["falkordb"]

    # scripted story through the real agents
    assert c.post(f"/api/tenants/{T}/reset", json={"scenario": "story"}).json()["ok"]
    s = c.get(f"/api/tenants/{T}/stats").json()
    assert s["current_facts"] > 5 and s["superseded_facts"] >= 1 and s["conflicts"] >= 1 and s["open_tickets"] >= 1, s
    alice = next(x for x in c.get(f"/api/tenants/{T}/customers").json() if x["key"] == "alice rao")
    assert alice["city"] == "pune" and alice["plan"] == "fiber 300" and alice["open_ticket"].startswith("PML-"), alice

    # you as a customer: conversational reply grounded in memory
    r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Alice Rao", "text": "I also got an Xbox and it drops wifi too.",
                                               "at": "2026-09-14T10:00:00+05:30"}).json()
    assert r["reply"] and any(f["object"] == "xbox" for f in r["learned"]) and r["cypher"], r

    # cited answer + path
    a = c.post(f"/api/tenants/{T}/ask", json={"question": "Where does Alice Rao live and which plan is she on?"}).json()
    assert "pune" in a["values"] and a["conflict"] and a["path"]["nodes"], a
    assert any(n["id"].startswith("ep:") for n in a["path"]["nodes"]) and any(n["id"] == "a:intake" for n in a["path"]["nodes"])

    # live graph + readable cards
    g = c.get(f"/api/tenants/{T}/graph").json()
    old = next(e for e in g["edges"] if e["label"] == "lives_in" and not e["active"])
    assert any(e["conflict"] for e in g["edges"]) and all(e["source"].startswith("e:") for e in g["edges"])
    fc = c.get(f"/api/tenants/{T}/card/{old['id']}").json()
    assert fc["title"].startswith("Alice Rao lives in Mumbai") and "Superseded" in fc["lines"][0], fc
    assert fc["active"] is False
    ec = c.get(f"/api/tenants/{T}/card/e:alice rao").json()
    assert ec["title"] == "Alice Rao" and "open ticket" in ec["lines"][0], ec
    assert c.get(f"/api/tenants/{T}/card/e:pune").json()["sections"]
    focus = c.get(f"/api/tenants/{T}/graph", params={"focus": "e:alice rao", "depth": 1}).json()
    assert focus["edges"] and len(focus["edges"]) <= len(g["edges"])

    tk = c.get(f"/api/tenants/{T}/tickets").json()
    assert tk and tk[0]["ticket"].startswith("PML-") and tk[0]["trail"], tk
    tc = c.get(f"/api/tenants/{T}/card/e:{tk[0]['ticket'].lower()}").json()
    assert tc["sections"][0]["title"] == "Status history", tc

    # two clocks diverge for the backdated move
    clk = c.get(f"/api/tenants/{T}/clock", params={"subject": "alice rao", "at": "2026-09-11"}).json()
    lives = lambda rows: [x["value"] for x in rows if x["predicate"] == "lives_in"]
    assert lives(clk["world"]) == ["pune"] and lives(clk["belief"]) == ["mumbai"], clk
    assert any(not h["active"] for h in c.get(f"/api/tenants/{T}/history", params={"subject": "alice rao"}).json())
    assert c.post(f"/api/tenants/{T}/consolidate").json()["communities"]

    # websocket streams events during a short simulation
    want = {"message", "fact_created", "fact_superseded", "cypher"}
    with c.websocket_connect(f"/ws/{T}") as ws:
        assert c.post(f"/api/tenants/{T}/sim/start", json={"customers": 1, "speed": 500}).json()["running"]
        seen = {}
        for _ in range(5000):
            ev = ws.receive_json()
            seen.setdefault(ev["type"], ev)
            if want <= set(seen):
                break
        c.post(f"/api/tenants/{T}/sim/stop")
    assert want <= set(seen), set(seen)
    sup = seen["fact_superseded"]["data"]
    assert sup["valid_to"] and sup["expired_at"] and sup["old_object"], sup
    assert seen["cypher"]["data"]["query"], seen["cypher"]
    sim.SIMS[T]._thread.join(timeout=120)
    db.graph(T).delete()
    print("test_api: all checks passed")


if __name__ == "__main__":
    test_api()
