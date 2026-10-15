"""The company's network as a graph, and the NOC agent that acts on it.

(:NetNode:Backbone) <-[:UPLINK]- (:NetNode:Pop) <-[:UPLINK]- (:NetNode:Olt) <-[:CONNECTED_VIA]- (:Entity:Customer)

When a node fails, the NOC finds every customer with no working path to a backbone (graph traversal), writes the
outage into shared memory, and messages those customers before they have to complain. That is the tagline:
"We'll fix it before you have to."
"""
import math
import re
from datetime import datetime, timedelta, timezone

from . import agents, config, db, events, kb, memory, queries as Q, sharing
from .memory import norm, to_ms

IST = timezone(timedelta(hours=5, minutes=30))
DUAL_HOMED_POP = 5_000_000  # cities this big (and backbone cities) get two uplinks; smaller ones are single-homed


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def pop_id(city):
    return f"pop-{_slug(city)}"


def olt_id(city, area):
    return f"olt-{_slug(city)}-{_slug(area)}"


def _km(a, b):
    p = math.pi / 180
    h = (math.sin((b["lat"] - a["lat"]) * p / 2) ** 2
         + math.cos(a["lat"] * p) * math.cos(b["lat"] * p) * math.sin((b["lon"] - a["lon"]) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def _topology(tenant):
    """Region's network from the catalogue: backbones -> a POP per city (nearest backbone; big and backbone cities
    dual-homed) -> an OLT per area."""
    region = kb.region_of(tenant)
    cities = {c["key"]: c for c in kb.cities(region)}
    cores = kb.world()["regions"][region]["backbones"]
    nodes = [{"id": b["id"], "kind": "backbone", "label": b["label"], "city": b["city"], "area": None,
              "country": cities[b["city"]]["country"]} for b in cores]
    links = []
    for key, c in cities.items():
        ranked = sorted(cores, key=lambda b: _km(c, cities[b["city"]]))
        dual = c["population"] >= DUAL_HOMED_POP or any(b["city"] == key for b in cores)
        nodes.append({"id": pop_id(key), "kind": "pop", "label": f"{c['name']} POP", "city": key, "area": None,
                      "country": c["country"]})
        links += [{"a": pop_id(key), "b": b["id"]} for b in ranked[:2 if dual and len(ranked) > 1 else 1]]
        for a in c["areas"]:
            nodes.append({"id": olt_id(key, a["key"]), "kind": "olt", "label": f"{a['name']} OLT", "city": key,
                          "area": a["key"], "country": c["country"]})
            links.append({"a": olt_id(key, a["key"]), "b": pop_id(key)})
    return nodes, links


SEED = """
UNWIND $nodes AS n
MERGE (x:NetNode {node_id:n.id})
SET x.kind=n.kind, x.label=n.label, x.name=n.label, x.city=n.city, x.area=n.area, x.country=n.country,
    x.status=coalesce(x.status, 'up')
"""
DROP_STALE = "MATCH (x:NetNode) WHERE NOT x.node_id IN $ids DETACH DELETE x"
NET_META = "MERGE (m:Meta {key:'network'}) RETURN m.version"
SET_NET_META = "MERGE (m:Meta {key:'network'}) SET m.version=$v, m.name='network ' + $v"
SEED_LINKS = "UNWIND $links AS l MATCH (a:NetNode {node_id:l.a}), (b:NetNode {node_id:l.b}) MERGE (a)-[:UPLINK]->(b)"
# Synthetic link capacities (area exchange -> city POP 10 Gbps, POP -> backbone 100 Gbps) and cable lengths measured
# between the city points with distance(). :Up marks working equipment so algorithms can route around faults.
LINK_SPECS = [
    "MATCH (:Olt)-[u:UPLINK]->(:Pop) SET u.capacity_gbps = coalesce(u.capacity_gbps, 10)",
    "MATCH (:Pop)-[u:UPLINK]->(:Backbone) SET u.capacity_gbps = coalesce(u.capacity_gbps, 100)",
    "MATCH (a:NetNode)-[u:UPLINK]->(b:NetNode) WHERE u.km IS NULL "
    "MATCH (ca:City {name_key:a.city}), (cb:City {name_key:b.city}) "
    "WHERE ca.location IS NOT NULL AND cb.location IS NOT NULL "
    "SET u.km = CASE WHEN ca = cb THEN 2 ELSE round(distance(ca.location, cb.location) / 1000) END",
    "MATCH (n:NetNode) WHERE n.status = 'up' SET n:Up",
    "MATCH (n:NetNode) WHERE n.status <> 'up' REMOVE n:Up",
]
HARMONIC = """
CALL algo.HarmonicCentrality({nodeLabels:['NetNode'], relationshipTypes:['UPLINK']}) YIELD node, score
SET node.harmonic = score
"""
CAPACITY = """
MATCH (s:NetNode:Up {node_id:$n})
MATCH (b:Backbone:Up)
WITH s, collect(b) AS cores
CALL algo.maxFlow({sourceNodes:[s], targetNodes:cores, capacityProperty:'capacity_gbps', nodeLabels:['Up'],
                   relationshipTypes:['UPLINK']}) YIELD maxFlow
RETURN maxFlow
"""
CABLE_PLAN = """
CALL algo.MSF({nodeLabels:['NetNode'], relationshipTypes:['UPLINK'], weightAttribute:'km'}) YIELD edges
UNWIND edges AS e
RETURN count(e), sum(e.km)
"""
ALL_LINKS_KM = "MATCH (:NetNode)-[u:UPLINK]->(:NetNode) RETURN count(u), sum(u.km)"
CRITICALITY = """
CALL algo.betweenness({nodeLabels:['NetNode'], relationshipTypes:['UPLINK']}) YIELD node, score
SET node.betweenness = score
"""
ATTACH = """
MATCH (c:Entity {name_key:$c})
OPTIONAL MATCH (c)-[old:CONNECTED_VIA]->()
DELETE old
WITH DISTINCT c
OPTIONAL MATCH (o:NetNode {node_id:$olt})
FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | MERGE (c)-[:CONNECTED_VIA]->(o))
"""
# OLTs that still reach a backbone through nodes that are all up.
UP_OLTS = """
MATCH p = (o:Olt)-[:UPLINK*1..3]->(:Backbone)
WHERE all(n IN nodes(p) WHERE n.status = 'up')
RETURN DISTINCT o.node_id
"""
AFFECTED = """
MATCH (c:Entity {type:'customer'})-[:CONNECTED_VIA]->(o:Olt)
WHERE NOT o.node_id IN $up
RETURN c.name_key, o.node_id, o.area, o.city ORDER BY c.name_key
"""
PATH = """
MATCH (c:Entity {name_key:$c}), (n:NetNode {node_id:$n})
WITH shortestPath((c)-[:CONNECTED_VIA|UPLINK*1..5]->(n)) AS p
WHERE p IS NOT NULL
RETURN [x IN nodes(p) | coalesce(x.node_id, 'e:' + x.name_key)]
"""
SET_STATUS = """
MATCH (n:NetNode {node_id:$n})
SET n.status=$status, n.outage=$outage, n.changed_at=$at
FOREACH (_ IN CASE WHEN $status = 'up' THEN [1] ELSE [] END | SET n:Up)
FOREACH (_ IN CASE WHEN $status = 'up' THEN [] ELSE [1] END | REMOVE n:Up)
RETURN n.label, n.city, n.area, n.kind
"""
VIEW_NODES = """
MATCH (n:NetNode)
OPTIONAL MATCH (c:Entity {type:'customer'})-[:CONNECTED_VIA]->(n)
RETURN n.node_id, n.kind, n.label, n.city, n.area, n.status, n.betweenness, count(c), n.country, n.harmonic
ORDER BY n.kind, n.node_id
"""
VIEW_EDGES = "MATCH (a:NetNode)-[:UPLINK]->(b:NetNode) RETURN a.node_id, b.node_id"
CITY_FACTS = """
MATCH (f:Fact {predicate:'lives_in', active:true})-[:ABOUT {role:'subject'}]->(c:Entity) WHERE c.name_key IN $cs
RETURN f.fact_id
"""
OUTAGE_FACTS = """
MATCH (f:Fact {predicate:'affects', active:true})-[:ABOUT {role:'subject'}]->(:Entity {name_key:$o}) RETURN f.object_value
"""


def seed(tenant):
    g = db.graph(tenant)
    v = kb._version(kb.region_of(tenant)) + "-net2"
    if g.query(NET_META).result_set[0][0] != v:
        nodes, links = _topology(tenant)
        g.query(DROP_STALE, {"ids": [n["id"] for n in nodes]})  # e.g. the old India-only topology
        for i in range(0, len(nodes), 300):
            g.query(SEED, {"nodes": nodes[i:i + 300]})
        for kind, lab in (("backbone", "Backbone"), ("pop", "Pop"), ("olt", "Olt")):
            g.query(f"MATCH (n:NetNode {{kind:'{kind}'}}) SET n:{lab}")
        for i in range(0, len(links), 300):
            g.query(SEED_LINKS, {"links": links[i:i + 300]})
        g.query(CRITICALITY)
        g.query(SET_NET_META, {"v": v})
    # Backfill: customers whose city was learned before they had a line (older tenants).
    for c, place in g.ro_query(UNATTACHED).result_set:
        attach(tenant, c, place)


UNATTACHED = """
MATCH (f:Fact {predicate:'lives_in', active:true})-[:ABOUT {role:'subject'}]->(c:Entity)
WHERE NOT (c)-[:CONNECTED_VIA]->()
RETURN c.name_key, f.object_value
"""


def attach(tenant, customer, place, log=None):
    """Connect a customer to the OLT for their area (or their city's first area). Outside this region's coverage:
    no connection here (another region's graph serves them)."""
    p = kb.resolve_place(place) if place else None
    olt = "none"
    if p and p["region"] == kb.region_of(tenant):
        area = p["area"] or kb.coverage(p["region"])[p["city"]][0]
        olt = olt_id(p["city"], area)
    db.run(tenant, "network: attach", ATTACH, {"c": norm(customer), "olt": olt}, log)


def _affected(tenant, log):
    up = [r[0] for r in db.run(tenant, "network: OLTs with a working path", UP_OLTS, log=log, ro=True)]
    return db.run(tenant, "network: affected customers", AFFECTED, {"up": up}, log, ro=True)


def _first(name):
    return name.split()[0].title()


def _session(customer, at_ms):
    return f"{norm(customer).replace(' ', '-')}-web-{datetime.fromtimestamp(at_ms / 1000, tz=IST):%Y%m%d}"  # = api /chat


ETA_HOURS = 4  # the NOC's standard estimate for a node fault


def _notify(tenant, customer, kind, text, about, at_ms, log):
    db.run(tenant, "notification", Q.NOTIFY, {"c": customer, "id": memory._id("ntf"), "kind": kind, "text": text,
                                              "about": about, "at": at_ms, "at_dt": memory.dt(at_ms)}, log)


def fail(tenant, node_id, at=None, log=None):
    at_ms = to_ms(at) if at else int(datetime.now(IST).timestamp() * 1000)
    before = {c for c, *_ in _affected(tenant, log)}
    rows = db.run(tenant, "network: mark down", SET_STATUS, {"n": node_id, "status": "down", "outage": None, "at": at_ms}, log)
    if not rows:
        raise KeyError(node_id)
    label, city, area, kind = rows[0]
    outage = norm(f"{label} fault")
    db.run(tenant, "network: name outage", SET_STATUS, {"n": node_id, "status": "down", "outage": outage, "at": at_ms}, log)
    hit = [r for r in _affected(tenant, log) if r[0] not in before]
    # Cities and areas both: a customer's memory may say "lives in Baner" or "lives in Pune".
    cities = sorted({r[3] for r in hit} | {r[2] for r in hit if r[2]} | ({city} if city else set()))
    # Shared memory: the outage and where it bites, written by the NOC, readable by every agent.
    memory.remember(tenant, agent="noc", session_id=f"noc-{node_id}", customer=None, at=at_ms, speaker="noc",
                    text=f"NOC: {label} is down; {len(hit)} customers lost their path to the backbone",
                    facts=[(outage, "affects", c) for c in cities], log=log)
    # The NOC knows who is affected because intake recorded where they live.
    sharing.consult(tenant, "noc", [r[0] for r in db.run(tenant, "network: city facts used", CITY_FACTS,
                                                         {"cs": [r[0] for r in hit]}, log, ro=True)], at=at_ms, log=log)
    open_tickets = {t["customer"]: t["ticket"] for t in agents.tickets(tenant, log) if t["status"] != "resolved"}
    affected = []
    for c, olt, a_area, a_city in hit:
        path = db.run(tenant, "network: path", PATH, {"c": c, "n": node_id}, log, ro=True)
        affected.append({"customer": c, "area": a_area, "path": path[0][0] if path else []})
        where = f"our {area.title()} exchange" if area else f"our {label}"
        text = (f"Hi {_first(c)}, this is {config.BRAND['company']}. We've spotted a fault at {where} that is affecting "
                f"your connection. Engineers are already on it, so there's no need to call or raise a ticket."
                + (f" I've noted it on {open_tickets[c].upper()}." if c in open_tickets else ""))
        memory.record_episode(tenant, agent="noc", session_id=_session(c, at_ms), customer=c, at=at_ms, speaker="noc",
                              mentions=[(c, "customer")], log=log, text=text)
        _notify(tenant, c, "outage warning", text, outage, at_ms, log)
    eta = at_ms + ETA_HOURS * 3_600_000  # an estimate the NOC sets; intake may quote it because the graph holds it
    db.run(tenant, "outage state", Q.OUTAGE_STATE, {"o": outage, "active": True, "at": at_ms, "at_dt": memory.dt(at_ms),
                                                    "eta": eta, "eta_dt": memory.dt(eta)}, log)
    events.emit(tenant, "outage_detected", {"node": node_id, "label": label, "city": city, "area": area,
                                            "affected": [x["customer"] for x in affected], "by": "noc"}, at_ms)
    return {"node": node_id, "label": label, "outage": outage, "affected": affected,
            "tickets": sorted(open_tickets[x["customer"]].upper() for x in affected if x["customer"] in open_tickets),
            "notified": [x["customer"] for x in affected]}


def restore(tenant, node_id, at=None, log=None):
    at_ms = to_ms(at) if at else int(datetime.now(IST).timestamp() * 1000)
    down_before = {c: (olt, a) for c, olt, a, _ in _affected(tenant, log)}
    rows = db.run(tenant, "network: read node", "MATCH (n:NetNode {node_id:$n}) RETURN n.label, n.outage, n.area", {"n": node_id}, log, ro=True)
    if not rows:
        raise KeyError(node_id)
    label, outage, area = rows[0]
    db.run(tenant, "network: mark up", SET_STATUS, {"n": node_id, "status": "up", "outage": None, "at": at_ms}, log)
    back = sorted(set(down_before) - {c for c, *_ in _affected(tenant, log)})
    if outage:
        eid = memory.record_episode(tenant, agent="noc", session_id=f"noc-{node_id}", customer=None, at=at_ms,
                                    speaker="noc", text=f"NOC: {label} restored", log=log)
        for city in [r[0] for r in db.run(tenant, "network: outage cities", OUTAGE_FACTS, {"o": outage}, log, ro=True)]:
            memory.retire_fact(tenant, agent="noc", episode_id=eid, subject=outage, predicate="affects", obj=city,
                               at=at_ms, log=log)
    where = f"our {area.title()} exchange" if area else f"our {label}"
    if outage:
        db.run(tenant, "outage state", Q.OUTAGE_STATE, {"o": outage, "active": False, "at": at_ms,
                                                        "at_dt": memory.dt(at_ms), "eta": None, "eta_dt": None}, log)
    for c in back:
        text = (f"Good news, {_first(c)}: the fault at {where} is fixed and your connection should be back. "
                f"If anything still looks off, just reply here.")
        memory.record_episode(tenant, agent="noc", session_id=_session(c, at_ms), customer=c, at=at_ms, speaker="noc",
                              mentions=[(c, "customer")], log=log, text=text)
        _notify(tenant, c, "outage resolved", text, outage, at_ms, log)
    events.emit(tenant, "outage_resolved", {"node": node_id, "label": label}, at_ms)
    return {"node": node_id, "notified": back}


def specs(tenant):
    """Link capacities, cable lengths, :Up labels and harmonic centrality (idempotent)."""
    g = db.graph(tenant)
    for q in LINK_SPECS:
        g.query(q)
    g.query(HARMONIC)


def capacity(tenant, node_id, log=None):
    """Gbps that can still flow from this node to the backbone through working equipment (MaxFlow)."""
    rows = db.run(tenant, "network: max flow", CAPACITY, {"n": node_id}, log, ro=True)
    return {"node": node_id, "gbps": float(rows[0][0]) if rows else 0.0}


def cable_plan(tenant, log=None):
    """Minimum spanning forest over cable km: the shortest cable set that still connects every node."""
    msf = db.run(tenant, "network: minimum spanning forest", CABLE_PLAN, log=log, ro=True)
    every = db.run(tenant, "network: all links", ALL_LINKS_KM, log=log, ro=True)
    return {"links": msf[0][0], "km": float(msf[0][1] or 0), "all_links": every[0][0], "all_km": float(every[0][1] or 0)}


def view(tenant, country=None, log=None):
    """Whole region, or one country (its POPs and OLTs plus the backbones they reach)."""
    nodes = [{"id": i, "kind": k, "label": lab, "city": c, "area": a, "status": s, "betweenness": b or 0, "customers": n,
              "country": iso, "harmonic": h or 0}
             for i, k, lab, c, a, s, b, n, iso, h in db.run(tenant, "network: nodes", VIEW_NODES, log=log, ro=True)]
    edges = [{"id": f"{a}>{b}", "source": a, "target": b, "kind": "UPLINK"}
             for a, b in db.run(tenant, "network: links", VIEW_EDGES, log=log, ro=True)]
    if country:
        keep = {n["id"] for n in nodes if n["country"] == country or n["kind"] == "backbone"}
        edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
        used = {x for e in edges for x in (e["source"], e["target"])}
        nodes = [n for n in nodes if n["id"] in keep and (n["kind"] != "backbone" or n["id"] in used)]
    region = kb.region_of(tenant)
    where = {c["key"]: c for c in kb.cities(region)}  # the map: every node sits at its city's coordinates
    for n in nodes:
        c = where.get(n["city"])
        n["lat"], n["lon"] = (c["lat"], c["lon"]) if c else (None, None)
    return {"nodes": nodes, "edges": edges, "region": region,
            "countries": [{"iso": i, "name": kb.country_name(i)} for i in kb.world()["regions"][region]["countries"]]}
