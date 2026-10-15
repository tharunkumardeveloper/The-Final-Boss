"""A Chicago prospect on the India desk: the address becomes facts, Kavya answers coverage instead of stalling, and
any price she quotes is the US one. Run: python -m tests.test_pallavi"""
import re

from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import converse, db, retrieve

T = "test-pallavi"  # region "in" by default, like the portal's pml desk

TRANSCRIPT = [
    "do u guys provide service in the chicago state",
    "what are the services u guys provide",
    "i would prefer a broadband installation",
    "175 North State Street, Chicago, IL 60601",
    "is it there?",
    "when will u know?",
    "any update?",
    "what plans do you have there and how much?",
    "ok book fiber 300 for me",
]


def main():
    c = TestClient(app)
    db.reset(T)
    sid, replies = None, []
    for i, text in enumerate(TRANSCRIPT):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Pallavi", "text": text, "session_id": sid,
                                                    "at": f"2026-10-14T08:{40 + i:02d}:00+05:30"}).json()
        sid = r["session_id"]
        replies.append(r["reply"])
        print(f"YOU:   {text}\nKAVYA: {r['reply']}\n")
        assert not converse._STALL.search(r["reply"]), "promised to check later"
        assert "₹" not in r["reply"] and not re.search(r"\b(inr|rupees?)\b", r["reply"], re.I), "India prices for Chicago"
    facts = {(p, o) for _, p, o, active, *_ in retrieve.history(T, "pallavi") if active}
    print("facts:", sorted(facts))
    assert ("lives_in", "chicago") in facts, facts
    assert any(p == "address" and "175 north state street" in o for p, o in facts), facts
    assert "serve" in replies[4].lower(), replies[4]  # "is it there?" gets a yes, not "still checking"
    assert "can't schedule" not in " ".join(replies).lower(), "booking works in chat"
    assert "$" in replies[-2], "US plans are quoted in dollars"
    orders = c.get(f"/api/tenants/{T}/orders", params={"customer": "pallavi"}).json()
    assert orders and orders[0]["plan"] == "fiber 300", orders
    profile = db.graph(T).query("MATCH (c:Customer {name_key:'pallavi'}) RETURN c.city, c.address").result_set
    assert profile[0][0] == "chicago" and "175 north state street" in profile[0][1], profile
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_pallavi: all checks passed")
