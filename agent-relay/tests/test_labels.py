"""Labels that carry state, so FalkorDB Browser's schema view and label filters say something. No LLM needed.
Run: python -m tests.test_labels"""
from relay import db, memory, orders, queries as Q

T = "test-labels"


def labels(query, params=None):
    return {tuple(sorted(r[0])) for r in db.graph(T).query(query, params or {}).result_set}


def main():
    db.reset(T)
    at = "2026-10-15T10:00:00+05:30"
    memory.remember(T, agent="intake", session_id="s1", customer="asha", at=at, speaker="customer",
                    text="I live in Pune", facts=[("asha", "lives_in", "pune")])
    memory.remember(T, agent="intake", session_id="s1", customer="asha", at="2026-10-16T10:00:00+05:30",
                    speaker="customer", text="I moved to Mumbai", facts=[("asha", "lives_in", "mumbai")])
    ep = memory.remember(T, agent="intake", session_id="s1", customer="asha", at=at, text="note", facts=[])["episode_id"]
    memory.remember(T, agent="intake", session_id="s1", customer="asha", at=at, speaker="customer",
                    text="I own a PS5", facts=[("asha", "owns_device", "ps5")])
    memory.retire_fact(T, agent="intake", episode_id=ep, subject="asha", predicate="owns_device", obj="ps5",
                       at="2026-10-17T10:00:00+05:30")
    facts = labels("MATCH (f:Fact {subject:'asha'}) RETURN labels(f)")
    assert facts == {("Current", "Fact"), ("Fact", "Superseded"), ("Fact", "Retired")}, facts
    kinds = labels("MATCH (e:Episode) RETURN labels(e)")
    assert ("CustomerMessage", "Episode") in kinds and ("Episode", "InternalNote") in kinds, kinds

    db.run(T, "profile", Q.PROFILE, {"c": "asha", "name": "Asha", "at": 1, "at_dt": None})
    assert ("Customer", "Entity", "Prospect") in labels("MATCH (c:Customer {name_key:'asha'}) RETURN labels(c)")
    memory.remember(T, agent="intake", session_id="s1", customer="asha", at=at, speaker="customer",
                    text="business connection", facts=[("asha", "on_plan", "fiber 300"), ("asha", "connection_type", "business")])
    db.run(T, "profile", Q.PROFILE, {"c": "asha", "name": "Asha", "at": 2, "at_dt": None})
    c = labels("MATCH (c:Customer {name_key:'asha'}) RETURN labels(c)")
    assert c == {("Business", "Customer", "Entity", "Subscriber")}, c

    memory.remember(T, agent="intake", session_id="s1", customer="asha", at=at, text="opened",
                    facts=[("asha", "has_ticket", "pml-1"), ("pml-1", "has_status", "open"), ("pml-1", "has_priority", "high")])
    db.run(T, "ticket", Q.TICKET_PROFILE, {"t": "pml-1"})
    t = labels("MATCH (t:Entity {name_key:'pml-1'}) RETURN labels(t)")
    assert t == {("Entity", "HighPriority", "Open", "Ticket")}, t

    memory.remember(T, agent="intake", session_id="s1", customer="kiran", at=at, speaker="customer",
                    text="I live in Pune", facts=[("kiran", "lives_in", "pune")])
    o = orders.place(T, customer="kiran", plan="fiber 300", at=at)
    assert ("Order", "Pending") in labels("MATCH (o:Order) RETURN labels(o)")
    orders.install(T, o["order_id"], "2026-10-16T10:00:00+05:30")
    assert labels("MATCH (o:Order) RETURN labels(o)") == {("Installed", "Order")}

    # the one-time backfill is idempotent on a graph that already has the labels
    db.state_labels(T)
    assert labels("MATCH (f:Fact {subject:'asha', predicate:'lives_in'}) RETURN labels(f)") == {("Current", "Fact"), ("Fact", "Superseded")}
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_labels: all checks passed")
