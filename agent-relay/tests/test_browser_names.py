"""What a judge sees in FalkorDB Browser: typed labels, typed edges, a readable `name` on every node,
and old graphs migrated in place. Run: python -m tests.test_browser_names"""
from relay import db, memory

T = "test-names"


def test_all():
    db.reset(T)
    memory.remember(T, agent="intake", session_id="s1", customer="Alice Rao", at="2026-10-01T10:00:00+05:30",
                    text="I live in Pune", facts=[("alice rao", "lives_in", "pune")])
    q = lambda s: db.graph(T).ro_query(s).result_set
    assert q("MATCH (n) WHERE n.name IS NULL RETURN labels(n), count(*)") == [], "every node has a name"
    assert q("MATCH (f:Fact) RETURN f.name") == [["alice rao LIVES_IN pune"]]
    # simulate an old graph: a generic RELATED edge and an unlabelled entity, then setup migrates it
    db.graph(T).query("MATCH (a:Customer)-[r:LIVES_IN]->(b) CREATE (a)-[:RELATED {predicate:'lives_in', fact_id:r.fact_id}]->(b) "
                      "DELETE r REMOVE a:Customer")
    db.setup(T)
    assert q("MATCH (a:Customer)-[r]->(b:City) RETURN type(r), a.name_key, b.name") == [["LIVES_IN", "alice rao", "Pune"]]
    assert q("MATCH ()-[r:RELATED]->() RETURN count(r)") == [[0]]
    db.graph(T).delete()
    print("test_browser_names: all checks passed")


if __name__ == "__main__":
    test_all()
