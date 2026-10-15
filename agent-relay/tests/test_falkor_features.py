"""FalkorDB features: geo points and distance(), GRAPH.COPY snapshots, GRAPH.SLOWLOG, GRAPH.INFO health, MaxFlow,
harmonic centrality and MSF on the network. No LLM. Run: python -m tests.test_falkor_features"""
from relay import db, kb, memory, network

T = "test-falkor"


def main():
    db.reset(T)  # an India-region tenant: catalogue, network, points, link specs
    g = db.graph(T)
    # geo: every served city has a point; Goa (we don't serve it) is nearest to a city we do
    assert g.query("MATCH (c:City) WHERE c.location IS NULL RETURN count(c)").result_set == [[0]]
    near = kb.nearest_served(T, "goa")
    print("nearest to Goa:", near)
    assert near and near["city"] in ("Pune", "Mumbai", "Bengaluru") and 200 < near["km"] < 600, near
    assert kb.locate("goa", "in")[2] == "IN", "Goa, India, not Goa, Philippines"

    # network: capacities, cable km, harmonic centrality, max flow, minimum spanning forest
    assert g.query("MATCH ()-[u:UPLINK]->() WHERE u.capacity_gbps IS NULL OR u.km IS NULL RETURN count(u)").result_set == [[0]]
    assert g.query("MATCH (n:NetNode) WHERE n.harmonic IS NULL RETURN count(n)").result_set == [[0]]
    before = network.capacity(T, "olt-pune-baner")["gbps"]
    assert before == 10.0, before  # an area exchange: one 10 Gbps link to its POP
    pop = network.capacity(T, "pop-pune")["gbps"]
    assert pop >= 100.0, pop
    network.fail(T, "pop-pune", at="2026-10-15T10:00:00+05:30")
    assert network.capacity(T, "olt-pune-baner")["gbps"] == 0.0, "nothing flows through a failed POP"
    network.restore(T, "pop-pune", at="2026-10-15T11:00:00+05:30")
    assert network.capacity(T, "olt-pune-baner")["gbps"] == 10.0
    plan = network.cable_plan(T)
    assert 0 < plan["km"] <= plan["all_km"] and plan["links"] <= plan["all_links"], plan

    # snapshots: copy, list, change, restore
    memory.remember(T, agent="intake", session_id="s", customer="asha", at="2026-10-15T10:00:00+05:30",
                    speaker="customer", text="I live in Pune", facts=[("asha", "lives_in", "pune")])
    name = db.snapshot(T, "test")
    assert db.snapshots(T)[0]["name"] == name
    g.query("MATCH (c:Customer {name_key:'asha'}) DETACH DELETE c")
    db.restore(T, name)
    assert db.graph(T).query("MATCH (c:Customer {name_key:'asha'}) RETURN count(c)").result_set == [[1]], "restored"
    db.client().select_graph(name).delete()

    # health and slow queries are live reads from the server
    h = db.health()
    assert h["ok"] and h["ping_ms"] > 0 and h["running"] >= 0 and "QUERY_MEM_CAPACITY" in h["config"], h
    assert isinstance(db.slowlog(T), list)
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_falkor_features: all checks passed")
