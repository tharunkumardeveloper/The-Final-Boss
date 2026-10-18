"""Write path: episodes in, facts out. Entity resolution, contradiction handling, two clocks."""
import re
import uuid
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

from . import config, db, embed, events, llm, queries as Q, registry as R

DAY_MS = 86_400_000


def norm(s):
    return " ".join(str(s).lower().replace("_", " ").split()).strip(" .,'\"")


def to_ms(d):
    """date/datetime/ISO string -> epoch ms (UTC)."""
    if isinstance(d, (int, float)):
        return int(d)
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def to_date(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if ms is not None else None


def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# Where, when and on what a problem happens. Embeddings barely see these ("slow wifi in bedroom" vs "... in kitchen"
# 0.09; "slow internet" vs "wifi slow upstairs" 0.17), so an alias could hand one customer another's detail.
_QUALIFIER = re.compile(r"\b(up|down)stairs\b|\b(bed|living|dining|bath|class)?rooms?\b|\b(kitchen|hall|garden|garage|"
                        r"balcony|terrace|office|floor|basement|attic|night|evenings?|mornings?|weekends?|peak|tv|phone|"
                        r"mobile|laptop|pc|desktop|tablet|console|xbox|ps\d|printer|camera|vpn|zoom|teams|calls?|"
                        r"gaming|games?|streaming|netflix|youtube|upload|download|cable|wired|ethernet|extender|mesh)\b")


def _qualifiers(s):
    return {m.group(0) for m in _QUALIFIER.finditer(s)}


def resolve_entity(tenant, name, typ, log=None):
    """Canonical key for an entity. Free-text types reuse an existing entity within ALIAS_MAX_DIST, but only one that
    names the same where/when/what (see _QUALIFIER)."""
    key = norm(name)
    if typ not in R.ALIAS_TYPES or db.run(tenant, "entity exists", Q.ENTITY_EXISTS, {"k": key}, log, ro=True):
        return key
    rows = db.run(tenant, "alias candidates", Q.ALIAS_CANDIDATES,
                  {"vec": embed.embed_one(key), "type": typ}, log, ro=True)
    if rows and rows[0][1] < config.ALIAS_MAX_DIST and _qualifiers(rows[0][0]) == _qualifiers(key):
        return rows[0][0]
    return key


def _digits(s):
    return re.findall(r"\d+", s)


def close_entity(tenant, name, predicate, typ, log=None):
    """A misspelt name ("tahne", "mumbia") -> the existing entity it means ("thane", "mumbai"); else the name itself.
    Candidates: objects this tenant already holds for the predicate. The alias is recorded on the entity."""
    import difflib
    if len(name) < 4 or db.run(tenant, "entity exists", Q.ENTITY_EXISTS, {"k": name}, log, ro=True):
        return name
    keys = [r[0] for r in db.run(tenant, "typo candidates", Q.OBJECTS_OF, {"p": predicate}, log, ro=True)]
    # ponytail: character ratio only; digits must match so "fiber 100" never becomes "fiber 300"
    best = max(((difflib.SequenceMatcher(None, name, k).ratio(), k) for k in keys
                if k and _digits(k) == _digits(name) and k[0] == name[0]), default=(0, None))
    if best[0] < config.TYPO_MIN_RATIO:
        return name
    db.run(tenant, "record alias", Q.ADD_ALIAS, {"k": best[1], "a": name}, log)
    return best[1]


def record_episode(tenant, *, agent, session_id, customer, text, at, speaker, mentions=(), log=None,
                   extraction=None):
    """Store one raw event. `mentions` = [(name, type)] entities it is about. extraction = (model, prompt version)
    that read it, for reproducibility."""
    eid = _id("ep")
    names = [(norm(n), t) for n, t in mentions if n]
    vecs = embed.embed([text] + [n for n, _ in names])
    xmodel, xprompt = extraction or (None, None)
    db.run(tenant, "write episode", Q.WRITE_EPISODE, {
        "agent": agent, "sid": session_id, "customer": norm(customer) if customer else None,
        "eid": eid, "text": text, "speaker": speaker, "vec": vecs[0], "at": to_ms(at), "at_dt": dt(at),
        "xmodel": xmodel, "xprompt": xprompt,
        "mentions": [{"key": n, "name": n, "type": t, "vec": v} for (n, t), v in zip(names, vecs[1:])],
    }, log)
    if customer:
        db.run(tenant, "customer session", Q.HAS_SESSION, {"c": norm(customer), "sid": session_id}, log)
    events.emit(tenant, "message", {"session_id": session_id, "customer": norm(customer) if customer else None,
                                    "speaker": agent if speaker == "agent" else speaker, "text": text,
                                    "episode_id": eid}, to_ms(at))
    return eid


def assert_triple(tenant, *, agent, episode_id, subject, predicate, obj, at, valid_from=None, log=None):
    """Write one fact (or corroborate an identical active one), then retire what it contradicts."""
    s_type, o_type = R.subject_type(predicate), R.object_type(predicate)
    if o_type == "city" and R.for_tenant(tenant) == "isp":
        from . import kb  # lazy: kb imports db
        place = kb.resolve_place(obj)  # "hsr layout bangalore" / "blr" -> the catalogue's canonical area or city
        o_n = norm(obj)
        if place and not place["area"] and o_n.endswith(" " + place["phrase"]):
            place = None  # "navi mumbai" is its own place, not "mumbai": keep the longer name
        obj = place["key"] if place else close_entity(tenant, o_n, predicate, o_type, log)
    s = resolve_entity(tenant, subject, s_type, log)
    o = resolve_entity(tenant, obj, o_type, log)
    at_ms = to_ms(at)
    fid, is_new, old_ids, old_objs, vf = db.run(tenant, "write fact", Q.write_fact(predicate), {
        "eid": episode_id, "s": s, "s_name": s, "s_type": s_type, "s_vec": embed.embed_name(s),
        "o": o, "o_name": o, "o_type": o_type, "o_vec": embed.embed_name(o),
        "tk": f"{s}|{predicate}|{o}", "fid": _id("f"), "p": predicate,
        "vf": to_ms(valid_from) if valid_from else at_ms, "at": at_ms, "agent": agent,
        "vf_dt": dt(valid_from or at_ms), "at_dt": dt(at_ms),
        "single": R.is_single(predicate), "any_agent": R.policy(predicate) == "latest",
        "card": "single" if R.is_single(predicate) else "multi", "policy": R.policy(predicate),
        "registry": R.for_tenant(tenant),
    }, log)[0]
    out = {"fact_id": fid, "triple": (s, predicate, o), "status": "new" if is_new else "corroborated",
           "superseded": [{"fact_id": i, "object": ob} for i, ob in zip(old_ids, old_objs)]}
    if predicate == "lives_in" and R.for_tenant(tenant) == "isp":
        from . import network  # lazy: network imports memory
        network.attach(tenant, s, o, log)  # the customer's line follows them: CONNECTED_VIA their area's OLT
    _emit_fact(tenant, out, agent, episode_id, at_ms, vf, log)
    track_conflict(tenant, s, predicate, at_ms, log)
    return out


LEARN_STEP = 0.05  # how far one person's confirmation (or rejection) moves a writer's trust on that predicate


def effective_trust(base, record):
    """A writer's trust on one predicate: its fixed trust, moved by its track record there, kept within (0, 1)."""
    return round(min(0.99, max(0.05, (base or 0) + LEARN_STEP * (record or 0))), 2)


def rerank(rows, record, writer=2, trust=3, seen=4):
    """Claims re-ranked by learned trust, then recency. rows are query rows; record maps writer -> confirmed minus
    rejected. With no record (no one has confirmed anything yet) the order is exactly the query's."""
    if not record:
        return rows
    out = [(*r[:trust], effective_trust(r[trust], record.get(r[writer])), *r[trust + 1:]) for r in rows]
    return sorted(out, key=lambda r: (-(r[trust] or 0), -(r[seen] or 0)))


def learned_trust(tenant, p, log=None):
    """writer -> its track record on predicate p (confirmed minus rejected claims). Empty if anything goes wrong:
    ranking then falls back to the fixed per-agent trust."""
    try:
        return {a: n for a, n in db.run(tenant, "learned trust", Q.TRACK_RECORD, {"p": p}, log, ro=True) if a}
    except Exception as e:
        print(f"learned trust: {e}")
        return {}


def ranked_claims(tenant, s, p, log=None):
    """Active claims for one subject+predicate, best first: learned trust, then recency."""
    rows = db.run(tenant, "active claims", Q.ACTIVE_CLAIMS, {"s": s, "p": p}, log, ro=True)
    return rerank(rows, learned_trust(tenant, p, log)) if len(rows) > 1 else rows


def confirm_claim(tenant, *, subject, predicate, fact_id, by="operator", log=None):
    """A person settles a disagreement. The chosen claim is confirmed, the other agents' claims are retired (both clocks
    close; they stay in history, marked rejected), the Conflict closes, and the outcome becomes each writer's track
    record on this predicate, so the next disagreement of this kind is ranked by learned trust, not only fixed trust."""
    s, at_ms = norm(subject), to_ms(datetime.now(timezone.utc))
    claims = db.run(tenant, "active claims", Q.ACTIVE_CLAIMS, {"s": s, "p": predicate}, log, ro=True)
    win = next((c for c in claims if c[0] == fact_id), None)
    if not win:
        raise ValueError("that claim isn't active any more")
    before = learned_trust(tenant, predicate, log)
    eid = record_episode(tenant, agent="operator", session_id=f"review-{s.replace(' ', '-')}", customer=s,
                         text=f"{by} confirmed: {s} {R.attribute(predicate)} {win[1]}", at=at_ms, speaker="action", log=log)
    db.run(tenant, "confirm claim", Q.CONFIRM_CLAIM, {"eid": eid, "fid": fact_id, "by": by, "at": at_ms,
                                                      "at_dt": dt(at_ms)}, log)
    rejected = []
    for fid, value, writer, *_ in claims:
        if fid != fact_id and value != win[1]:
            rejected += _retire(tenant, agent=writer, episode_id=eid, subject=s, predicate=predicate, obj=value,
                                at=at_ms, log=log)
    if rejected:
        db.run(tenant, "mark rejected", Q.MARK_REJECTED, {"fids": [r["fact_id"] for r in rejected], "eid": eid}, log)
    if predicate == "lives_in" and R.for_tenant(tenant) == "isp":
        from . import network  # lazy: network imports memory
        network.attach(tenant, s, win[1], log)  # retiring the other city must not take the confirmed one's line away
    db.run(tenant, "conflict close", Q.CONFLICT_CLOSE, {"id": f"conflict:{s}|{predicate}", "at": at_ms,
                                                        "at_dt": dt(at_ms), "how": f"confirmed by {by}: {win[1]}"}, log)
    after = learned_trust(tenant, predicate, log)
    base = {a: v["trust"] for a, v in config.AGENTS.items()}
    moved = [{"agent": a, "from": effective_trust(base.get(a), before.get(a)), "to": effective_trust(base.get(a), after.get(a))}
             for a in sorted({win[2], *(c[2] for c in claims if c[0] != fact_id)}) if a]
    events.emit(tenant, "conflict_resolved", {"subject": s, "predicate": predicate, "value": win[1], "by": by,
                                              "rejected": [r["triple"][2] for r in rejected], "trust": moved}, at_ms)
    return {"confirmed": {"fact_id": fact_id, "value": win[1], "asserted_by": win[2]},
            "rejected": [{"fact_id": r["fact_id"], "value": r["triple"][2]} for r in rejected], "trust": moved,
            "episode_id": eid}


def track_conflict(tenant, s, p, at_ms, log=None):
    """A (:Conflict) node while two agents' claims about one single-valued fact are both active; resolved when only
    one is left. Ranked by trust, then recency (the read-time policy), and the preferred claim is named."""
    if not (R.is_single(p) and R.policy(p) == "trust"):
        return
    claims = ranked_claims(tenant, s, p, log)
    cid = f"conflict:{s}|{p}"
    if len({c[1] for c in claims}) > 1:
        db.run(tenant, "conflict open", Q.CONFLICT_OPEN, {
            "id": cid, "s": s, "p": p, "at": at_ms, "at_dt": dt(at_ms), "values": [c[1] for c in claims],
            "preferred": claims[0][1], "fids": [c[0] for c in claims],
            "agents": [c[2] for c in claims]}, log)
    else:
        db.run(tenant, "conflict close", Q.CONFLICT_CLOSE, {"id": cid, "at": at_ms, "at_dt": dt(at_ms),
                                                          "how": "only one claim left active"}, log)


def _emit_fact(tenant, f, agent, episode_id, at_ms, valid_from, log):
    if not events.listening(tenant):
        return
    s, p, o = f["triple"]
    base = {"fact_id": f["fact_id"], "subject": s, "predicate": p, "object": o, "agent": agent, "memory": R.memory_kind(p)}
    events.emit(tenant, "fact_created" if f["status"] == "new" else "fact_corroborated",
                base | {"episode_id": episode_id}, at_ms)
    for old in f["superseded"]:  # the old fact's two clocks close here: true until valid_to, on file until expired_at
        events.emit(tenant, "fact_superseded", base | {
            "old_fact_id": old["fact_id"], "old_object": old["object"], "valid_from": events.iso(valid_from),
            "valid_to": events.iso(valid_from), "expired_at": events.iso(at_ms)}, at_ms)
    if p == "has_status":
        events.emit(tenant, "ticket_status", {"ticket": s.upper(), "status": o}, at_ms)
    if R.is_single(p) and R.policy(p) == "trust":
        claims = ranked_claims(tenant, s, p, log)
        if len({c[1] for c in claims}) > 1:
            events.emit(tenant, "conflict", {"subject": s, "predicate": p, "claims": [
                {"fact_id": fid, "value": v, "agent": a, "trust": t, "preferred": i == 0}
                for i, (fid, v, a, t, _) in enumerate(claims)]}, at_ms)


def retire_fact(tenant, *, agent, episode_id, subject, predicate, obj, at, valid_to=None, log=None):
    out = _retire(tenant, agent=agent, episode_id=episode_id, subject=subject, predicate=predicate, obj=obj, at=at,
                  valid_to=valid_to, log=log)
    if out:
        track_conflict(tenant, out[0]["triple"][0], predicate, to_ms(at), log)
    return out


def _retire(tenant, *, agent, episode_id, subject, predicate, obj, at, valid_to=None, log=None):
    """End a fact with no replacement. obj '' = whatever value is current."""
    if obj and R.object_type(predicate) == "city" and R.for_tenant(tenant) == "isp":
        from . import kb
        place = kb.resolve_place(obj)
        obj = place["key"] if place else obj
    s = resolve_entity(tenant, subject, R.subject_type(predicate), log)
    o = resolve_entity(tenant, obj, R.object_type(predicate), log) if obj else ""
    at_ms = to_ms(at)
    vt = to_ms(valid_to) if valid_to else at_ms
    rows = db.run(tenant, "retire fact", Q.RETIRE, {
        "eid": episode_id, "s": s, "p": predicate, "o": o, "vt": vt, "at": at_ms, "agent": agent,
        "vt_dt": dt(vt), "at_dt": dt(at_ms), "any_agent": R.policy(predicate) == "latest"}, log)
    if rows and predicate == "lives_in" and R.for_tenant(tenant) == "isp":
        from . import network
        network.attach(tenant, s, "", log)  # moved away: no line any more
    for fid, value in rows:
        events.emit(tenant, "fact_retired", {"fact_id": fid, "subject": s, "predicate": predicate, "object": value,
                                             "memory": R.memory_kind(predicate), "agent": agent, "episode_id": episode_id, "valid_to": events.iso(vt),
                                             "expired_at": events.iso(at_ms)}, at_ms)
    return [{"fact_id": fid, "triple": (s, predicate, value), "status": "retired"} for fid, value in rows]


def _valid_from(raw, at):
    try:
        return to_ms(raw) if raw else None
    except ValueError:
        return None


def dt(ms):
    """'2026-09-01T09:35:01' (IST) for FalkorDB's localdatetime(): readable in Browser next to the ms integers."""
    if ms is None:
        return None
    return datetime.fromtimestamp(to_ms(ms) / 1000, IST).strftime("%Y-%m-%dT%H:%M:%S")


# A purchase needs a clear yes; a question about a plan is interest ("can i opt for fiber 1000 for 1000 rupees").
_ASKING = re.compile(r"\?|^\s*(can|could|may|should|is|are|do|does|will|what|which|how)\b|\b(can|could) (i|we|u|you)\b", re.I)
_BUYING = re.compile(r"\b(i'?ll (buy|take)|i will (buy|take)|buy it|book it|go ahead|sign me up|place the order|"
                     r"i want (to buy|it|that)|let'?s do it|yes,? (book|buy|order))\b", re.I)


def ingest_turn(tenant, *, agent, session_id, customer, text, at, speaker="customer", ticket=None, log=None,
                tolerate_outage=False, asked=None):
    """One conversation turn -> episode + extracted facts. Returns what was learned and what was dropped."""
    customer_key = norm(customer)
    try:
        raw = llm.extract(text, customer=customer_key, ticket=ticket, date=to_date(to_ms(at)), speaker=speaker,
                          registry=R.for_tenant(tenant), asked=asked)
        extraction_failed = False
    except llm.Unavailable:
        if not tolerate_outage:  # the benchmark loader must wait and retry, never load a turn without its facts
            raise
        raw, extraction_failed = [], True  # live chat: keep the message, learn nothing this turn
    # Identifiers have exact formats: a pattern never misses one, whatever the model did.
    if speaker == "customer" and R.for_tenant(tenant) == "isp":
        got = {f["predicate"] for f in raw}
        for p, rx in IDENTIFIERS:
            m = rx.search(text)
            if m and p not in got:
                raw.append({"about_customer": True, "subject": customer_key, "predicate": p, "attribute": None,
                            "object": re.sub(r"[\s-]", "", m.group(0)) if p == "phone" else m.group(0),
                            "valid_from": None, "ended": False})
    triples, endings, dropped, held = [], [], [], []
    for f in raw:
        p = f["predicate"]
        if p == "none":
            continue
        if p == "other":  # open attribute: anything concrete outside the core registry
            p = open_predicate(tenant, f.get("attribute"), log)
            if not p:
                dropped.append(f)
                continue
        if p == "wants_to_buy" and _ASKING.search(text) and not _BUYING.search(text):
            p = f["predicate"] = "interested_in"  # "can i opt for fiber 1000?" asks; only a clear yes places an order
        if R.object_type(p) == "plan" and R.for_tenant(tenant) == "isp":
            plan = catalogue_plan(f["object"])
            if not plan and p == "on_plan" and re.fullmatch(r"[a-z ]+ \d+", norm(f["object"])):
                # ponytail: "basic 50" is a legacy plan they're on, a claim worth keeping (billing outranks it);
                # any "<word> <number>" passes, so a misheard tier is kept too. Upgrade: a legacy-plan list.
                plan = norm(f["object"])
            if not plan:  # "Fiber 200" can't be bought: never store a plan to sell that the catalogue doesn't have
                dropped.append(f)
                continue
            f = {**f, "object": plan}
        if p == "budget":
            f = {**f, "object": money_value(f["object"])}  # "1000 rupees", "rs 1000", "₹1,000" -> "1000 inr"
        if p == "moving_to" and PAST_MOVE.search(text) and not FUTURE_MOVE.search(text):
            p = "lives_in"  # "I moved to Bengaluru on the 10th": done, not planned (weaker fallback models mix these up)
            f = {**f, "predicate": p}
        if R.object_type(p) == "router" and R.for_tenant(tenant) == "isp":
            f = {**f, "object": catalogue_router(f["object"])}
        if R.object_type(p) == "addon" and R.for_tenant(tenant) == "isp":
            addon = catalogue_addon(f["object"])
            if not addon:
                dropped.append(f)
                continue
            f = {**f, "object": addon}
        if p == "has_status" and agent == "intake":  # intake never opens, moves or closes a ticket's status
            dropped.append(f)
            continue
        st = R.subject_type(p)
        if st == "customer":
            subject = customer_key if f["about_customer"] else None
        elif st == "ticket":
            subject = ticket
        else:
            subject = f["subject"]
        obj = norm(f["object"])
        if R.object_type(p) == "status":
            obj = R.STATUS_ALIASES.get(obj, obj)
            if obj not in R.STATUSES:
                subject = None
        if R.object_type(p) == "agent" and obj not in config.AGENTS:
            subject = None
        if obj and not f.get("ended") and not R.valid_value(p, obj):  # a router stored as "wifi": never written
            subject = None
        if f.get("ended") and subject:
            endings.append((subject, p, obj, _valid_from(f["valid_from"], at)))
            continue
        if st == "ticket" and not ticket and obj:  # problem details before the ticket exists: written once it opens
            held.append((p, obj, _valid_from(f["valid_from"], at)))
            continue
        if not subject or not obj:
            dropped.append(f)
            continue
        if R.object_type(p) == "city" and R.for_tenant(tenant) == "isp":
            from . import kb
            said, got = kb.resolve_place(text), kb.resolve_place(obj)
            if said and said["area"] and got and got["city"] == said["city"] and not got["area"]:
                obj = said["area"]  # the model kept "Bangalore" but the message said "HSR Layout, Bangalore"
        triples.append((subject, p, obj, _valid_from(f["valid_from"], at)))

    mentions = [(customer_key, "customer")] + ([(ticket, "ticket")] if ticket else [])
    eid = record_episode(tenant, agent=agent, session_id=session_id, customer=customer_key, text=text,
                         at=at, speaker=speaker, mentions=mentions, log=log,
                         extraction=None if extraction_failed else llm.last_extraction())
    facts = [assert_triple(tenant, agent=agent, episode_id=eid, subject=s, predicate=p, obj=o,
                           at=at, valid_from=vf, log=log) for s, p, o, vf in triples]
    retired = [r for s, p, o, vt in endings
               for r in retire_fact(tenant, agent=agent, episode_id=eid, subject=s, predicate=p, obj=o, at=at,
                                    valid_to=vt, log=log)]
    # A planned move that has happened: "moving to Bengaluru" ends once they live there.
    for f in facts:
        s, p, o = f["triple"]
        if p == "lives_in":
            for plan_key, in db.run(tenant, "planned move", PLANNED_MOVE, {"s": s}, log, ro=True):
                if _same_city(plan_key, o):  # moving to Bengaluru, now lives in Koramangala (Bengaluru): done
                    retired += retire_fact(tenant, agent=agent, episode_id=eid, subject=s, predicate="moving_to",
                                           obj=plan_key, at=at, log=log)
    orders = []
    if R.for_tenant(tenant) == "isp":
        from . import orders as O  # lazy: orders imports memory
        orders = [O.place(tenant, customer=s, plan=o, at=at, episode_id=eid, log=log)
                  for s, p, o in (f["triple"] for f in facts) if p == "wants_to_buy"]
    db.run(tenant, "customer profile", Q.PROFILE, {"c": customer_key, "name": customer.title(), "at": to_ms(at), "at_dt": dt(at)}, log)
    return {"episode_id": eid, "facts": facts, "retired": retired, "dropped": dropped, "orders": orders, "held": held,
            "extraction_failed": extraction_failed}


PLANNED_MOVE = """
MATCH (f:Fact {predicate:'moving_to', active:true})-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s}) RETURN f.object_value
"""


def _same_city(a, b):
    if a == b:
        return True
    from . import kb
    pa, pb = kb.resolve_place(a), kb.resolve_place(b)
    return bool(pa and pb and pa["city"] == pb["city"])


OPEN_PREDICATES = "MATCH (f:Fact) WHERE f.predicate STARTS WITH 'open:' RETURN DISTINCT f.predicate"
OPEN_MAX_DIST = 0.25


def open_predicate(tenant, attribute, log=None):
    """Normalise an open attribute name against the ones this tenant already uses, so "works_remotely" and
    "works_from_home" become one attribute instead of fragmenting memory."""
    name = R.open_name(attribute)
    if not name:
        return None
    existing = [r[0] for r in db.run(tenant, "open attributes", OPEN_PREDICATES, log=log, ro=True)]
    if name in existing or not existing:
        return name
    import numpy as np
    vec = lambda p: np.array(embed.embed_name(R.attribute(p)))
    dist = lambda a, b: 1 - float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    v = vec(name)
    best = min(existing, key=lambda e: dist(v, vec(e)))
    return best if dist(v, vec(best)) < OPEN_MAX_DIST else name


_CURRENCY = {"₹": "inr", "rs": "inr", "rs.": "inr", "rupee": "inr", "rupees": "inr", "inr": "inr", "$": "usd",
             "usd": "usd", "dollar": "usd", "dollars": "usd", "€": "eur", "eur": "eur", "euro": "eur", "euros": "eur",
             "£": "gbp", "gbp": "gbp", "pound": "gbp", "pounds": "gbp"}


def money_value(text):
    """One form for an amount, whichever model extracted it: '1000 inr', '50 usd'. Unrecognised text is kept."""
    t = str(text).lower().replace(",", "")
    num = re.search(r"\d+(?:\.\d+)?", t)
    cur = next((code for word, code in _CURRENCY.items() if word in t.replace(num.group(0), " ").split()
                or (len(word) == 1 and word in t)), None) if num else None
    if not num:
        return text
    n = num.group(0).rstrip("0").rstrip(".") if "." in num.group(0) else num.group(0)
    return f"{n} {cur}" if cur else n


PAST_MOVE = re.compile(r"\b(moved|relocated|shifted|we'?ve moved|i'?ve moved|settled in|i'?m (now |already )?in|"
                       r"we'?re (now |already )?in|now (live|living|based) in)\b", re.I)
FUTURE_MOVE = re.compile(r"\b(will|going to|gonna|planning|plan to|about to|next (week|month|year)|soon|moving|"
                         r"want to move|would like to move|thinking of)\b", re.I)

IDENTIFIERS = [
    ("account_id", re.compile(r"\bpml-?ac[\w-]+\b", re.I)),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone", re.compile(r"(?<![\w@])\+?\d(?:[\s-]?\d){9,13}\b")),  # 10-14 digits: never a date
]


def catalogue_addon(text):
    """'the mesh extender add-on' -> 'mesh extender'; names too ('Family Shield' -> 'parental controls')."""
    from . import kb
    t = f" {norm(text)} "
    for a in sorted(kb.world()["addons"], key=lambda a: -len(a["key"])):
        if f" {a['key']} " in t or f" {norm(a['name'])} " in t:
            return a["key"]
    return None


def catalogue_plan(text):
    """'the fiber 1000 plan' -> 'fiber 1000'; the speed on the router box works too ('300 mbps', '1 gbps');
    None if no catalogue plan is named."""
    from . import kb
    t = f" {norm(text)} "
    keys = sorted((p["key"] for p in kb.world()["plans"]), key=len, reverse=True)
    named = next((k for k in keys if f" {k} " in t or f" {k.replace(' ', '')} " in t), None)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s?(mbps|gbps|gig)\b", t)
    if named or not m:
        return named
    mbps = float(m.group(1)) * (1000 if m.group(2) != "mbps" else 1)
    return next((p["key"] for p in kb.world()["plans"] if p["down"] == mbps and p["key"].startswith("fiber")), None)


def catalogue_router(text):
    """'hub 6 pro' -> 'pml hub 6 pro' (the catalogue's router node); unknown models are kept as said."""
    from . import kb
    t = f" {norm(text)} "
    for r in sorted(kb.world()["routers"], key=lambda r: -len(r["key"])):
        if f" {r['key']} " in t or f" {r['key'].removeprefix('pml ')} " in t:
            return r["key"]
    return norm(text)


def remember(tenant, *, agent, session_id, customer, text, at, facts, speaker="action", log=None):
    """Structured write without the LLM (agent actions, tool results): one episode + (s, p, o[, valid_from]) facts.
    speaker "action" = an internal note (opened a ticket, picked one up): memory and the console see it, the customer's
    chat does not."""
    customer_key = norm(customer) if customer else None
    mentions = [(customer_key, "customer")] if customer_key else []
    eid = record_episode(tenant, agent=agent, session_id=session_id, customer=customer_key, text=text,
                         at=at, speaker=speaker, mentions=mentions, log=log)
    return {"episode_id": eid, "facts": [
        assert_triple(tenant, agent=agent, episode_id=eid, subject=f[0], predicate=f[1], obj=f[2], at=at,
                      valid_from=f[3] if len(f) > 3 else None, log=log) for f in facts]}
