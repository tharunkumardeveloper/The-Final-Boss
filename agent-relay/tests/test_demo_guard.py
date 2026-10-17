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


if __name__ == "__main__":
    test_demo_guard()
    print("demo guard ok")
