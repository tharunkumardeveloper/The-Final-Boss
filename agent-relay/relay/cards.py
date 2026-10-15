"""Readable node cards, the live graph and answer paths, all built straight from the graph (no LLM).
Ids follow api/CONTRACT.md: e:<name_key>, f:<fact_id>, ep:<episode_id>, s:<session_id>, a:<agent_id>, c:<community_id>."""
from datetime import datetime, timezone

from . import agents, db, queries as Q, registry as R, retrieve

VERB = {"lives_in": "lives in", "on_plan": "is on", "has_router": "has the router", "prefers_channel": "prefers contact by",
        "has_ticket": "has ticket", "owns_device": "owns", "reported_issue": "reported", "has_status": "status is",
        "assigned_to": "is assigned to", "ticket_about": "is about", "tried_fix": "tried", "fixed_by": "was fixed by", "resolves": "resolves",
        "affects": "affects", "moving_to": "is planning to move to", "interested_in": "is interested in",
        "budget": "has a budget of", "household_size": "has a household of", "wants_to_buy": "wants to buy",
        "current_provider": "currently uses", "occupation": "works as", "visit_reason": "came about",
        "asked_about": "asked about", "requested": "asked us to", "plays_game": "plays", "watches": "watches", "address": "has the address",
        "awaiting": "has not yet told us their", "phone": "has the phone number", "email": "has the email",
        "account_id": "has the account", "alt_phone": "also uses the number", "installed_at": "was installed",
        "connection_type": "has a connection type of", "preferred_name": "prefers to be called",
        "billing_contact": "has bills handled by", "has_addon": "has the add-on", "referred": "referred",
        "previous_contact": "contacted us before", "service_request": "requested", "calling_for": "is calling for",
        "on_waitlist": "is on the waitlist for", "doesnt_know": "doesn't know their", "issue_type": "is of type",
        "issue_started": "started", "frequency": "happens", "severity": "affects", "affected_device": "affects",
        "error_message": "shows the error", "router_lights": "has router lights", "speed_reported": "measured",
        "connection_medium": "happens on", "affected_users": "affects people:", "distance_from_router": "is used",
        "has_priority": "has priority"}


def display(key, kind=None):
    if key is None:
        return ""
    if kind == "ticket" or key.startswith("pml-") or key.startswith("tkt-"):
        return key.upper()
    if kind in ("customer", "city", "plan", "router", "outage", "agent"):
        return " ".join(w.upper() if w in ("pml", "ax3000") else w.capitalize() for w in key.split())
    return key


def day(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d %b %Y").lstrip("0") if ms else "?"


def sentence(s, p, o, s_kind=None, o_kind=None):
    if R.is_open(p):  # open attribute: "Tharun, works from home: yes"
        return f"{display(s, s_kind)}, {R.attribute(p)}: {o}"
    return f"{display(s, s_kind)} {VERB.get(p, p.replace('_', ' '))} {display(o, o_kind)}"


def _split(node_id):
    kind, _, raw = node_id.partition(":")
    return kind, raw


# ---------------------------------------------------------------- cards

def card(tenant, node_id, log=None):
    kind, raw = _split(node_id)
    fn = {"f": _fact, "ep": _episode, "e": _entity, "s": _session, "a": _agent, "c": _community}.get(kind)
    out = fn(tenant, raw, log) if fn else None
    return out and {"id": node_id, "summary": None, "sections": [], **out}


def _fact(tenant, fid, log):
    rows = db.run(tenant, "card: fact", Q.CARD_FACT, {"id": fid}, log, ro=True)
    if not rows:
        return None
    p, active, vf, vt, rec, exp, by, s, st, o, ot, replaced, replaced_by, eps = rows[0]
    eps = [e for e in eps if e[0]]
    first = eps[0] if eps else None
    learned = f"learned by {first[5]} in session {first[4]}" if first else "source unknown"
    if active:
        line = f"Current since {day(vf)}, {learned}"
        line += f", replaced {', '.join(display(x, ot) for x in replaced)}." if replaced else "."
    elif replaced_by:
        line = (f"Superseded. True {day(vf)} to {day(vt)}; on file {day(rec)} to {day(exp)}; "
                f"replaced by {', '.join(display(x, ot) for x in replaced_by)}.")
    else:
        line = (f"No longer true, with nothing replacing it. True {day(vf)} to {day(vt)}; "
                f"on file {day(rec)} to {day(exp)}.")
    lines = [line]
    if len(eps) > 1:
        lines.append(f"Confirmed {len(eps) - 1} more time(s) since.")
    if R.is_single(p) and R.policy(p) == "trust" and active:
        claims = retrieve.claims(tenant, s, p, log)
        if len({c[1] for c in claims}) > 1:
            lines.append("Disputed: " + "; ".join(f"{c[2]} says {display(c[1], ot)} (trust {c[3]})" for c in claims)
                         + f". Preferred: {display(claims[0][1], ot)}.")
    return {"kind": "fact", "active": active, "title": sentence(s, p, o, st, ot) + ".",
            "subtitle": f"{p} · {'current' if active else 'superseded' if replaced_by else 'no longer true'}",
            "lines": lines,
            "sections": [{"title": "Two clocks", "rows": [["true in the world", f"{day(vf)} → {day(vt) if vt else 'now'}"],
                                                          ["on file", f"{day(rec)} → {day(exp) if exp else 'now'}"],
                                                          ["asserted by", by]]},
                         {"title": "Sources", "rows": [[f"{e[1]} · {day(e[3])}", e[2]] for e in eps[:6]]}]}


def _episode(tenant, eid, log):
    rows = db.run(tenant, "card: episode", Q.CARD_EPISODE, {"id": eid}, log, ro=True)
    if not rows:
        return None
    speaker, text, at, sid, agent, customer, facts = rows[0]
    facts = [f for f in facts if f[0]]
    return {"kind": "episode", "title": f"“{text}”", "subtitle": f"{speaker} · {day(at)} · session {sid}",
            "lines": [f"Recorded by {agent}" + (f" in a conversation with {display(customer, 'customer')}." if customer else ".")],
            "sections": [{"title": "Facts it produced", "rows": [[f[2], f"{display(f[3])} {'' if f[4] else '(since replaced)'}".strip()]
                                                                 for f in facts]}] if facts else []}


def _entity(tenant, key, log):
    rows = db.run(tenant, "card: entity", Q.CARD_ENTITY, {"id": key}, log, ro=True)
    if not rows:
        return None
    typ, sal, community, facts, sessions, n_eps = rows[0]
    incoming = [f for f in facts if f[0] and f[7] == "object" and f[3]]
    facts = [f for f in facts if f[0] and f[7] == "subject"]
    cur = [f for f in facts if f[3]]
    old = [f for f in facts if not f[3]]
    sessions = [s for s in sessions if s]
    out = {"kind": typ, "title": display(key, typ), "subtitle": typ, "lines": [], "sections": []}
    if typ == "ticket":
        t = next((t for t in agents.tickets(tenant, log) if t["ticket"] == key), None)
        status = sorted((f for f in facts if f[1] == "has_status"), key=lambda f: f[6])
        trail = agents.handoff_trail(tenant, key, log)
        out["lines"] = [f"{display(t['customer'], 'customer')} · {', '.join(t['issues'])} · now {t['status']}" if t else ""]
        out["sections"] = [{"title": "Status history", "rows": [[day(f[6]), f[2]] for f in status]},
                           {"title": "Handoff trail", "rows": [[day(at), f"{a} {act.replace('_', ' ').lower()}"
                                                                + (f" → {to}" if to else "") + (f" ({note})" if note else "")]
                                                               for a, act, at, to, note in trail]}]
        return out
    open_t = sum(1 for t in agents.tickets(tenant, log) if t["customer"] == key and t["status"] != "resolved") \
        if typ == "customer" else 0
    parts = [f"{len(cur)} current facts", f"{len(old)} superseded"]
    if typ == "customer":
        parts += [f"{open_t} open ticket{'s' if open_t != 1 else ''}", f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}"]
    out["lines"] = [f"{display(key, typ)}: {', '.join(parts)}."]
    if sal is not None:
        out["lines"].append(f"Salience {sal:.3f} (PageRank) · community {community}.")
    if not facts and incoming:
        out["lines"] = [f"{display(key, typ)}: linked from {len(incoming)} current fact{'s' if len(incoming) != 1 else ''}."]
    out["sections"] = [s for s in (
        {"title": "Current", "rows": [[f[1], display(f[2])] for f in sorted(cur, key=lambda f: f[1])]},
        {"title": "History", "rows": [[f[1], f"{display(f[2])} ({day(f[4])} → {day(f[5])})"] for f in old]},
        {"title": "Linked from", "rows": [[f[1], sentence(f[8], f[1], key, None, typ)] for f in incoming[:20]]},
    ) if s["rows"]]
    return out


def _session(tenant, sid, log):
    rows = db.run(tenant, "card: session", Q.CARD_SESSION, {"id": sid}, log, ro=True)
    if not rows:
        return None
    customer, started, summary, n, agents_ = rows[0]
    return {"kind": "session", "title": f"Session {sid}", "subtitle": f"{display(customer, 'customer')} · {day(started)}",
            "summary": summary, "lines": [f"{n} messages · agents: {', '.join(a for a in agents_ if a)}"]}


def _agent(tenant, aid, log):
    rows = db.run(tenant, "card: agent", Q.CARD_AGENT, {"id": aid}, log, ro=True)
    if not rows:
        return None
    role, trust, n_eps, n_handoffs = rows[0]
    return {"kind": "agent_node", "title": aid.capitalize(), "subtitle": role,
            "lines": [f"Trust {trust} · wrote {n_eps} episodes · {n_handoffs} handoffs/pick-ups"]}


def _community(tenant, cid, log):
    rows = db.run(tenant, "card: community", Q.CARD_COMMUNITY, {"id": int(cid)}, log, ro=True)
    if not rows:
        return None
    size, top, sal, summary, members = rows[0]
    return {"kind": "community", "title": f"Community {cid}", "subtitle": f"{size} entities · salience {sal or 0:.3f}",
            "summary": summary, "lines": [", ".join(display(m) for m in members[:12])]}


# ---------------------------------------------------------------- graphs

def _graph_from(rows):
    nodes, edges, active_by_sp = {}, [], {}
    for fid, p, active, s, st, ssal, scom, o, ot, osal, ocom, at, until in rows:
        for k, t, sal, com in ((s, st, ssal, scom), (o, ot, osal, ocom)):
            nodes[f"e:{k}"] = {"id": f"e:{k}", "kind": t, "label": display(k, t), "salience": sal, "community": com}
        edges.append({"id": f"f:{fid}", "source": f"e:{s}", "target": f"e:{o}", "label": p, "active": active,
                      "at": at, "until": until})
        if active and R.is_single(p) and R.policy(p) == "trust":
            active_by_sp.setdefault((s, p), set()).add(o)
    for e in edges:
        s, p = e["source"][2:], e["label"]
        e["conflict"] = e["active"] and len(active_by_sp.get((s, p), ())) > 1
    return {"nodes": list(nodes.values()), "edges": edges}


def graph(tenant, focus=None, depth=2, limit=400, log=None):
    if focus:
        rows = db.run(tenant, "graph: focus", Q.graph_focus(max(1, min(int(depth), 3))),
                      {"k": _split(focus)[1] if ":" in focus else focus, "limit": limit}, log, ro=True)
    else:
        rows = db.run(tenant, "graph: all", Q.GRAPH_ALL, {"limit": limit}, log, ro=True)
    return _graph_from(rows)


def path_graph(tenant, fact_ids, log=None):
    """retrieve.explain() in CONTRACT ids: fact, entity, episode, session and agent nodes."""
    ex = retrieve.explain(tenant, fact_ids, log)
    nodes, edges = {}, {}
    for (fid, pred, obj, active, s, st, o, ot, eid, text, speaker, at, sid, agent, old_id, old_obj) in ex["rows"]:
        nodes[f"f:{fid}"] = {"id": f"f:{fid}", "kind": "fact", "label": sentence(s, pred, obj, st, ot), "active": active}
        nodes[f"e:{s}"] = {"id": f"e:{s}", "kind": st, "label": display(s, st)}
        nodes[f"e:{o}"] = {"id": f"e:{o}", "kind": ot, "label": display(o, ot)}
        nodes[f"ep:{eid}"] = {"id": f"ep:{eid}", "kind": "episode", "label": f"{speaker} · {day(at)}: {text[:70]}"}
        nodes[f"s:{sid}"] = {"id": f"s:{sid}", "kind": "session", "label": sid}
        nodes[f"a:{agent}"] = {"id": f"a:{agent}", "kind": "agent_node", "label": agent.capitalize()}
        for src, dst, label in ((f"f:{fid}", f"e:{s}", "subject"), (f"f:{fid}", f"e:{o}", "object"),
                                (f"ep:{eid}", f"f:{fid}", "DERIVED"), (f"ep:{eid}", f"s:{sid}", "IN"),
                                (f"a:{agent}", f"ep:{eid}", "WROTE")):
            edges[(src, dst, label)] = {"id": f"{src}>{label}>{dst}", "source": src, "target": dst, "label": label,
                                        "active": True}
        if old_id:
            nodes[f"f:{old_id}"] = {"id": f"f:{old_id}", "kind": "fact", "label": sentence(s, pred, old_obj, st, ot),
                                    "active": False}
            edges[(f"f:{fid}", f"f:{old_id}", "SUPERSEDES")] = {
                "id": f"f:{fid}>SUPERSEDES>f:{old_id}", "source": f"f:{fid}", "target": f"f:{old_id}",
                "label": "SUPERSEDES", "active": False}
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
