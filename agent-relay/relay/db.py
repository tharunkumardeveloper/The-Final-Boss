import re
import time
from functools import lru_cache

from falkordb import FalkorDB

from . import config, events, queries as Q


@lru_cache
def client():
    return FalkorDB(host=config.FALKOR_HOST, port=config.FALKOR_PORT,
                    username=config.FALKOR_USER, password=config.FALKOR_PASS)


def key(tenant):
    return f"mem:{tenant}"


def graph(tenant):
    return client().select_graph(key(tenant))


def run(tenant, name, query, params=None, log=None, ro=False):
    """Run one Cypher query; append name/query/params/rows/latency to `log` for the UI's 'Cypher used' panel."""
    params = params or {}
    g = graph(tenant)
    t = time.perf_counter()
    rows = (g.ro_query(query, params, timeout=config.READ_TIMEOUT_MS) if ro else g.query(query, params)).result_set
    ms = round((time.perf_counter() - t) * 1000, 1)
    if log is not None:
        log.append({"name": name, "query": query.strip(),
                    "params": {k: v for k, v in params.items() if not k.endswith("vec") and k != "mentions"},
                    "rows": len(rows), "ms": ms})
    if events.listening(tenant):  # live Cypher drawer
        events.emit(tenant, "cypher", {"name": name, "ms": ms, "rows": len(rows), "query": query.strip()[:2000]})
    return rows


_WRITES = re.compile(r"\b(CREATE|MERGE|SET|DELETE|REMOVE|DETACH|DROP|LOAD\s+CSV)\b|db\.idx|GRAPH\.", re.I)


def writes(query):
    """Does this Cypher change the graph? Label and relationship names are ignored (the fibre drop is `:DROP`)."""
    return bool(_WRITES.search(re.sub(r"[:`][A-Za-z_][A-Za-z0-9_]*", " ", query or "")))


def plan(tenant, query, params=None, profile=False):
    """GRAPH.EXPLAIN (the plan, nothing runs) or GRAPH.PROFILE (runs it, with rows and time per step).
    Profile is refused for anything that writes, so it can't change the graph. Missing params become null."""
    from falkordb.helpers import stringify_param_value
    if profile and writes(query):
        raise ValueError("Profile runs the query, so it is only allowed for read-only queries. Use Explain.")
    params = dict(params or {})
    for name in set(re.findall(r"\$(\w+)", query)) - params.keys():
        params[name] = None  # the Cypher log drops vectors and long lists; a plan doesn't need their values
    header = ("CYPHER " + " ".join(f"{k}={stringify_param_value(v)}" for k, v in params.items()) + " ") if params else ""
    cmd = ["GRAPH.PROFILE" if profile else "GRAPH.EXPLAIN", key(tenant), header + query]
    if profile:
        cmd += ["timeout", config.READ_TIMEOUT_MS]
    return [line if isinstance(line, str) else line.decode() for line in client().connection.execute_command(*cmd)]


SNAP = "snap:"  # snapshots live outside mem:, so they never show up as tenants
SNAPS_KEPT = 3  # per tenant: each copy counts against the free tier's 100 MB


def snapshot(tenant, label="manual"):
    """GRAPH.COPY: a full clone (nodes, edges, indexes, constraints) of the tenant's graph, as of now."""
    name = f"{SNAP}{tenant}:{time.strftime('%Y%m%d-%H%M%S')}:{re.sub(r'[^a-z0-9-]', '', label.lower())[:20]}"
    client().connection.execute_command("GRAPH.COPY", key(tenant), name)
    for old in snapshots(tenant)[SNAPS_KEPT:]:
        client().select_graph(old["name"]).delete()
    return name


def snapshots(tenant):
    """Newest first: [{name, at, label}]."""
    out = []
    for k in client().list_graphs():
        if k.startswith(f"{SNAP}{tenant}:"):
            _, _, stamp, label = k.split(":", 3)
            out.append({"name": k, "at": stamp, "label": label})
    return sorted(out, key=lambda x: x["at"], reverse=True)


def restore(tenant, name):
    """Replace the tenant's graph with a snapshot (the snapshot itself is kept)."""
    if not name.startswith(f"{SNAP}{tenant}:") or name not in client().list_graphs():
        raise KeyError(name)
    try:
        graph(tenant).delete()
    except Exception:  # no current graph: nothing to delete
        pass
    client().connection.execute_command("GRAPH.COPY", name, key(tenant))


def slowlog(tenant):
    """GRAPH.SLOWLOG: the 10 slowest queries (10 ms or more) on this graph, slowest first."""
    rows = client().connection.execute_command("GRAPH.SLOWLOG", key(tenant))
    out = [{"at": float(r[0]), "command": r[1], "query": r[2], "ms": float(r[3]), "params": r[4]} for r in rows]
    return sorted(out, key=lambda x: -x["ms"])


SAFETY = {"TIMEOUT_DEFAULT": 60000}  # a ceiling for any query that doesn't set its own (the server default is none)


def server_config(apply=False):
    """GRAPH.CONFIG: the server's query limits; apply=True sets the safety defaults (not persisted by the server, so
    the API sets them at start). Returns {name: value} and {name: error} for anything the server refused."""
    conn = client().connection
    if apply:
        for k, v in SAFETY.items():
            try:
                conn.execute_command("GRAPH.CONFIG", "SET", k, v)
            except Exception as e:
                print(f"GRAPH.CONFIG SET {k}: {e}")
    out = {}
    for k in ("TIMEOUT_DEFAULT", "TIMEOUT_MAX", "QUERY_MEM_CAPACITY", "MAX_QUEUED_QUERIES", "RESULTSET_SIZE"):
        try:
            out[k] = conn.execute_command("GRAPH.CONFIG", "GET", k)[1]
        except Exception as e:
            out[k] = f"unavailable: {str(e)[:60]}"
    return out


def health():
    """Live database status: round trip, running and waiting queries (GRAPH.INFO), memory, limits."""
    conn = client().connection
    t = time.perf_counter()
    conn.ping()
    ping_ms = round((time.perf_counter() - t) * 1000, 1)
    info = conn.execute_command("GRAPH.INFO", "RunningQueries", "WaitingQueries")
    sections = dict(zip(info[::2], info[1::2]))
    running = sections.get("# Running queries") or []
    waiting = sections.get("# Waiting queries") or []
    graphs = []
    for t_ in tenants():
        try:
            graphs.append({"tenant": t_, "mb": memory_mb(t_).get("total_graph_sz_mb")})
        except Exception:
            graphs.append({"tenant": t_, "mb": None})
    return {"ok": True, "ping_ms": ping_ms, "running": len(running), "waiting": len(waiting),
            "running_queries": [str(q)[:300] for q in running], "config": server_config(),
            "memory_mb": sum(g["mb"] or 0 for g in graphs), "limit_mb": config.FREE_TIER_MB, "graphs": graphs,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def memory_mb(tenant):
    """GRAPH.MEMORY USAGE: what this graph costs against the free tier's 100 MB (data + indexes)."""
    raw = client().connection.execute_command("GRAPH.MEMORY", "USAGE", key(tenant))
    stats = dict(zip(raw[::2], raw[1::2]))
    return {k: v for k, v in stats.items() if isinstance(v, (int, float))}


SCRATCH = ("test-", "api-test")  # graphs tests make and delete; a crashed test leaves one behind


def scratch(tenant):
    return tenant.startswith(SCRATCH)


def clear_scratch():
    """Delete leftover test graphs and their snapshots (the free tier's 100 MB fills up otherwise)."""
    c, gone = client().connection, []
    for g in client().list_graphs():
        name = g.split(":", 1)[1] if ":" in g else g
        if g.startswith(("mem:", "snap:")) and scratch(name) and not (g.startswith("mem:") and name == "api-test"):
            c.execute_command("GRAPH.DELETE", g)
            gone.append(g)
    return gone


def tenants():
    return sorted(g[4:] for g in client().list_graphs() if g.startswith("mem:"))


def setup(tenant):
    g = graph(tenant)
    for q in Q.SCHEMA:
        try:
            g.query(q)
        except Exception as e:
            if "already indexed" not in str(e).lower():
                raise
    for kind, label, prop in Q.CONSTRAINTS:
        try:
            client().connection.execute_command("GRAPH.CONSTRAINT", "CREATE", key(tenant), kind,
                                                "NODE", label, "PROPERTIES", 1, prop)
        except Exception as e:
            if "already" not in str(e).lower():
                if (kind, label, prop) == Q.CONSTRAINTS[0]:
                    raise  # the canonical-entity constraint is load-bearing; the others are schema hygiene
                print(f"{key(tenant)}: {kind} {label}.{prop} not created: {e}")
    # Constraints build asynchronously: PENDING means "not enforcing yet". One that existing data violates FAILS:
    # reported, not fatal, except the canonical-entity one.
    for _ in range(100):
        rows = g.ro_query("CALL db.constraints()").result_set
        if rows and not any(r[-1] == "PENDING" for r in rows):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f"constraints on {key(tenant)} never left PENDING")
    for r in rows:
        if r[-1] != "OPERATIONAL":
            if r[1] == "Entity" and r[2] == ["name_key"]:
                raise RuntimeError(f"unique name_key constraint on {key(tenant)} is {r[-1]}")
            print(f"{key(tenant)}: constraint {r[0]} {r[1]}.{r[2]} is {r[-1]}")
    for agent_id, a in config.AGENTS.items():
        g.query(Q.UPSERT_AGENT, {"id": agent_id, "role": a["role"], "trust": a["trust"]})
    for q in Q.BACKFILL_NAMES:
        g.query(q)
    migrate_schema(tenant)
    state_labels(tenant)
    try:
        from . import udf
        udf.load()  # readable output in FalkorDB Browser: relay.sentence(f), relay.money(...), relay.ago(...)
    except Exception as e:  # servers without UDF support still work
        print(f"relay UDF library not loaded: {e}")
    for q in Q.EDGE_TIME_BACKFILL + Q.LINK_BACKFILL:
        g.query(q)
    from . import llm
    g.query("MERGE (m:Meta {key:'memory'}) SET m.name = 'memory settings', m.embedding_model = $em, m.dim = $dim, "
            "m.extraction_prompt = $xp", {"em": config.EMBED_MODEL, "dim": config.DIM,
                                          "xp": llm.PROMPT_VERSION.get("isp")})
    fact_metadata(tenant)
    from . import experts, kb, network, registry  # lazy: they import db
    if registry.for_tenant(tenant) == "isp":
        kb.seed(tenant)
        kb.geo(tenant)
        network.seed(tenant)
        network.specs(tenant)
        experts.seed(tenant)


def fact_metadata(tenant):
    """Registry metadata, corroboration counts and readable times on facts written before they existed."""
    from . import registry as R
    from .memory import dt
    g = graph(tenant)
    g.query("MATCH (f:Fact) WHERE f.corroboration_count IS NULL "
            "OPTIONAL MATCH (f)<-[:DERIVED]-(e) WITH f, count(e) AS n SET f.corroboration_count = CASE WHEN n > 0 THEN n ELSE 1 END")
    reg = R.for_tenant(tenant)
    for (p,) in g.query("MATCH (f:Fact) WHERE f.cardinality IS NULL RETURN DISTINCT f.predicate").result_set:
        g.query("MATCH (f:Fact {predicate:$p}) WHERE f.cardinality IS NULL SET f.cardinality = $c, f.policy = $pol, "
                "f.registry = $r", {"p": p, "c": "single" if R.is_single(p) else "multi", "pol": R.policy(p), "r": reg})
    rows = g.query("MATCH (f:Fact) WHERE f.learned_dt IS NULL RETURN f.fact_id, f.valid_from, f.recorded_at, f.valid_to, "
                   "f.expired_at LIMIT 5000").result_set
    for i in range(0, len(rows), 200):
        g.query("UNWIND $rows AS r MATCH (f:Fact {fact_id:r.id}) SET f.valid_from_dt = localdatetime(r.vf), "
                "f.learned_dt = localdatetime(r.at), "
                "f.valid_to_dt = CASE WHEN r.vt IS NULL THEN null ELSE localdatetime(r.vt) END, "
                "f.expired_dt = CASE WHEN r.ex IS NULL THEN null ELSE localdatetime(r.ex) END",
                {"rows": [{"id": a, "vf": dt(b or c), "at": dt(c), "vt": dt(d) if d else None, "ex": dt(e) if e else None}
                          for a, b, c, d, e in rows[i:i + 200]]})
    g.query("MATCH (f:Fact) WHERE f.is_new IS NOT NULL REMOVE f.is_new")


def state_labels(tenant):
    """Labels that carry state (:Current/:Superseded/:Retired facts, :Subscriber/:Prospect customers, :Open tickets,
    episode kinds), for graphs written before they existed. Cheap and idempotent."""
    g = graph(tenant)
    for q in Q.STATE_LABELS:
        g.query(q)
    for key_, name in g.query(Q.CUSTOMERS_TO_LABEL).result_set:
        g.query(Q.PROFILE, {"c": key_, "name": name or key_.title(), "at": None, "at_dt": None})
    for (t,) in g.query(Q.TICKETS_TO_LABEL).result_set:
        g.query(Q.TICKET_PROFILE, {"t": t})


def migrate_schema(tenant):
    """Graphs written before typed naming: add type labels to entities and turn generic RELATED edges into typed
    ones (LIVES_IN, HAS_TICKET...). Idempotent and cheap when there is nothing to do."""
    from . import registry as R
    g = graph(tenant)
    types = {t for p in R._ALL for t in (R.subject_type(p), R.object_type(p))} | {
        "addon", "service", "policy", "area", "technician"}
    for t in sorted(types):
        g.query(f"MATCH (e:Entity {{type:'{t}'}}) WHERE NOT e:{R.label(t)} SET e:{R.label(t)}")
    if "RELATED" in {r[0] for r in g.ro_query(Q.REL_TYPES_PRESENT).result_set}:
        for p in R._ALL:
            g.query(f"MATCH (a)-[r:RELATED {{predicate:'{p}'}}]->(b) "
                    f"CREATE (a)-[:{R.rel_type(p)} {{predicate:r.predicate, fact_id:r.fact_id}}]->(b) DELETE r")


def reset(tenant):
    if key(tenant) in client().list_graphs():
        graph(tenant).delete()
    setup(tenant)
