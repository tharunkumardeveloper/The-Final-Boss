"""'Who on the team has worked on this before?' Field technicians are entities; tickets they worked are linked
(:Ticket)-[:WORKED_BY {at}]->(:Technician), so expertise is a traversal: technician -> tickets -> issue / router."""
import re

from . import db, kb, memory
from .memory import norm, to_ms


def technicians(region):
    """city key -> technician names, from the worldwide catalogue."""
    return {c: ts for c, ts in kb.world()["technicians"].items() if c in kb.coverage(region)}


SEED = """
UNWIND $techs AS t
MERGE (e:Entity {name_key:t.k})
  ON CREATE SET e.name=t.k, e.type='technician', e.created_at=0
SET e:Technician, e.city=t.city
WITH e, t
OPTIONAL MATCH (c:City {name_key:t.city})
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (e)-[:BASED_IN]->(c))
"""
ASSIGN = """
MATCH (t:Entity {name_key:$ticket}), (x:Entity {name_key:$tech})
MERGE (t)-[w:WORKED_BY]->(x)
  ON CREATE SET w.at = $at
MERGE (v:TechVisit {visit_id:'visit-' + $ticket})
  ON CREATE SET v.name = 'visit for ' + toUpper($ticket), v.status = 'scheduled', v.scheduled_for = $visit_at,
                v.scheduled_dt = localdatetime($visit_dt), v.outcome = null
MERGE (x)-[:VISITS]->(v)
MERGE (v)-[:FOR_TICKET]->(t)
"""
VISIT_DONE = """
MATCH (v:TechVisit {visit_id:'visit-' + $ticket})
SET v.status = 'done', v.outcome = $outcome, v.done_at = $at, v.done_dt = localdatetime($at_dt)
"""
VISIT_HOURS = 24  # next-day slot
WORK = """
MATCH (tech:Technician)<-[w:WORKED_BY]-(t:Entity)
OPTIONAL MATCH (t)-[:TICKET_ABOUT]->(i:Entity)
OPTIONAL MATCH (c:Entity)-[:HAS_TICKET]->(t)
OPTIONAL MATCH (c)-[:HAS_ROUTER]->(r:Entity)
OPTIONAL MATCH (st:Fact {predicate:'has_status', active:true})-[:ABOUT {role:'subject'}]->(t)
OPTIONAL MATCH (fx:Fact {predicate:'tried_fix'})-[:ABOUT {role:'subject'}]->(t)
RETURN tech.name_key, tech.city, t.name_key, w.at, st.object_value,
       collect(DISTINCT i.name_key) + collect(DISTINCT r.name_key) + collect(DISTINCT fx.object_value)
"""


def seed(tenant):
    techs = technicians(kb.region_of(tenant))
    db.graph(tenant).query(SEED, {"techs": [{"k": k, "city": c} for c, ks in techs.items() for k in ks]})


def assign(tenant, ticket, city, at, log=None):
    """Field technician for a ticket: one from the customer's city, spread by ticket number."""
    techs_by_city = technicians(kb.region_of(tenant))
    techs = techs_by_city.get(norm(city or "")) or next(iter(techs_by_city.values()))
    tech = techs[sum(map(ord, ticket)) % len(techs)]
    visit = to_ms(at) + VISIT_HOURS * 3_600_000
    db.run(tenant, "assign technician", ASSIGN, {"ticket": ticket, "tech": tech, "at": to_ms(at), "visit_at": visit,
                                                 "visit_dt": memory.dt(visit)}, log)
    memory.record_episode(tenant, agent="resolver", session_id=f"work-{ticket}", customer=None, at=at, speaker="action",
                          text=f"resolver assigned field technician {tech.title()} to {ticket.upper()}", log=log)
    return tech


def _stem(word):
    return re.sub(r"(ing|ed|es|s)$", "", word) if len(word) > 4 else word


def _words(text):
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def find(tenant, topic="", log=None):
    """Technicians ranked by resolved tickets whose issue, router or tried fixes match the topic words."""
    want = _words(topic)
    by = {}
    for tech, city, ticket, at, status, topics in db.run(tenant, "experts: work", WORK, log=log, ro=True):
        if want and not (want & _words(" ".join(t for t in topics if t))):
            continue
        e = by.setdefault(tech, {"technician": tech, "city": city, "tickets": 0, "resolved": 0, "last_at": None, "via": []})
        e["tickets"] += 1
        e["resolved"] += status == "resolved"
        e["last_at"] = max(filter(None, [e["last_at"], at]), default=None)
        e["via"].append(ticket.upper())
    return sorted(by.values(), key=lambda e: (-e["resolved"], -e["tickets"], e["technician"]))
