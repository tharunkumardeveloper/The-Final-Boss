"""Dayal's chat (from the portal): a gamer and content creator. Every question and want is memory (not only the job),
pictures come from Wikipedia only for named things, once each, and the bot sells: an offer comes up unasked.
Run: python -m tests.test_dayal"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, retrieve

T = "test-dayal"
TRANSCRIPT = [
    "Dayal",
    "What are the services that you guys offer?",
    "gaming",
    "cool this looks nice can i get any game based offers as well",
    "nono any video game that u guys would provide me based on the console or device that i have",
    "im a yt content creator and i play GTA 5",
]


def main():
    c = TestClient(app)
    db.reset(T)
    sid, replies, pics = None, [], []
    for i, text in enumerate(TRANSCRIPT):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Dayal", "text": text, "session_id": sid, "greeted": True,
                                                    "at": f"2026-10-14T17:{32 + i:02d}:00+05:30"}).json()
        sid = r["session_id"]
        replies.append(r["reply"])
        pics.append([p["title"] for p in (r.get("images") or {}).get("images", [])])
        print(f"YOU: {text}\nBOT: {r['reply']}\n     pictures: {pics[-1]}\n")
    facts = {(p, o) for _, p, o, on, *_ in retrieve.history(T, "dayal") if on}
    print("facts:", sorted(facts))
    preds = {p for p, _ in facts}
    assert {"asked_about", "plays_game"} <= preds and any("creator" in o for _, o in facts), facts
    assert ("plays_game", "gta 5") in facts, facts
    assert any(p in ("interested_in", "requested") for p in preds), facts
    assert not any(pics[:3]), "no pictures for a name, the services question or a bare 'gaming'"
    assert pics[5] == ["Grand Theft Auto V"], pics[5]
    sold = " ".join(replies[2:]).lower()
    assert "gaming boost" in sold and ("₹" in sold or "/month" in sold or "a month" in sold), "an offer with its price"
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_dayal: all checks passed")
