"""The fixed tool catalogue: every way an agent (or an MCP client) may read the graph, as named, typed tools over
hand-written parameterised Cypher. The model never writes Cypher: it picks a tool and fills typed args.

Every name arg is resolved against the graph first (exact key, or one clear typo winner for customers). A name the
graph doesn't hold is `unknown_entity` and the tool's own query never runs. Each call is recorded (tool, args, ms,
rows, outcome) and emitted on the tenant's event stream as `catalog_call`, which the console's Cypher drawer shows.

Outcomes use the answer contract of retrieve.ask: path (multi-hop rows) / memory (one-hop facts) / not_in_graph
(names resolved, nothing of the asked kind) / unknown_entity (a name isn't in the graph: no query ran).
"""
import collections
import threading
import time

from . import agents, db, events, network, queries as Q, registry as R, retrieve
from .memory import norm, to_date, to_ms

MAX_DEPTH = 4
NOW = 2**62  # facts_at(at="now"): the open end of the world clock


class Unknown(Exception):
    """A name arg the graph doesn't hold."""


class BadArg(ValueError):
    """An arg of the wrong type or out of range (the API answers 422)."""


_calls: dict[str, collections.deque] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- arg validation

def _entity(tenant, name, kinds, log):
    rows = db.run(tenant, "tool: resolve name", Q.RESOLVE_ENTITY, {"k": norm(name)}, log, ro=True)
    if rows and rows[0][1] in kinds:
        return rows[0][0]
    if "customer" in kinds and not rows:  # "alise rao" is Alice Rao when exactly one customer fits
        hit = retrieve.fuzzy_customers(tenant, name, log)
        words = retrieve._words(name)
        # every word typed must be a near miss of the hit's name: "kevin zzz" is not Kevin
        if hit and len(words) == len(hit[0].split()) and all(
                min(retrieve._lev(w, t) for t in hit[0].split()) <= 2 for w in words):
            return hit[0]
    raise Unknown(name)


def _node(tenant, node_id, log):
    rows = db.run(tenant, "tool: resolve network node", Q.RESOLVE_NODE, {"k": str(node_id).strip().lower()}, log, ro=True)
    if not rows:
        raise Unknown(node_id)
    return {"id": rows[0][0], "label": rows[0][1], "name": rows[0][2]}


def _date(v):
    if str(v).strip().lower() == "now":
        return NOW
    try:
        return to_ms(str(v).strip())
    except ValueError:
        raise BadArg(f"not an ISO date: {v!r}")


def _depth(v):
    try:
        d = int(v)
    except (TypeError, ValueError):
        raise BadArg(f"depth must be an integer, got {v!r}")
    if not 1 <= d <= MAX_DEPTH:
        raise BadArg(f"depth must be 1..{MAX_DEPTH}, got {d}")
    return d


def _predicate(v):
    p = str(v).strip().lower()
    if p not in R.PREDICATES and not R.is_open(p):
        raise BadArg(f"unknown predicate {v!r}; use one of {sorted(R.PREDICATES)}")
    return p


KINDS = {
    "customer": lambda t, v, log: _entity(t, v, {"customer"}, log),
    "ticket":   lambda t, v, log: _entity(t, v, {"ticket"}, log),
    "issue":    lambda t, v, log: _entity(t, v, {"issue"}, log),
    "node":     lambda t, v, log: _node(t, v, log),
    "date":     lambda t, v, log: _date(v),
    "depth":    lambda t, v, log: _depth(v),
    "predicate": lambda t, v, log: _predicate(v),
}


# ---------------------------------------------------------------- the tools

def _hop(a, rel, b, **extra):
    return {"from": a, "rel": rel, "to": b, **extra}


def recall_customer(tenant, log, name):
    """Everything memory holds about one customer: their facts, their tickets' facts, outages in their city."""
    facts = retrieve.customer_facts(tenant, name, log)
    tickets = {f["object"]: f for f in facts if f["subject"] == name and f["predicate"] == "has_ticket"}
    paths = [([retrieve.hop(tickets[f["subject"]])] if f["subject"] in tickets else []) + [retrieve.hop(f)] for f in facts]
    return [{k: f[k] for k in retrieve.FIELDS if k != "salience"} | {"conflict": f.get("conflict")} for f in facts], paths, {}


def facts_at(tenant, log, name, at):
    """Two clocks: what was true of a customer at `at` (world clock, with who wrote each fact) and what the system
    had on file at `at` (belief clock). at: ISO date, or "now"."""
    rows = db.run(tenant, "tool: world clock at", Q.FACTS_AT, {"s": name, "t": at}, log, ro=True)
    world = [{"fact_id": fid, "subject": s, "predicate": p, "object": o, "active": act, "valid_from": vf,
              "valid_to": vt, "recorded_at": rec, "agents": ags, "support": tr}
             for fid, s, p, o, act, vf, vt, rec, ags, tr in rows]
    belief = [{"predicate": p, "value": v, "fact_id": f} for p, v, f in
              (retrieve.belief_at(tenant, name, at, log) if at != NOW else [])]
    return world, [[retrieve.hop(f)] for f in world], {"belief": belief, "at": None if at == NOW else to_date(at)}


def claims(tenant, log, name, predicate):
    """Every active claim for one customer + predicate, best supported first (trust, then recency), with each
    claim's writers and the Conflict node that records the disagreement."""
    rows = db.run(tenant, "tool: claims with trust", Q.CLAIMS, {"s": name, "p": predicate}, log, ro=True)
    out, conflict = [], None
    for i, (fid, val, by, trust, seen, ags, vf, rec, cid, status, policy, pref) in enumerate(rows):
        out.append({"fact_id": fid, "value": val, "asserted_by": by, "trust": trust, "agents": ags, "rank": i + 1,
                    "preferred": i == 0, "since": to_date(vf), "learned": to_date(rec)})
        if cid and not conflict:
            conflict = {"id": cid, "status": status, "policy": policy, "preferred": pref}
    rel = R.rel_type(predicate)
    paths = [[_hop(name, rel, c["value"], fact_id=c["fact_id"], by=c["agents"], since=c["since"],
                   learned=c["learned"], active=True)] for c in out]
    return out, paths, {"conflict": conflict, "disputed": len({c["value"] for c in out}) > 1}


def who_handled(tenant, log, ticket):
    """A ticket's owner, customer and the trail of agents that picked it up or handed it off."""
    t = next((x for x in agents.tickets(tenant, log) if x["ticket"] == ticket), {})
    trail = [{"agent": a, "action": kind, "at": events.iso(at), "to": to, "note": note}
             for a, kind, at, to, note in agents.handoff_trail(tenant, ticket, log)]
    paths = [[_hop(s["agent"], s["action"], ticket, since=(s["at"] or "")[:10] or None)]
             + ([_hop(ticket, "HANDED_TO", s["to"])] if s["to"] else []) for s in trail]
    return trail, paths, {"ticket": t}


def affected_by(tenant, log, node, depth):
    """Blast radius: what hangs below a network node within `depth` hops (1..4), each row with its path."""
    rows = db.run(tenant, f"tool: affected by (depth {depth})", Q.affected_by(node["label"], depth),
                  {"n": node["id"]}, log, ro=True)
    out = [{"id": k, "kind": kind, "hops": d, "names": names, "rels": rels} for k, kind, d, names, rels in rows]
    paths = [[_hop(r["names"][i], r["rels"][i], r["names"][i + 1]) for i in range(len(r["rels"]))] for r in out]
    return out, paths, {"node": node, "depth": depth, "customers": sum(r["kind"] == "customer" for r in out)}


def capacity(tenant, log, node):
    """Gbps that can still flow from a network node to the backbone through working equipment (algo.maxFlow)."""
    rows = db.run(tenant, "tool: capacity (algo.maxFlow)", network.CAPACITY, {"n": node["id"]}, log, ro=True)
    return [{"node": node["id"], "gbps": float(r[0])} for r in rows], [], {"node": node}


def past_fixes(tenant, log, symptoms):
    """What fixed this issue before: fixes with how often they worked, and procedures as ordered step paths."""
    fixes = [{"fix": fx, "times": n} for fx, n in
             db.run(tenant, "tool: fixes that resolved it", Q.FIXES_FOR, {"issue": symptoms}, log, ro=True)]
    procs = [{"id": pid, "steps": steps, "successes": ok, "failures": bad, "last_used": last}
             for pid, steps, ok, bad, last in
             db.run(tenant, "tool: procedures that resolved it", Q.PROCEDURES_FOR, {"issue": symptoms}, log, ro=True)]
    paths = [[_hop(f["fix"], "RESOLVES", symptoms)] for f in fixes]
    paths += [[_hop(p["id"], "RESOLVES", symptoms)]
              + [_hop(a, "NEXT" if i else "FIRST", b) for i, (a, b) in enumerate(zip([p["id"]] + p["steps"], p["steps"]))]
              for p in procs]
    return fixes + procs, paths, {}


# name -> (function, {arg: kind}); the order of args is the order of the function's parameters
TOOLS = {
    "recall_customer": (recall_customer, {"name": "customer"}),
    "facts_at":        (facts_at, {"name": "customer", "at": "date"}),
    "claims":          (claims, {"name": "customer", "predicate": "predicate"}),
    "who_handled":     (who_handled, {"ticket": "ticket"}),
    "affected_by":     (affected_by, {"node": "node", "depth": "depth"}),
    "capacity":        (capacity, {"node": "node"}),
    "past_fixes":      (past_fixes, {"symptoms": "issue"}),
}


def catalogue():
    return [{"name": n, "args": spec, "doc": " ".join(fn.__doc__.split())} for n, (fn, spec) in TOOLS.items()]


def _validate(tenant, spec, args, log):
    extra = set(args) - set(spec)
    missing = [a for a in spec if args.get(a) in (None, "")]
    if extra or missing:
        raise BadArg(f"args must be exactly {list(spec)}" + (f"; missing {missing}" if missing else "")
                     + (f"; unexpected {sorted(extra)}" if extra else ""))
    if any(not isinstance(args[a], (str, int)) or isinstance(args[a], bool) for a in spec):
        raise BadArg("args must be strings (depth may be an integer)")
    # cheap checks first, so a bad date or depth never costs a name lookup
    order = sorted(spec, key=lambda a: spec[a] in ("customer", "ticket", "issue", "node"))
    return {a: KINDS[spec[a]](tenant, args[a], log) for a in order}


def record(tenant, row):
    with _lock:
        _calls.setdefault(tenant, collections.deque(maxlen=60)).appendleft(row)
    events.emit(tenant, "catalog_call", row)


def recent(tenant):
    with _lock:
        return list(_calls.get(tenant, ()))


def call(tenant, name, args, log=None):
    """Run one catalogue tool. -> {tool, args, ms, rows, outcome, queries, result, paths, extra, note}.
    Raises KeyError for a tool that isn't in the catalogue, BadArg for malformed args."""
    fn, spec = TOOLS[name]
    log = [] if log is None else log
    n0, t0 = len(log), time.perf_counter()
    try:
        vals = _validate(tenant, spec, dict(args or {}), log)
        result, paths, extra = fn(tenant, log, **vals)
        outcome = ("not_in_graph" if not result else "path" if any(len(p) > 1 for p in paths) else "memory")
        note = None if result else "Every name resolved, but nothing in the graph connects them this way."
    except Unknown as e:
        result, paths, extra, outcome = [], [], {}, "unknown_entity"
        note = f"{e} is not in the graph: the tool's query never ran."
    row = {"tool": name, "args": {k: v for k, v in (args or {}).items()}, "ms": round((time.perf_counter() - t0) * 1000, 1),
           "rows": len(result), "outcome": outcome, "queries": [q["name"] for q in log[n0:]], "at": int(time.time() * 1000)}
    record(tenant, row)
    return row | {"result": result, "paths": paths, "extra": extra, "note": note}


# ---------------------------------------------------------------- the one-click demos' picks (read-only)

def demo_picks(tenant, log=None):
    """Real entities from this tenant's graph for the 15-second contrasts; None where the graph has none."""
    out = {"clock": None, "conflict": None, "exchange": None}
    ch = db.run(tenant, "demo: a fact that changed", Q.DEMO_CHANGED, log=log, ro=True)
    if ch:
        who, p, old, old_from, new, new_from = ch[0]
        q = f"Where does {who.title()} live?" if p == "lives_in" else f"What is {who.title()}'s {R.attribute(p).replace('_', ' ')}?"
        out["clock"] = {"name": who, "predicate": p, "question": q, "before": to_date((old_from + new_from) // 2),
                        "old": old, "new": new, "changed": True}
    else:  # nothing changed yet: the contrast is "known now" vs "not yet true then"
        kn = db.run(tenant, "demo: an address on file", Q.DEMO_KNOWN, log=log, ro=True)
        if kn:
            who, new, since = kn[0]
            out["clock"] = {"name": who, "predicate": "lives_in", "question": f"Where does {who.title()} live?",
                            "before": to_date(since - 86_400_000), "old": None, "new": new, "changed": False}
    cf = db.run(tenant, "demo: a disputed claim", Q.DEMO_CONFLICT, log=log, ro=True)
    if cf:
        who, p = cf[0]
        out["conflict"] = {"name": who, "predicate": p,
                           "question": f"What plan is {who.title()} on?" if p == "on_plan"
                           else f"What is {who.title()}'s {R.attribute(p).replace('_', ' ')}?"}
    ex = db.run(tenant, "demo: the busiest exchange", Q.DEMO_EXCHANGE, log=log, ro=True)
    if ex:
        out["exchange"] = {"node": ex[0][0], "label": ex[0][1], "customers": ex[0][2]}
    return out
