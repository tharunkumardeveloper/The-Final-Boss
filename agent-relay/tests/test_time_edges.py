"""Edges that change over time: a replaced or retired fact edge becomes a WAS edge with valid_from/valid_to, and a
multi-hop traversal at time t filters edges while it expands. No LLM needed. Run: python -m tests.test_time_edges"""
from relay import db, memory, retrieve
from relay.memory import to_ms

T = "test-time-edges"
D = lambda day: to_ms(f"2026-09-{day:02d}T10:00:00+05:30")  # noqa: E731


def ends(t):
    return {(tuple(x["path"]), tuple(x["predicates"]), tuple(x["past"])) for x in retrieve.graph_at(T, "alice", t)}


def main():
    db.reset(T)
    say = lambda day, facts: memory.remember(T, agent="intake", session_id=f"s{day}", customer="alice", at=D(day),  # noqa: E731
                                             speaker="customer", text="...", facts=[f + (D(day),) for f in facts])
    say(1, [("alice", "lives_in", "chennai"), ("alice", "owns_device", "ps5")])
    say(5, [("alice", "has_ticket", "pml-9"), ("pml-9", "ticket_about", "evening wifi drops")])
    say(10, [("alice", "lives_in", "pune")])                      # a move: chennai becomes a WAS edge
    ep = say(12, [])["episode_id"]
    memory.retire_fact(T, agent="intake", episode_id=ep, subject="alice", predicate="owns_device", obj="ps5", at=D(12))

    g = db.graph(T)
    was = g.query("MATCH (:Entity {name_key:'alice'})-[w:WAS]->(o) RETURN o.name_key, w.predicate, w.valid_from, w.valid_to "
                  "ORDER BY o.name_key").result_set
    assert was == [["chennai", "lives_in", D(1), D(10)], ["ps5", "owns_device", D(1), D(12)]], was
    assert g.query("MATCH (:Entity {name_key:'alice'})-[r:LIVES_IN]->(o) RETURN o.name_key, r.valid_from").result_set == [["pune", D(10)]]

    on_3 = ends(D(3))   # before the ticket: Chennai and the PS5, both now in the past
    assert (("alice", "chennai"), ("lives_in",), (True,)) in on_3 and (("alice", "ps5"), ("owns_device",), (True,)) in on_3, on_3
    assert not any("pml-9" in p for p, _, _ in on_3), "the ticket didn't exist yet"
    on_7 = ends(D(7))   # two hops, both valid on the 7th
    assert (("alice", "pml-9", "evening wifi drops"), ("has_ticket", "ticket_about"), (False, False)) in on_7, on_7
    now = ends(D(20))
    assert (("alice", "pune"), ("lives_in",), (False,)) in now and not any("chennai" in p or "ps5" in p for p, _, _ in now), now

    # a graph written before edges carried time is backfilled the same way, once
    db.setup(T)
    assert len(g.query("MATCH (:Entity {name_key:'alice'})-[w:WAS]->() RETURN w").result_set) == 2, "backfill is idempotent"
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_time_edges: all checks passed")
