"""The portal conversation that went wrong, replayed on the weakest model, as a regression test.
Run: python -m tests.test_transcript"""
import re

from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import config, converse, db, retrieve

T = "test-transcript"

TRANSCRIPT = [
    "what do you know about me",
    "so i live in chennai currently do you guys provide any service there?",
    "im planning to move to blr by next month so what services do you offer",
    "its at hsr layout bangalore",
    "what fiber broadband services u offer?",
    "can it be used with a mobile?",
    "what plans do you have for 2000 rupees",
    "im willing to buy this but before that how many devices can be connected to this",
    "when can you deliver stuff?",
    "okay i will relocate to koramangala then",
    "can i opt for fiber 1000 for a 1000 rupees",
    "ill buy it i am in koramangala now",
    "how to buy",
    "My wifi drops every evening, mostly on my PS5.",
    "Which plan am I on?",
    "How much is Fiber 300?",
]


def unit():
    bad = converse.catalogue_problems("We have Fiber 200 at Rs 2,000 and Fiber 300 at ₹949.", "Fiber 300 ₹949/month")
    assert bad == ["Fiber 200", "Rs 2,000"], bad
    assert converse.catalogue_problems("Fiber 300 is ₹949.", "Plans: Fiber 300 ₹949/month") == []
    steps = converse._clean("To buy: 1. Pick a plan. 2. Confirm your address. 3. Choose a slot. 4. Pay the first month.")
    assert steps.endswith("4. Pay the first month."), steps
    prices = {"fiber 100": 649, "fiber 300": 949, "fiber 1000": 1399}
    assert converse.catalogue_problems("1000 INR is the monthly price for Fiber 300.", "Fiber 300 ₹949 1000 INR", prices) == ["1000 INR"]
    assert converse.catalogue_problems("Fiber 300 is ₹949/month.", "Fiber 300 ₹949", prices) == []
    note = converse.budget_note("1000 inr", [{"name": n.title(), "label": f"₹{a:,}", "amount": a} for n, a in prices.items()])
    assert "Within budget: Fiber 100 ₹649, Fiber 300 ₹949." in note and "Over budget (never call these a fit): Fiber 1000 ₹1,399." in note, note
    assert converse.catalogue_problems("For 1000 INR I recommend Fiber 1000.", "1000", prices, {"fiber 1000"}) == ["1000 INR", "Fiber 1000 (over their budget)"]
    assert converse.catalogue_problems("Fiber 300 offers 1000 Mbps and handles 60 devices.", "", prices) == ["1000 Mbps", "60 devices"]
    cut = converse._clean("Try this. " + " ".join(f"{i}. Step number {i} of the long fix list." for i in range(1, 12)))
    assert not cut.rstrip().endswith(tuple(f"{i}." for i in range(10))), cut
    assert converse._clean("Hey Tharun! Welcome to Ping Me Later! Fiber 300 is ₹949.", first_turn=False) == "Fiber 300 is ₹949."


def replay():
    config.ROUTES["reply"] = ["allam-2-7b"]  # worst case: every better model is out of quota
    c = TestClient(app)
    db.reset(T)
    sid, replies = None, []
    for i, text in enumerate(TRANSCRIPT):
        r = c.post(f"/api/tenants/{T}/chat", json={"customer": "Tharun", "text": text, "session_id": sid,
                                                    "at": f"2026-10-13T23:{10 + i:02d}:00+05:30"}).json()
        sid = r["session_id"]
        replies.append(r["reply"])
        print(f"YOU:   {text}\nKAVYA: {r['reply']}\n")
        low = r["reply"].lower()
        assert not re.search(r"fiber\s?(200|2000|500)\b", low), "invented plan"
        prices = {p["key"]: p["amount"] for p in converse.kb.price_list(T, "IN")}
        allowed = " ".join(converse.kb.relevant(T, text) + converse.customer_notes(T, "tharun")[0]
                           + [p["label"] for p in converse.kb.price_list(T, "IN")])  # planned replies quote the price list
        budget = next((o for _, p, o, active, *_ in retrieve.history(T, "tharun") if active and p == "budget"), None)
        over = converse.over_budget(budget, converse.kb.price_list(T, "IN"))
        assert not converse.catalogue_problems(r["reply"], allowed, prices, over), r["reply"]
        assert not re.search(r"\b\d\.\s*$", r["reply"]), "a list was cut off"
        assert "opened pml" not in low and "[" not in r["reply"]
    assert "₹949" in replies[-1], "a direct price question gets the price"
    after_hsr = " ".join(replies[3:]).lower()
    assert not converse._NO_COVER.search(after_hsr), "HSR Layout and Koramangala are covered"
    assert replies[-2].startswith("You're not on any of our plans yet."), replies[-2]
    facts = {(p, o) for _, p, o, active, *_ in retrieve.history(T, "tharun") if active}
    assert not any(p == "on_plan" for p, _ in facts), facts
    assert ("lives_in", "koramangala") in facts, facts
    print("orders:", c.get(f"/api/tenants/{T}/orders", params={"customer": "tharun"}).json())
    conv = c.get(f"/api/tenants/{T}/conversation", params={"customer": "tharun"}).json()
    texts = [m["text"].lower() for s in conv["sessions"] for m in s["messages"]]
    assert not any(t.startswith("intake opened") for t in texts), "internal notes leaked into the chat history"
    db.graph(T).delete()


if __name__ == "__main__":
    unit()
    print("unit checks ok")
    replay()
    print("test_transcript: all checks passed")
