"""Network Lab: the last mile as a graph, a fault injector with hidden ground truth, and the resolver loop that has to
find the cause from readings alone, act on the network, and prove the fix by measuring again.

  (:Backbone)<-[:UPLINK {role, active, link_status}]-(:Pop)<-[:UPLINK]-(:Olt)<-[:PON]-(:Splitter)<-[:DROP]-(:Ont)<-[:HAS_ONT]-(:Entity customer)

Physical state lives on the nodes (feeder cut, drop loss, frozen box, suspended account, cut uplink, evening demand).
Readings (light level, box state, session, capacity, evening headroom, Wi-Fi interference) are derived from that state
with Cypher and algo.maxFlow. The truth about what was broken is written to a separate graph, chaos:<tenant>, that the
resolver never reads: only the world (which applies actions) and the scoreboard do.
"""
import hashlib
import random
import re
import threading
import time
import uuid

from . import cards, config, db, events, experts, kb, llm, memory, network, procedural, retrieve, sharing
from .memory import norm

HOMES_PER_SPLITTER = 14
NORMAL_PEAK_GBPS = 6.0
OLT_UPLINK_GBPS = 10
# Share of the evening peak used at each hour of the day (21:00 = 1.0).
CURVE = [0.30, 0.22, 0.18, 0.16, 0.16, 0.20, 0.30, 0.42, 0.50, 0.55, 0.58, 0.60,
         0.62, 0.60, 0.58, 0.60, 0.66, 0.74, 0.84, 0.93, 0.98, 1.00, 0.92, 0.62]
# Real seconds a field job takes in the lab (fast-forwarded; the customer is told the real-world time).
DELAY = {"dispatch_technician_home": 6, "dispatch_cable_crew": 8, "dispatch_backbone_crew": 8, "send_payment_link": 5}
STEP_PAUSE = 0.55  # pacing so the trace reads like work being done, not a dump

_lock = threading.Lock()
_runs: dict[str, list] = {}           # tenant -> recent runs (newest first)
_busy: set = set()                    # (tenant, customer) with a run in progress
_expected: set = set()                # a complaint just arrived; the run starts right after intake has noted it
_gen: dict[str, int] = {}             # tenant -> reset generation (delayed jobs from before a reset are dropped)

# ---------------------------------------------------------------- the catalogue

PRESETS = {
    "frozen_box": {
        "title": "Frozen box", "layer": "Home", "icon": "box",
        "blurb": "The customer's box (ONT) has hung. Light is fine, but it stopped passing traffic.",
        "says": "My internet isn't working at all since morning. The lights on the box look normal I think.",
        "fix": "remote_reboot"},
    "wifi_interference": {
        "title": "Wi-Fi interference", "layer": "Home", "icon": "wifi",
        "blurb": "Fourteen neighbouring networks crowd the same Wi-Fi channel. The line itself is perfect.",
        "says": "My PS5 keeps disconnecting from the wifi, but my laptop near the router is fine.",
        "fix": "change_wifi_channel"},
    "damaged_drop": {
        "title": "Damaged home fibre", "layer": "Last mile", "icon": "cable",
        "blurb": "The fibre from the street cabinet into one home is bent or damaged: the light reaching the box is weak.",
        "says": "There's a red light blinking on my internet box and the internet keeps going off.",
        "fix": "dispatch_technician_home"},
    "area_cable_cut": {
        "title": "Street cable cut", "layer": "Area", "icon": "scissors",
        "blurb": "The cable feeding a street cabinet is cut (roadworks). Every home on that cabinet goes dark.",
        "says": "Internet is completely gone and the box has a red light.",
        "fix": "dispatch_cable_crew"},
    "hub_link_dual": {
        "title": "City hub link down (has backup)", "layer": "City", "icon": "route",
        "blurb": "The main link from a city hub to the core is cut. This hub has a standby link the resolver can switch to.",
        "says": "Nothing is loading, the internet is down.",
        "fix": "reroute_standby", "needs": "dual"},
    "hub_link_single": {
        "title": "City hub link down (no backup)", "layer": "City", "icon": "route",
        "blurb": "The only link from a city hub to the core is cut. No reroute possible: someone has to repair it.",
        "says": "Nothing is loading, the internet is down.",
        "fix": "dispatch_backbone_crew", "needs": "single"},
    "evening_congestion": {
        "title": "Evening congestion", "layer": "Area", "icon": "gauge",
        "blurb": "The area exchange's uplink is nearly full every evening. Daytime tests look perfect.",
        "says": "The internet becomes super slow every night, Netflix keeps buffering.",
        "fix": "upgrade_uplink"},
    "payment_failed": {
        "title": "Payment failed", "layer": "Account", "icon": "card",
        "blurb": "The network is healthy; the account was paused after a failed payment. A trap for anyone who sends a technician.",
        "says": "My internet suddenly stopped working this morning.",
        "fix": "send_payment_link"},
}

NOTICE = {  # what you'd see at home: symptoms only, never the cause
    "frozen_box": "All the lights on your box look normal and green, but nothing loads on any device, wired or Wi-Fi.",
    "wifi_interference": "Your laptop right next to the box works fine. Your phone and PS5 in the bedroom keep dropping off the Wi-Fi.",
    "damaged_drop": "The light marked LOS on your box keeps blinking red, and the internet cuts out every few minutes.",
    "area_cable_cut": "The LOS light on your box is solid red. Your neighbour just messaged that theirs is out too.",
    "hub_link_dual": "The box lights look normal, but nothing loads. The society WhatsApp group says the whole area is down.",
    "hub_link_single": "The box lights look normal, but nothing loads. The society WhatsApp group says the whole area is down.",
    "evening_congestion": "In the day it's fast. Every night around 9, videos buffer and games lag badly.",
    "payment_failed": "The box looks normal, but nothing loads. You changed your bank card last month.",
}
CAUSES = {  # what the resolver can conclude -> the action that addresses it
    "frozen_box": "remote_reboot", "wifi_interference": "change_wifi_channel",
    "damaged_drop": "dispatch_technician_home", "area_cable_cut": "dispatch_cable_crew",
    "hub_link_down": "reroute_standby", "evening_congestion": "upgrade_uplink",
    "payment_failed": "send_payment_link", "equipment_down": "escalate", "healthy": "none",
}
TRUE_CAUSE = {"hub_link_dual": "hub_link_down", "hub_link_single": "hub_link_down"}  # preset -> cause name
FIX_NAME = {  # procedural memory: the fix as the team would name it
    "remote_reboot": "remote box restart", "change_wifi_channel": "change wifi channel",  # the team's own fix names
    "dispatch_technician_home": "replace fiber cable", "dispatch_cable_crew": "street cable repair",
    "reroute_standby": "reroute via standby link", "dispatch_backbone_crew": "hub link repair",
    "upgrade_uplink": "area uplink upgrade", "send_payment_link": "payment reactivation",
}
ACTION_LABEL = {
    "remote_reboot": "Restart the box remotely", "change_wifi_channel": "Move Wi-Fi to a quieter channel",
    "dispatch_technician_home": "Send a technician to the home", "dispatch_cable_crew": "Send the cable crew to the street cabinet",
    "reroute_standby": "Switch the hub to its standby link", "dispatch_backbone_crew": "Send the backbone team to the hub link",
    "upgrade_uplink": "Add capacity to the area uplink", "send_payment_link": "Send a secure payment link",
    "escalate": "Hand over to network operations", "none": "Nothing to fix",
}

# ---------------------------------------------------------------- Cypher

UNSEEDED = """
MATCH (c:Entity {type:'customer'})-[:CONNECTED_VIA]->(olt:Olt)
WHERE NOT (c)-[:HAS_ONT]->()
RETURN c.name_key, olt.node_id, olt.label, olt.area
"""
ENSURE_SPLITTER = """
MATCH (olt:Olt {node_id:$olt})
MERGE (s:LastMile:Splitter {node_id:$sid})
ON CREATE SET s.label=$label, s.feeder='ok', s.ports=32
MERGE (s)-[:PON]->(olt)
SET olt.peak_demand_gbps = coalesce(olt.peak_demand_gbps, $peak)
RETURN s.node_id
"""
ENSURE_ONT = """
MATCH (s:Splitter {node_id:$sid})
MERGE (o:LastMile:Ont {node_id:$oid})
ON CREATE SET o.home=$home, o.port=$port, o.base_rx=$rx, o.drop_loss=0.0, o.box_state='online', o.account='active',
              o.wifi_channel=$ch, o.wifi_interference=$wi, o.nearby_networks=$nn, o.uptime_h=$up, o.customer=$c
MERGE (o)-[:DROP {port:$port}]->(s)
WITH o
OPTIONAL MATCH (c:Entity {name_key:$c})
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:HAS_ONT]->(o))
"""
SPLITTER_PORTS = "MATCH (:Splitter {node_id:$sid})<-[d:DROP]-() RETURN collect(d.port)"
POP_LINKS = "MATCH (p:Pop)-[u:UPLINK]->(b:Backbone) RETURN p.node_id, b.node_id, u.km, u.role"
SET_ROLE = """
MATCH (:Pop {node_id:$p})-[u:UPLINK]->(:Backbone {node_id:$b})
SET u.role=$role, u.active=$active, u.link_status=coalesce(u.link_status, 'up')
"""
REFRESH_FLOW = """
MATCH ()-[u:UPLINK]->()
SET u.flow_gbps = CASE WHEN coalesce(u.active, true) AND coalesce(u.link_status, 'up') = 'up'
                       THEN coalesce(u.capacity_gbps, 10) ELSE 0 END
"""
LINE = """
MATCH (c:Entity {name_key:$c})-[:HAS_ONT]->(o:Ont)-[:DROP]->(s:Splitter)-[:PON]->(olt:Olt)-[ou:UPLINK]->(pop:Pop)
RETURN properties(o), s.node_id, s.label, s.feeder, olt.node_id, olt.label, olt.status, olt.area, olt.city,
       coalesce(olt.peak_demand_gbps, $peak), coalesce(ou.capacity_gbps, 10), pop.node_id, pop.label, pop.status, pop.city
"""
NEIGHBOURS = """
MATCH (s:Splitter {node_id:$s})<-[:DROP]-(o:Ont)
RETURN o.node_id, o.customer, o.base_rx, o.drop_loss, o.box_state
"""
FLOW = """
MATCH (s:Olt:Up {node_id:$olt})
MATCH (b:Backbone:Up)
WITH s, collect(b) AS cores
CALL algo.maxFlow({sourceNodes:[s], targetNodes:cores, capacityProperty:'flow_gbps', nodeLabels:['Up'],
                   relationshipTypes:['UPLINK']}) YIELD maxFlow
RETURN maxFlow
"""
HUB = """
MATCH (p:Pop {node_id:$p})-[u:UPLINK]->(b:Backbone)
RETURN b.node_id, b.label, b.status, u.role, coalesce(u.active, true), coalesce(u.link_status, 'up'),
       coalesce(u.capacity_gbps, 100), coalesce(u.flow_gbps, 0)
ORDER BY u.role
"""
VIEW = """
MATCH (pop:Pop {node_id:$pop})<-[ou:UPLINK]-(olt:Olt)<-[:PON]-(s:Splitter)<-[:DROP]-(o:Ont)
RETURN olt.node_id, olt.label, olt.status, coalesce(olt.peak_demand_gbps, $peak), coalesce(ou.capacity_gbps, 10),
       s.node_id, s.label, s.feeder, properties(o)
ORDER BY olt.node_id, o.port
"""
CUSTOMERS = """
MATCH (c:Entity {type:'customer'})-[:HAS_ONT]->(o:Ont)-[:DROP]->(s:Splitter)-[:PON]->(olt:Olt)-[:UPLINK]->(pop:Pop)
OPTIONAL MATCH (pop)-[u:UPLINK]->(:Backbone)
RETURN c.name_key, olt.city, olt.area, pop.node_id, pop.label, count(u)
ORDER BY c.name_key
"""
PLAN_OF = """
MATCH (f:Fact {predicate:'on_plan', active:true})-[:ABOUT {role:'subject'}]->(:Entity {name_key:$c})
RETURN f.object_value ORDER BY f.recorded_at DESC LIMIT 1
"""
LAST_SAID = """
MATCH (ep:Episode {customer:$c, speaker:'customer'}) RETURN ep.text ORDER BY ep.recorded_at DESC LIMIT 1
"""
HEAL_ALL = [
    "MATCH (o:Ont) SET o.drop_loss=0.0, o.box_state='online', o.account='active'",
    "MATCH (s:Splitter) SET s.feeder='ok'",
    "MATCH (o:Olt) WHERE o.peak_demand_gbps IS NOT NULL SET o.peak_demand_gbps=$peak",
    "MATCH (:Olt)-[u:UPLINK]->(:Pop) SET u.capacity_gbps=$cap",
    "MATCH (:Pop)-[u:UPLINK]->(:Backbone) SET u.link_status='up', u.active = (u.role = 'primary')",
]


def _h(s):
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


def _baseline(oid):
    h = _h(oid)
    return {"rx": -(17 + (h % 40) / 10), "ch": [1, 6, 11][h % 3], "wi": round(0.08 + (h % 15) / 100, 2),
            "nn": 2 + h % 4, "up": 24 + h % 400}


def _chaos(tenant):
    return db.client().select_graph(f"chaos:{tenant}")


def _q(tenant, name, query, params=None, log=None, ro=False):
    return db.run(tenant, f"lab: {name}", query, params, log, ro=ro)


def _ms():
    return int(time.time() * 1000)


# ---------------------------------------------------------------- the last mile

def ensure(tenant, log=None):
    """Give every connected customer a box on a street cabinet with neighbour homes; set hub link roles. Idempotent."""
    procedural.setup(tenant)  # indexes for the procedure graph
    for c, olt, label, area in _q(tenant, "customers without a line", UNSEEDED, log=log, ro=True):
        sid = f"spl-{olt[4:]}"
        _q(tenant, "street cabinet", ENSURE_SPLITTER,
           {"olt": olt, "sid": sid, "label": f"{(area or label).title()} street cabinet", "peak": NORMAL_PEAK_GBPS}, log)
        taken = set(_q(tenant, "ports in use", SPLITTER_PORTS, {"sid": sid}, log, ro=True)[0][0] or [])
        if not taken:  # a new cabinet gets its neighbourhood
            for i in range(1, HOMES_PER_SPLITTER + 1):
                port = 2 * i + 1
                oid = f"ont-{sid[4:]}-{port:02d}"
                b = _baseline(oid)
                _q(tenant, "neighbour home", ENSURE_ONT, {"sid": sid, "oid": oid, "home": f"Home {port:02d}", "port": port,
                                                         "rx": b["rx"], "ch": b["ch"], "wi": b["wi"], "nn": b["nn"],
                                                         "up": b["up"], "c": None}, log)
                taken.add(port)
        port = next(p for p in range(2, 33) if p not in taken)
        oid = f"ont-{network._slug(c)}"
        b = _baseline(oid)
        _q(tenant, "customer box", ENSURE_ONT, {"sid": sid, "oid": oid, "home": cards.display(c, "customer"), "port": port,
                                               "rx": b["rx"], "ch": b["ch"], "wi": b["wi"], "nn": b["nn"], "up": b["up"],
                                               "c": c}, log)
    by_pop = {}
    for p, b, km, role in _q(tenant, "hub links", POP_LINKS, log=log, ro=True):
        by_pop.setdefault(p, []).append((km if km is not None else 1e9, b, role))
    for p, links in by_pop.items():
        if all(role for *_, role in links):
            continue
        for i, (_, b, _) in enumerate(sorted(links)):
            _q(tenant, "hub link role", SET_ROLE, {"p": p, "b": b, "role": "primary" if i == 0 else "standby",
                                                   "active": i == 0}, log)
    _q(tenant, "link flow", REFRESH_FLOW, log=log)


def _plan_mbps(tenant, customer, log=None):
    rows = _q(tenant, "customer plan", PLAN_OF, {"c": customer}, log, ro=True)
    spec = next((p for p in kb.world()["plans"] if rows and p["key"] == rows[0][0]), None)
    return (spec["down"] if spec else 100), (rows[0][0] if rows else None)


# ---------------------------------------------------------------- readings

def _light(ont, feeder):
    if feeder == "cut":
        return None
    return round(ont["base_rx"] - (ont.get("drop_loss") or 0), 1)


def _box(rx, state):
    if rx is None or rx < -30:
        return "no-signal"
    if rx < -27:
        return "flapping"
    return state


def flow(tenant, olt, log=None):
    rows = _q(tenant, "capacity to core (algo.maxFlow)", FLOW, {"olt": olt}, log, ro=True)
    return float(rows[0][0]) if rows else 0.0


def measure(tenant, customer, log=None):
    """Every reading the resolver can take for one customer, straight from the graph."""
    rows = _q(tenant, "line test", LINE, {"c": customer, "peak": NORMAL_PEAK_GBPS}, log, ro=True)
    if not rows:
        return None
    (ont, sid, slabel, feeder, olt, olabel, ostatus, area, city, peak, ocap, pop, plabel, pstatus, pcity) = rows[0]
    rx = _light(ont, feeder)
    box = _box(rx, ont["box_state"])
    neigh = _q(tenant, "neighbours on the street cabinet", NEIGHBOURS, {"s": sid}, log, ro=True)
    others = [r for r in neigh if r[0] != ont["node_id"]]
    bad = [r for r in others if _box(_light({"base_rx": r[2], "drop_loss": r[3]}, feeder), r[4]) != "online"]
    gbps = flow(tenant, olt, log)
    hub = [{"id": b, "label": lab, "status": st, "role": role, "active": act, "link": link, "gbps": cap, "flow": fl}
           for b, lab, st, role, act, link, cap, fl in _q(tenant, "hub uplinks", HUB, {"p": pop}, log, ro=True)]
    plan_mbps, plan = _plan_mbps(tenant, customer, log)
    free_peak = max(0.0, gbps - peak) * 1000 if gbps > 0 else 0.0
    if box != "online":
        session = "down"
    elif ont["account"] != "active":
        session = "rejected: account paused"
    elif gbps <= 0:
        session = "no route to the internet"
    else:
        session = "ok"
    return {
        "customer": customer, "ont": ont["node_id"], "port": ont["port"], "rx": rx, "box": box,
        "account": ont["account"], "session": session, "uptime_h": ont.get("uptime_h"),
        "wifi": {"channel": ont["wifi_channel"], "interference": ont["wifi_interference"], "nearby": ont["nearby_networks"]},
        "splitter": {"id": sid, "label": slabel, "feeder": feeder, "homes": len(neigh), "others_down": len(bad),
                     "others": len(others)},
        "olt": {"id": olt, "label": olabel, "status": ostatus, "area": area, "city": city, "peak_gbps": peak,
                "uplink_gbps": ocap},
        "pop": {"id": pop, "label": plabel, "status": pstatus, "city": pcity, "links": hub},
        "flow_gbps": gbps, "free_peak_mbps": round(free_peak), "plan": plan, "plan_mbps": plan_mbps,
        "util_peak": round(min(1.0, peak / gbps), 3) if gbps > 0 else None,
    }


def problems(m):
    """What is wrong in these readings, in the order a technician would read them."""
    out = []
    if m["box"] in ("no-signal", "flapping"):
        out.append("light")
    elif m["box"] != "online":
        out.append("box")
    if m["account"] != "active":
        out.append("account")
    if m["flow_gbps"] <= 0:
        out.append("route")
    elif m["free_peak_mbps"] < m["plan_mbps"]:
        out.append("evening")
    if m["wifi"]["interference"] >= 0.5:
        out.append("wifi")
    return out


# ---------------------------------------------------------------- the world (applies actions; knows the truth)

def _faults(tenant, active_only=True):
    g = _chaos(tenant)
    try:
        rows = g.ro_query("MATCH (f:Fault) " + ("WHERE f.active " if active_only else "") +
                          "RETURN properties(f) ORDER BY f.injected_at DESC").result_set
    except Exception:
        return []
    return [r[0] for r in rows]


def _set_fault(tenant, fid, **props):
    _chaos(tenant).query("MATCH (f:Fault {id:$id}) SET f += $p", {"id": fid, "p": props})


def _touches(fault, m):
    """Does this fault sit on this customer's path? (the world's view, never the resolver's)"""
    t = fault["target"]
    return t in (m["ont"], m["splitter"]["id"], m["olt"]["id"], m["pop"]["id"])


def inject(tenant, preset, customer=None, blind=False, complain=True):
    ensure(tenant)
    custs = customers(tenant)
    if preset == "random":
        options = [(p, c["key"]) for p in PRESETS for c in custs if _applies(PRESETS[p], c)]
        if not options:
            raise ValueError("no customer has a line yet")
        preset, customer = random.choice(options)
        blind = True
    spec = PRESETS[preset]
    c = next((x for x in custs if x["key"] == norm(customer or "")), None) or next(
        (x for x in custs if _applies(spec, x)), None)
    if not c or not _applies(spec, c):
        raise ValueError(f"no customer fits '{spec['title']}'")
    m = measure(tenant, c["key"])
    target, label = _apply_fault(tenant, preset, m)
    fid = f"flt-{uuid.uuid4().hex[:6]}"
    _chaos(tenant).query("CREATE (:Fault {id:$id, preset:$p, cause:$cause, fix:$fix, customer:$c, target:$t, label:$l, "
                         "active:true, mitigated:false, blind:$b, injected_at:$at})",
                         {"id": fid, "p": preset, "cause": TRUE_CAUSE.get(preset, preset), "fix": spec["fix"],
                          "c": c["key"], "t": target, "l": label, "b": blind, "at": _ms()})
    events.emit(tenant, "lab_state", {"why": "fault injected", "fault": fid, "blind": blind})
    if complain:
        threading.Thread(target=_complain, args=(tenant, c["key"], spec["says"]), daemon=True).start()
    return {"fault": fid, "preset": preset if not blind else None, "customer": c["key"], "blind": blind}


def _applies(spec, c):
    need = spec.get("needs")
    return need is None or (need == "dual") == (c["uplinks"] > 1)


def _apply_fault(tenant, preset, m):
    if preset == "frozen_box":
        _q(tenant, "fault: freeze box", "MATCH (o:Ont {node_id:$o}) SET o.box_state='frozen'", {"o": m["ont"]})
        return m["ont"], f"box of {m['customer']}"
    if preset == "wifi_interference":
        _q(tenant, "fault: crowd wifi", "MATCH (o:Ont {node_id:$o}) SET o.wifi_interference=0.88, o.nearby_networks=14, "
           "o.wifi_channel=6", {"o": m["ont"]})
        return m["ont"], f"Wi-Fi of {m['customer']}"
    if preset == "damaged_drop":
        _q(tenant, "fault: damage drop", "MATCH (o:Ont {node_id:$o}) SET o.drop_loss=11.5", {"o": m["ont"]})
        return m["ont"], f"home fibre of {m['customer']}"
    if preset == "area_cable_cut":
        _q(tenant, "fault: cut feeder", "MATCH (s:Splitter {node_id:$s}) SET s.feeder='cut'", {"s": m["splitter"]["id"]})
        return m["splitter"]["id"], m["splitter"]["label"]
    if preset in ("hub_link_dual", "hub_link_single"):
        _q(tenant, "fault: cut hub link", "MATCH (:Pop {node_id:$p})-[u:UPLINK {role:'primary'}]->() SET u.link_status='cut'",
           {"p": m["pop"]["id"]})
        _q(tenant, "link flow", REFRESH_FLOW)
        return m["pop"]["id"], f"{m['pop']['label']} main link"
    if preset == "evening_congestion":
        _q(tenant, "fault: evening demand", "MATCH (o:Olt {node_id:$o}) SET o.peak_demand_gbps=9.95", {"o": m["olt"]["id"]})
        return m["olt"]["id"], f"{m['olt']['label']} uplink"
    if preset == "payment_failed":
        _q(tenant, "fault: pause account", "MATCH (o:Ont {node_id:$o}) SET o.account='suspended'", {"o": m["ont"]})
        return m["ont"], f"account of {m['customer']}"
    raise ValueError(preset)


def act(tenant, action, m, on_done=None):
    """The world carries out an action at the place the resolver chose. It reports what it did, never whether that
    fixed anything: the resolver has to measure. Field jobs finish later (on_done is called then)."""
    gen = _gen.get(tenant, 0)
    if action in DELAY:
        def later():
            time.sleep(DELAY[action])
            if _gen.get(tenant, 0) == gen:
                _field_job(tenant, action, m)
                events.emit(tenant, "lab_state", {"why": f"{action} finished"})
            if on_done:
                on_done()
        threading.Thread(target=later, daemon=True).start()
        return {"delayed": DELAY[action]}
    if action == "remote_reboot":
        _q(tenant, "action: reboot box", "MATCH (o:Ont {node_id:$o}) SET o.uptime_h=0, "
           "o.box_state = CASE WHEN o.box_state='frozen' THEN 'online' ELSE o.box_state END", {"o": m["ont"]})
        _close(tenant, m, ("frozen_box",))
    elif action == "change_wifi_channel":
        best = min((1, 6, 11), key=lambda ch: 99 if ch == m["wifi"]["channel"] else ch)
        _q(tenant, "action: change wifi channel", "MATCH (o:Ont {node_id:$o}) SET o.wifi_channel=$ch, "
           "o.wifi_interference = CASE WHEN o.wifi_interference >= 0.5 THEN 0.14 ELSE o.wifi_interference END, "
           "o.nearby_networks = CASE WHEN o.nearby_networks > 6 THEN 3 ELSE o.nearby_networks END",
           {"o": m["ont"], "ch": best})
        _close(tenant, m, ("wifi_interference",))
    elif action == "reroute_standby":
        _q(tenant, "action: activate standby link", "MATCH (:Pop {node_id:$p})-[u:UPLINK {role:'standby'}]->(b:Backbone:Up) "
           "SET u.active=true", {"p": m["pop"]["id"]})
        _q(tenant, "link flow", REFRESH_FLOW)
        for f in _faults(tenant):
            if f["target"] == m["pop"]["id"] and f["preset"] == "hub_link_dual":
                _set_fault(tenant, f["id"], mitigated=True)
    elif action == "upgrade_uplink":
        _q(tenant, "action: second 10G port", "MATCH (o:Olt {node_id:$o})-[u:UPLINK]->(:Pop) "
           "SET u.capacity_gbps = coalesce(u.capacity_gbps, 10) + 10", {"o": m["olt"]["id"]})
        _q(tenant, "link flow", REFRESH_FLOW)
        _close(tenant, m, ("evening_congestion",), where="olt")
    events.emit(tenant, "lab_state", {"why": action})
    return {"delayed": 0}


def _field_job(tenant, action, m):
    if action == "dispatch_technician_home":
        _q(tenant, "field: replace home fibre", "MATCH (o:Ont {node_id:$o}) SET o.drop_loss=0.0, o.uptime_h=0, "
           "o.box_state='online'", {"o": m["ont"]})
        _close(tenant, m, ("damaged_drop", "frozen_box"))
    elif action == "dispatch_cable_crew":
        _q(tenant, "field: splice street cable", "MATCH (s:Splitter {node_id:$s}) SET s.feeder='ok'",
           {"s": m["splitter"]["id"]})
        _close(tenant, m, ("area_cable_cut",), where="splitter")
    elif action == "dispatch_backbone_crew":
        _q(tenant, "field: repair hub link", "MATCH (:Pop {node_id:$p})-[u:UPLINK]->() "
           "SET u.link_status='up', u.active = (u.role = 'primary')", {"p": m["pop"]["id"]})
        _q(tenant, "link flow", REFRESH_FLOW)
        _close(tenant, m, ("hub_link_dual", "hub_link_single"), where="pop")
    elif action == "send_payment_link":  # the customer pays from the link
        _q(tenant, "customer paid", "MATCH (o:Ont {node_id:$o}) WHERE o.account='suspended' SET o.account='active'",
           {"o": m["ont"]})
        _close(tenant, m, ("payment_failed",))


def _close(tenant, m, presets, where="ont"):
    target = {"ont": m["ont"], "splitter": m["splitter"]["id"], "olt": m["olt"]["id"], "pop": m["pop"]["id"]}[where]
    for f in _faults(tenant):
        if f["preset"] in presets and f["target"] == target:
            _set_fault(tenant, f["id"], active=False, healed_at=_ms())


def reset(tenant):
    """Heal everything and forget the faults (the scoreboard starts over)."""
    with _lock:
        _gen[tenant] = _gen.get(tenant, 0) + 1
        _runs[tenant] = []
        for k in [k for k in _awaiting if k[0] == tenant]:
            _awaiting.pop(k)
    ensure(tenant)
    for q in HEAL_ALL:
        _q(tenant, "heal", q, {"peak": NORMAL_PEAK_GBPS, "cap": OLT_UPLINK_GBPS})
    _q(tenant, "link flow", REFRESH_FLOW)
    try:
        _chaos(tenant).delete()
    except Exception:
        pass
    events.emit(tenant, "lab_state", {"why": "reset"})


# ---------------------------------------------------------------- the resolver loop

_SYMPTOMS = [
    ("no internet", r"\b(not working|isn'?t working|no internet|gone|down|stopped|nothing (is )?loading|dead)\b"),
    ("slow", r"\b(slow|buffer\w*|lag\w*|laggy)\b"),
    ("evenings", r"\b(every (night|evening)|at night|evenings?|nights?)\b"),
    ("drops", r"\b(drop\w*|disconnect\w*|keeps going off|cuts? out)\b"),
    ("one device", r"\b(ps5|xbox|console|tv|phone|laptop|tablet)\b"),
    ("red light", r"\bred light|blinking\b"),
    ("something wrong", r"\b(internet|wi-?fi|connection|net)\b.{0,30}\b(weird|off|wrong|not right|acting up|issues?|problems?)\b"
                        r"|\b(weird|wrong|off|issues?|problems?)\b.{0,30}\b(internet|wi-?fi|connection)\b"),
    ("lights look normal", r"\blights? (look|are|seem) (normal|fine|ok)\b"),
    ("can't connect", r"\b(ethernet|lan|cable|port|wired)\b.{0,25}\b(not|no|isn'?t|won'?t|doesn'?t|can'?t)\b.{0,15}"
                      r"\b(detect\w*|connect\w*|work\w*|recogni[sz]\w*)\b|\b(not|can'?t|won'?t) (detect\w*|connect\w*)\b"),
]
# asking for someone to come, or for help, on a case that is already open: the resolver takes it, not small talk
_STILL = re.compile(r"\bstill\b|\bdidn'?t (help|work|fix)\b|\bsame (issue|problem)\b|\bnot (fixed|working)\b", re.I)
VISIT_ASK = re.compile(r"\b(send|need|want|get)\b.{0,25}\b(technician|engineer|someone|somebody|men|guy|person|team|visit|"
                       r"assistance|help)\b|\bassist(ance)?\b|\bhelp me\b|\bcome (and )?fix\b", re.I)


def symptoms(text):
    t = (text or "").lower()
    return [name for name, rx in _SYMPTOMS if re.search(rx, t)]


DECIDE_SYSTEM = """You are the resolver agent at an internet provider. A customer has a problem. You get the readings
your tools took from the network graph, what the customer said, and the actions already tried. Name the most likely
cause and the ONE next action. Rules of thumb a good engineer uses:
- No light or weak light at the box: if most neighbours on the same street cabinet are dark too, the street cable is
  cut; if only this home, the fibre into the home is damaged. Never ask the customer to restart for a light problem.
- Box frozen with normal light: restart it remotely.
- Account paused: it is billing, not the network. Send the payment link; never send a technician.
- No route to the internet with a cut main hub link: switch to the standby link if one exists and is up; otherwise
  send the backbone team.
- Fine in the day but evening headroom below the plan speed: add uplink capacity.
- Line perfect up to the box but heavy Wi-Fi interference: change the Wi-Fi channel.
Do not repeat an action that was already tried. Answer in JSON."""
DECIDE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["cause", "action", "why"],
    "properties": {"cause": {"type": "string", "enum": list(CAUSES)},
                   "action": {"type": "string", "enum": [a for a in ACTION_LABEL if a != "none"] + ["none"]},
                   "why": {"type": "string"}},
}


def rules(m, tried):
    """The deterministic engineer: used when no model is available, and as the check on the model."""
    p = problems(m)
    if "light" in p:
        s = m["splitter"]
        if s["others"] >= 2 and s["others_down"] / s["others"] >= 0.5:
            return "area_cable_cut", "dispatch_cable_crew"
        return "damaged_drop", "dispatch_technician_home"
    if "box" in p:
        return "frozen_box", "remote_reboot"
    if "account" in p:
        return "payment_failed", "send_payment_link"
    if "route" in p:
        if m["olt"]["status"] != "up" or m["pop"]["status"] != "up":
            return "equipment_down", "escalate"
        standby = [x for x in m["pop"]["links"] if x["role"] == "standby" and x["status"] == "up" and x["link"] == "up"]
        if standby and not any(x["active"] for x in standby) and "reroute_standby" not in tried:
            return "hub_link_down", "reroute_standby"
        return "hub_link_down", "dispatch_backbone_crew"
    if "evening" in p:
        return "evening_congestion", "upgrade_uplink"
    if "wifi" in p:
        return "wifi_interference", "change_wifi_channel"
    return "healthy", "none"


def _readings_text(m, said):
    links = "; ".join(f"{x['role']} link to {x['label']}: {x['link']}{'' if x['active'] else ' (standby, not in use)'}"
                      f", core {x['status']}" for x in m["pop"]["links"])
    s = m["splitter"]
    evening = (f"Free at 9 pm: {m['free_peak_mbps']} Mbps; plan needs {m['plan_mbps']} Mbps." if m["flow_gbps"] > 0 else
               "Evening headroom: not measurable, because there is no route to the core at all (that is NOT congestion).")
    return (f"Customer said: {said or '(nothing)'}\n"
            f"Light at the box: {m['rx'] if m['rx'] is not None else 'none'} dBm (normal -8 to -27). Box: {m['box']}. "
            f"Session: {m['session']}. Account: {m['account']}.\n"
            f"Street cabinet {s['label']}: {s['others_down']} of {s['others']} neighbour homes also offline.\n"
            f"Area exchange {m['olt']['label']}: {m['olt']['status']}. City hub {m['pop']['label']}: {m['pop']['status']}. "
            f"{links}.\n"
            f"Capacity to the core now (maxFlow): {m['flow_gbps']} Gbps. {evening}\n"
            f"Wi-Fi: channel {m['wifi']['channel']}, interference {round(m['wifi']['interference'] * 100)}%, "
            f"{m['wifi']['nearby']} nearby networks.")


def feasible(action, m):
    """Can this action be carried out on this line at all? (None if yes, else why not.)"""
    if action == "reroute_standby" and not any(x["role"] == "standby" and x["status"] == "up" and x["link"] == "up"
                                               and not x["active"] for x in m["pop"]["links"]):
        return f"{m['pop']['label']} has no working standby link to switch to"
    if action == "upgrade_uplink" and m["flow_gbps"] <= 0:
        return "there is no route at all, so more capacity wouldn't carry anything"
    if action == "send_payment_link" and m["account"] == "active":
        return "the account is already active"
    return None


CAUSE_OF = {a: c for c, a in CAUSES.items()} | {"dispatch_backbone_crew": "hub_link_down"}


def _memory_says(s):
    return (f"{ACTION_LABEL[s['action']]}: fixed this {s['successes']} time{'s' if s['successes'] != 1 else ''} "
            f"({s['nearby']} nearby), failed {s['failures']}; past path {' → '.join(s['steps'])}")


def from_memory(run, m, tried, issues):
    """Ask the procedure graph first. A confident, feasible match decides; otherwise it is context for the model."""
    log = []
    s = procedural.suggest(run.tenant, m, run.data["symptoms"], issues, tried, _ms(), log)
    if s is None:
        run.step("memory", "Procedural memory: no past procedure for these readings",
                 "Nothing verified yet for " + (", ".join(procedural.readings(m)) or "these readings") + ".", "info", log)
        return None, None
    why_not = feasible(s["action"], m)
    if not s["confident"] or why_not:
        run.step("memory", f"Procedural memory: closest match is {ACTION_LABEL[s['action']].lower()}, not taking it",
                 _memory_says(s) + (f". Not feasible: {why_not}" if why_not else
                                    f". Success rate {s['rate']:.0%} is below {procedural.CONFIDENT:.0%}") +
                 "; the model decides, with this as context.", "info", log, {"procedure": s})
        return None, s
    times = f"{s['successes']} time{'s' if s['successes'] != 1 else ''}"
    run.step("memory", f"Procedural memory: {ACTION_LABEL[s['action']].lower()} fixed this {times} "
             f"({s['nearby']} nearby) — taking it",
             f"{_memory_says(s)}. Score {s['score']} (success {s['rate']:.0%}, nearest {s['nearest_hops']} hops).",
             "ok", log, {"procedure": s})
    r_cause, r_action = rules(m, tried)
    cause = CAUSE_OF[s["action"]]
    return {"cause": cause, "action": s["action"], "by": "procedural memory", "procedure": s["id"],
            "agrees": (cause, s["action"]) == (r_cause, r_action), "rules": {"cause": r_cause, "action": r_action},
            "why": f"Procedural memory: this exact reading pattern was fixed by a "
                   f"{FIX_NAME.get(s['action'], s['action'])} {times} before ({s['nearby']} nearby)."}, s


def decide(m, said, tried, hint=None):
    """The model reasons over the readings; the rules are the fallback and the safety net."""
    r_cause, r_action = rules(m, tried)
    try:
        out = llm.chat_json("answer", DECIDE_SYSTEM,
                            _readings_text(m, said) + f"\nAlready tried: {', '.join(tried) or 'nothing'}"
                            + (f"\nProcedural memory (past verified fixes, not proof): {_memory_says(hint)}" if hint else ""),
                            DECIDE_SCHEMA, "lab_decide")
        cause, action, why, model = out["cause"], out["action"], out["why"].strip(), out.get("_model")
        if action not in ACTION_LABEL or action in tried or (action == "none" and problems(m)):
            raise ValueError("invalid or repeated action")
        if (why_not := feasible(action, m)) and r_action not in ("none", "escalate"):
            return {"cause": r_cause, "action": r_action, "by": "rules", "agrees": False, "overruled": action,
                    "rules": {"cause": r_cause, "action": r_action},
                    "why": f"{_rule_why(r_cause, m)} (The model wanted to {ACTION_LABEL[action].lower()}, but {why_not}.)"}
        return {"cause": cause, "action": action, "why": why, "by": model or "model",
                "rules": {"cause": r_cause, "action": r_action}, "agrees": (cause, action) == (r_cause, r_action)}
    except Exception:
        return {"cause": r_cause, "action": r_action, "by": "rules", "agrees": True,
                "rules": {"cause": r_cause, "action": r_action}, "why": _rule_why(r_cause, m)}


def _rule_why(cause, m):
    s = m["splitter"]
    return {
        "area_cable_cut": f"No light at the box and {s['others_down']} of {s['others']} neighbours on the same cabinet are dark: the problem is upstream of the cabinet.",
        "damaged_drop": f"Light is {m['rx']} dBm while the neighbours are fine: the fibre into this one home is losing signal.",
        "frozen_box": "Light is healthy but the box stopped passing traffic: a remote restart clears that.",
        "payment_failed": "Network path and light are healthy; the login is rejected because the account is paused.",
        "hub_link_down": "No route to the core: the city hub's main link is cut.",
        "evening_congestion": f"Only {m['free_peak_mbps']} Mbps free at 9 pm against a {m['plan_mbps']} Mbps plan.",
        "wifi_interference": f"Everything up to the box is healthy, but Wi-Fi interference is {round(m['wifi']['interference'] * 100)}%.",
        "equipment_down": "Network equipment on the path is down; network operations own that.",
        "healthy": "Every reading is healthy.",
    }[cause]


class Run:
    def __init__(self, tenant, customer, ticket, chat_sid, said, picked=False):
        self.tenant, self.customer, self.ticket, self.chat_sid, self.said = tenant, customer, ticket, chat_sid, said
        self.picked = picked
        self.followup = False
        self.id = f"run-{uuid.uuid4().hex[:6]}"
        self.data = {"id": self.id, "customer": customer, "name": cards.display(customer, "customer"),
                     "ticket": ticket.upper() if ticket else None, "said": said, "symptoms": symptoms(said),
                     "started_at": _ms(), "status": "running", "steps": [], "messages": [], "diagnosis": None,
                     "actions": [], "fault": None, "verdict": None}
        with _lock:
            _runs.setdefault(tenant, []).insert(0, self.data)
            del _runs[tenant][20:]

    def step(self, kind, title, detail="", status="info", log=None, data=None):
        s = {"i": len(self.data["steps"]), "kind": kind, "title": title, "detail": detail, "status": status,
             "at": _ms(), "data": data or {},
             "cypher": [{"name": e["name"], "query": e["query"], "ms": e["ms"], "rows": e["rows"]} for e in (log or [])][:4]}
        self.data["steps"].append(s)
        events.emit(self.tenant, "lab_step", {"run": self.id, "step": s})
        time.sleep(STEP_PAUSE)
        return s

    def hear(self, text):
        """The customer's reply, as it shows in their chat."""
        msg = {"text": text, "at": _ms(), "me": True}
        self.data["messages"].append(msg)
        events.emit(self.tenant, "lab_step", {"run": self.id, "message": msg})

    def tell(self, text, image=None):
        """A plain-language message in the customer's own chat."""
        at = _ms()
        sid = self.chat_sid or network._session(self.customer, at)
        memory.remember(self.tenant, agent="resolver", session_id=sid, customer=self.customer, text=text, at=at,
                        facts=[], speaker="resolver")
        msg = {"text": text, "at": at, **({"image": image} if image else {})}
        self.data["messages"].append(msg)
        events.emit(self.tenant, "lab_step", {"run": self.id, "message": msg})


SCRIPTED: set = set()  # tenants whose scripted demo story is loading right now (it uses the old fixed tools)


def lab_on(tenant):
    """Live chats always diagnose on the network graph (built on demand); only the scripted story doesn't."""
    return tenant not in SCRIPTED


def has_line(tenant, customer):
    """Connected in the network graph (a box on a street cabinet, or at least an area exchange to give one)."""
    return bool(_q(tenant, "has a line", "MATCH (:Entity {name_key:$c})-[:HAS_ONT|CONNECTED_VIA]->() RETURN 1 LIMIT 1",
                   {"c": norm(customer)}, ro=True))


def start(tenant, customer, ticket=None, chat_sid=None, said=None, picked=False, followup=False):
    """Investigate in the background; returns the run id (None if one is already running for this customer)."""
    key = (tenant, norm(customer))
    with _lock:
        _expected.discard(key)
        if key in _busy:
            return None
        _busy.add(key)
    run = Run(tenant, norm(customer), norm(ticket) if ticket else None, chat_sid, said, picked)
    run.followup = followup

    def go():
        try:
            investigate(run)
        except Exception as e:  # a crash is shown as a failed run, never swallowed silently
            run.data["status"] = "error"
            run.step("verify", "The run stopped", str(e)[:300], "bad")
        finally:
            with _lock:
                _busy.discard(key)
            run.data["ended_at"] = _ms()
            events.emit(tenant, "lab_run", {"run": run.id, "status": run.data["status"]})
    threading.Thread(target=go, daemon=True).start()
    return run.id


def _first(c):
    return cards.display(c, "customer").split()[0]


def _network_complaint(text):
    """A problem with the connection, not a question about it ("which plans?", "do you support PS5?")."""
    return bool(set(symptoms(text)) - {"one device"})


def _candidates(text):
    """Hidden causes that fit what the customer described (the world picks one; the resolver has to find it)."""
    t, sy = (text or "").lower(), symptoms(text)
    normal = "lights look normal" in sy
    if "red light" in sy or re.search(r"\blos\b", t):
        return ["damaged_drop", "area_cable_cut"]
    if re.search(r"\bwi-?fi\b", t) or "one device" in sy:
        return ["wifi_interference", "wifi_interference", "frozen_box"]
    if "evenings" in sy or re.search(r"\b(9|nine) ?(pm)?\b.*\b(slow|buffer)", t):
        return ["evening_congestion"]
    if "slow" in sy:
        return ["evening_congestion", "wifi_interference"]
    if "no internet" in sy or "drops" in sy or normal or _NETTALK.search(t):
        out = ["frozen_box", "payment_failed", "hub_link_dual", "hub_link_single"]
        return out if normal else out + ["area_cable_cut", "damaged_drop"]
    return []


def _match_complaint(tenant, customer, said):
    """Nothing is broken on this line yet, but the customer says something is: the simulated world makes it so,
    with a cause consistent with their words. The resolver is not told which."""
    c = next((x for x in customers(tenant) if x["key"] == customer), None)
    options = [p for p in _candidates(said) if c and _applies(PRESETS[p], c)]
    if not options:
        return None
    preset = random.choice(options)
    out = inject(tenant, preset, customer, blind=True, complain=False)
    _set_fault(tenant, out["fault"], notice=NOTICE[preset], matched=True)
    return out["fault"]


_SIMULATED: set = set()  # (tenant, customer) whose complaint came from Break it: nobody is typing, so a simulated customer answers


def _simulated_answer(run, kind):
    """Break it has no human on the other end. The customer answers the resolver the way a real one would, through the
    same path a chat takes (the reply is an episode, visit details are the customer's facts, on_chat wakes the run)."""
    time.sleep(2.5)
    t, c = run.tenant, run.customer
    if kind == "details":
        me = next((x for x in customers(t) if x["key"] == c), {})
        n = int(hashlib.sha1(c.encode()).hexdigest(), 16)
        address = ", ".join(x for x in (f"Flat {n % 40 + 2}", f"{n % 9 + 1} Cross Road", (me.get("area") or "").title(),
                                         (me.get("city") or "").title()) if x)
        phone = f"9{n % 10 ** 9:09d}"
        text = f"{address}. My mobile is {phone}. Evening works for me."
        memory.remember(t, agent="intake", session_id=run.chat_sid or network._session(c, _ms()), customer=c, at=_ms(),
                        text=text, speaker="customer", facts=[(c, "address", address.lower()), (c, "phone", phone)])
    else:
        text = {"guided": "I checked the thin cable at the back of the box. It's clicked in and not bent.",
                "confirm": "Yes, it's working now. Thanks!"}.get(kind, "Okay.")
        memory.record_episode(t, agent="intake", session_id=run.chat_sid or network._session(c, _ms()), customer=c,
                              text=text, at=_ms(), speaker="customer")
    run.hear(text)
    on_chat(t, c, text)


def _wait_for(run, kind, what, timeout=300):
    """Pause the run until the customer answers in the chat (on_chat wakes it). Returns their reply, or None."""
    ev = threading.Event()
    entry = {"run": run.id, "ticket": run.ticket, "kind": kind, "what": what, "event": ev, "reply": None}
    with _lock:
        _awaiting[(run.tenant, run.customer)] = entry
    run.data["awaiting"] = kind
    run.step("wait", f"Waiting for {_first(run.customer)}", what, "pending")
    if (run.tenant, run.customer) in _SIMULATED:
        threading.Thread(target=_simulated_answer, args=(run, kind), daemon=True).start()
    ev.wait(timeout)
    if kind != "details":
        with _lock:
            if _awaiting.get((run.tenant, run.customer)) is entry:
                _awaiting.pop((run.tenant, run.customer), None)
        run.data["awaiting"] = None
    return entry["reply"]


SLOT_LABEL = {"morning": "tomorrow morning (9 to 12)", "afternoon": "tomorrow afternoon (12 to 4)",
              "evening": "tomorrow evening (4 to 8)", "any": "the first free slot tomorrow"}


def _slot(text):
    t = (text or "").lower()
    if re.search(r"\b(any ?time|whenever|any slot|anything works)\b", t):
        return "any"
    for word, slot in (("morning", "morning"), ("afternoon", "afternoon"), ("evening", "evening"), ("night", "evening")):
        if word in t:
            return slot
    m = re.search(r"\b(\d{1,2})(?::\d\d)?\s*(am|pm)\b", t)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
        return "morning" if h < 12 else "afternoon" if h < 16 else "evening"
    return None


def _visit_details(run):
    facts = [f for f in retrieve.customer_facts(run.tenant, run.customer) if f["active"] and f["subject"] == run.customer]
    pick = lambda p: next((f["object"] for f in reversed(facts) if f["predicate"] == p), None)
    address, phone = pick("address"), pick("phone") or pick("alt_phone")
    need = []
    if not address or not re.search(r"\d", address):
        need.append("your full street address (house or flat number and street)")
    if not phone:
        need.append("a mobile number the technician can call")
    if not run.data.get("slot"):
        need.append("a time that suits you: morning (9 to 12), afternoon (12 to 4) or evening (4 to 8)")
    return {"address": address, "phone": phone, "slot": run.data.get("slot"), "need": need}


def _collect_details(run):
    """Before anyone is sent to a home: street address, a mobile number and a visit slot, asked for in the chat."""
    d = _visit_details(run)
    if not d["need"]:
        return d
    run.step("think", "A home visit needs the customer's details first",
             "Missing: " + "; ".join(d["need"]) + ".", "info")
    run.tell(f"To send a technician to your home I need a few details, {_first(run.customer)}: "
             + "; ".join(d["need"]) + ".")
    for _ in range(2):  # intake keeps asking for whatever is still missing; the resolver checks after each answer
        deadline = time.time() + 300
        while time.time() < deadline:
            d = _visit_details(run)
            if not d["need"]:
                with _lock:
                    _awaiting.pop((run.tenant, run.customer), None)
                run.data["awaiting"] = None
                run.step("memory", "Got everything for the visit", f"{d['address']} · mobile ending "
                         f"{re.sub(r'[^0-9]', '', d['phone'])[-4:]} · {SLOT_LABEL[d['slot']]}", "ok")
                return d
            if _wait_for(run, "details", "Street address, mobile number and a visit slot", timeout=60) is None:
                continue
        run.tell("Whenever you're ready, just send me " + "; ".join(d["need"]) + ", and I'll book the visit.")
    with _lock:
        _awaiting.pop((run.tenant, run.customer), None)
    return None


def investigate(run):
    t, c = run.tenant, run.customer
    ensure(t)  # a customer who just told intake where they live gets their box on a street cabinet now
    events.emit(t, "lab_run", {"run": run.id, "status": "running", "customer": c})
    if run.ticket and not run.picked:  # the resolver takes the ticket (so the console's auto-pickup won't run it twice)
        from . import queries as Q
        at = _ms()
        db.run(t, "pick up", Q.PICKUP, {"agent": "resolver", "ticket": run.ticket, "at": at})
        events.emit(t, "pickup", {"ticket": run.ticket.upper(), "agent": "resolver"}, at)
        memory.remember(t, agent="resolver", session_id=f"work-{run.ticket}", customer=c, at=at,
                        text=f"resolver picked up {run.ticket.upper()}",
                        facts=[(run.ticket, "has_status", "in progress")])
    # 1. shared memory: what intake learned, read by the resolver (and recorded as CONSULTED)
    log = []
    facts = [f for f in retrieve.customer_facts(t, c, log=log) if f["active"]
             and f["predicate"] in ("lives_in", "on_plan", "reported_issue", "owns_device", "has_router",
                                    "prefers_channel", "ticket_about", "address", "connection_type", "affected_device",
                                    "frequency", "issue_started", "connection_medium", "tried_fix")]
    sharing.consult(t, "resolver", [f["fact_id"] for f in facts], at=_ms(), log=log)
    about = [f["object"] for f in facts if f["predicate"] == "ticket_about" and run.ticket and f["subject"] == run.ticket]
    if not run.said:  # a picked-up ticket: its own issue; otherwise the last thing the customer typed, else intake's notes
        last = None if (run.picked and about) else _q(t, "last customer message", LAST_SAID, {"c": c}, ro=True)
        said = about if run.picked and about else [last[0][0]] if last else \
            [f["object"] for f in facts if f["predicate"] in ("reported_issue", "ticket_about")]
        run.said = said[0] if said else ""
    heard = " ".join([run.said] + [f["object"] for f in facts if f["predicate"] in ("reported_issue", "ticket_about")])
    run.data["said"], run.data["symptoms"] = run.said, symptoms(heard)
    run.step("memory", f"Read {len(facts)} facts from shared memory",
             "Written by intake from the chat; the resolver never asked the customer again.", "ok", log,
             {"facts": [{"id": f["fact_id"], "text": cards.sentence(f["subject"], f["predicate"], f["object"]),
                         "by": (f.get("agents") or ["?"])[0]} for f in facts],
              "symptoms": run.data["symptoms"]})
    network_issue = _network_complaint(heard)
    if network_issue and not run.followup and not _fault_for(t, measure(t, c)):
        _match_complaint(t, c, heard)  # the world's side; the resolver never sees this
    recent = any(r["customer"] == c and r["id"] != run.id and r["started_at"] > _ms() - 30 * 60_000 for r in _runs.get(t, []))
    on = (f"your ticket {run.ticket.upper()} ({about[0]})" if run.ticket and about else "your case")
    run.tell("Thanks for telling me. I'm taking another look at your line right now." if run.followup or recent else
             f"Hi {_first(c)}, I'm the resolver on {on}. I'm checking your connection from our side right now, "
             f"so you don't need to do anything yet.")
    m = before = _read(run)
    run.data["fault"] = _fault_for(t, m)
    if not problems(m):
        _healthy(run, m, network_issue)
        return
    tried, last = [], None
    issues = [norm(f["object"]) for f in facts if f["predicate"] in ("reported_issue", "ticket_about")]
    for _ in range(3):
        if not problems(m):
            break
        d, hint = from_memory(run, m, tried, issues)
        d = d or decide(m, run.said, tried, hint)
        run.data["diagnosis"] = d
        run.step("think", d["why"], f"Cause: {d['cause'].replace('_', ' ')} · next: {ACTION_LABEL[d['action']]}", "info",
                 data={"cause": d["cause"], "action": d["action"], "by": d["by"], "agrees": d["agrees"],
                       "rules": d["rules"], "hypotheses": _hypotheses(m)})
        if d["action"] in ("none", "escalate"):
            run.tell(_say("act", m, cause=d["cause"]))
            run.data["status"] = "handed over"
            _score(run, before, m, False)
            return
        visit = None
        if d["action"] == "dispatch_technician_home":
            # remote checks are done; one guided step with the customer before anyone is sent
            run.tell(f"Your box is only getting a weak signal through the fibre. Before I send anyone, one quick check: "
                     f"is the thin cable at the back of the box clicked in properly and not bent sharply? "
                     f"Push it in gently, then tell me once you've looked. [guide:fibre_cable]")
            _wait_for(run, "guided", "Checking the fibre cable at the back of the box", timeout=240)
            m2 = _read(run, verify=True)
            if not problems(m2):
                m, last = m2, "guided_check"
                break
            visit = _collect_details(run)
            if visit is None:
                run.step("wait", "Paused: waiting for the customer's visit details", "The case stays open.", "pending")
                run.tell("No rush. I'll book the visit as soon as you send those details.")
                run.data["status"] = "waiting on customer"
                return
        blast = _blast_radius(run, d["action"], m)  # a graph tool decides priority and who to warn, before acting
        tried.append(d["action"])
        run.data["actions"].append(d["action"])
        last = d["action"]
        done = threading.Event()
        res = act(t, d["action"], m, on_done=done.set)
        run.step("act", ACTION_LABEL[d["action"]], _act_detail(d["action"], m, res), "ok",
                 data={"action": d["action"], "delayed": res["delayed"]})
        if visit is not None:
            tech = experts.assign(t, run.ticket, m["olt"]["city"], _ms()) if run.ticket else None
            run.data["technician"] = tech
            digits = re.sub(r"[^0-9]", "", visit["phone"] or "")
            run.tell(f"Booked. {(tech or 'Our technician').title()} will come {SLOT_LABEL[visit['slot']]} to "
                     f"{visit['address'].title()} and replace the damaged cable. They'll call you on the number ending "
                     f"{digits[-4:]} before they arrive. You don't need to restart anything.")
        else:
            run.tell(_say("act", m, action=d["action"], tech=run.data.get("technician"), retry=len(tried) > 1))
        if d["action"] in ("dispatch_cable_crew", "dispatch_backbone_crew"):
            _notify_area(run, d["action"], m, blast)
        if res["delayed"]:
            run.step("wait", "Waiting for the field job", f"Fast-forwarded: {res['delayed']} s in the lab "
                     f"(about {'2 hours' if d['action'] != 'send_payment_link' else 'a few minutes'} in real life).",
                     "pending")
            done.wait(res["delayed"] + 5)
        m = _read(run, verify=True)
        if d.get("procedure") and problems(m):  # memory's pick didn't fix it: the graph learns that
            log = []
            p = procedural.failed(t, d["procedure"], run.ticket, _ms(), log)
            run.step("memory", "Procedural memory was wrong here: failure recorded",
                     f"{ACTION_LABEL[d['action']]} did not clear {', '.join(problems(m))}; that procedure now has "
                     f"{p['failures'] if p else '?'} failure(s).", "bad", log)
    ok = not problems(m)
    run.step("verify", "Verified: every reading is healthy" if ok else "Still failing: " + ", ".join(problems(m)),
             "Proved by measuring the network again, not by trusting the action.", "ok" if ok else "bad")
    if tried and last != "guided_check":  # the ordered path, failed attempts included; a success only if re-measured
        log = []
        p = procedural.record(t, before, tried, ok, run.data["symptoms"], issues, run.ticket, _ms(), log)
        if p:
            run.step("memory", f"Procedural memory: {'saved' if ok else 'marked failed'} the path {' → '.join(tried)}",
                     f"{p['successes']} success(es), {p['failures']} failure(s) for this procedure"
                     + (" — only counted because the re-measurement passed." if ok else "."), "ok" if ok else "bad",
                     log, {"procedure": p})
    if ok and last == "reroute_standby":  # working again on the backup; book the permanent repair
        act(t, "dispatch_backbone_crew", m)
        run.step("act", ACTION_LABEL["dispatch_backbone_crew"], "Service is restored on the standby link; the main link "
                 "still needs a physical repair, so the backbone team is booked.", "ok")
    _score(run, before, m, ok)
    if ok:
        if last == "guided_check":
            run.tell(f"That did it, {_first(c)}: the signal is healthy again now the cable is seated properly. "
                     f"Can you check on your side and tell me if it's working?")
        else:
            _remember_fix(run, before, m, tried)
            run.tell(_say("done", m, action=last, tech=run.data.get("technician"), before=before)
                     + " Can you check on your side and tell me if it's working now?")
        run.data["status"] = "resolved"
        _ask_confirmation(run)
    else:
        tech = experts.assign(t, run.ticket, m["olt"]["city"], _ms()) if run.ticket else None
        run.step("verify", "Not fixed after three attempts", f"Escalated to a senior technician"
                 f"{' (' + tech.title() + ')' if tech else ''}.", "bad")
        run.tell(f"{_first(c)}, I've tried what I can remotely and it isn't fully fixed yet, so I've booked a senior "
                 f"technician to take over. I'm sorry this is taking longer.")
        run.data["status"] = "unresolved"


def _healthy(run, m, network_issue):
    """Every reading is fine. Never 'you're good to go' to someone who says it's broken: it's probably inside the home."""
    first = _first(run.customer)
    if not network_issue:
        issue = (run.said or "your request").strip().rstrip(".")
        run.step("think", "Not a network problem", "The line is healthy; this is a request for the team.", "info")
        run.tell(f"I've picked up your request ({issue}). Your connection itself is healthy, so the team will take it "
                 f"from here and update you right here.")
        run.data["status"] = "handed over"
        return
    run.step("think", "Every reading up to the box is healthy",
             "So the trouble is most likely inside the home: the box itself, its placement, or a device.", "info")
    run.tell(f"I've tested everything from our side again and it's healthy all the way to your box, {first}, so it's "
             f"probably something inside your home. Could you restart the box for me? Unplug it, wait 10 seconds and "
             f"plug it back in. [guide:restart_box] Tell me once it's back on, and whether it's still acting up."
             if run.followup else
             f"I've tested your line from our side and it's healthy all the way to your box, {first}, so it's probably "
             f"something inside your home. Could you restart the box for me? Unplug it, wait 10 seconds and plug it "
             f"back in. [guide:restart_box] Tell me once it's back on.")
    reply = _wait_for(run, "guided", "Restarting the box", timeout=300)
    if not reply:  # no answer is not "fixed": the case stays open for them
        run.step("wait", f"No reply from {first} yet", "The case stays open until they answer.", "pending")
        run.data["status"] = "waiting on customer"
        return
    if _NO.search(reply) or VISIT_ASK.search(reply) or _STILL.search(reply):  # "send someone", "still not working": a visit
        run.tell("Thanks for trying. I'll get a technician to check inside your home.")
        visit = _collect_details(run)
        if visit:
            tech = experts.assign(run.tenant, run.ticket, m["olt"]["city"], _ms()) if run.ticket else None
            run.tell(f"Booked. {(tech or 'Our technician').title()} will come {SLOT_LABEL[visit['slot']]} to "
                     f"{visit['address'].title()}. They'll call you before they arrive.")
            _home_visit(run, tech, visit)
            return
    run.tell(f"Thanks, {first}. If it acts up again, tell me what you were doing when it happened and I'll dig in.")
    run.data["status"] = "resolved"


def _home_visit(run, tech, visit):
    """Sent help finishes the case: the technician goes (a field job, fast-forwarded like the others, so the crew shows on
    the customer's line), fixes what is inside the home, the line is measured again, and the case is written as fixed
    (fixed_by, the ticket resolved, and a resolves fact so the next similar case benefits). The customer has the last word."""
    who, delay = (tech or "our technician").title(), DELAY["dispatch_technician_home"]
    run.step("act", ACTION_LABEL["dispatch_technician_home"], f"{who}, {SLOT_LABEL[visit['slot']]}, at {visit['address'].title()}.",
             "ok", data={"action": "dispatch_technician_home", "delayed": delay})
    run.step("wait", "Waiting for the field job", f"Fast-forwarded: {delay} s in the lab (about 2 hours in real life).", "pending")
    time.sleep(delay)
    after = _read(run, verify=True)
    issue = (run.said or "the problem inside the home").strip().rstrip(".")
    fix = "technician home visit"
    if run.ticket:
        memory.remember(run.tenant, agent="resolver", session_id=f"work-{run.ticket}", customer=run.customer, at=_ms(),
                        text=f"{who} visited {run.customer} for {run.ticket.upper()} and fixed it inside the home ({issue}); "
                             f"line re-measured: light {after['rx']} dBm, box {after['box']}, login {after['session']}",
                        facts=[(run.ticket, "tried_fix", fix), (run.ticket, "fixed_by", fix), (run.ticket, "has_status", "resolved"),
                               (fix, "resolves", norm(issue))])
    # an in-home fix has no injected fault to grade against: the re-measure only shows the line is still healthy,
    # so the close rests on the technician's word, never on "verified by re-measurement"
    graded = bool(run.data.get("fault")) and not problems(after)
    run.step("verify", f"{who} fixed it inside the home" if graded else f"Technician confirmed fixed: {who}",
             f"{issue}; " + ("the re-measure proves the fault is gone, so the case is closed" if graded else
                             "nothing on the line to re-measure against, so the case is closed on the technician's "
                             "confirmation") + " and the fix is saved to procedural memory.", "ok")
    run.tell(f"{who} has been and fixed it ({issue}), and your line is healthy. Can you check on your side and tell me "
             f"if it's working now?")
    run.data["status"] = "resolved"
    _ask_confirmation(run)


def _read(run, verify=False):
    t, c = run.tenant, run.customer
    log = []
    m = measure(t, c, log)
    if m is None:
        raise RuntimeError("this customer has no line in the network graph")
    kind = "verify" if verify else "check"
    tag = "Re-measured: " if verify else ""
    light_ok = m["box"] not in ("no-signal", "flapping")
    run.step(kind, f"{tag}line test on {_first(c)}'s box",
             f"Light {m['rx'] if m['rx'] is not None else 'none'} dBm · box {m['box']} · login {m['session']}",
             "ok" if light_ok and m["session"] == "ok" else "bad", log[:1],
             {"rx": m["rx"], "box": m["box"], "session": m["session"], "account": m["account"]})
    s = m["splitter"]
    run.step(kind, f"{tag}neighbours on {s['label']}", f"{s['others_down']} of {s['others']} other homes offline",
             "bad" if s["others_down"] else "ok", log[1:2], {"down": s["others_down"], "of": s["others"]})
    route = " → ".join([m["olt"]["label"], m["pop"]["label"]] +
                       [f"{x['label']} ({'cut' if x['link'] == 'cut' else 'standby' if not x['active'] else 'up'})"
                        for x in m["pop"]["links"]])
    run.step(kind, f"{tag}capacity to the core (algo.maxFlow)", f"{m['flow_gbps']:g} Gbps · {route}",
             "ok" if m["flow_gbps"] > 0 else "bad", log[2:4],
             {"gbps": m["flow_gbps"], "links": m["pop"]["links"]})
    curve = [round(min(1.0, m["olt"]["peak_gbps"] * x / m["flow_gbps"]), 3) if m["flow_gbps"] > 0 else 1.0 for x in CURVE]
    run.step(kind, f"{tag}evening headroom at 9 pm", f"{m['free_peak_mbps']:,} Mbps free · plan needs {m['plan_mbps']} Mbps",
             "ok" if m["free_peak_mbps"] >= m["plan_mbps"] else "bad", [],
             {"curve": curve, "free": m["free_peak_mbps"], "plan": m["plan_mbps"]})
    w = m["wifi"]
    run.step(kind, f"{tag}Wi-Fi survey", f"Channel {w['channel']} · interference {round(w['interference'] * 100)}% · "
             f"{w['nearby']} nearby networks", "ok" if w["interference"] < 0.5 else "bad", [], w)
    return m


def _hypotheses(m):
    p = problems(m)
    s = m["splitter"]
    out = [
        ("Box frozen", "box" in p, f"box reports '{m['box']}'"),
        ("Fibre into the home", "light" in p and not (s["others"] and s["others_down"] / s["others"] >= 0.5),
         f"light {m['rx']} dBm, {s['others_down']}/{s['others']} neighbours down"),
        ("Street cable", "light" in p and s["others"] and s["others_down"] / s["others"] >= 0.5,
         f"{s['others_down']}/{s['others']} neighbours down"),
        ("City hub link", "route" in p, f"{m['flow_gbps']:g} Gbps to the core"),
        ("Evening congestion", "evening" in p, f"{m['free_peak_mbps']} Mbps free at 9 pm"),
        ("Wi-Fi", "wifi" in p, f"interference {round(m['wifi']['interference'] * 100)}%"),
        ("Billing", "account" in p, f"account {m['account']}"),
    ]
    return [{"label": a, "likely": bool(b), "evidence": e} for a, b, e in out]


def _act_detail(action, m, res):
    return {
        "remote_reboot": f"Restart command sent to box {m['ont']}.",
        "change_wifi_channel": f"Wi-Fi moved off channel {m['wifi']['channel']}.",
        "dispatch_technician_home": f"Technician booked for port {m['port']} at {m['splitter']['label']}.",
        "dispatch_cable_crew": f"Cable crew sent to the feeder of {m['splitter']['label']}.",
        "reroute_standby": f"Standby link activated at {m['pop']['label']}.",
        "dispatch_backbone_crew": f"Backbone team sent to {m['pop']['label']}.",
        "upgrade_uplink": f"Second 10 Gbps port added on {m['olt']['label']}.",
        "send_payment_link": "Secure payment link sent to the registered number.",
    }.get(action, "") + (f" The world reports back in {res['delayed']} s." if res["delayed"] else "")


def _say(phase, m, action=None, cause=None, tech=None, before=None, retry=False):
    """What the customer reads, keyed by what was actually done (never by a guess about the cause)."""
    first = _first(m["customer"])
    city = (m["pop"]["city"] or "").title()
    tech = tech.title() if tech else "our technician"
    if phase == "act":
        text = {
            "remote_reboot": "Your internet box had frozen, so I've restarted it from our side. The lights will blink for "
                             "about a minute; that's normal.",
            "change_wifi_channel": f"Your line is perfect all the way to your box. The trouble is Wi-Fi: "
                                   f"{m['wifi']['nearby']} nearby networks share your channel, so I've moved yours to a "
                                   "quieter one. Your devices may reconnect for a few seconds. Tip: keep the box out in "
                                   "the open, at chest height, away from the TV and microwave. [guide:router_placement]",
            "dispatch_technician_home": f"The cable that brings internet into your home is damaged, so your box only gets "
                                        f"a very weak signal. That needs a hands-on fix, so I've booked {tech}. You don't "
                                        f"need to restart anything.",
            "dispatch_cable_crew": f"It's not your home: the cable to your street cabinet is cut, and "
                                   f"{m['splitter']['others_down']} homes nearby are affected too. Our repair crew is on "
                                   f"the way, and your box will come back on its own.",
            "reroute_standby": f"Our {city} hub lost its main link to the internet. I've switched your area to our backup "
                               f"link, so you should be back in a moment.",
            "dispatch_backbone_crew": f"Our {city} hub lost its link to the internet and it has to be repaired by hand. "
                                      f"Our network team is on it now; your box will reconnect by itself.",
            "upgrade_uplink": "Your connection is fine in the day, but in the evening the shared line in your area is "
                              "almost full. I've added more capacity to your area.",
            "send_payment_link": "Your connection itself is healthy, but your account is paused because the last payment "
                                 "didn't go through. I've sent a secure payment link to your registered number; once "
                                 "it's paid, you're back online automatically.",
        }.get(action)
        if text is None:  # nothing the resolver can do itself
            text = ("Our network team is already fixing a fault in your area, and I've linked your case to it."
                    if cause == "equipment_down" else
                    f"I've checked everything from our side and it all looks healthy right now, {first}. If it happens "
                    f"again, tell me what you were doing and I'll catch it.")
        return ("That didn't fully fix it, so I'm trying something else. " + text) if retry else text
    return {
        "remote_reboot": f"You're back online, {first}. The box restarted fine and the connection test passes.",
        "change_wifi_channel": f"Done, {first}: Wi-Fi interference is down from "
                               f"{round((before or m)['wifi']['interference'] * 100)}% to "
                               f"{round(m['wifi']['interference'] * 100)}%. Your devices should stay connected now.",
        "dispatch_technician_home": f"{tech} replaced the cable. Your signal is healthy again ({m['rx']} dBm) and "
                                    f"you're back online.",
        "dispatch_cable_crew": "The street cable is repaired and your connection is back. Sorry for the trouble!",
        "reroute_standby": "You're back online on our backup link. The main link is being repaired, and you won't "
                           "notice the switch back.",
        "dispatch_backbone_crew": f"The {city} hub link is repaired and you're back online.",
        "upgrade_uplink": f"At 9 pm you now have {m['free_peak_mbps']:,} Mbps to spare, "
                          + (f"more than your {m['plan'].title()} plan needs." if m["plan"] else "plenty for any of our plans.")
                          + " Evenings should be smooth now.",
        "send_payment_link": "Payment received, thank you! Your internet is back on.",
    }.get(action, f"Everything checks out, {first}. You're good to go.")


# where a fault that isn't in one home sits, and how far below it the customers are (customer -> box -> cabinet -> exchange -> hub)
UPSTREAM = {"dispatch_cable_crew": ("splitter", 2, "street cabinet"), "upgrade_uplink": ("olt", 3, "exchange"),
            "reroute_standby": ("pop", 4, "hub"), "dispatch_backbone_crew": ("pop", 4, "hub")}


def _blast_radius(run, action, m):
    """The resolver's graph tool, called mid-decision, before it acts: who else hangs below the failing node. It is the
    same typed catalogue tool MCP clients get (tools_catalog.affected_by, a bounded traversal returning each path).
    Its answer decides the ticket's priority (one field job clears everyone behind the node) and who is warned first."""
    if action not in UPSTREAM:
        return None
    from . import tools_catalog  # lazy: the catalogue imports the network module, which imports this one's callers
    where, depth, word = UPSTREAM[action]
    node, log = m[where], []
    out = tools_catalog.call(run.tenant, "affected_by", {"node": node["id"], "depth": depth}, log)
    people = sorted({r["id"] for r in out["result"] if r["kind"] == "customer"})
    others = [c for c in people if c != run.customer]
    if others and run.ticket:
        memory.remember(run.tenant, agent="resolver", session_id=f"work-{run.ticket}", customer=run.customer, at=_ms(),
                        text=f"resolver raised {run.ticket.upper()} to high priority: {len(people)} customers are behind "
                             f"{node['label']}", facts=[(run.ticket, "has_priority", "high")], log=log)
    decision = (f"high priority: one field job clears all {len(people)}, and the other {len(others)} are warned before they complain"
                if others else f"normal priority: only {_first(run.customer)} is behind it")
    run.step("think", f"Blast radius: {len(people)} customer{'s' if len(people) != 1 else ''} behind the {word} {node['label']}",
             f"Graph tool affected_by(node={node['id']}, depth={depth}): {out['rows']} nodes below it in {out['ms']} ms. "
             f"Decision: {decision}.", "info", log=log,
             data={"tool": "affected_by", "args": {"node": node["id"], "depth": depth}, "customers": people,
                   "priority": "high" if others else "normal", "outcome": out["outcome"]})
    return others


def _notify_area(run, action, m, others=None):
    """Tell the other real customers behind the same fault before they have to complain: the ones the blast-radius
    tool found (or, if it didn't run, the same walk below the cabinet or hub)."""
    t = run.tenant
    where = "street cabinet" if action == "dispatch_cable_crew" else "hub"
    if others is None:
        rows = (_q(t, "customers on the cabinet", "MATCH (s:Splitter {node_id:$s})<-[:DROP]-(o:Ont) WHERE o.customer IS NOT NULL "
                   "RETURN o.customer", {"s": m["splitter"]["id"]}, ro=True) if where == "street cabinet" else
                _q(t, "customers on the hub", "MATCH (:Pop {node_id:$p})<-[:UPLINK]-(:Olt)<-[:PON]-(:Splitter)<-[:DROP]-(o:Ont) "
                   "WHERE o.customer IS NOT NULL RETURN o.customer", {"p": m["pop"]["id"]}, ro=True))
        others = sorted({r[0] for r in rows} - {run.customer})
    for c in others:
        at = _ms()
        memory.remember(t, agent="resolver", session_id=network._session(c, at), customer=c, at=at, facts=[],
                        speaker="resolver", text=f"Hi {_first(c)}, heads up: there's a fault on our {where} near you that "
                        f"may affect your internet. A crew is already fixing it, so there's no need to call.")
    if others:
        run.step("act", f"Told {len(others)} other customer{'s' if len(others) > 1 else ''} before they complained",
                 ", ".join(cards.display(c, "customer") for c in others), "ok")


def _fault_for(tenant, m):
    f = next((f for f in _faults(tenant) if _touches(f, m)), None)
    return f["id"] if f else None


def _score(run, before, after, ok):
    fid = run.data.get("fault")
    if not fid:
        return
    f = next((x for x in _faults(run.tenant, active_only=False) if x["id"] == fid), None)
    if not f:
        return
    d = run.data.get("diagnosis") or {}
    correct = d.get("cause") == f["cause"]
    _set_fault(run.tenant, fid, diagnosed_as=d.get("cause"), correct=correct, fixed=ok,
               actions=run.data["actions"], first_action=(run.data["actions"] or [None])[0],
               run=run.id, solved_at=_ms())
    run.data["verdict"] = {"truth": f["cause"], "truth_label": PRESETS[f["preset"]]["title"],
                           "said": d.get("cause"), "correct": correct, "fixed": ok}
    run.step("verify", f"Graded against the hidden truth: {'correct' if correct else 'wrong'} diagnosis"
             + (", fixed" if ok else ", not fixed"),
             f"Injected fault: {PRESETS[f['preset']]['title']}. The resolver never read this.",
             "ok" if correct and ok else "bad")


def _remember_fix(run, before, after, tried):
    """Procedural memory, but only for a fix the readings proved: the evidence goes in the same episode."""
    if not run.ticket or not tried:
        return
    fix = FIX_NAME.get(tried[-1], tried[-1])
    from .agents import tickets
    info = next((x for x in tickets(run.tenant) if x["ticket"] == run.ticket), None)
    issues = (info or {}).get("issues") or ([run.said] if run.said else [])
    evidence = (f"before: light {before['rx']} dBm, box {before['box']}, login {before['session']}, "
                f"{before['flow_gbps']:g} Gbps, {before['free_peak_mbps']} Mbps free at 9 pm; after: light {after['rx']} dBm, "
                f"box {after['box']}, login {after['session']}, {after['flow_gbps']:g} Gbps, "
                f"{after['free_peak_mbps']} Mbps free at 9 pm")
    facts = [(run.ticket, "tried_fix", fix), (run.ticket, "fixed_by", fix), (run.ticket, "has_status", "resolved")] + \
            [(fix, "resolves", norm(i)) for i in issues[:2]]
    memory.remember(run.tenant, agent="resolver", session_id=f"work-{run.ticket}", customer=run.customer, at=_ms(),
                    text=f"resolver verified '{fix}' on {run.ticket.upper()} by re-measuring ({evidence})", facts=facts)
    run.step("memory", f"Saved '{fix}' to procedural memory", "Only written because the re-measurement passed; "
             "the evidence is stored with it.", "ok", data={"fix": fix, "evidence": evidence})


# ---------------------------------------------------------------- complaints and the console view

def _complain(tenant, customer, text):
    """The customer reports it the way a non-technical person would, through intake (a real chat turn)."""
    from .agents import Intake, open_ticket_for
    with _lock:
        _SIMULATED.add((tenant, norm(customer)))  # and answers the resolver's questions by itself
    at = _ms()
    sid = network._session(customer, at)
    try:
        out = Intake().handle(tenant, customer=cards.display(customer, "customer"), session_id=sid, text=text, at=at,
                              reply_llm=True)
        opened = out.get("ticket_opened")
    except Exception as e:
        print(f"lab complaint via intake: {e}")
        opened = None
    if not opened:  # an older ticket is still open, or intake couldn't run: the resolver takes it from here
        start(tenant, customer, ticket=open_ticket_for(tenant, customer), chat_sid=sid, said=text)


def trouble(tenant, customer):
    """'I have a problem': a hidden fault on this customer's own line. They only get told what they'd notice at home."""
    ensure(tenant)
    c = next((x for x in customers(tenant) if x["key"] == norm(customer)), None)
    if not c:
        raise ValueError("tell the assistant where you live first, so you have a line in the network")
    for f in _faults(tenant):  # one problem at a time on your own line
        if f["customer"] == c["key"]:
            return {"fault": f["id"], "notice": f.get("notice") or NOTICE[f["preset"]], "customer": c["key"]}
    preset = random.choice([p for p, spec in PRESETS.items() if _applies(spec, c)])
    out = inject(tenant, preset, c["key"], blind=True, complain=False)
    _set_fault(tenant, out["fault"], notice=NOTICE[preset], human=True)
    return {"fault": out["fault"], "notice": NOTICE[preset], "customer": c["key"]}


def home(tenant, customer):
    """The customer's own box as they'd see it: lights, a speed test, Wi-Fi, and what they've noticed."""
    m = measure(tenant, norm(customer))
    if m is None:
        return None
    nosig, flap, ok = m["box"] == "no-signal", m["box"] == "flapping", m["session"] == "ok"
    hour = time.localtime().tm_hour
    free_now = max(0.0, m["flow_gbps"] - m["olt"]["peak_gbps"] * CURVE[hour]) * 1000 if m["flow_gbps"] > 0 else 0
    poor_wifi = m["wifi"]["interference"] >= 0.5
    notice = next((f.get("notice") for f in _faults(tenant) if f["customer"] == m["customer"] and f.get("notice")), None)
    return {
        "lights": {"power": "on", "pon": "off" if nosig else "blink" if flap else "on",
                   "los": "red" if nosig else "blink" if flap else "off",
                   "internet": "on" if ok else "off", "wifi": "blink" if poor_wifi else "on"},
        "speed_now": round(min(m["plan_mbps"], free_now)) if ok else 0,
        "speed_9pm": round(min(m["plan_mbps"], m["free_peak_mbps"])) if ok else 0,
        "plan": m["plan"], "plan_mbps": m["plan_mbps"], "online": ok, "hour": hour,
        "wifi": "poor away from the box" if poor_wifi else "strong", "notice": notice,
        "area": m["olt"]["area"], "cabinet": m["splitter"]["label"], "hub": m["pop"]["label"],
    }


# ---------------------------------------------------------------- the customer closes the loop

_awaiting: dict = {}  # (tenant, customer) -> {"run", "ticket"}
_YES = re.compile(r"\b(yes|yeah|yep|yup|ya|works|working|fixed|perfect|great|all good|it'?s (fine|good|back)|back online|sorted)\b", re.I)
_NO = re.compile(r"^\s*(no|nope|nah|not really)\b|\b(not|isn'?t|doesn'?t|didn'?t|still)\s+(work\w*|fixed|good|better|ok|okay|right)"
                 r"|\bstill\b.{0,30}\b(drop\w*|slow|down|broken|same|cutting|going off|lag\w*)|\bsame (problem|issue|thing)\b"
                 r"|\b(again|worse)\b", re.I)
_NETTALK = re.compile(r"\b(internet|wifi|wi-fi|net|connection|router|box|light)\b", re.I)


def _ask_confirmation(run):
    with _lock:
        _awaiting[(run.tenant, run.customer)] = {"run": run.id, "ticket": run.ticket, "kind": "confirm"}
        if (run.tenant, run.customer) in _SIMULATED:
            threading.Thread(target=_simulated_answer, args=(run, "confirm"), daemon=True).start()
    run.data["awaiting"] = True
    run.step("wait", f"Asked {_first(run.customer)} to confirm on their side",
             "The readings say it's fixed; the customer gets the final word.", "info")


def _run(tenant, rid):
    return next((r for r in _runs.get(tenant, []) if r["id"] == rid), None)


def _note(tenant, rid, kind, title, detail, status):
    r = _run(tenant, rid)
    if not r:
        return
    s = {"i": len(r["steps"]), "kind": kind, "title": title, "detail": detail, "status": status, "at": _ms(), "data": {},
         "cypher": []}
    r["steps"].append(s)
    events.emit(tenant, "lab_step", {"run": rid, "step": s})


def on_chat(tenant, customer, text, opened=None):
    """Every customer chat turn: a yes/no to 'is it working now?', or a fresh complaint on a broken line."""
    c = norm(customer)
    with _lock:
        waiting = _awaiting.get((tenant, c))
    if waiting and waiting.get("kind") in ("guided", "details"):
        r = _run(tenant, waiting["run"])
        if waiting["kind"] == "details" and (slot := _slot(text)) and r is not None:
            r["slot"] = slot
        waiting["reply"] = text
        waiting["event"].set()
        return waiting["kind"]
    if waiting:
        no, yes = bool(_NO.search(text or "")), bool(_YES.search(text or ""))
        if not (yes or no):
            return None
        with _lock:
            _awaiting.pop((tenant, c), None)
        r = _run(tenant, waiting["run"])
        if r:
            r["awaiting"] = False
        at = _ms()
        if yes and not no:
            if r:
                r["confirmed"] = True
            _note(tenant, waiting["run"], "verify", f"{_first(c)} confirmed it's working", f"“{text}”", "ok")
            memory.remember(tenant, agent="resolver", session_id=f"work-{waiting['ticket'] or c}", customer=c, at=at,
                            facts=[], text=f"customer confirmed the fix on {(waiting['ticket'] or 'the line').upper()}: {text}")
            for f in _faults(tenant, active_only=False):
                if f.get("run") == waiting["run"]:
                    _set_fault(tenant, f["id"], confirmed=True)
            events.emit(tenant, "lab_state", {"why": "confirmed"})
            return "confirmed"
        _note(tenant, waiting["run"], "verify", f"{_first(c)} says it's still not right", f"“{text}”", "bad")
        return start(tenant, c, ticket=waiting["ticket"], said=text, followup=True)
    with _lock:
        expected = (tenant, c) in _expected
    from .agents import open_ticket_for
    if opened or not (expected or (has_line(tenant, c) and (_network_complaint(text) or _visit_ask(tenant, c, text))
                                   and not claimed(tenant, c))):
        stalled = None if opened else _stalled_ticket(tenant, c)
        if not stalled:
            return None  # a new ticket starts the resolver through the normal handoff (start() clears the claim)
        # an open case nobody is working: pick it back up from what memory already holds (said=None makes
        # investigate() read the ticket's issue and intake's facts), so the customer never has to say it again
        ticket, status = stalled
        return start(tenant, c, ticket=ticket, picked=status == "in progress")  # an open one is taken first
    ticket = open_ticket_for(tenant, c)
    if not expected and not _visit_ask(tenant, c, text) and not details_ready(tenant, c, ticket):
        return None  # intake is still asking about the problem; the handoff starts the resolver once it's done
    return start(tenant, c, ticket=ticket, said=text)  # an open ticket, or none: still look


_IDLE_MS = 10 * 60_000


def _stalled_ticket(tenant, customer):
    """The customer's open fault ticket when no resolver run is working it: never run, or the last run errored or went
    quiet. A run waiting for the customer or handed to a person is someone's work, so it is left alone."""
    from .agents import _request_only, tickets
    if claimed(tenant, customer) or not has_line(tenant, customer):
        return None
    mine = [t for t in tickets(tenant) if t["customer"] == customer and t["status"] in ("open", "in progress")
            and not _request_only(t["issues"])]
    if not mine:
        return None
    ticket, status = mine[0]["ticket"], mine[0]["status"]
    if not details_ready(tenant, customer, ticket):
        return None
    runs = [r for r in _runs.get(tenant, []) if (r.get("ticket") or "").lower() == ticket.lower()]
    if not runs:  # includes a restart: runs live in memory, the ticket in the graph
        return ticket, status
    r = runs[0]  # newest first
    if r.get("status") == "error":
        return ticket, status
    if r.get("status") in ("waiting on customer", "handed over", "unresolved") or r.get("awaiting"):
        return None
    idle = r.get("status") != "running" and (r.get("ended_at") or 0) < _ms() - _IDLE_MS
    return (ticket, status) if idle else None


def resolver_turn(tenant, customer, kind, handled, session_id, text=None):
    """The resolver's own answer while it owns the case, so intake doesn't talk over it. Returns (text, episode id)."""
    c = norm(customer)
    first = _first(c)
    if kind == "busy":
        text = "I'm still on it, checking your line right now. I'll message you here in a moment."
    elif kind == "guided":
        said = text or ""
        text = ("Understood, I'll arrange a technician for you." if (_NO.search(said) or VISIT_ASK.search(said) or _STILL.search(said))
                else "Thanks! Checking your line again now.")
    elif kind == "details":
        with _lock:
            w = _awaiting.get((tenant, c))
        r = _run(tenant, w["run"]) if w else None
        need = _visit_details(_Shim(tenant, c, r))["need"] if r else []
        text = ("Thanks. I still need " + "; ".join(need) + ".") if need else "Got everything. Booking the visit now."
    elif kind == "confirm":
        text = ("Brilliant, thanks for checking! I've closed your case. If anything acts up again, just tell me here."
                if handled == "confirmed" else
                "Sorry it's still acting up. I'm taking another look right now." if handled else
                f"Is it working for you now, {first}? Just tell me yes or no.")
    else:
        return None, None
    eid = memory.record_episode(tenant, agent="resolver", session_id=session_id, customer=c, text=text, at=_ms(),
                                speaker="resolver")
    return text, eid


def waiting_kind(tenant, customer):
    """What the resolver is waiting on for this customer: confirm / guided / details / busy, or None."""
    c = norm(customer)
    with _lock:
        w = _awaiting.get((tenant, c))
        return (w or {}).get("kind") or ("busy" if (tenant, c) in _busy or (tenant, c) in _expected else None)


def before_chat(tenant, customer, text):
    """Runs before intake replies, so both agents know the same things: the resolver claims a fresh complaint, and a
    visit slot in this message counts before intake decides what to ask."""
    c = norm(customer)
    with _lock:
        _SIMULATED.discard((tenant, c))  # a person is typing now (talk mode): they answer for themselves
        w = _awaiting.get((tenant, c))
        claimed_now = (tenant, c) in _busy or w is not None
    if w and w.get("kind") == "details" and (slot := _slot(text)):
        r = _run(tenant, w["run"])
        if r is not None:
            r["slot"] = slot
    if not claimed_now and (_network_complaint(text) or _visit_ask(tenant, c, text)) and has_line(tenant, c)             and (_visit_ask(tenant, c, text) or _ready_now(tenant, c)):
        with _lock:
            _expected.add((tenant, c))
        # ponytail: a fixed expiry; if the handoff never starts a run, intake stops deferring after 90 s
        threading.Timer(90, lambda: _expected.discard((tenant, c))).start()


def _ready_now(tenant, customer):
    from .agents import open_ticket_for  # lazy: agents imports this module
    return details_ready(tenant, customer, open_ticket_for(tenant, customer))


def _visit_ask(tenant, customer, text):
    """Asking for someone to come, or for help, while a ticket is open."""
    if not VISIT_ASK.search(text or ""):
        return False
    from .agents import open_ticket_for  # lazy: agents imports this module
    return bool(open_ticket_for(tenant, customer))


def details_ready(tenant, customer, ticket):
    """Intake has finished asking about the problem on this ticket (when it started, whole home or one device, WiFi or
    cable; an "I don't know" counts as answered). Until then the resolver waits,
    so it never diagnoses off a bare "my wifi has issues". A Break it customer is simulated: nobody answers intake."""
    c = norm(customer)
    with _lock:
        if (tenant, c) in _SIMULATED:
            return True
    if not ticket:
        return False
    from . import intake  # lazy: intake imports retrieve, which this module also uses
    have = intake.ticket_facts(tenant, norm(ticket))
    gave_up = {f["object"] for f in retrieve.customer_facts(tenant, c) if f["active"] and f["predicate"] == "doesnt_know"}
    return all(s.key in gave_up or any(p in have for p in s.preds) for s in intake.ASKED_ISSUE)


def claimed(tenant, customer):
    """True while the resolver is working on this customer or waiting for their answer."""
    c = norm(customer)
    with _lock:
        return (tenant, c) in _busy or (tenant, c) in _awaiting or (tenant, c) in _expected


def status_note(tenant, customer):
    """A line for intake's notes, so the two agents speak with one voice."""
    c = norm(customer)
    with _lock:
        w, busy = _awaiting.get((tenant, c)), (tenant, c) in _busy
    if w and w.get("kind") == "details":
        r = _run(tenant, w["run"])
        need = _visit_details(_Shim(tenant, c, r)).get("need") if r else []
        return ("The resolver is booking a home technician visit and still needs: " + "; ".join(need) +
                ". Ask the customer for exactly those, in one short message. Do not confirm a visit time yourself."
                if need else "The resolver has everything for the visit and is booking it now; just acknowledge.")
    if w and w.get("kind") == "guided":
        return (f"The resolver asked the customer to do one quick check ({w.get('what', '').lower()}) and is waiting. "
                "Just acknowledge what they say; the resolver will reply. Give no other troubleshooting steps.")
    if w and w.get("kind") == "confirm":
        return ("The resolver fixed the problem and asked whether it works now. If they say it works: thank them and "
                "say their case is now closed, in one or two short sentences. If it still doesn't work: say the resolver "
                "is looking at it again right now. Ask no other question.")
    with _lock:
        busy = busy or (tenant, c) in _expected
    if busy:
        return ("The resolver is checking this customer's connection right now. Do not give troubleshooting steps, do "
                "not promise or schedule a technician, and do not ask diagnostic questions; just say the resolver is on "
                "it and will message them here.")
    return None


class _Shim:  # what _visit_details needs from a run, rebuilt from the stored run data
    def __init__(self, tenant, customer, data):
        self.tenant, self.customer, self.data = tenant, customer, data


def customers(tenant, log=None):
    return [{"key": c, "name": cards.display(c, "customer"), "city": city, "area": area, "pop": pop, "pop_label": pl,
             "uplinks": n}
            for c, city, area, pop, pl, n in _q(tenant, "lab customers", CUSTOMERS, log=log, ro=True)]


def view(tenant, customer=None):
    ensure(tenant)
    custs = customers(tenant)
    focus = next((c for c in custs if c["key"] == norm(customer or "")), custs[0] if custs else None)
    out = {"customers": custs, "focus": focus["key"] if focus else None,
           "presets": [{"key": k, **{x: v[x] for x in ("title", "layer", "icon", "blurb", "says")},
                        "action": ACTION_LABEL[v["fix"]],
                        "customers": [c["key"] for c in custs if _applies(v, c)]} for k, v in PRESETS.items()],
           "faults": [], "runs": [], "score": score(tenant), "network": None, "home": None}
    faults = _faults(tenant, active_only=False)
    running = {r["fault"] for r in _runs.get(tenant, []) if r["status"] == "running"}
    out["faults"] = [{"id": f["id"], "active": f["active"], "mitigated": f.get("mitigated", False), "blind": f["blind"],
                      "customer": f["customer"], "injected_at": f["injected_at"],
                      **({} if f["blind"] and (f["active"] or f["id"] in running) and not f.get("solved_at") else
                         {"preset": f["preset"], "title": PRESETS[f["preset"]]["title"], "label": f["label"]})}
                     for f in faults[:12]]
    out["runs"] = _runs.get(tenant, [])[:8]
    if not focus:
        return out
    out["home"] = home(tenant, focus["key"])
    pop = focus["pop"]
    rows = _q(tenant, "lab view", VIEW, {"pop": pop, "peak": NORMAL_PEAK_GBPS}, ro=True)
    olts, homes, spl = {}, [], {}
    for olt, olabel, ostatus, peak, cap, sid, slabel, feeder, ont in rows:
        if olt not in olts:
            g = flow(tenant, olt)
            olts[olt] = {"id": olt, "label": olabel, "status": ostatus, "peak_gbps": peak, "uplink_gbps": cap,
                         "flow_gbps": g, "free_peak_mbps": round(max(0.0, g - peak) * 1000) if g > 0 else 0,
                         "curve": [round(min(1.0, peak * x / g), 3) if g > 0 else 1.0 for x in CURVE]}
        spl[sid] = {"id": sid, "label": slabel, "feeder": feeder, "olt": olt}
        rx = _light(ont, feeder)
        box = _box(rx, ont["box_state"])
        g = olts[olt]["flow_gbps"]
        homes.append({"id": ont["node_id"], "splitter": sid, "port": ont["port"], "customer": ont.get("customer"),
                      "name": ont.get("home"), "rx": rx, "box": box, "account": ont["account"],
                      "wifi": ont["wifi_interference"],
                      "state": ("dark" if box == "no-signal" else "flapping" if box == "flapping" else
                                "frozen" if box != "online" else "paused" if ont["account"] != "active" else
                                "offline" if g <= 0 else "slow" if olts[olt]["free_peak_mbps"] < 100 else
                                "wifi" if ont["wifi_interference"] >= 0.5 else "ok")})
    hub = [{"id": b, "label": lab, "status": st, "role": role, "active": act_, "link": link, "gbps": cap, "flow": fl}
           for b, lab, st, role, act_, link, cap, fl in _q(tenant, "hub uplinks", HUB, {"p": pop}, ro=True)]
    out["network"] = {"pop": {"id": pop, "label": focus["pop_label"], "city": focus["city"]}, "links": hub,
                      "olts": list(olts.values()), "splitters": list(spl.values()), "homes": homes}
    return out


def score(tenant):
    fs = [f for f in _faults(tenant, active_only=False)]
    solved = [f for f in fs if f.get("solved_at")]
    secs = [(f["solved_at"] - f["injected_at"]) / 1000 for f in solved if f.get("fixed")]
    return {"injected": len(fs), "investigated": len(solved), "correct": sum(1 for f in solved if f.get("correct")),
            "fixed": sum(1 for f in solved if f.get("fixed")),
            "first_try": sum(1 for f in solved if f.get("fixed") and len(f.get("actions") or []) == 1),
            "avg_seconds": round(sum(secs) / len(secs), 1) if secs else None}


def manual(tenant, action, customer):
    """An operator tries an action by hand: same world, same verification. Lets you show a wrong fix failing."""
    ensure(tenant)
    m = measure(tenant, norm(customer))
    if m is None:
        raise ValueError("no line for this customer")
    done = threading.Event()
    res = act(tenant, action, m, on_done=done.set)
    if res["delayed"]:
        done.wait(res["delayed"] + 5)
    after = measure(tenant, norm(customer))
    return {"action": action, "label": ACTION_LABEL[action], "before": problems(m), "after": problems(after),
            "fixed": bool(problems(m)) and not problems(after)}


if __name__ == "__main__":  # self-check of the pure parts, no database
    assert _network_complaint("my internet is acting weird today") and _network_complaint("wifi keeps disconnecting")
    assert not _network_complaint("what internet plans do you have?") and not _network_complaint("do you support ps5")
    assert not _network_complaint("i want a new connection")
    assert _NO.search("no, still not working") and _YES.search("yes it's working now") and not _NO.search("yes it works")
    assert symptoms("my PS5 keeps disconnecting from the wifi") == ["drops", "one device"]
    assert symptoms("The internet becomes super slow every night") == ["slow", "evenings"]
    base = {"rx": -19.0, "box": "online", "account": "active", "session": "ok", "flow_gbps": 10.0, "free_peak_mbps": 4000,
            "plan_mbps": 300, "wifi": {"interference": 0.1, "channel": 6, "nearby": 3},
            "splitter": {"others": 14, "others_down": 0, "label": "x"}, "olt": {"status": "up"},
            "pop": {"status": "up", "links": []}}
    assert rules(base, []) == ("healthy", "none")
    assert rules({**base, "box": "no-signal", "splitter": {"others": 14, "others_down": 14}}, [])[0] == "area_cable_cut"
    assert rules({**base, "box": "flapping"}, [])[0] == "damaged_drop"
    assert rules({**base, "box": "frozen"}, [])[1] == "remote_reboot"
    assert rules({**base, "account": "suspended"}, [])[1] == "send_payment_link"
    assert rules({**base, "free_peak_mbps": 50}, [])[1] == "upgrade_uplink"
    sb = {"role": "standby", "status": "up", "link": "up", "active": False}
    assert rules({**base, "flow_gbps": 0, "pop": {"status": "up", "links": [sb]}}, [])[1] == "reroute_standby"
    assert rules({**base, "flow_gbps": 0, "pop": {"status": "up", "links": []}}, [])[1] == "dispatch_backbone_crew"
    assert feasible("reroute_standby", {**base, "pop": {"label": "Kolkata POP", "links": []}})
    assert feasible("reroute_standby", {**base, "pop": {"label": "x", "links": [sb]}}) is None
    assert _box(-31.0, "online") == "no-signal" and _box(-28.5, "online") == "flapping" and _box(-19, "frozen") == "frozen"
    print("lab self-check ok")
