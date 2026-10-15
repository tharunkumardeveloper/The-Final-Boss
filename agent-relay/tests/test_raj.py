"""Someone who says they already use us, with nothing on file: Kavya digs (steps shown live), asks for what she needs
before troubleshooting, remembers what she asked, and reads the bare answer against her question.
Run: python -m tests.test_raj"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import converse, db, events, intake, retrieve

T = "test-raj"

TRANSCRIPT = [
    "Im using one of your broadband services and its currently sucks",
    "whenever i play a HD video or stream video it just lags",
    "Baner, Pune",
    "tell me now?",
]


def active(customer):
    return {(p, o) for _, p, o, on, *_ in retrieve.history(T, customer) if on}


def main():
    c = TestClient(app)
    db.reset(T)
    steps = []
    stop = events.subscribe(T, lambda e: e["type"] == "kavya_step" and steps.append(e["data"]["step"]))
    sid, replies, snapshots = None, [], []
    for i, text in enumerate(TRANSCRIPT):
        steps.clear()
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Raj Kumar", "text": text, "session_id": sid,
                                                    "at": f"2026-10-14T09:{25 + i:02d}:00+05:30"}).json()
        sid = r["session_id"]
        replies.append(r["reply"])
        snapshots.append(active("raj kumar"))
        print(f"YOU:   {text}\n  steps: {' > '.join(steps)}\n  facts: {sorted(snapshots[-1])}\nKAVYA: {r['reply']}\n")
        assert steps and steps[-1] == "Writing your reply", steps
        assert not converse._STALL.search(r["reply"]), "promised to check later"
    stop()
    # spec order: who they are before anything else, and no troubleshooting for a stranger
    for r in replies[:2]:
        assert intake.SLOTS["identifier"].words.search(r) and "?" in r, r
        assert not intake.FIX_ADVICE.search(r), r
    assert ("awaiting", "identifier") in snapshots[1], snapshots[1]
    # the bare place is still understood, the network is checked and the result said
    assert ("lives_in", "baner") in snapshots[2], snapshots[2]
    assert "network there is up" in replies[2], replies[2]
    assert not any("?" in s and intake.SLOTS["area"].words.search(s) for r in replies[2:] for s in intake.sentences(r)), \
        "re-asked the area"
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_raj: all checks passed")
