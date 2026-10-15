"""locked.in's service lines (Fiber, Gaming Zone, Binge Club, The Hub) are memory Mr.Lowkey can search, and he stays
inside them: no named streaming partners, no promised ping. Run: python -m tests.test_lockedin"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, kb

T = "test-lockedin"
TRANSCRIPT = [
    "hey I'm Arjun, what do you guys offer?",
    "do you have anything for gamers?",
    "can you guarantee 20 ms ping in valorant?",
    "is netflix included with the plans?",
]


def main():
    c = TestClient(app)
    db.reset(T)
    sid, replies = None, []
    for i, text in enumerate(TRANSCRIPT):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Arjun", "text": text, "session_id": sid,
                                                    "at": f"2026-10-14T18:{10 + i:02d}:00+05:30"}).json()
        sid = r["session_id"]
        replies.append(r["reply"])
        print(f"YOU:       {text}\nMR.LOWKEY: {r['reply']}\n")
    n = db.run(T, "offerings", "MATCH (o:Offering) RETURN count(o)")[0][0]
    assert n >= 14, n
    assert any(k.startswith("Gaming Zone, Gaming dashboard") for k in kb.relevant(T, "do you have a gaming dashboard?"))
    assert "kavya" not in " ".join(replies).lower() and "ping me later" not in " ".join(replies).lower()
    assert "gam" in replies[1].lower(), "gamers hear about the Gaming Zone"
    assert "guarantee" not in replies[2].lower().replace("can't guarantee", "").replace("cannot guarantee", "") \
        .replace("don't guarantee", "").replace("no guarantee", ""), "no promised ping"
    assert "netflix is included" not in replies[3].lower() and "includes netflix" not in replies[3].lower(), \
        "no unconfirmed partner"
    assert "i remember" not in replies[2].lower(), "'I remember' is for what the customer said, not policy"
    assert "partnership" not in replies[3].lower(), "internal partner policy stays internal"
    assert " ".join(replies[1:]).lower().count("got this") == 0, "the tagline isn't filler"
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_lockedin: all checks passed")
