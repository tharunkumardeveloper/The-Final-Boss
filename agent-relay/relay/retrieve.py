"""Read path: entity linking + vector entry points -> graph expansion -> conflict ranking -> cited answer."""
import re
from functools import lru_cache

import numpy as np

from . import db, embed, events, llm, queries as Q, registry as R
from .memory import norm, to_date, to_ms

FIELDS = ["fact_id", "subject", "predicate", "object", "active", "valid_from", "valid_to",
          "recorded_at", "expired_at", "asserted_by", "support", "last_seen", "agents"]

# Ablations switch off one graph capability at a time.
MODES = {
    "full":        {"hops": 2, "temporal": True},
    "no_temporal": {"hops": 2, "temporal": False},
    "no_hops":     {"hops": 0, "temporal": True},
}
MAX_LINES = 30
SALIENCE_WEIGHT = 0.05  # predicate relevance spans ~0.3-0.8; salience only breaks near-ties


@lru_cache
def _predicate_vecs():
    vecs = embed.embed([f"{p.replace('_', ' ')}: {s} {p.replace('_', ' ')} {o}" for p, (s, o, *_) in R.PREDICATES.items()])
    return {p: np.array(v) / np.linalg.norm(v) for p, v in zip(R.PREDICATES, vecs)}


def detect_entities(tenant, question, log=None):
    """Exact entity linking: known names (and unique customer first names) found in the question."""
    q = " " + re.sub(r"[^a-z0-9\- ]", " ", question.lower()) + " "
    q = " ".join(q.split())
    q = f" {q} "
    rows = db.run(tenant, "known entities", Q.KNOWN_ENTITIES, log=log, ro=True)
    found = [k for k, _ in rows if f" {k} " in q]
    first = {}
    for k, t in rows:
        if t == "customer":
            first.setdefault(k.split()[0], []).append(k)
    found += [ks[0] for name, ks in first.items() if len(ks) == 1 and f" {name} " in q and ks[0] not in found]
    if not any(t == "customer" for k, t in rows if k in found):
        found += [k for k in fuzzy_customers(tenant, q, log) if k not in found]
    return sorted(found, key=len, reverse=True)


_STOP = set("what where when which does did have has the and for from with about who how is are was were this that "
            "live lives living plan plans router ticket city moved move still now currently their they them".split())


def fuzzy_customers(tenant, text, log=None):
    """Customers named with a typo ("alise rao" is Alice Rao), through FalkorDB's full-text index (one edit away).
    Only a clear winner counts: two customers who fit equally well are not guessed between."""
    words = [w for w in text.split() if len(w) >= 4 and w not in _STOP and w.isalpha()]
    if not words:
        return []
    q = "|".join(f"%{w}%" for w in words)
    try:
        rows = db.run(tenant, "fuzzy customers", Q.FUZZY_CUSTOMERS_FLEX, {"q": q, "words": words}, log, ro=True)
    except Exception:  # FLEX not loaded on this server: score alone
        try:
            rows = [r + [0] for r in db.run(tenant, "fuzzy customers", Q.FUZZY_CUSTOMERS, {"q": q}, log, ro=True)]
        except Exception:  # graphs set up before the full-text index existed
            return []
    if not rows or (len(rows) > 1 and (rows[1][1], -rows[1][2]) >= (rows[0][1], -rows[0][2])):
        return []
    return [rows[0][0]]


def _annotate_conflicts(facts):
    groups = {}
    for f in facts:
        if f["active"] and R.is_single(f["predicate"]):
            groups.setdefault((f["subject"], f["predicate"]), []).append(f)
    for claims in groups.values():
        if len({c["object"] for c in claims}) > 1:
            claims.sort(key=lambda c: (c["support"] or 0, c["last_seen"] or 0), reverse=True)
            for i, c in enumerate(claims):
                c["conflict"] = "PREFERRED" if i == 0 else "not preferred"


def fmt(f, temporal=True):
    head = f"[{f['fact_id']}] {f['subject']} | {f['predicate']} | {f['object']}"
    if not temporal:
        return head
    if f["active"]:
        when = f"CURRENT | true from {to_date(f['valid_from'])} | on file from {to_date(f['recorded_at'])}"
    else:
        when = (f"SUPERSEDED | true from {to_date(f['valid_from'])} to {to_date(f['valid_to'])} | "
                f"on file from {to_date(f['recorded_at'])} to {to_date(f['expired_at'])}")
    conflict = f" | CONFLICT: {f['conflict']}" if f.get("conflict") else ""
    return f"{head} | {when} | source {','.join(f['agents'])} (trust {f['support']}){conflict}"


def recall(tenant, question, *, mode="full", k=8, log=None):
    cfg = MODES[mode]
    qvec = embed.embed_one(question)
    linked = detect_entities(tenant, question, log)
    vrows = db.run(tenant, "vector seeds", Q.VECTOR_SEEDS, {"qvec": qvec, "k": k, "limit": 8}, log, ro=True)
    if linked:
        extra = [key for key, typ, _ in vrows if typ != "customer" and key not in linked][:3]
        seeds, dist = linked + extra, {s: 0 for s in linked} | {s: 1 for s in extra}
    else:
        seeds = [key for key, _, _ in vrows][:5]
        dist = {s: 0 for s in seeds}
    rows = db.run(tenant, "retrieve facts", Q.retrieve_facts(cfg["hops"]),
                  {"seeds": seeds, "max_entities": 100, "max_facts": 400}, log, ro=True)
    facts = [dict(zip(FIELDS, r)) for r in rows]
    if cfg["temporal"]:
        _annotate_conflicts(facts)
    # Rank by hops from the linked entities, then by how well the predicate fits the question.
    changed = True
    while changed:
        changed = False
        for f in facts:
            for a, b in ((f["subject"], f["object"]), (f["object"], f["subject"])):
                if a in dist and dist.get(b, 99) > dist[a] + 1:
                    dist[b], changed = dist[a] + 1, True
    q = np.array(qvec) / np.linalg.norm(qvec)
    pv = _predicate_vecs()
    # Importance (Generative Agents): PageRank salience from consolidation, a light nudge within a hop tier.
    keys = list({k for f in facts for k in (f["subject"], f["object"])})
    sal = dict(db.run(tenant, "entity salience", Q.ENTITY_SALIENCE, {"keys": keys}, log, ro=True)) if keys else {}
    top = max(sal.values(), default=0) or 1
    importance = lambda f: max(sal.get(f["subject"], 0), sal.get(f["object"], 0)) / top
    facts.sort(key=lambda f: (min(dist.get(f["subject"], 9), dist.get(f["object"], 9)),
                              -(float(pv[f["predicate"]] @ q) + SALIENCE_WEIGHT * importance(f)),
                              not f["active"], f["recorded_at"]))
    facts = facts[:MAX_LINES]
    return {"seeds": seeds, "facts": facts, "lines": [fmt(f, cfg["temporal"]) for f in facts]}


def customer_context(tenant, customer, log=None):
    """customer_facts() as memory lines."""
    return [fmt(f) for f in customer_facts(tenant, customer, log)]


def customer_facts(tenant, customer, log=None):
    """What intake may tell this customer: only their own facts, their tickets' facts and outages in their city.
    Never other customers' memory (the team-wide recall() is for agents, not for customer-facing replies)."""
    key = norm(customer)
    rows = db.run(tenant, "customer memory", Q.retrieve_facts(1),
                  {"seeds": [key], "max_entities": 60, "max_facts": 300}, log, ro=True)
    facts = [dict(zip(FIELDS, r)) for r in rows]
    mine = {key} | {f["object"] for f in facts if f["subject"] == key and f["predicate"] == "has_ticket"}
    cities = {f["object"] for f in facts if f["subject"] == key and f["predicate"] == "lives_in" and f["active"]}
    keep = [f for f in facts
            if f["subject"] in mine or (f["predicate"] == "affects" and f["active"] and f["object"] in cities)]
    _annotate_conflicts(keep)
    keep.sort(key=lambda f: (not f["active"], f["subject"] != key, f["predicate"], f["recorded_at"]))
    return keep[:40]


def ask(tenant, question, *, mode="full", agent=None, log=None):
    """agent: who is asking; when given, the facts the answer cites are recorded as CONSULTED by that agent.
    (The benchmark leaves it None so measuring never writes to the graph it measures.)"""
    r = recall(tenant, question, mode=mode, log=log)
    a = llm.answer(question, r["lines"])
    known = {f["fact_id"] for f in r["facts"]}
    a = {**a, "cited_ids": [i for i in a["cited_ids"] if i in known], "recall": r}
    if agent:
        from . import sharing  # lazy: sharing -> memory -> ... keeps import order simple
        sharing.consult(tenant, agent, a["cited_ids"], log=log)
    events.emit(tenant, "answer", {k: a[k] for k in ("answer", "cited_ids", "conflict", "unknown")} | {"question": question})
    return a


def explain(tenant, fact_ids, log=None):
    """The path behind an answer as a small graph: {nodes, edges} ready to draw."""
    rows = db.run(tenant, "explain path", Q.EXPLAIN, {"fids": list(fact_ids)}, log, ro=True) if fact_ids else []
    nodes, edges = {}, set()
    for (fid, pred, obj, active, s, s_type, o, o_type, eid, text, speaker, at, sid, agent, old_id, old_obj) in rows:
        nodes[fid] = {"label": f"{pred}\n{obj}", "kind": "fact", "active": active}
        nodes[s] = {"label": s, "kind": s_type}
        nodes[o] = {"label": o, "kind": o_type}
        nodes[eid] = {"label": f"{speaker} @ {to_date(at)}\n{text[:60]}", "kind": "episode"}
        nodes[sid] = {"label": sid, "kind": "session"}
        nodes[agent] = {"label": agent, "kind": "agent"}
        edges |= {(fid, s, "subject"), (fid, o, "object"), (eid, fid, "DERIVED"), (eid, sid, "IN"),
                  (agent, eid, "WROTE")}
        if old_id:
            nodes[old_id] = {"label": f"{pred}\n{old_obj}", "kind": "fact", "active": False}
            edges.add((fid, old_id, "SUPERSEDES"))
    return {"nodes": nodes, "edges": sorted(edges), "rows": rows}


def neighborhood(tenant, key, log=None):
    rows = db.run(tenant, "neighborhood", Q.NEIGHBORHOOD, {"k": norm(key)}, log, ro=True)
    nodes, edges = {}, set()
    for fid, pred, active, s, s_type, o, o_type in rows:
        nodes[s] = {"label": s, "kind": s_type}
        nodes[o] = {"label": o, "kind": o_type}
        edges.add((s, o, pred if active else f"{pred} (old)"))
    return {"nodes": nodes, "edges": sorted(edges)}


def graph_at(tenant, subject, t, hops=2, log=None):
    """Paths from an entity that were true at time t (current edges and WAS edges), e.g. where Alice lived and which
    line served her on 5 September. Returns [{path, predicates, past}]."""
    rows = db.run(tenant, "graph at time", Q.world_graph_at(hops), {"s": norm(subject), "t": t}, log, ro=True)
    return [{"path": p, "predicates": preds, "past": was} for p, preds, was in rows]


def world_at(tenant, subject, t, now=None, log=None):
    return db.run(tenant, "world clock", Q.WORLD_AT,
                  {"s": norm(subject), "t": to_ms(t), "now": to_ms(now) if now else 2**62}, log, ro=True)


def belief_at(tenant, subject, t, log=None):
    return db.run(tenant, "system clock", Q.BELIEF_AT, {"s": norm(subject), "t": to_ms(t)}, log, ro=True)


def history(tenant, subject, log=None):
    return db.run(tenant, "fact history", Q.FACT_HISTORY, {"s": norm(subject)}, log, ro=True)


def claims(tenant, subject, predicate, log=None):
    return db.run(tenant, "active claims", Q.ACTIVE_CLAIMS, {"s": norm(subject), "p": predicate}, log, ro=True)
