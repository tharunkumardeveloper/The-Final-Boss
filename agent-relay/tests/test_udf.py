"""The relay UDF library returns readable text from inside FalkorDB queries. No LLM needed.
Run: python -m tests.test_udf"""
from relay import db, memory, udf
from relay.memory import to_ms

T = "test-udf"


def main():
    db.reset(T)  # setup loads the library
    udf.load(force=True)
    at = lambda d: to_ms(f"2026-09-{d:02d}T10:00:00+05:30")  # noqa: E731
    memory.remember(T, agent="intake", session_id="s", customer="alice rao", at=at(1), speaker="customer", text="..",
                    facts=[("alice rao", "lives_in", "chennai")])
    memory.remember(T, agent="intake", session_id="s", customer="alice rao", at=at(9), speaker="customer", text="..",
                    facts=[("alice rao", "lives_in", "pune")])
    g = db.graph(T)
    said = sorted(r[0] for r in g.query("MATCH (f:Fact {subject:'alice rao'}) RETURN relay.sentence(f)").result_set)
    assert said == ["Alice Rao lives in Pune", "Alice Rao no longer lives in Chennai (replaced)"], said
    assert g.query("RETURN relay.money(949, 'INR'), relay.money(37.99, 'GBP'), relay.money(1399, 'INR'), relay.money(0, 'INR')"
                   ).result_set == [["₹949", "£37.99", "₹1,399", "free"]]
    assert g.query(f"RETURN relay.ago({at(1)}, {at(4)})").result_set == [["3 days ago"]]
    states = {r[0] for r in g.query("MATCH (f:Fact) RETURN relay.state(f)").result_set}
    assert states == {"Current", "Superseded"}, states
    listed = db.client().connection.execute_command("GRAPH.UDF", "LIST")
    assert "relay" in str(listed), listed
    # FalkorDB's FLEX library loads beside ours; its edit distance ranks fuzzy names
    assert g.query("RETURN flex.text.levenshtein('alise', 'alice')").result_set == [[1]]
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_udf: all checks passed")
