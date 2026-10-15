"""Replay the conversation that went wrong, on the weakest model, and print Kavya's replies.
Run: python -m tests.replay_kavya"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import config, db

T = "test-kavya"
config.ROUTES["reply"] = ["allam-2-7b"]  # worst case: every better model out of quota
c = TestClient(app)
db.reset(T)
sid = None
for i, msg in enumerate(["whats my name", "there is an issue with the fiber", "ummmm", "why are u typing so much",
                         "I moved house last week, to madurai", "why are u saying updated field and all"]):
    r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Tharun", "text": msg, "session_id": sid,
                                                "at": f"2026-10-13T18:{50 + i}:00+05:30"}).json()
    sid = r["session_id"]
    print(f"YOU:   {msg}\nKAVYA: {r['reply']}  ({len(r['reply'].split())} words)\n")
    low = r["reply"].lower()
    assert "ps5" not in low and "field" not in low and "[" not in r["reply"] and len(r["reply"].split()) <= 61, r["reply"]
db.graph(T).delete()
print("replay ok")
