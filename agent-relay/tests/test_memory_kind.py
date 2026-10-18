"""Which kind of memory a fact is, as the product labels it (registry.memory_kind): facts about the world are semantic,
everything about handling a case is procedural; episodic memory is the messages themselves. No database.
Run: python -m tests.test_memory_kind"""
from relay import registry as R


def test_memory_kind():
    for p in ("lives_in", "on_plan", "has_router", "owns_device", "reported_issue", "prefers_channel", "moving_to", "phone"):
        assert R.memory_kind(p) == "semantic", p
    # a ticket and everything about it, the fixes tried, the one that worked, and what a fix resolves
    for p in ("has_ticket", "ticket_about", "has_status", "assigned_to", "has_priority", "tried_fix", "fixed_by", "resolves",
              "issue_started", "severity", "connection_medium"):
        assert R.memory_kind(p) == "procedural", p
    assert R.memory_kind("not_a_predicate") == "semantic"


if __name__ == "__main__":
    test_memory_kind()
    print("memory kind ok")
