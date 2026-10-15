"""How the agents share what they know, recorded in the graph: (:Agent)-[:CONSULTED {count}]->(:Fact).
A fact written by intake and consulted by the resolver is knowledge that crossed between agents."""
from . import config, db, events, queries as Q
from .memory import to_ms


def consult(tenant, agent, fact_ids, at=None, log=None):
    """Record that `agent` used these facts; emits a `consulted` event with who originally wrote them."""
    fids = sorted({f for f in fact_ids if f})
    if not fids:
        return {}
    at_ms = to_ms(at) if at is not None else None
    writers = dict(db.run(tenant, "consulted", Q.CONSULT, {"agent": agent, "fids": fids, "at": at_ms}, log))
    events.emit(tenant, "consulted", {"agent": agent, "fact_ids": fids, "writers": writers}, at_ms)
    return writers


def summary(tenant, n=10, log=None):
    from .cards import sentence as _sentence  # lazy: cards imports agents
    from . import registry as R
    sentence = lambda s, p, o: _sentence(s, p, o, R.subject_type(p), R.object_type(p))
    rows = {a: (w, c, o, u) for a, w, c, o, u in db.run(tenant, "sharing: agents", Q.SHARING_AGENTS, log=log, ro=True)}
    # The whole team, including agents that haven't acted yet, with the role and trust that settle conflicts.
    agents = [{"agent": a, "role": cfg["role"], "trust": cfg["trust"], "wrote": w, "consulted": c,
               "consulted_from_others": o, "uses": int(u or 0), "reuse_pct": round(100 * o / c) if c else 0}
              for a, cfg in config.AGENTS.items() for w, c, o, u in [rows.get(a, (0, 0, 0, 0))]]
    flows = [{"from": a, "to": b, "facts": n_} for a, b, n_ in db.run(tenant, "sharing: flows", Q.SHARING_FLOWS, log=log, ro=True)]
    top = [{"fact_id": fid, "sentence": sentence(s, p, o) + ".", "writer": w, "readers": r, "uses": int(u)}
           for fid, s, p, o, w, r, u in db.run(tenant, "sharing: top", Q.SHARING_TOP, {"n": n}, log, ro=True)]
    return {"agents": agents, "flows": flows, "top_shared": top}


def crossings(tenant, reader=None, writer=None, n=40, log=None):
    """Each fact one agent wrote and another used: who read it, who wrote it, what it says, how often, when last."""
    from .cards import sentence as _sentence  # lazy: cards imports agents
    from . import registry as R
    rows = db.run(tenant, "sharing: crossings", Q.SHARING_CROSSINGS, {"reader": reader, "writer": writer, "n": n}, log, ro=True)
    return [{"reader": a, "writer": w, "fact_id": fid, "subject": s,
             "sentence": _sentence(s, p, o, R.subject_type(p), R.object_type(p)) + ".", "uses": int(c or 0),
             "last": events.iso(last) if last else None}
            for a, w, fid, s, p, o, c, last in rows]
