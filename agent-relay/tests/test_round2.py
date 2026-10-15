"""Retired facts, 'we' = the customer, conversation history, usage ledger. Run: python -m tests.test_round2"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, events, retrieve, usage

T = "test-round2"
c = TestClient(app)


def lives_in(name):
    return [(r[2], r[3]) for r in retrieve.history(T, name) if r[1] == "lives_in"]


def test_all():
    db.reset(T)
    got = []
    off = events.subscribe(T, got.append)

    def chat(text, at):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Meera Iyer", "text": text, "at": at})
        assert r.status_code == 200, r.text
        return r.json()

    first = chat("Hi, I live in Chennai and I'm on the Fiber 300 plan.", "2026-10-01T10:00:00+05:30")
    assert ("chennai", True) in lives_in("meera iyer"), lives_in("meera iyer")
    sid = first["session_id"]

    # "no longer" with no new value: the fact ends, nothing replaces it, history stays
    r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Meera Iyer", "text": "I no longer live in Chennai.",
                                                "session_id": sid, "at": "2026-10-05T10:00:00+05:30"}).json()
    assert any(x["status"] == "retired" and x["object"] == "chennai" for x in r["learned"]), r["learned"]
    assert lives_in("meera iyer") == [("chennai", False)], lives_in("meera iyer")
    assert any(e["type"] == "fact_retired" and e["data"]["object"] == "chennai" for e in got)
    fid = next(x["fact_id"] for x in r["learned"] if x["status"] == "retired")
    card = c.get(f"/api/tenants/{T}/card/f:{fid}").json()
    assert card["active"] is False and "no longer" in card["subtitle"], card

    # "we" from the customer counts as the customer
    chat("We're based in Mumbai now.", "2026-10-06T10:00:00+05:30")
    assert ("mumbai", True) in lives_in("meera iyer"), lives_in("meera iyer")

    # readable in FalkorDB Browser: typed labels; the current city is a LIVES_IN edge, the old one a WAS edge
    rows = db.run(T, "browser view", "MATCH (c:Customer {name_key:'meera iyer'})-[r]->(x:City) "
                  "RETURN type(r), x.name_key, labels(x) ORDER BY type(r)", ro=True)
    assert rows == [["LIVES_IN", "mumbai", ["Entity", "City"]], ["WAS", "chennai", ["Entity", "City"]]], rows

    # conversation history: both sides, grouped by session, oldest first
    conv = c.get(f"/api/tenants/{T}/conversation", params={"customer": "Meera Iyer"}).json()
    msgs = [m for s in conv["sessions"] for m in s["messages"]]
    assert msgs[0]["text"].startswith("Hi, I live in Chennai") and {"customer", "intake"} <= {m["speaker"] for m in msgs}
    assert any(s["session_id"] == sid and len(s["messages"]) >= 4 for s in conv["sessions"]), conv

    # privacy: a brand-new customer must never be told about another customer's memory
    from relay import memory
    memory.remember(T, agent="intake", session_id="s-divya", customer="Divya Menon", at="2026-10-02T10:00:00+05:30",
                    text="Divya reported connection drops", facts=[("divya menon", "reported_issue", "connection drops"),
                                                               ("divya menon", "has_ticket", "pml-2065")])
    assert retrieve.customer_context(T, "Tharun Test") == []
    r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Tharun Test", "text": "Is your service available in Chennai?",
                                                "at": "2026-10-07T10:00:00+05:30"}).json()
    low = r["reply"].lower()
    assert "divya" not in low and "pml-2065" not in low and "connection drop" not in low, r["reply"]
    assert not any(ord(ch) > 0x2600 for ch in r["reply"]), f"emoji in reply: {r['reply']!r}"
    assert r["reply_episode_id"] and r["episode_id"], r
    assert not [x for x in r["learned"] if x["predicate"] == "lives_in"], "asking about coverage is not living there"

    # usage ledger: real calls counted, limits editable, routes editable
    u = c.get("/api/usage").json()
    assert {"openai/gpt-oss-20b", "openai/gpt-oss-120b"} <= {m["model"] for m in u["models"]}
    assert sum(m["used"]["requests"] + m["used"]["cache_hits"] for m in u["models"]) > 0
    m = c.put("/api/usage/limits", json={"model": "gemini:gemini-3.5-flash-lite", "rpd": 1500}).json()
    assert next(x for x in m["models"] if x["model"] == "gemini:gemini-3.5-flash-lite")["limits"]["rpd"] == 1500
    routes = u["routes"]["summary"]
    assert c.put("/api/usage/routes", json={"job": "summary", "models": routes[::-1]}).json()["routes"]["summary"] == routes[::-1]
    c.put("/api/usage/routes", json={"job": "summary", "models": routes})
    (usage._DIR / "routes.json").unlink(missing_ok=True)  # don't leave a test override behind
    assert c.put("/api/usage/routes", json={"job": "nope", "models": ["x"]}).status_code == 400
    assert not usage.exhausted("never-used-model")

    # benchmark tenants can't be wiped from the app
    for path in ("reset", "sim/start"):
        assert c.post(f"/api/tenants/pml-bench/{path}", json={"scenario": "empty"}).status_code == 403

    off()
    db.graph(T).delete()
    print("test_round2: all checks passed")


if __name__ == "__main__":
    test_all()
