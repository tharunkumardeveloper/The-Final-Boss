"""Schema items 1-9: sessions, written-by, escalation, notifications, outage state, technician visits, service pause,
simulator agent. No LLM needed. Run: python -m tests.test_schema_items"""
from relay import agents, db, experts, memory, network, queries as Q

T = "test-schema-items"
AT = "2026-10-15T10:00:00+05:30"


def one(q, p=None):
    return db.graph(T).query(q, p or {}).result_set


def main():
    db.reset(T)
    memory.remember(T, agent="intake", session_id="asha-s1", customer="asha", at=AT, speaker="customer",
                    text="I live in Baner", facts=[("asha", "lives_in", "baner")])
    memory.remember(T, agent="intake", session_id="asha-s1", customer="asha", at="2026-10-15T10:05:00+05:30",
                    speaker="customer", text="my wifi drops", facts=[("asha", "reported_issue", "wifi drops")])
    # 1. session linked to the customer, with start/end and readable times
    s = one("MATCH (:Customer {name_key:'asha'})-[:HAS_SESSION]->(s:Session) RETURN s.started_dt, s.ended_dt, s.ended_at > s.started_at")
    assert s and s[0][2] and s[0][0] and s[0][1], s
    # 2. every fact one hop from the agent that wrote it
    assert one("MATCH (f:Fact {subject:'asha'})-[:WRITTEN_BY]->(a:Agent) RETURN count(f), collect(DISTINCT a.agent_id)") == [[2, ["intake"]]]
    # 9. the simulator is an agent like the others
    assert one("MATCH (a:Agent {agent_id:'simulator'}) RETURN a.trust") == [[0.5]]

    memory.remember(T, agent="intake", session_id="asha-s1", customer="asha", at=AT, text="opened",
                    facts=[("asha", "has_ticket", "pml-1"), ("pml-1", "ticket_about", "wifi drops"),
                           ("pml-1", "has_status", "open"), ("pml-1", "assigned_to", "resolver")])
    # 4. escalation node + customer flag
    db.run(T, "escalate", Q.ESCALATE, {"t": "pml-1", "id": "esc-1", "reason": "contacted us before", "by": "intake",
                                      "at": memory.to_ms(AT), "at_dt": memory.dt(AT)})
    assert one("MATCH (:Entity {name_key:'pml-1'})-[:ESCALATED]->(e:Escalation) RETURN e.reason, e.raised_by") == [["contacted us before", "intake"]]
    assert one("MATCH (c:Customer {name_key:'asha'}) RETURN c.is_escalated") == [[True]]

    # 5 + 7. the NOC: an outage with state and an ETA, a notification per customer, then resolved
    out = network.fail(T, "olt-pune-baner", at=AT)
    assert "asha" in out["notified"], out
    o = one(f"MATCH (o:Outage {{name_key:'{out['outage']}'}}) RETURN o.active, o.eta > o.started_at, o.eta_dt IS NOT NULL")
    assert o == [[True, True, True]], o
    n = one("MATCH (:Customer {name_key:'asha'})-[:RECEIVED]->(n:Notification)-[:ABOUT]->(o:Outage) RETURN n.kind, n.channel")
    assert n == [["outage warning", "chat"]], n
    network.restore(T, "olt-pune-baner", at="2026-10-15T12:00:00+05:30")
    assert one(f"MATCH (o:Outage {{name_key:'{out['outage']}'}}) RETURN o.active, o.resolved_dt IS NOT NULL") == [[False, True]]
    assert len(one("MATCH (:Customer {name_key:'asha'})-[:RECEIVED]->(n:Notification) RETURN n")) == 2

    # 6. technician visit: scheduled at assignment, done when the fix works
    tech = experts.assign(T, "pml-1", "pune", AT)
    v = one("MATCH (x:Entity {name_key:$t})-[:VISITS]->(v:TechVisit)-[:FOR_TICKET]->(:Entity {name_key:'pml-1'}) "
            "RETURN v.status, v.scheduled_dt IS NOT NULL", {"t": tech})
    assert v == [["scheduled", True]], v
    agents.Resolver().try_fix(T, ticket="pml-1", fix="change wifi channel", worked=True, at="2026-10-16T11:00:00+05:30")
    assert one("MATCH (v:TechVisit {visit_id:'visit-pml-1'}) RETURN v.status, v.outcome") == [["done", "resolved by change wifi channel"]]

    # 8. a pause request as its own node
    db.run(T, "pause", Q.SERVICE_PAUSE, {"c": "asha", "t": "pml-1", "id": "pause-1", "reason": "travelling for 2 months",
                                        "at": memory.to_ms(AT), "at_dt": memory.dt(AT)})
    assert one("MATCH (:Customer {name_key:'asha'})-[:REQUESTED]->(p:ServicePause)-[:FOR_TICKET]->() RETURN p.status") == [["requested"]]

    # backfill is idempotent
    db.setup(T)
    assert one("MATCH (:Customer {name_key:'asha'})-[r:HAS_SESSION]->() RETURN count(r)")[0][0] >= 1
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_schema_items: all checks passed")
