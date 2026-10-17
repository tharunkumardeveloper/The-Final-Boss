"""Learned trust (memory.rerank / effective_trust): people's confirmations re-rank future disagreements; with no
confirmations the order is exactly the query's. Pure functions: no database, no LLM. Run: python -m tests.test_learned_trust"""
from relay.memory import effective_trust, rerank

# ACTIVE_CLAIMS rows: fact_id, value, asserted_by, support (fixed trust), last_seen
ROWS = [("f1", "fiber 300", "intake", 0.9, 100), ("f2", "fiber 100", "resolver", 0.6, 200)]


def test_learned_trust():
    assert rerank(ROWS, {}) is ROWS  # nobody has confirmed anything: untouched, same order
    assert effective_trust(0.6, 0) == 0.6 and effective_trust(0.6, 2) == 0.7 and effective_trust(0.9, -3) == 0.75
    assert effective_trust(0.9, 50) == 0.99 and effective_trust(0.6, -50) == 0.05  # never certain, never zero
    # the resolver was right about plans 7 times and intake wrong 1 time: the resolver's claim now ranks first
    out = rerank(ROWS, {"resolver": 7, "intake": -1})
    assert [r[0] for r in out] == ["f2", "f1"] and out[0][3] == 0.95 and out[1][3] == 0.85
    # equal learned trust: the more recent claim wins (the read-time policy's tie-break)
    tie = rerank([("a", "x", "p", 0.6, 100), ("b", "y", "q", 0.6, 300)], {"p": 1, "q": 1})
    assert [r[0] for r in tie] == ["b", "a"]
    # CLAIMS rows carry more columns after last_seen: they are kept as they were
    wide = rerank([("f1", "v", "intake", 0.9, 1, ["intake"], 0, 0, None, None, None, None)], {"intake": 1})
    assert wide[0][3] == 0.95 and len(wide[0]) == 12 and wide[0][5] == ["intake"]


if __name__ == "__main__":
    test_learned_trust()
    print("learned trust ok")
