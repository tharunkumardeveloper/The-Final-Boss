"""A new prospect in Goa: no "welcome back", one greeting, "what services do you offer" is not a place, and since we
serve everywhere, never "we don't cover Goa" or a waitlist. Run: python -m tests.test_chandran"""
import re

from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, retrieve

T = "test-chandran"
TRANSCRIPT = [
    "Im a gamer and yt content creator living in goa",
    "what services do you offer",
    "why is that",
    "cool, can i get a connection here?",
    "yeah any offers on that?",
    "any offer on the games?",
]


def main():
    c = TestClient(app)
    db.reset(T)
    sid, replies = None, []
    for i, text in enumerate(TRANSCRIPT):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Chandran", "text": text, "session_id": sid,
                                                    "at": f"2026-10-14T13:{35 + i:02d}:00+05:30"}).json()
        sid = r["session_id"]
        replies.append(r["reply"])
        print(f"YOU:   {text}\nBOT:   {r['reply']}\n")
        assert "do you offer" not in r["reply"].lower(), "a question taken as a place"
        low = r["reply"].lower()
        assert not any(x in low for x in ("waitlist", "don't cover", "do not cover", "don't serve", "outside our")), r["reply"]
    assert "welcome back" not in replies[0].lower(), "a first-time visitor isn't welcomed back"
    assert len(re.findall(r"\b(hi|hey|hello)\b", replies[0], re.I)) <= 1, "one greeting"
    facts = {(p, o) for _, p, o, on, *_ in retrieve.history(T, "chandran") if on}
    print("facts:", sorted(facts))
    assert ("lives_in", "goa") in facts, facts
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_chandran: all checks passed")
