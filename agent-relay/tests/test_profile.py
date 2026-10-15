"""Customer nodes carry a readable profile for FalkorDB Browser. Run: python -m tests.test_profile"""
from relay import db, memory, orders
T = "test-profile"
db.reset(T)
memory.ingest_turn(T, agent="intake", session_id="s1", customer="Asha", text="I live in Koramangala and I'll buy Fiber 300, budget 1000 rupees",
                   at="2026-10-13T10:00:00+05:30")
p = db.graph(T).query("MATCH (c:Customer {name_key:'asha'}) RETURN c.name, c.city, c.budget, c.pending_order").result_set
assert p == [["Asha", "koramangala", "1000 inr", "fiber 300"]], p
o = orders.for_customer(T, "asha")[0]["order_id"]
orders.install(T, o, "2026-10-14T10:00:00+05:30")
r = db.graph(T).query("MATCH (c:Customer {name_key:'asha'}) RETURN c.city, c.plan, c.pending_order").result_set
print(r); assert r[0][1] == "fiber 300" and r[0][2] is None, r
db.graph(T).delete(); print("test_profile: all checks passed")
