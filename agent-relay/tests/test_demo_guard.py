"""Public demo protection: resets need RELAY_RESET_KEY, writes are rate-limited per address. Both run in the HTTP
middleware before any query, so this needs no database and no LLM. Run: python -m tests.test_demo_guard"""
import os

os.environ.update(RELAY_RESET_KEY="test-reset-key", RELAY_CHAT_PER_MIN="2", RELAY_WRITES_PER_MIN="3")

from fastapi.testclient import TestClient  # noqa: E402

from api import main  # noqa: E402


def test_demo_guard():
    c = TestClient(main.app)  # not as a context manager: no startup events, so no database
    # a reset without the key, or with the wrong one, is refused before the tenant check or any query
    r = c.post("/api/tenants/pml/reset", json={"scenario": "empty"})
    assert r.status_code == 403 and r.json()["need"] == "reset_key", r.text
    r = c.post("/api/tenants/pml/lab/reset", headers={"X-Reset-Key": "wrong"})
    assert r.status_code == 403, r.text
    assert c.put("/api/usage/routes", json={}).status_code == 403
    # with the key it gets past the lock (and stops at the tenant key: no tenant key sent)
    r = c.post("/api/tenants/pml/lab/reset", headers={"X-Reset-Key": "test-reset-key"})
    assert r.status_code == 401, r.text
    # reads are never locked or limited
    assert c.get("/api/tenants/pml/reset").status_code == 401
    # chat: 2 per minute per address, then 429 with Retry-After
    codes = [c.post("/api/tenants/pml/chat", json={"customer": "x", "text": "hi"}).status_code for _ in range(3)]
    assert codes[:2] == [401, 401] and codes[2] == 429, codes
    r = c.post("/api/tenants/pml/chat", json={"customer": "x", "text": "hi"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    # another address has its own budget
    assert c.post("/api/tenants/pml/chat", json={"customer": "x", "text": "hi"},
                  headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 401


def test_errors_reach_the_browser():
    """A crash inside a request comes back as a readable 500 with the CORS header (no database here, so a tenant
    request fails for real): the browser shows the error instead of a misleading "blocked by CORS policy"."""
    from relay import tenancy
    main.db.setup = lambda tenant: (_ for _ in ()).throw(ConnectionError("no database in this test"))
    main._ready.discard("pml")
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.get("/api/tenants/pml/stats", headers={"X-Tenant-Key": tenancy.key_for("pml"), "Origin": "https://wifight.vercel.app"})
    assert r.status_code == 500 and "ConnectionError" in r.json()["detail"], r.text
    assert r.headers.get("access-control-allow-origin") in ("*", "https://wifight.vercel.app"), dict(r.headers)


def test_baseline_on_an_empty_graph():
    """The compare baseline on a fresh graph (no episodes) is empty instead of crashing."""
    from eval import run_eval
    real = run_eval.db.run
    run_eval.db.run = lambda *a, **k: []
    try:
        vs = run_eval.VectorStore("pml", [])
        assert vs.texts == [] and vs.lines("what plan is asha on?", dated=True) == []
    finally:
        run_eval.db.run = real


if __name__ == "__main__":
    test_demo_guard()
    test_errors_reach_the_browser()
    test_baseline_on_an_empty_graph()
    print("demo guard ok")
