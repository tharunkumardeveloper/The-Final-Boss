"""Constraints and indexes visible in FalkorDB Browser's schema view, and fuzzy entity linking through the full-text
index. No LLM needed. Run: python -m tests.test_schema"""
from relay import db, memory, queries as Q, retrieve

T = "test-schema"


def main():
    db.reset(T)
    at = "2026-10-15T10:00:00+05:30"
    for name, city in [("alice rao", "pune"), ("bob menon", "mumbai"), ("chitra iyer", "chennai"), ("chitra rao", "pune")]:
        memory.remember(T, agent="intake", session_id=f"s-{name}", customer=name, at=at, speaker="customer",
                        text=f"I live in {city}", facts=[(name, "lives_in", city)])
        db.run(T, "profile", Q.PROFILE, {"c": name, "name": name.title(), "at": 1, "at_dt": None})
    g = db.graph(T)

    cons = {(r[0], r[1], tuple(r[2]), r[-1]) for r in g.query("CALL db.constraints()").result_set}
    want = {(k, label, (p,), "OPERATIONAL") for k, label, p in Q.CONSTRAINTS}
    assert want <= cons, want - cons
    idx = {r[0]: r[2] for r in g.query("CALL db.indexes()").result_set}
    assert idx.get("Customer", {}).get("name") == ["FULLTEXT"], idx.get("Customer")

    # exact names still win; a typo finds the one customer it fits
    assert retrieve.detect_entities(T, "where does alice rao live?") == ["alice rao"]
    assert "alice rao" in retrieve.detect_entities(T, "where does alise rao live?"), "one typo"
    assert "bob menon" in retrieve.detect_entities(T, "what plan is bob menn on?"), "typo in the last name"
    # two customers fit "chitra" equally: no guess
    assert not any(k.startswith("chitra") for k in retrieve.fuzzy_customers(T, "chitraa")), "ambiguous: no guess"

    # a mandatory property is enforced by the database itself
    try:
        g.query("CREATE (:Fact {predicate:'lives_in'})")
        raise AssertionError("a Fact without triple_key was accepted")
    except Exception as e:
        assert "mandatory" in str(e).lower(), e
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_schema: all checks passed")
