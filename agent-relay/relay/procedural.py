"""Procedural memory as a graph: what the resolver did, in order, and how well it worked, so the next decision is a
query over that graph instead of a guess.

  (:Procedure {id, signature, actions, fix, scope, successes, failures, last_used})
      -[:FIRST]->(:ProcStep {action, order})-[:NEXT {order}]->(:ProcStep)...      the steps, failed attempts included
      -[:SEEN_WITH]->(:Signal {name, kind})                                         readings ('reads:box') and symptoms ('said:no internet')
      -[:RESOLVES]->(:Entity issue)                                                 the issues intake recorded on the ticket
      -[:WORKED_AT {times, last, scope}]->(:Splitter)                               where it fixed a line (proximity is hops from there)
      -[:LEARNED_FROM {at, ok, actions}]->(:Entity ticket)                          provenance, one edge per case

Identity is (signature, ordered actions), so a repeat MERGEs onto the same path and only the counters move. Everything
here reads and writes mem:<tenant>; nothing in this module can see chaos:<tenant> (the hidden truth).
"""
import hashlib

from . import db

SCHEMA = [
    "CREATE INDEX FOR (p:Procedure) ON (p.id)",
    "CREATE INDEX FOR (s:ProcStep) ON (s.id)",
    "CREATE INDEX FOR (g:Signal) ON (g.name)",
]
_ready: set = set()

# A layer per fix: where in the network the procedure acts (shown as "the kind of place it worked on").
SCOPE = {"remote_reboot": "home", "change_wifi_channel": "home", "dispatch_technician_home": "home",
         "send_payment_link": "home", "dispatch_cable_crew": "cabinet", "upgrade_uplink": "exchange",
         "reroute_standby": "hub", "dispatch_backbone_crew": "hub"}
NEARBY_HOPS = 4    # same cabinet 0, same exchange 2, same hub 4 (Splitter-[:PON]->Olt-[:UPLINK]->Pop), other hubs 6
CONFIDENT = 0.6    # success rate (Laplace-smoothed) a match needs before it can decide without the model

# One atomic write per case: MERGE the procedure by identity, bump its counters, and (re)link its ordered steps,
# signals, issues, the cabinet it worked at and the ticket it came from. Re-running with the same ordered actions
# touches the same nodes and edges (MERGE), so repeats count up instead of duplicating.
RECORD = """
MERGE (p:Procedure {id:$id})
ON CREATE SET p.signature=$sig, p.actions=$actions, p.fix=last($actions), p.scope=$scope, p.readings=size($readings),
              p.successes=0, p.failures=0, p.created_at=$at
SET p.successes = p.successes + $ok, p.failures = p.failures + 1 - $ok, p.last_used = $at
FOREACH (x IN $signals |
  MERGE (g:Signal {name:x.name}) ON CREATE SET g.kind = x.kind
  MERGE (p)-[:SEEN_WITH]->(g))
FOREACH (i IN range(0, size($actions) - 1) |
  MERGE (s:ProcStep {id: $id + ':' + toString(i)}) ON CREATE SET s.action = $actions[i], s.order = i)
FOREACH (i IN range(1, size($actions) - 1) |
  MERGE (a:ProcStep {id: $id + ':' + toString(i - 1)})
  MERGE (b:ProcStep {id: $id + ':' + toString(i)})
  MERGE (a)-[:NEXT {order:i}]->(b))
MERGE (f:ProcStep {id: $id + ':0'})
MERGE (p)-[:FIRST]->(f)
WITH p
OPTIONAL MATCH (sp:Splitter {node_id:$splitter})
FOREACH (_ IN CASE WHEN sp IS NULL OR $ok = 0 THEN [] ELSE [1] END |
  MERGE (p)-[w:WORKED_AT]->(sp)
  SET w.times = coalesce(w.times, 0) + 1, w.last = $at, w.scope = $scope)
WITH p
OPTIONAL MATCH (t:Entity {name_key:$ticket})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
  CREATE (p)-[:LEARNED_FROM {at:$at, ok:$ok, actions:$actions}]->(t))
WITH p
OPTIONAL MATCH (i:Entity) WHERE $ok = 1 AND i.name_key IN $issues
WITH p, collect(i) AS issues
FOREACH (i IN issues | MERGE (p)-[:RESOLVES]->(i))
RETURN p.successes, p.failures
"""

# A suggestion that the re-measurement proved wrong: the procedure it came from loses confidence (and the ticket
# that showed it is kept as provenance).
FAILED = """
MATCH (p:Procedure {id:$id})
SET p.failures = p.failures + 1, p.last_failed = $at
WITH p
OPTIONAL MATCH (t:Entity {name_key:$ticket})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
  CREATE (p)-[:LEARNED_FROM {at:$at, ok:0, actions:[p.fix]}]->(t))
RETURN p.successes, p.failures
"""

# The decision query. From the readings measured now, traverse to every procedure learned on exactly those readings,
# walk its FIRST/NEXT chain to the step that fixed it, then weigh it by
#   success rate   (successes+1)/(successes+failures+2)
#   proximity      hops from this line's cabinet to the cabinets it worked at (both walk up PON/UPLINK and meet;
#                  FalkorDB has no undirected shortestPath, and the access network is a tree, so this is the distance)
#   recency        e^(-age/7 days)
#   evidence       symptoms the customer reported and issues intake recorded that the procedure resolved before.
SUGGEST = """
UNWIND $readings AS r
MATCH (:Signal {name:r})<-[:SEEN_WITH]-(p:Procedure)
WITH p, count(*) AS hit
WHERE hit = size($readings) AND p.readings = size($readings)
MATCH chain = (p)-[:FIRST]->(:ProcStep)-[:NEXT*0..]->(fix:ProcStep)
WHERE NOT (fix)-[:NEXT]->() AND NOT fix.action IN $tried
OPTIONAL MATCH (p)-[:SEEN_WITH]->(sy:Signal {kind:'symptom'}) WHERE sy.name IN $said
WITH p, chain, fix, count(sy) AS said_hit
OPTIONAL MATCH (p)-[:RESOLVES]->(i:Entity) WHERE i.name_key IN $issues
WITH p, chain, fix, said_hit, count(i) AS issue_hit
MATCH (here:Splitter {node_id:$splitter})
OPTIONAL MATCH (p)-[w:WORKED_AT]->(there:Splitter)
OPTIONAL MATCH hop = (here)-[:PON|UPLINK*0..3]->()<-[:PON|UPLINK*0..3]-(there)
WITH p, chain, fix, said_hit, issue_hit, there, w, min(length(hop)) AS hops
WITH p, chain, fix, said_hit, issue_hit, min(hops) AS nearest,
     sum(CASE WHEN hops <= $nearby THEN w.times ELSE 0 END) AS nearby,
     collect(CASE WHEN there IS NULL THEN NULL ELSE {at: there.node_id, hops: hops, times: w.times} END) AS places
WITH p, fix, [n IN nodes(chain) WHERE n:ProcStep | n.action] AS steps, said_hit, issue_hit, nearest, nearby, places,
     (p.successes + 1.0) / (p.successes + p.failures + 2.0) AS rate,
     exp(-($now - p.last_used) / 604800000.0) AS recency
RETURN p.id, fix.action, steps, p.successes, p.failures, rate, recency, nearest, nearby, places, said_hit, issue_hit,
       rate * (0.6 + 0.25 * CASE WHEN nearest IS NULL THEN 0.0 ELSE 1.0 / (1 + nearest) END + 0.15 * recency)
         + 0.05 * said_hit + 0.05 * issue_hit AS score
ORDER BY score DESC LIMIT 3
"""

# For the API: every procedure with its ordered steps and counters.
LIST = """
MATCH chain = (p:Procedure)-[:FIRST]->(:ProcStep)-[:NEXT*0..]->(last:ProcStep)
WHERE NOT (last)-[:NEXT]->()
OPTIONAL MATCH (p)-[w:WORKED_AT]->(sp:Splitter)
WITH p, chain, collect({at: sp.node_id, times: w.times}) AS places
OPTIONAL MATCH (p)-[:RESOLVES]->(i:Entity)
WITH p, chain, places, collect(DISTINCT i.name_key) AS issues
OPTIONAL MATCH (p)-[l:LEARNED_FROM]->(t:Entity)
RETURN p.id, p.signature, p.scope, [n IN nodes(chain) WHERE n:ProcStep | n.action], p.successes, p.failures,
       p.last_used, places, issues, collect(DISTINCT t.name_key)
ORDER BY p.successes DESC, p.last_used DESC LIMIT 50
"""


def setup(tenant):
    if tenant in _ready:
        return
    g = db.graph(tenant)
    for q in SCHEMA:
        try:
            g.query(q)
        except Exception as e:
            if "already indexed" not in str(e).lower():
                raise
    _ready.add(tenant)


def readings(m):
    """The readings that define a case (from lab.problems), with light split the way an engineer splits it."""
    from .lab import problems
    out = []
    for p in problems(m):
        if p == "light":
            s = m["splitter"]
            p = "light:area" if s["others"] >= 2 and s["others_down"] / s["others"] >= 0.5 else "light:home"
        out.append("reads:" + p)
    return sorted(out)


def _id(sig, actions):
    return "proc-" + hashlib.sha256((sig + "|" + ">".join(actions)).encode()).hexdigest()[:10]


def suggest(tenant, m, symptoms, issues, tried, now, log=None):
    """The best procedure for these readings, or None. `confident` says whether it may decide on its own."""
    reads = readings(m)
    if not reads:
        return None
    rows = db.run(tenant, "procedural: best past procedure (path query)", SUGGEST,
                  {"readings": reads, "said": ["said:" + s for s in symptoms], "issues": list(issues),
                   "tried": list(tried), "splitter": m["splitter"]["id"], "now": now, "nearby": NEARBY_HOPS},
                  log, ro=True)
    if not rows:
        return None
    pid, action, steps, ok, bad, rate, recency, nearest, nearby, places, said_hit, issue_hit, score = rows[0]
    return {"id": pid, "action": action, "steps": steps, "successes": ok, "failures": bad, "rate": round(rate, 3),
            "recency": round(recency, 3), "nearest_hops": nearest, "nearby": int(nearby or 0),
            "places": [x for x in places if x], "said_hit": said_hit, "issue_hit": issue_hit, "score": round(score, 3),
            "readings": reads, "confident": ok >= 1 and ok > bad and rate >= CONFIDENT,
            "others": [{"id": r[0], "action": r[1], "score": round(r[12], 3)} for r in rows[1:]]}


def record(tenant, m, actions, ok, symptoms=(), issues=(), ticket=None, at=None, log=None):
    """One case's procedure: the ordered actions on these (before) readings, a success or a failure."""
    reads = readings(m)
    if not actions or not reads:
        return None
    sig = ",".join(reads)
    pid = _id(sig, actions)
    signals = [{"name": r, "kind": "reading"} for r in reads] + [{"name": "said:" + s, "kind": "symptom"} for s in symptoms]
    rows = db.run(tenant, "procedural: record procedure path", RECORD,
                  {"id": pid, "sig": sig, "actions": list(actions), "scope": SCOPE.get(actions[-1], "home"),
                   "readings": reads, "signals": signals, "ok": 1 if ok else 0, "at": at,
                   "splitter": m["splitter"]["id"], "ticket": ticket or "", "issues": list(issues)}, log)
    return {"id": pid, "successes": rows[0][0], "failures": rows[0][1]} if rows else None


def failed(tenant, pid, ticket=None, at=None, log=None):
    """A procedure memory suggested was carried out and the re-measurement says it didn't fix the line."""
    rows = db.run(tenant, "procedural: suggestion failed", FAILED, {"id": pid, "ticket": ticket or "", "at": at}, log)
    return {"id": pid, "successes": rows[0][0], "failures": rows[0][1]} if rows else None


def procedures(tenant, log=None):
    return [{"id": r[0], "signature": r[1], "scope": r[2], "steps": r[3], "successes": r[4], "failures": r[5],
             "last_used": r[6], "places": [x for x in r[7] if x.get("at")], "issues": r[8], "tickets": r[9]}
            for r in db.run(tenant, "procedural: procedures with ordered steps", LIST, log=log, ro=True)]
