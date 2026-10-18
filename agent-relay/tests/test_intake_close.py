"""From a real chat: a plan upgrade was escalated as a repeat of a network fault, and "resolve the tickets, everything
is fine" was ignored. No database; same_problem uses the local embedding model when words don't overlap.
Run: python -m tests.test_intake_close"""
from relay import intake, lab


def test_close_ask():
    for ask in ("resolve the tickets i have connection right now. everything is fine", "please close my ticket",
                "you can close it now", "cancel the complaint", "mark it as resolved", "close PML-2050-4E00"):
        assert intake.CLOSE_ASK.search(ask), ask
    for other in ("my internet is closed off", "cancel my connection", "I want to cancel my plan", "is my ticket open?",
                  "everything is slow", "can you resolve my wifi drops"):
        assert not intake.CLOSE_ASK.search(other), other


def test_same_problem():
    assert intake.same_problem("evening wifi drops", "wifi drops at night")
    assert intake.same_problem("no internet", "internet down") is not None
    assert not intake.same_problem("network difficulties", "plan upgrade")
    assert not intake.same_problem("damaged router", "billing dispute")


def test_resolver_owns_only_its_replies():
    # while it waits on the customer, the resolver takes what's about its case; anything else is intake's to answer
    assert lab.owns_reply("details", "Flat 4, 2nd Cross Road, Adyar") and lab.owns_reply("details", "evening works")
    assert lab.owns_reply("details", "9876512345")
    assert not lab.owns_reply("details", "I'd also like to request a plan upgrade to fiber 1000")
    assert lab.owns_reply("busy", "what should I try?") and not lab.owns_reply("busy", "do you have a fiber 1000 plan?")
    assert lab.owns_reply("confirm", "connection is fine right now. everything is fine")
    assert not lab.owns_reply("confirm", "what plans do you have")
    assert lab._YES.search("everything is fine") and lab._NO.search("still not working")


if __name__ == "__main__":
    test_close_ask()
    test_same_problem()
    test_resolver_owns_only_its_replies()
    print("intake close + repeat ok")
