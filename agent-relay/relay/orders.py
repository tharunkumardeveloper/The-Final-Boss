"""Orders: "I'll buy Fiber 1000" becomes an Order in the graph, not a plan change. The plan only becomes the
customer's ON_PLAN fact when the order is installed.

  (:Customer)-[:PLACED]->(:Order {status})-[:FOR_PLAN]->(:Plan)        (:Order)-[:INSTALL_AT]->(:Area|:City)
"""
import uuid

from . import db, events, kb, memory
from .memory import norm, to_ms

PLACE = """
MATCH (c:Entity {name_key:$c}), (p:Entity {name_key:$plan})
OPTIONAL MATCH (c)-[:PLACED]->(open:Order) WHERE open.status IN ['pending', 'scheduled']
WITH c, p, open
FOREACH (_ IN CASE WHEN open IS NULL THEN [1] ELSE [] END |
  CREATE (c)-[:PLACED]->(:Order:Pending {order_id:$oid, name:'order ' + $oid, status:'pending', plan:$plan,
                                created_at:$at, eta:$eta, episode_id:$eid}))
WITH c, p
MATCH (c)-[:PLACED]->(o:Order) WHERE o.status IN ['pending', 'scheduled']
SET o.plan = $plan
WITH c, p, o
OPTIONAL MATCH (o)-[old:FOR_PLAN]->() DELETE old
WITH c, p, o
MERGE (o)-[:FOR_PLAN]->(p)
WITH c, o
OPTIONAL MATCH (c)-[:LIVES_IN]->(home:Entity)
FOREACH (_ IN CASE WHEN home IS NULL THEN [] ELSE [1] END | MERGE (o)-[:INSTALL_AT]->(home))
RETURN o.order_id, o.status, o.plan, home.name_key
"""
LIST = """
MATCH (c:Entity {name_key:$c})-[:PLACED]->(o:Order)
OPTIONAL MATCH (o)-[:INSTALL_AT]->(a:Entity)
RETURN o.order_id, o.status, o.plan, o.created_at, o.eta, a.name_key ORDER BY o.created_at DESC
"""
SET_STATUS = """
MATCH (o:Order {order_id:$oid})<-[:PLACED]-(c:Entity)
SET o.status=$status, o.updated_at=$at
FOREACH (_ IN CASE WHEN $status = 'installed' THEN [1] ELSE [] END | REMOVE o:Pending SET o:Installed)
RETURN c.name_key, o.plan
"""
INSTALL_HOURS = 48


def place(tenant, *, customer, plan, at, episode_id=None, log=None):
    """One open order per customer: a new "I'll buy X" updates the open order's plan instead of stacking orders."""
    at_ms = to_ms(at)
    oid = f"ord-{uuid.uuid4().hex[:6]}"
    rows = db.run(tenant, "place order", PLACE, {"c": norm(customer), "plan": plan, "oid": oid, "at": at_ms,
                                                 "eta": at_ms + INSTALL_HOURS * 3_600_000, "eid": episode_id}, log)
    order_id, status, plan, place_key = rows[0]
    out = {"order_id": order_id, "status": status, "plan": plan, "install_at": place_key,
           "eta_hours": INSTALL_HOURS, "covered": True}  # we serve everywhere
    events.emit(tenant, "order", {**out, "customer": norm(customer)}, at_ms)
    return out


def for_customer(tenant, customer, log=None):
    return [{"order_id": i, "status": s, "plan": p, "created_at": events.iso(c), "eta": events.iso(e), "install_at": a}
            for i, s, p, c, e, a in db.run(tenant, "orders", LIST, {"c": norm(customer)}, log, ro=True)]


def install(tenant, order_id, at, agent="resolver", log=None):
    """The technician finished: the order is installed and the plan becomes the customer's current plan."""
    rows = db.run(tenant, "install order", SET_STATUS, {"oid": order_id, "status": "installed", "at": to_ms(at)}, log)
    if not rows:
        raise KeyError(order_id)
    customer, plan = rows[0]
    memory.remember(tenant, agent=agent, session_id=f"order-{order_id}", customer=customer, at=at,
                    text=f"{agent} installed {plan} for {customer} ({order_id})", facts=[(customer, "on_plan", plan)], log=log)
    db.run(tenant, "customer profile", memory.Q.PROFILE, {"c": customer, "name": customer.title(), "at": to_ms(at), "at_dt": memory.dt(at)}, log)
    events.emit(tenant, "order", {"order_id": order_id, "status": "installed", "plan": plan, "customer": customer}, to_ms(at))
    return {"order_id": order_id, "status": "installed", "plan": plan, "customer": customer}
