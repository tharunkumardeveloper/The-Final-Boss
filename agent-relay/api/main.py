"""Relay API: REST + WebSocket events over the memory engine. Contract: api/CONTRACT.md.
Run: uvicorn api.main:app --reload"""
import asyncio
import json
import os
import re
import threading
import time
import uuid

from relay import memory as relay_memory
from datetime import datetime

from fastapi import Body, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from relay import agents, cards, config, db, events, experts, images, kb, lab, network, orders, tenancy, queries as Q, registry as R, retrieve, sharing, sim, tools_catalog, usage
from relay.memory import norm, to_ms

app = FastAPI(title="Relay API", description=f"Shared graph memory for {config.BRAND['company']}'s AI support desk")
_TENANT_PATH = re.compile(r"^/api/tenants/([^/]+)(?:/|$)")

# A public demo: wipes and model settings could break it for everyone watching, so with RELAY_RESET_KEY set they need
# that key (X-Reset-Key). Unset (local runs), nothing is locked.
RESET_KEY = os.environ.get("RELAY_RESET_KEY", "")
_LOCKED = re.compile(r"^/api/(?:tenants/[^/]+/(?:reset|lab/reset|snapshots/[^/]+/restore)|usage/(?:limits|routes))$")
# Per-address limits on writes, per minute: a chat turn costs model quota, so it has its own, lower one. Off (0) unless
# set, so local runs and the test suites aren't throttled; render.yaml turns them on for the public demo.
RATE = {"chat": int(os.environ.get("RELAY_CHAT_PER_MIN", "0")), "write": int(os.environ.get("RELAY_WRITES_PER_MIN", "0"))}
_hits: dict = {}  # (address, bucket) -> request times in the last minute
_hits_lock = threading.Lock()


def _reset_key_ok(key):
    import hmac
    return not RESET_KEY or bool(key) and hmac.compare_digest(key.encode(), RESET_KEY.encode())


def _over_limit(addr, bucket):
    limit, now = RATE[bucket], time.time()
    if limit <= 0:
        return False
    with _hits_lock:
        recent = [t for t in _hits.get((addr, bucket), ()) if now - t < 60]
        over = len(recent) >= limit
        _hits[(addr, bucket)] = recent if over else recent + [now]
        if len(_hits) > 5000:  # forget addresses that went quiet
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60]:
                _hits.pop(k, None)
    return over


@app.middleware("http")
async def tenant_key(request, call_next):
    """Every request for a tenant's memory carries that tenant's key; a cross-tenant lookup needs an operator key.
    Writes are rate-limited per address, and wipes need the reset key when one is set.
    Registered before CORS, so CORS wraps it and a refusal reaches the browser as a readable 401/403/429."""
    from fastapi.responses import JSONResponse
    from urllib.parse import unquote
    path = request.url.path
    if request.method in ("POST", "PUT", "DELETE") and path.startswith("/api/"):
        if _LOCKED.match(path) and not _reset_key_ok(request.headers.get("x-reset-key")):
            return JSONResponse({"detail": "Resets are locked on this public demo. They need the reset key.",
                                 "need": "reset_key"}, status_code=403)
        fwd = request.headers.get("x-forwarded-for")  # Render's proxy puts the visitor's address first
        addr = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
        if _over_limit(addr, "chat" if path.endswith("/chat") else "write"):
            return JSONResponse({"detail": "Too many requests from your address. Please wait a minute and try again."},
                                status_code=429, headers={"Retry-After": "60"})
    if request.method != "OPTIONS":
        m = _TENANT_PATH.match(path)
        if m:
            tenant = unquote(m.group(1))
            why = tenancy.check(tenant, request.headers.get("x-tenant-key"))
            if why:
                return JSONResponse({"detail": "This request needs the tenant's key." if why == "missing" else
                                     f"That key doesn't open tenant '{tenant}'."}, status_code=401 if why == "missing" else 403)
        elif path == "/api/isolation" and tenancy.check(tenancy.ADMIN, request.headers.get("x-admin-key")):
            return JSONResponse({"detail": "Looking a customer up across tenants needs an operator key."}, status_code=403)
    try:
        return await call_next(request)
    except Exception as e:  # answered here, inside CORS: the browser sees the error, not a misleading "CORS blocked"
        import traceback
        traceback.print_exc()
        return JSONResponse({"detail": f"Server error: {type(e).__name__}: {str(e)[:200]}"}, status_code=500)


app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
                   allow_methods=["*"], allow_headers=["*"])

_ready: set[str] = set()
# The first request for a tenant prepares its graph (schema, catalogue, network). The portal fires several requests at
# once, and parallel first-time seeds of one graph hung in the browser test, so each graph is set up once, in order.
# One lock per tenant: a long first seed of one region never blocks requests for another.
_setup_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
TRUST_SINGLE = [p for p in R._ALL if R.is_single(p) and R.policy(p) == "trust"]


def T(tenant):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", tenant or ""):
        raise HTTPException(400, "tenant must be 1-40 chars: lowercase letters, digits, '-' or '_'")
    if tenant not in _ready:
        with _locks_guard:
            lock = _setup_locks.setdefault(tenant, threading.Lock())
        with lock:
            if tenant not in _ready:
                db.setup(tenant)
                if R.for_tenant(tenant) == "isp":
                    agents.sweep_outages(tenant, now_ms(tenant))
                _ready.add(tenant)
    return tenant


@app.on_event("startup")
def _warm_regions():
    """Prepare every region graph in the background at start, so no visitor waits for a catalogue seed."""
    def warm():
        for r in kb.world()["regions"].values():
            try:
                T(r["tenant"])
            except Exception as e:  # a region that fails here is retried on its first request
                print(f"warm {r['tenant']}: {e}")
    threading.Thread(target=warm, daemon=True).start()


def _guard(tenant):
    if tenant in config.PROTECTED_TENANTS:
        raise HTTPException(403, f"'{tenant}' holds benchmark data and can't be reset from the app. "
                                 "Use a demo tenant such as 'pml'.")


def now_ms(tenant):
    s = sim.SIMS.get(tenant)
    return s.now if s and s.running else int(time.time() * 1000)


def fact_changes(facts):
    return [{"fact_id": f["fact_id"], "subject": f["triple"][0], "predicate": f["triple"][1], "object": f["triple"][2],
             "status": "updated" if f["superseded"] else f["status"],
             **({"replaced": f["superseded"]} if f["superseded"] else {})} for f in facts]


def _ticket(tenant, ticket):
    key = norm(ticket)
    if key not in {t["ticket"] for t in agents.tickets(tenant)}:
        raise HTTPException(404, f"unknown ticket {ticket}")
    return key


# ---------------------------------------------------------------- models

class TenantIn(BaseModel):
    name: str


class ResetIn(BaseModel):
    scenario: str = "empty"
    background: bool = False  # the console asks for this and follows the phases; scripts and tests wait for the end


_NAME_LEAD = re.compile(r"^(?:(?:hi|hello|hey|namaste|vanakkam|sir|madam|myself|my name is|my name's|i am|i'm|im|"
                        r"this is|here is|call me|me|it's|its)\b[\s,.:!-]*)+", re.I)


class ChatIn(BaseModel):
    customer: str
    text: str
    session_id: str | None = None
    at: str | None = None
    greeted: bool = False  # the client already greeted them by name (the portal does): no second greeting
    country: str | None = None  # where the visitor is browsing from (ISO code), for prices before they give an address

    @field_validator("customer")
    @classmethod
    def person_name(cls, v):
        """"Myself Adit Raj" is Adit Raj, whatever client sent it."""
        name = _NAME_LEAD.sub("", v.strip()).strip(" .,!")
        if not name:
            raise ValueError("customer name is empty")
        return name


class FixIn(BaseModel):
    fix: str
    worked: bool


class ConfirmIn(BaseModel):
    subject: str
    predicate: str
    fact_id: str
    by: str = "operator"


class AskIn(BaseModel):
    question: str
    agent: str = "resolver"


class SimIn(BaseModel):
    customers: int = 6
    speed: float = 6.0
    reset: bool = False  # play resumes; only an explicit reset wipes the graph


# ---------------------------------------------------------------- REST

@app.get("/health")
def health():
    try:
        ok_db = bool(db.client().connection.ping())
    except Exception:
        ok_db = False
    return {"ok": ok_db, "falkordb": ok_db, "models": config.ROUTES}


@app.get("/api/tenants")
def tenants():
    return [t for t in db.tenants() if not t.startswith("test-")]  # graphs a failed test run left behind


@app.post("/api/tenants")
def create_tenant(body: TenantIn):
    name = norm(body.name).replace(" ", "-")
    T(name)
    return {"name": name}


_resets: dict = {}  # tenant -> phase of a reset in progress


def _do_reset(tenant, scenario):
    say = lambda phase, detail="": (_resets.__setitem__(tenant, phase),
                                    events.emit(tenant, "reset_status", {"phase": phase, "detail": detail}))
    try:
        say("snapshot", "Saving a snapshot you can restore from the Database page")
        try:  # a reset can be undone: restore this snapshot from the Database page (test graphs aren't worth 100 MB)
            if not db.scratch(tenant):
                db.snapshot(tenant, "before-reset")
        except Exception as e:
            print(f"snapshot before reset: {e}")
        if scenario == "benchmark":
            from data.load import load_scenario
            say("loading", "Loading the benchmark dataset")
            load_scenario(tenant)
        else:
            say("clearing", "Clearing the graph and re-seeding the catalogue and network")
            db.reset(tenant)  # re-seeds the schema, catalogue and network
            if scenario == "story":
                say("story", "Playing the demo story through the real agents (about a minute)")
                sim.load_story(tenant)
        say("done")
    except Exception as e:
        say("error", str(e)[:200])
    finally:
        _resets.pop(tenant, None)


@app.post("/api/tenants/{tenant}/reset")
def reset(tenant: str, body: ResetIn):
    T(tenant)
    _guard(tenant)
    if body.scenario not in ("empty", "story", "benchmark"):
        raise HTTPException(400, "scenario must be empty, story or benchmark")
    if tenant in _resets:
        raise HTTPException(409, "a reset is already running")
    sim.stop(tenant)
    sim.SIMS.pop(tenant, None)  # a fresh graph starts a fresh simulation
    _resets[tenant] = "starting"
    if not body.background:
        _do_reset(tenant, body.scenario)
        return {"ok": True}
    threading.Thread(target=_do_reset, args=(tenant, body.scenario), daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/api/tenants/{tenant}/reset")
def reset_status(tenant: str):
    return {"phase": _resets.get(T(tenant))}


@app.get("/api/tenants/{tenant}/stats")
def stats(tenant: str):
    T(tenant)
    cur, old, eps, ents, custs = db.run(tenant, "stats", Q.STATS, ro=True)[0]
    conflicts = db.run(tenant, "conflict count", Q.CONFLICT_COUNT, {"preds": TRUST_SINGLE}, ro=True)[0][0]
    open_t = sum(t["status"] != "resolved" for t in agents.tickets(tenant))
    return {"current_facts": cur, "superseded_facts": old, "episodes": eps, "entities": ents, "customers": custs,
            "open_tickets": open_t, "conflicts": conflicts}


def _build_tickets(tenant):
    opened = dict(db.run(tenant, "ticket opened", Q.TICKET_OPENED, ro=True))
    return [{"ticket": t["ticket"].upper(), "customer": t["customer"], "status": t["status"],
             "assigned_to": t["assigned_to"], "issues": t["issues"], "opened_at": events.iso(opened.get(t["ticket"])),
             "trail": [{"agent": a, "action": act.lower(), "at": events.iso(at), "to": to, "note": note}
                       for a, act, at, to, note in agents.handoff_trail(tenant, t["ticket"])]}
            for t in agents.tickets(tenant)]


def _build_customers(tenant, all_tickets):
    trust = {a: v["trust"] for a, v in config.AGENTS.items()}
    open_by = {t["customer"]: t["ticket"].upper() for t in all_tickets if t["status"] != "resolved"}
    out = []
    for key, facts, last in db.run(tenant, "customers", Q.CUSTOMERS, ro=True):
        facts = [f for f in facts if f[0]]
        best = {}
        for p, o, rec, by in sorted(facts, key=lambda f: (trust.get(f[3], 0), f[2] or 0)):
            best[p] = o
        out.append({"key": key, "name": cards.display(key, "customer"), "city": best.get("lives_in"),
                    "plan": best.get("on_plan"), "router": best.get("has_router"), "channel": best.get("prefers_channel"),
                    "devices": sorted({o for p, o, _, _ in facts if p == "owns_device"}),
                    "open_ticket": open_by.get(key), "last_seen": events.iso(last)})
    return out


@app.get("/api/tenants/{tenant}/summary")
def summary(tenant: str):
    """Stats + tickets + customers in one round trip — used by the console to cut 3 requests to 1."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    T(tenant)
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_stats = ex.submit(lambda: db.run(tenant, "stats", Q.STATS, ro=True)[0])
        f_conf = ex.submit(lambda: db.run(tenant, "conflict count", Q.CONFLICT_COUNT, {"preds": TRUST_SINGLE}, ro=True)[0][0])
        f_tix = ex.submit(_build_tickets, tenant)
        cur, old, eps, ents, custs = f_stats.result()
        conflicts = f_conf.result()
        tix = f_tix.result()
    open_t = sum(t["status"] != "resolved" for t in tix)
    return {
        "stats": {"current_facts": cur, "superseded_facts": old, "episodes": eps, "entities": ents,
                  "customers": custs, "open_tickets": open_t, "conflicts": conflicts},
        "tickets": tix,
        "customers": _build_customers(tenant, tix),
    }


@app.get("/api/tenants/{tenant}/customers")
def customers(tenant: str):
    T(tenant)
    return _build_customers(tenant, agents.tickets(tenant))


@app.get("/api/tenants/{tenant}/graph")
def graph(tenant: str, focus: str | None = None, depth: int = 2):
    return cards.graph(T(tenant), focus=focus, depth=depth)


@app.get("/api/tenants/{tenant}/my-graph")
def my_graph(tenant: str, customer: str):
    """A customer's own memory as a graph: their facts and their tickets' facts, nothing about anyone else
    (the same scope intake may use). For the customer-facing screen."""
    T(tenant)
    key = norm(customer)
    facts = retrieve.customer_facts(tenant, key)
    rows = [(f["fact_id"], f["predicate"], f["active"], f["subject"], R.subject_type(f["predicate"]), None, None,
             f["object"], R.object_type(f["predicate"]), None, None, f["recorded_at"], f["expired_at"])
            for f in facts if f["predicate"] not in ("awaiting", "doesnt_know", "has_priority")]
    return cards._graph_from(rows)


@app.get("/api/tenants/{tenant}/card/{node_id:path}")
def card(tenant: str, node_id: str):
    c = cards.card(T(tenant), node_id)
    if not c:
        raise HTTPException(404, f"no node {node_id}")
    return c


@app.get("/api/tenants/{tenant}/tickets")
def tickets(tenant: str):
    T(tenant)
    return _build_tickets(tenant)


@app.post("/api/tenants/{tenant}/chat")
def chat(tenant: str, body: ChatIn):
    T(tenant)
    log = []
    at = to_ms(body.at) if body.at else now_ms(tenant)
    sid = body.session_id or f"{norm(body.customer).replace(' ', '-')}-web-{datetime.fromtimestamp(at / 1000):%Y%m%d}"
    owner = lab.waiting_kind(tenant, body.customer)  # the resolver is mid-case: only it answers (one voice at a time)
    try:  # before intake replies: the resolver claims a fresh complaint, so the two agents don't talk over each other
        lab.before_chat(tenant, body.customer, body.text)
    except Exception as e:
        print(f"lab before_chat: {e}")
    out = agents.Intake().handle(tenant, customer=body.customer, session_id=sid, text=body.text, at=at,
                                 reply_llm=True, greeted=body.greeted, country=body.country, speak=not owner, log=log)
    handled = None
    try:  # the resolver hears this too: a yes/no to "is it working now?", or a complaint about a broken line
        handled = lab.on_chat(tenant, body.customer, body.text, out.get("ticket_opened"))
    except Exception as e:
        print(f"lab on_chat: {e}")
    speaker = "intake"
    if owner:
        out["reply"], out["reply_episode_id"] = lab.resolver_turn(tenant, body.customer, owner, handled, sid, body.text)
        speaker = "resolver"
    shown = None  # instruction pictures travel as [guide:...] markers in the messages instead
    retired = [{"fact_id": r["fact_id"], "subject": r["triple"][0], "predicate": r["triple"][1],
                "object": r["triple"][2], "status": "retired"} for r in out.get("retired", [])]
    return {"reply": out["reply"], "speaker": speaker, "session_id": sid, "learned": fact_changes(out["facts"]) + retired,
            "episode_id": out["episode_id"], "reply_episode_id": out.get("reply_episode_id"), "orders": out.get("orders", []),
            "ticket_opened": out["ticket_opened"].upper() if out["ticket_opened"] else None, "cypher": log,
            "how": _how(tenant, body.customer, out["reply"], at),
            "images": shown}



def _how(tenant, customer, reply, at):
    """"How I know": the customer's own earlier facts the reply rests on (empty when it rests on none)."""
    try:
        return retrieve.grounding(tenant, customer, reply, at)
    except Exception as e:  # a missing footnote must never cost the customer their reply
        print(f"grounding: {e}")
        return []


@app.post("/api/tenants/{tenant}/claims/confirm")
def confirm_claim(tenant: str, body: ConfirmIn):
    """"This one is right": a person settles a disagreement between agents. The other claims are retired (kept in
    history as rejected), the Conflict closes, and each writer's trust on this predicate learns from it."""
    T(tenant)
    _guard(tenant)  # the benchmark tenants' disagreements are the test set: never settled by hand
    if body.predicate not in R._ALL or not (R.is_single(body.predicate) and R.policy(body.predicate) == "trust"):
        raise HTTPException(400, f"'{body.predicate}' isn't a fact agents can disagree on")
    try:
        return relay_memory.confirm_claim(tenant, subject=body.subject, predicate=body.predicate,
                                          fact_id=body.fact_id, by=(body.by or "operator").strip()[:40])
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/tenants/{tenant}/orders")
def list_orders(tenant: str, customer: str):
    return orders.for_customer(T(tenant), customer)


@app.post("/api/tenants/{tenant}/orders/{order_id}/install")
def install_order(tenant: str, order_id: str):
    T(tenant)
    try:
        return orders.install(tenant, order_id, at=now_ms(tenant))
    except KeyError:
        raise HTTPException(404, f"unknown order {order_id}")


@app.get("/api/tenants/{tenant}/conversation")
def conversation(tenant: str, customer: str, limit: int = 400, include_actions: bool = False):
    """Everything said with one customer, grouped into sessions (oldest first). Internal action notes only on request."""
    T(tenant)
    sessions = {}
    for sid, started, summary, eid, speaker, agent, text, at in db.run(
            tenant, "conversation", Q.CONVERSATION, {"c": norm(customer), "limit": min(limit, 2000)}, ro=True):
        if speaker == "action" and not include_actions:
            continue
        s = sessions.setdefault(sid, {"session_id": sid, "started_at": events.iso(started), "summary": summary,
                                      "messages": []})
        s["messages"].append({"episode_id": eid, "speaker": agent if speaker == "agent" else speaker,
                              "text": text, "at": events.iso(at)})
    return {"customer": norm(customer), "sessions": list(sessions.values())}


@app.get("/api/tenants/{tenant}/procedural")
def procedural_memory(tenant: str, customer: str | None = None):
    """Procedural memory: fixes that resolved issues before (fix -[RESOLVES]-> issue).
    Shared knowledge written by the resolver and readable by any agent."""
    T(tenant)
    QUERY = """
MATCH (f:Fact {predicate:'resolves', active:true})-[:ABOUT {role:'subject'}]->(fx:Entity)
MATCH (f)-[:ABOUT {role:'object'}]->(issue:Entity)
MATCH (f)<-[:DERIVED]-(ep:Episode)
RETURN fx.name_key, issue.name_key, count(DISTINCT ep) AS times, max(ep.recorded_at) AS last_used
ORDER BY times DESC LIMIT 30
"""
    rows = db.run(tenant, "procedural memory", QUERY, ro=True)
    from relay import procedural  # ordered procedure paths from the network lab (steps, successes, failures)
    procs = [{**p, "last_used": events.iso(p["last_used"])} for p in procedural.procedures(tenant)]
    return {"fixes": [{"fix": r[0], "issue": r[1], "times": r[2], "last_used": events.iso(r[3])} for r in rows],
            "procedures": procs}


@app.get("/api/tenants/{tenant}/network")
def network_view(tenant: str, country: str | None = None):
    return network.view(T(tenant), country=country)


@app.post("/api/tenants/{tenant}/network/{node_id}/fail")
def network_fail(tenant: str, node_id: str):
    T(tenant)
    _guard(tenant)
    log = []
    try:
        return {**network.fail(tenant, node_id, at=now_ms(tenant), log=log), "cypher": log}
    except KeyError:
        raise HTTPException(404, f"unknown network node {node_id}")


@app.post("/api/tenants/{tenant}/network/{node_id}/restore")
def network_restore(tenant: str, node_id: str):
    T(tenant)
    _guard(tenant)
    log = []
    try:
        return {**network.restore(tenant, node_id, at=now_ms(tenant), log=log), "cypher": log}
    except KeyError:
        raise HTTPException(404, f"unknown network node {node_id}")


@app.get("/api/tenants/{tenant}/experts")
def find_experts(tenant: str, topic: str = ""):
    """Who on the team has worked on this before? Technicians ranked by resolved tickets on matching issues/routers."""
    return [{**e, "last_at": events.iso(e["last_at"])} for e in experts.find(T(tenant), topic)]


@app.get("/api/tenants/{tenant}/sharing")
def knowledge_sharing(tenant: str):
    """Who wrote what, who used it: facts consulted by an agent other than the one that wrote them."""
    return sharing.summary(T(tenant))


@app.get("/api/tenants/{tenant}/kb")
def company_kb(tenant: str, country: str | None = None):
    """The company's plans, add-ons, services, policies and coverage for one country, read back from the tenant graph."""
    return kb.catalogue(T(tenant), iso=country)


REGION_STATS = """
OPTIONAL MATCH (c:Entity {type:'customer'}) WITH count(c) AS customers
OPTIONAL MATCH (f:Fact) WITH customers, count(f) AS facts
OPTIONAL MATCH (n) WITH customers, facts, count(n) AS nodes
RETURN customers, facts, nodes
"""


@app.get("/api/regions")
def regions():
    """One graph per region (data residency): what each holds, live."""
    present = set(db.tenants())
    out = []
    for r in kb.region_summary():
        stats = dict(zip(("customers", "facts", "nodes"),
                         db.run(r["tenant"], "region stats", REGION_STATS, ro=True)[0])) if r["tenant"] in present else None
        mem = None
        if r["tenant"] in present:
            try:
                mem = db.memory_mb(r["tenant"])
            except Exception:  # older servers without GRAPH.MEMORY
                mem = None
        out.append({**r, "graph": f"mem:{r['tenant']}", "loaded": r["tenant"] in present, "stats": stats,
                    "memory_mb": mem and mem.get("total_graph_sz_mb"), "memory": mem})
    return out


class PlanIn(BaseModel):
    query: str
    params: dict = {}
    profile: bool = False


@app.post("/api/tenants/{tenant}/plan")
def query_plan(tenant: str, body: PlanIn):
    """The execution plan of a logged query (Explain), or its per-operation rows and time (Profile, read-only only)."""
    try:
        return {"plan": db.plan(T(tenant), body.query, body.params, body.profile), "profile": body.profile}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(422, f"FalkorDB: {e}")


class QueryIn(BaseModel):
    query: str
    params: dict = {}


def _plain(v):
    """A FalkorDB value as JSON: nodes and edges as their labels and properties (embeddings left out)."""
    from falkordb import Edge, Node, Path
    if isinstance(v, Node):
        return {"_node": v.labels, **{k: _plain(x) for k, x in v.properties.items() if k != "embedding"}}
    if isinstance(v, Edge):
        return {"_edge": v.relation, **{k: _plain(x) for k, x in v.properties.items()}}
    if isinstance(v, Path):
        return {"_path": [_plain(n) for n in v.nodes()]}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v][:50]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


@app.post("/api/tenants/{tenant}/query")
def run_query(tenant: str, body: QueryIn):
    """Read-only Cypher from the Database page: writes are refused, results are capped at 200 rows."""
    T(tenant)
    if db.writes(body.query):
        raise HTTPException(400, "This console is read-only: no CREATE, MERGE, SET, DELETE or index changes.")
    t = time.perf_counter()
    try:
        res = db.graph(tenant).ro_query(body.query, body.params, timeout=10_000)
    except Exception as e:
        raise HTTPException(422, f"FalkorDB: {str(e)[:300]}")
    ms = round((time.perf_counter() - t) * 1000, 1)
    cols = [h[1] if isinstance(h, (list, tuple)) else str(h) for h in res.header]
    return {"columns": cols, "rows": [[_plain(v) for v in r] for r in res.result_set[:200]],
            "count": len(res.result_set), "ms": ms}


# --- canary test: plant a unique marker in one tenant's graph, hunt for it from every other tenant, then remove it.
CANARY_SWEEP = """
MATCH (n) WHERE (n:Entity AND (n.name_key STARTS WITH 'canary ' OR n.name_key ENDS WITH ' canary street')) OR (n:Fact AND n.triple_key CONTAINS 'canary ')
   OR (n:Episode AND n.session_id STARTS WITH 'canary-') OR (n:Session AND n.session_id STARTS WITH 'canary-')
WITH n LIMIT 200 DETACH DELETE n RETURN count(*)
"""


class CanaryIn(BaseModel):
    token: str | None = None  # the tester's own secret word: no pre-recorded run could know it


@app.post("/api/tenants/{tenant}/canary")
def plant_canary(tenant: str, body: CanaryIn | None = None):
    """Write a unique marker into this tenant's graph only: a customer 'canary <token>' with an address fact. No model call.
    Any canary left over from an earlier, interrupted test is swept first."""
    T(tenant)
    token = ((body.token if body else None) or uuid.uuid4().hex[:6]).strip().lower()
    if not re.fullmatch(r"[a-z0-9]{4,16}", token):
        raise HTTPException(422, "the secret word must be 4-16 lowercase letters or digits")
    db.run(tenant, "canary: sweep old", CANARY_SWEEP)
    customer, value = f"canary {token}", f"{token} canary street"
    out = relay_memory.remember(tenant, agent="intake", session_id=f"canary-{token}", customer=customer, at=now_ms(tenant),
                          text=f"isolation audit: canary {token} planted", facts=[(customer, "address", value)])
    found = db.run(tenant, "canary: read back", "MATCH (n:Entity) WHERE n.name_key CONTAINS $t RETURN n.name_key", {"t": token}, ro=True)
    return {"token": token, "customer": customer, "value": value, "graph": db.key(tenant), "server_time": time.time(),
            "facts": [f.get("fact_id") for f in out.get("facts", []) if isinstance(f, dict)], "read_back": [r[0] for r in found]}


@app.delete("/api/tenants/{tenant}/canary/{token}")
def remove_canary(tenant: str, token: str):
    """Delete the marker (its entity, fact, episode and session), then count what is left: should be 0."""
    T(tenant)
    if not re.fullmatch(r"[a-z0-9]{4,16}", token):
        raise HTTPException(400, "bad token")
    db.run(tenant, "canary: remove", CANARY_SWEEP)
    left = db.run(tenant, "canary: count left", "MATCH (n:Entity) WHERE n.name_key CONTAINS $t RETURN count(n)", {"t": token}, ro=True)
    return {"token": token, "left": left[0][0] if left else 0}


@app.get("/api/tenants/{tenant}/schema")
def schema(tenant: str):
    """What is in this graph: node labels and relationship types with counts, and the indexes."""
    T(tenant)
    labels = db.run(tenant, "schema: labels", "MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY c DESC", ro=True)
    rels = db.run(tenant, "schema: relationships", "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC", ro=True)
    try:
        idx = [{"label": r[0], "properties": r[1], "types": {k: list(v) for k, v in dict(r[2]).items()}, "entity": r[6],
                "status": r[7]} for r in db.graph(tenant).ro_query("CALL db.indexes()").result_set]
    except Exception:
        idx = []
    return {"labels": [{"label": l, "count": c} for l, c in labels], "relationships": [{"type": t, "count": c} for t, c in rels],
            "indexes": idx}


@app.get("/api/db/health")
def db_health():
    """Live database status: ping, running/waiting queries (GRAPH.INFO), memory per graph, server limits."""
    try:
        return db.health()
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@app.get("/api/tenants/{tenant}/slowlog")
def slow_queries(tenant: str):
    return {"tenant": tenant, "queries": db.slowlog(T(tenant))}


@app.get("/api/tenants/{tenant}/snapshots")
def list_snapshots(tenant: str):
    return {"tenant": tenant, "snapshots": db.snapshots(T(tenant)), "kept": db.SNAPS_KEPT}


class SnapshotIn(BaseModel):
    label: str = "manual"


@app.post("/api/tenants/{tenant}/snapshots")
def take_snapshot(tenant: str, body: SnapshotIn):
    """GRAPH.COPY of the tenant's graph (the newest few are kept)."""
    return {"name": db.snapshot(T(tenant), body.label), "snapshots": db.snapshots(tenant)}


@app.post("/api/tenants/{tenant}/snapshots/{name}/restore")
def restore_snapshot(tenant: str, name: str):
    _guard(tenant)
    try:
        db.restore(T(tenant), name)
    except KeyError:
        raise HTTPException(404, f"no snapshot {name}")
    _ready.discard(tenant)  # re-prepare on next use (indexes, labels, UDFs)
    return {"ok": True, "restored": name}


@app.get("/api/tenants/{tenant}/network/{node_id}/capacity")
def node_capacity(tenant: str, node_id: str):
    return network.capacity(T(tenant), node_id)


@app.get("/api/tenants/{tenant}/network-cable-plan")
def cable_plan(tenant: str):
    return network.cable_plan(T(tenant))


@app.on_event("startup")
def _server_safety():
    """GRAPH.CONFIG isn't persisted by the server, so the safety limits are set each time the API starts."""
    try:
        db.server_config(apply=True)
        print("cleared leftover test graphs:", db.clear_scratch())
    except Exception as e:
        print(f"server config: {e}")


@app.get("/api/memory")
def memory():
    """Every graph's size against the free tier's 100 MB, which holds data and query scratch space together."""
    rows = []
    for t in db.tenants():
        try:
            rows.append({"tenant": t, "mb": db.memory_mb(t).get("total_graph_sz_mb")})
        except Exception as e:
            rows.append({"tenant": t, "mb": None, "error": str(e)[:120]})
    total = sum(r["mb"] or 0 for r in rows)
    return {"limit_mb": config.FREE_TIER_MB, "total_mb": total, "graphs": rows}


# ---------------------------------------------------------------- network lab

class InjectIn(BaseModel):
    preset: str
    customer: str | None = None
    blind: bool = False
    complain: bool = True


class LabActionIn(BaseModel):
    action: str
    customer: str


class LabCustomerIn(BaseModel):
    customer: str


@app.get("/api/tenants/{tenant}/lab")
def lab_view(tenant: str, customer: str | None = None):
    return lab.view(T(tenant), customer)


@app.post("/api/tenants/{tenant}/lab/inject")
def lab_inject(tenant: str, body: InjectIn):
    T(tenant)
    _guard(tenant)
    if body.preset != "random" and body.preset not in lab.PRESETS:
        raise HTTPException(400, f"unknown fault '{body.preset}'")
    try:
        return lab.inject(tenant, body.preset, body.customer, body.blind, body.complain)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tenants/{tenant}/lab/action")
def lab_action(tenant: str, body: LabActionIn):
    T(tenant)
    _guard(tenant)
    if body.action not in lab.ACTION_LABEL or body.action in ("none", "escalate"):
        raise HTTPException(400, f"unknown action '{body.action}'")
    try:
        return lab.manual(tenant, body.action, body.customer)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tenants/{tenant}/lab/investigate")
def lab_investigate(tenant: str, body: LabCustomerIn):
    T(tenant)
    _guard(tenant)
    c = norm(body.customer)
    rid = lab.start(tenant, c, ticket=agents.open_ticket_for(tenant, c))
    if rid is None:
        raise HTTPException(409, "the resolver is already working on this customer")
    return {"run": rid}


@app.post("/api/tenants/{tenant}/lab/trouble")
def lab_trouble(tenant: str, body: LabCustomerIn):
    """'I have a problem': a hidden fault on your own line; you only learn what you'd notice at home."""
    T(tenant)
    _guard(tenant)
    try:
        return lab.trouble(tenant, body.customer)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tenants/{tenant}/lab/reset")
def lab_reset(tenant: str):
    T(tenant)
    _guard(tenant)
    lab.reset(tenant)
    return {"ok": True}


@app.get("/api/tenants/{tenant}/sharing/story")
def sharing_story(tenant: str, ticket: str):
    out = sharing.story(T(tenant), ticket)
    if out is None:
        raise HTTPException(404, f"no ticket {ticket}")
    return out


@app.get("/api/tenants/{tenant}/sharing/crossings")
def sharing_crossings(tenant: str, reader: str | None = None, writer: str | None = None):
    return sharing.crossings(T(tenant), reader or None, writer or None)


@app.get("/api/locate")
def locate(tz: str | None = None, lang: str | None = None):
    """The visitor's likely country and the region desk that serves it, from their browser's timezone and language."""
    return kb.locate_visitor(tz, lang) or {"country": None}


@app.get("/api/demo/keys")
def demo_keys():
    """The demo's own web app gets every tenant's key (and the operator key). Off with RELAY_DEMO_KEYS=0, where keys
    are handed to each tenant out of band instead."""
    if not tenancy.DEMO_KEYS:
        raise HTTPException(404, "keys are issued per tenant in this deployment")
    return {"tenants": {t: tenancy.key_for(t) for t in db.tenants()}, "operator": tenancy.key_for(tenancy.ADMIN)}


@app.get("/api/isolation")
def isolation(customer: str):
    """The same customer name looked up in every region graph: memory exists only where they live."""
    key, out = norm(customer), []
    present = set(db.tenants())
    for r in kb.region_summary():
        rows = db.run(r["tenant"], "isolation check", "MATCH (c:Entity {name_key:$k}) OPTIONAL MATCH (f:Fact)-[:ABOUT]->(c) "
                      "RETURN count(DISTINCT c), count(DISTINCT f)", {"k": key}, ro=True) if r["tenant"] in present else [[0, 0]]
        out.append({"region": r["code"], "name": r["name"], "graph": f"mem:{r['tenant']}", "found": rows[0][0] > 0,
                    "facts": rows[0][1]})
    return {"customer": key, "regions": out,
            "query": "MATCH (c:Entity {name_key:$k}) OPTIONAL MATCH (f:Fact)-[:ABOUT]->(c) RETURN count(DISTINCT c), count(DISTINCT f)"}


# ---------------------------------------------------------------- LLM usage

class LimitsIn(BaseModel):
    model: str
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None


class RouteIn(BaseModel):
    job: str
    models: list[str]


@app.get("/api/usage")
def get_usage():
    return usage.snapshot()


class CheckIn(BaseModel):
    model: str | None = None  # one model, or every model in the routes


@app.post("/api/usage/check")
def check_models(body: CheckIn):
    """'Check now': a real 1-token request to each model (a few tokens each), so the status shown is a fact."""
    from relay import llm
    names = [body.model] if body.model else sorted({m for ms in config.ROUTES.values() for m in ms})
    keyed = [n for n in names if usage.has_key(n.split(":", 1)[0] if ":" in n else "groq")]
    for n in keyed:
        llm.check(n)
    return usage.snapshot()


@app.on_event("startup")
def _status_checker():
    """Every minute: re-test models whose provider-stated recovery time has passed, so the console shows them
    coming back by themselves instead of staying red until a real request happens to try them."""
    from relay import llm

    def loop():
        time.sleep(5)  # once at start: every model in the routes gets one real check, so the console opens on facts
        for n in sorted({m for ms in config.ROUTES.values() for m in ms}):
            if usage.has_key(n.split(":", 1)[0] if ":" in n else "groq"):
                try:
                    llm.check(n)
                except Exception as e:
                    print(f"status check {n}: {e}")
        while True:
            time.sleep(60)
            try:
                for n in usage.due_for_check():
                    llm.check(n)
            except Exception as e:
                print(f"status checker: {e}")
    threading.Thread(target=loop, daemon=True).start()


@app.put("/api/usage/limits")
def put_limits(body: LimitsIn):
    usage.set_limits(body.model, rpm=body.rpm, rpd=body.rpd, tpm=body.tpm, tpd=body.tpd)
    return usage.snapshot()


@app.put("/api/usage/routes")
def put_route(body: RouteIn):
    try:
        usage.set_route(body.job, body.models)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return usage.snapshot()


@app.post("/api/tenants/{tenant}/tickets/{ticket}/pickup")
def pickup(tenant: str, ticket: str):
    T(tenant)
    log = []
    out = agents.Resolver().pick_up(tenant, ticket=_ticket(tenant, ticket), at=now_ms(tenant), log=log)
    return {"observations": out["observations"], "suggestions": out["suggestions"], "cypher": log}


@app.post("/api/tenants/{tenant}/tickets/{ticket}/fix")
def fix(tenant: str, ticket: str, body: FixIn):
    T(tenant)
    log = []
    out = agents.Resolver().try_fix(tenant, ticket=_ticket(tenant, ticket), fix=body.fix, worked=body.worked,
                                    at=now_ms(tenant), log=log)
    return {"learned": fact_changes(out["facts"]), "cypher": log}


@app.post("/api/tenants/{tenant}/ask")
def ask(tenant: str, body: AskIn):
    T(tenant)
    log = []
    a = retrieve.ask(tenant, body.question, agent=body.agent, log=log)
    # The graph knows about a dispute even when the answer model forgets to say so.
    disputed = any(f.get("conflict") and f["fact_id"] in a["cited_ids"] for f in a["recall"]["facts"])
    tools_catalog.record(tenant, {"tool": "ask", "args": {"question": body.question}, "ms": round(sum(q["ms"] for q in log), 1),
                                  "rows": len(a["cited_ids"]), "outcome": a["outcome"], "queries": [q["name"] for q in log],
                                  "at": int(time.time() * 1000)})
    return {"answer": a["answer"], "values": a["values"], "conflict": a["conflict"] or disputed, "unknown": a["unknown"],
            "cited_ids": a["cited_ids"], "path": cards.path_graph(tenant, a["cited_ids"], log),
            "outcome": a["outcome"], "paths": a["paths"], "learned": a["learned"], "note": a["note"],
            "lines": a["recall"]["lines"], "cypher": log}


@app.get("/api/tenants/{tenant}/tools")
def tools_list(tenant: str):
    """The fixed tool catalogue (name, typed args, what it does) and this tenant's recent calls."""
    T(tenant)
    return {"tools": tools_catalog.catalogue(), "calls": tools_catalog.recent(tenant)}


@app.post("/api/tenants/{tenant}/tools/{name}")
def tools_call(tenant: str, name: str, args: dict = Body(default={})):
    T(tenant)
    if name not in tools_catalog.TOOLS:
        raise HTTPException(404, f"unknown tool {name!r}; the catalogue is {sorted(tools_catalog.TOOLS)}")
    log = []
    try:
        out = tools_catalog.call(tenant, name, args, log)
    except tools_catalog.BadArg as e:
        raise HTTPException(422, str(e))
    return out | {"cypher": log}


@app.get("/api/tenants/{tenant}/demos")
def demos(tenant: str):
    """Real entities from this tenant for the one-click contrasts (read-only; empty where the graph has none)."""
    return tools_catalog.demo_picks(T(tenant))


@app.get("/api/tenants/{tenant}/clock")
def clock(tenant: str, subject: str, at: str):
    T(tenant)
    rows = lambda rs: [{"predicate": p, "value": v, "fact_id": f} for p, v, f in rs]
    return {"world": rows(retrieve.world_at(tenant, subject, at)), "belief": rows(retrieve.belief_at(tenant, subject, at))}


@app.get("/api/tenants/{tenant}/history")
def history(tenant: str, subject: str):
    T(tenant)
    return [{"fact_id": fid, "predicate": p, "value": v, "active": act, "valid_from": events.iso(vf),
             "valid_to": events.iso(vt), "recorded_at": events.iso(rec), "expired_at": events.iso(exp), "agents": ags}
            for fid, p, v, act, vf, vt, rec, exp, _by, ags in retrieve.history(tenant, subject)]


@app.post("/api/tenants/{tenant}/consolidate")
def consolidate(tenant: str):
    rows = agents.consolidate(T(tenant), summaries=True)
    return {"communities": [{"id": cid, "size": n, "top": top, "salience": sal, "summary": summ}
                            for cid, n, top, sal, summ in rows]}


@app.post("/api/tenants/{tenant}/sim/start")
def sim_start(tenant: str, body: SimIn, x_reset_key: str | None = Header(None)):
    T(tenant)
    _guard(tenant)
    if body.reset and not _reset_key_ok(x_reset_key):  # starting over wipes the graph, like a reset
        raise HTTPException(403, "Resets are locked on this public demo. They need the reset key.")
    sim.start(tenant, customers=body.customers, speed=body.speed, reset=body.reset)
    return {"running": True}


@app.post("/api/tenants/{tenant}/sim/speed")
def sim_speed(tenant: str, body: SimIn):
    T(tenant)
    return sim.set_speed(tenant, body.speed)


@app.post("/api/tenants/{tenant}/sim/stop")
def sim_stop(tenant: str):
    sim.stop(T(tenant))
    return {"running": False}


@app.get("/api/tenants/{tenant}/sim")
def sim_status(tenant: str):
    return sim.status(T(tenant))


_vectors: dict = {}  # tenant -> (built at, VectorStore): embedding every episode takes a few seconds


@app.post("/api/tenants/{tenant}/compare")
def compare(tenant: str, body: AskIn):
    """One question, two memories, same answer model: Relay's graph vs the benchmark's vector-store baseline (B1)."""
    T(tenant)
    from eval.run_eval import VectorStore  # lazy: numpy and the baseline are only needed here
    from relay import llm
    built, vs = _vectors.get(tenant, (0, None))
    if vs is None or time.time() - built > 120:
        custs = [c for (c,) in db.run(tenant, "customers", "MATCH (c:Entity {type:'customer'}) RETURN c.name_key", ro=True)]
        vs = VectorStore(tenant, custs)
        _vectors[tenant] = (time.time(), vs)
    if not vs.texts:  # a fresh graph: no conversation for either memory to answer from yet
        raise HTTPException(409, "This graph has no conversations yet. Chat on the home page, play Judge mode, or load "
                                 "the demo story (console → reset → story), then compare.")
    t0 = time.perf_counter()
    g = retrieve.ask(tenant, body.question, mode="full")
    t1 = time.perf_counter()
    lines = vs.lines(body.question, dated=True, k=10)
    v = llm.answer(body.question, lines)
    t2 = time.perf_counter()
    strip = lambda ln: re.sub(r"^\[[^\]]+\]\s*", "", ln)
    pack = lambda a, ev, ms: {"answer": a.get("answer"), "unknown": a.get("unknown"), "conflict": a.get("conflict"),
                              "evidence": [strip(x) for x in ev][:8], "ms": round(ms * 1000)}
    return {"question": body.question, "graph": pack(g, g["recall"]["lines"], t1 - t0), "vector": pack(v, lines, t2 - t1),
            "model": g.get("_model")}


@app.get("/api/benchmark")
def benchmark():
    read = lambda name: json.loads(p.read_text()) if (p := config.ROOT / "eval" / name).exists() else None
    return {"results": read("results.json"), "bench": read("bench.json")}


# ---------------------------------------------------------------- WebSocket

@app.websocket("/ws/{tenant}")
async def ws(websocket: WebSocket, tenant: str):
    if tenancy.check(tenant, websocket.query_params.get("key")):  # someone else's live stream: refused at the handshake
        await websocket.close(code=4403)  # before accept this is an HTTP 403, which every proxy passes on
        return
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

    def push(ev):
        loop.call_soon_threadsafe(lambda: queue.full() or queue.put_nowait(ev))

    unsubscribe = events.subscribe(tenant, push)
    receiver = asyncio.create_task(websocket.receive_text())  # completes (or raises) when the client goes away
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                if receiver.exception() is not None:
                    break
                receiver = asyncio.create_task(websocket.receive_text())  # ignore client messages
                continue
            await websocket.send_json(getter.result())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        unsubscribe()
        receiver.cancel()
