"""Identifiers 10-16: ticket times, handoff/event ids, fact metadata and corroboration, provenance, Conflict nodes,
customer signals. No LLM needed. Run: python -m tests.test_identifiers"""
from relay import agents, db, events, memory, queries as Q

T = "test-identifiers"
AT = lambda d: f"2026-10-{d:02d}T10:00:00+05:30"  # noqa: E731


def one(q, p=None):
    return db.graph(T).query(q, p or {}).result_set


def main():
    db.reset(T)
    got = []
    stop = events.subscribe(T, got.append)
    memory.remember(T, agent="intake", session_id="kiran-s1", customer="kiran", at=AT(1), speaker="customer",
                    text="I'm on Fiber 300", facts=[("kiran", "on_plan", "fiber 300")])
    memory.remember(T, agent="intake", session_id="kiran-s2", customer="kiran", at=AT(2), speaker="customer",
                    text="yes Fiber 300", facts=[("kiran", "on_plan", "fiber 300")])
    stop()
    # 11. every live event carries its own id
    assert got and all(len(e.get("id", "")) == 16 for e in got) and len({e["id"] for e in got}) == len(got)

    # 12 + 17/18. registry metadata, corroboration count, readable times, no is_new on the node
    f = one("MATCH (f:Fact {subject:'kiran', predicate:'on_plan'}) RETURN f.cardinality, f.policy, f.registry, "
            "f.corroboration_count, f.learned_dt IS NOT NULL, f.valid_from_dt IS NOT NULL, f.is_new")
    assert f == [["single", "trust", "isp", 2, True, True, None]], f

    # 14. two agents disagree: an open Conflict between the two claims, preferred by trust; resolved when one goes
    memory.remember(T, agent="resolver", session_id="work-x", customer="kiran", at=AT(3), speaker="tool:billing",
                    text="Billing system: kiran is on fiber 100", facts=[("kiran", "on_plan", "fiber 100")])
    c = one("MATCH (c:Conflict:Open {subject:'kiran', predicate:'on_plan'})-[:BETWEEN]->(f:Fact) "
            "RETURN c.preferred, c.resolution_policy, count(f)")
    assert c == [["fiber 300", "trust, then recency", 2]], c
    ep = memory.remember(T, agent="resolver", session_id="work-x", customer="kiran", at=AT(4), text="cleared",
                         facts=[])["episode_id"]
    memory.retire_fact(T, agent="resolver", episode_id=ep, subject="kiran", predicate="on_plan", obj="fiber 100", at=AT(4))
    assert one("MATCH (c:Conflict:Resolved {subject:'kiran'}) RETURN c.resolution") == [["only one claim left active"]]

    # 10. ticket opened/closed times; 11. handoff ids
    memory.remember(T, agent="intake", session_id="kiran-s2", customer="kiran", at=AT(5), text="opened",
                    facts=[("kiran", "has_ticket", "pml-7"), ("pml-7", "ticket_about", "wifi drops"),
                           ("pml-7", "has_status", "open"), ("pml-7", "assigned_to", "resolver")])
    db.run(T, "handoff", Q.HANDOFF, {"from_agent": "intake", "ticket": "pml-7", "at": memory.to_ms(AT(5)),
                                     "to_agent": "resolver", "note": "wifi drops"})
    assert len(one("MATCH ()-[h:HANDED_OFF]->(:Entity {name_key:'pml-7'}) RETURN h.handoff_id")[0][0]) == 36
    agents.Resolver().try_fix(T, ticket="pml-7", fix="change wifi channel", worked=True, at=AT(6))
    t = one("MATCH (t:Ticket {name_key:'pml-7'}) RETURN t.opened_at, t.closed_at, t.status")
    assert t[0][0] == memory.to_ms(AT(5)) and t[0][1] == memory.to_ms(AT(6)) and t[0][2] == "resolved", t

    # 15. customer signals on the profile
    memory.remember(T, agent="intake", session_id="kiran-s2", customer="kiran", at=AT(6), speaker="customer",
                    text="talk in Tamil please", facts=[("kiran", "preferred_language", "tamil")])
    db.run(T, "profile", Q.PROFILE, {"c": "kiran", "name": "Kiran", "at": memory.to_ms(AT(6)), "at_dt": memory.dt(AT(6))})
    p = one("MATCH (c:Customer {name_key:'kiran'}) RETURN c.contact_count, c.same_issue_count, c.preferred_language")
    assert p == [[2, 1, "tamil"]], p  # kiran-s1 and kiran-s2; the resolver's work sessions aren't contacts

    # 13. memory settings on a Meta node
    assert one("MATCH (m:Meta {key:'memory'}) RETURN m.embedding_model, m.dim")[0][1] == 384
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_identifiers: all checks passed")
