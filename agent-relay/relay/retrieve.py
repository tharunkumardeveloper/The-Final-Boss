"""Read path: entity linking + vector entry points -> graph expansion -> conflict ranking -> cited answer."""
import re
from functools import lru_cache

import numpy as np

from . import db, embed, events, llm, queries as Q, registry as R
from .memory import norm, to_date, to_ms

FIELDS = ["fact_id", "subject", "predicate", "object", "active", "valid_from", "valid_to",
          "recorded_at", "expired_at", "asserted_by", "support", "last_seen", "agents", "salience"]

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


def _pvec(p):
    """Registry predicates are embedded once; open ones (`open:<attribute>`) the first time they show up."""
    pv = _predicate_vecs()
    if p not in pv:
        v = np.array(embed.embed_one(p.split(":", 1)[-1].replace("_", " ")))
        pv[p] = v / np.linalg.norm(v)
    return pv[p]


LINK_TYPES = {"customer", "ticket", "city", "outage", "plan", "router"}  # what recall may seed from by name
MAX_GRAM = 8  # longest entity name, in words, that exact linking looks up

_STOP = set("what where when which does did have has the and for from with about who how is are was were this that "
            "live lives living plan plans router ticket city moved move still now currently their they them".split())


def _words(text):
    return re.sub(r"[^a-z0-9\- ]", " ", str(text).lower()).split()


def _grams(words):
    return sorted({" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, min(i + MAX_GRAM, len(words)) + 1)})


def _lev(a, b):
    """Edit distance; names are short, so the O(len^2) table is nothing."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def _fuzzy_words(words):
    return [w for w in words if len(w) >= 4 and w not in _STOP and w.isalpha()]


def _fuzzy_pick(rows, words):
    """[(key, score)] from the full-text index -> [the one clear winner] or []. Equal scores break on edit distance:
    only name words the message came close to (<= 2 edits) count, more of the name matched wins, then fewer edits.
    An untyped surname never decides ("chitraa" stays ambiguous between two Chitras)."""
    def dist(key):
        hit = [d for d in (min(_lev(t, w) for w in words) for t in key.split()) if d <= 2]
        return sum(hit) - 10 * len(hit)
    rows = sorted(((key, score, dist(key)) for key, score in rows), key=lambda r: (-r[1], r[2]))[:5]
    if not rows or (len(rows) > 1 and (rows[1][1], -rows[1][2]) >= (rows[0][1], -rows[0][2])):
        return []
    return [rows[0][0]]


def _link(tenant, question, qvec, k=8, log=None):
    """Round trip 1: exact names, unique first names, typo names and vector seeds, one UNION query.
    -> {linked: entity keys (longest first), vector: [(key, type, distance)], unknown: names memory doesn't hold,
        person: whether a customer was linked}"""
    words = _words(question)
    fuzzy = _fuzzy_words(words)
    rows = db.run(tenant, "recall: link", Q.RECALL_LINK, {
        "grams": _grams(words), "names": "|".join(sorted({w for w in words if w.isalpha() and len(w) >= 2})),
        "fuzzy": "|".join(f"%{w}%" for w in fuzzy), "qvec": qvec, "k": k, "limit": 8}, log, ro=True)
    by = {}
    for src, key, typ, score in rows:
        by.setdefault(src, []).append((key, typ, score))
    exact = by.get("exact", [])
    found = [key for key, typ, _ in exact if typ in LINK_TYPES]
    first = {}
    for key, _, _ in by.get("name", []):
        first.setdefault(key.split()[0], set()).add(key)
    found += [min(ks) for name, ks in first.items() if len(ks) == 1 and name in words and min(ks) not in found]
    customers = {key for key, typ, _ in exact if typ == "customer"} | {key for key, _, _ in by.get("name", [])}
    if not customers & set(found) and fuzzy:
        found += [key for key in _fuzzy_pick([(key, s) for key, _, s in by.get("fuzzy", [])], fuzzy)
                  if key not in found]
        customers |= set(found)
    near = {t for src in ("name", "fuzzy") for key, _, _ in by.get(src, []) for t in key.split()}
    return {"linked": sorted(found, key=len, reverse=True), "vector": by.get("vector", []),
            "unknown": _unknown_names(question, {key for key, _, _ in exact} | set(found), near, _tenant_vocab(tenant)),
            "person": bool(customers & set(found))}


def detect_entities(tenant, question, log=None):
    """Entity linking: known names, unique customer first names, else one clear typo match ("alise rao")."""
    return _link(tenant, question, embed.embed_one(question), log=log)["linked"]


# Ordinary words that are never a person's name, even capitalised or right after "does"/"about".
# ponytail: a hand list plus the catalogue's and registry's vocabulary; an unusual word in a person slot can still
# read as a name (the cost is "I don't know", never someone else's facts). Upgrade: a POS tagger.
_COMMON = set("""
a an the i me my mine we us our you your he him his she her they them their it its this that these those there here
what which who whom whose where when why how whats wheres whos hows is are was were be been being am do does did done
have has had having will would shall should can could may might must not no yes ok okay please thanks thank hi hello
hey dear sir madam of in on at to for from by with about into onto over under after before since until during
between through against without within near across and or but if then else so than too very just also only even
still now currently today yesterday tomorrow ago recently lately again ever never always often sometimes all any
some each every most more less many much few several other another same such own both either neither none one two
three first last next new old current previous latest earlier later back up down out off get got give gave tell told
say said know knew show find found need needs want wants like likes make made take took see seen look check going go
went come came call called use uses used using pay paid move moved moving live lives living lived stay stays stayed
work works working worked happen happened happening fix fixed fixing break broke broken stop stopped start started
anyone anybody someone somebody everyone everybody nobody customer customers subscriber subscribers user users person
people member members client clients account accounts name names number numbers address addresses email phone mobile
city cities area areas town place places location home house office country region plan plans package packages
router routers modem device devices ticket tickets outage outages issue issues problem problems complaint complaints
status speed speeds internet broadband fiber fibre wifi network line lines connection connections service services
bill bills billing payment payments price prices cost costs order orders install installation technician technicians
visit visits appointment slot support team agent agents resolver intake history fact facts memory record records data
info information detail details question answer reason time date day days week weeks month months year years morning
evening night least best worst top total count average mbps gbps monthly
""".split())


@lru_cache
def _vocab():
    """Words of the catalogue (cities, aliases, areas, plans, routers, add-ons, services) and of the registry."""
    from . import kb  # lazy: kb imports db
    w = kb.world()
    names = [c["key"] for c in w["cities"]] + [a for c in w["cities"] for a in c.get("aliases", [])]
    names += [a["key"] for c in w["cities"] for a in c.get("areas", [])]
    names += [x[f] for kind in ("plans", "routers", "addons", "services") for x in w[kind] for f in ("key", "name")]
    names += [str(t) for p, (s, o, *_) in R.PREDICATES.items() for t in (p, s, o)]
    return frozenset(t for n in names for t in _words(n.replace("_", " ")))


_CUE = {"does", "did", "is", "was", "has", "had", "will", "can", "about", "for", "of", "with", "named", "called"}
_ID = re.compile(r"[a-z]+-\d[a-z0-9-]*")  # ticket-like ids: pml-2041-b343, tkt-7


@lru_cache(maxsize=64)
def _tenant_vocab(tenant):
    """Words of what this tenant's memory names besides people (issues, fixes, playbooks): "slow" in "slow speed".
    ponytail: read once per process; a word first seen after that can still read as a name until restart."""
    rows = db.run(tenant, "recall: vocabulary", Q.TOPIC_WORDS, ro=True)
    return frozenset(t for (k,) in rows for t in _words(k))


def _unknown_names(question, known, near, vocab=frozenset()):
    """The specific people (or ids) a question names that memory doesn't hold.
    A word reads as a name when it isn't ordinary, catalogue or graph vocabulary and it is possessive ("kevin's"),
    capitalised mid-sentence ("does Kevin"), or in a subject slot ("where does kevin live", "about kevin").
    known: entity keys the question matched; near: name words of customers the full-text index reached
    (a typo of a customer's name, or an ambiguous first name, is not unknown)."""
    covered = {t for key in known for t in key.split()}
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]*(?:['’]s\b)?|[.?!]", question)
    out = []
    for i, tok in enumerate(toks):
        possessive = tok[-2:].lower() in ("'s", "’s")
        w = (tok[:-2] if possessive else tok).lower()
        if _ID.fullmatch(w):
            out += [] if w in known else [w]
            continue
        if (len(w) < 3 or not w.isalpha() or w.endswith("ing") or w in _COMMON or w in _STOP or w in covered or w in _vocab() or w in vocab
                or any(_lev(w, t) <= 1 for t in near)):
            continue
        prev = toks[i - 1].lower() if i else "."
        if possessive or (tok[0].isupper() and prev not in ".?!") or prev in _CUE:
            out.append(w)
    return list(dict.fromkeys(out))


def fuzzy_customers(tenant, text, log=None):
    """Customers named with a typo ("alise rao" is Alice Rao), through FalkorDB's full-text index (one edit away).
    Only a clear winner counts: two customers who fit equally well are not guessed between."""
    words = _fuzzy_words(_words(text))
    if not words:
        return []
    rows = db.run(tenant, "fuzzy customers", Q.FUZZY_CUSTOMERS, {"q": "|".join(f"%{w}%" for w in words)}, log, ro=True)
    return _fuzzy_pick(rows, words)


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
    """Two round trips: link (names + vector seeds), then the bounded hop expansion with salience on each fact.
    -> {seeds, facts, lines, unknown}. unknown: people/ids the question names that memory doesn't hold. Naming one
    with no known customer alongside means no facts at all: never another person's memory in their place."""
    cfg = MODES[mode]
    qvec = embed.embed_one(question)
    ln = _link(tenant, question, qvec, k, log)
    linked, vrows = ln["linked"], ln["vector"]
    if ln["unknown"] and not ln["person"]:
        return {"seeds": [], "facts": [], "lines": [], "unknown": ln["unknown"], "linked": [], "dist": {}, "parent": {}}
    if linked:
        extra = [key for key, typ, _ in vrows if typ != "customer" and key not in linked][:3]
        seeds, dist = linked + extra, {s: 0 for s in linked} | {s: 1 for s in extra}
    else:
        seeds = [key for key, _, _ in vrows][:5]
        dist = {s: 0 for s in seeds}
    rows = db.run(tenant, "recall: facts", Q.retrieve_facts(cfg["hops"]),
                  {"seeds": seeds, "max_entities": 100, "max_facts": 400}, log, ro=True) if seeds else []
    facts = [dict(zip(FIELDS, r)) for r in rows]
    if cfg["temporal"]:
        _annotate_conflicts(facts)
    # Rank by hops from the linked entities, then by how well the predicate fits the question.
    # parent: the fact (and the entity on its near side) that first reached each entity: the answer's path back
    parent = {}
    changed = True
    while changed:
        changed = False
        for f in facts:
            for a, b in ((f["subject"], f["object"]), (f["object"], f["subject"])):
                if a in dist and dist.get(b, 99) > dist[a] + 1:
                    dist[b], parent[b], changed = dist[a] + 1, (f, a), True
                elif a in dist and dist[b] == dist[a] + 1 and b not in parent and (a in parent or dist[a] == 0):
                    parent[b] = (f, a)  # a vector seed the traversal also reaches: keep the traversal's path
    q = np.array(qvec) / np.linalg.norm(qvec)
    pv = _predicate_vecs()
    # Importance (Generative Agents): PageRank salience from consolidation, a light nudge within a hop tier.
    top = max((f["salience"] or 0 for f in facts), default=0) or 1
    facts.sort(key=lambda f: (min(dist.get(f["subject"], 9), dist.get(f["object"], 9)),
                              -(float(_pvec(f["predicate"]) @ q) + SALIENCE_WEIGHT * (f["salience"] or 0) / top),
                              not f["active"], f["recorded_at"]))
    facts = facts[:MAX_LINES]
    return {"seeds": seeds, "facts": facts, "lines": [fmt(f, cfg["temporal"]) for f in facts], "unknown": ln["unknown"],
            "linked": linked, "dist": dist, "parent": parent}


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


# The answer contract: every answer comes back as exactly one of four shapes.
#   path           the answer needed a multi-hop traversal: a cited fact was reached through other facts (Alice ->
#                  LIVES_IN -> Mumbai <- AFFECTS <- outage). `paths` holds the hops, in the order recall walked them.
#   memory         the answer is a fact written about the asked entity itself, in an earlier session, by an agent:
#                  one hop, with `learned` saying when it went on file and who wrote it.
#   not_in_graph   the question named entities the graph holds (or none at all), but no fact of the asked kind
#                  connects them: "not modelled", which is not the same as "nothing is true".
#   unknown_entity the question names someone the graph doesn't hold: abstained after name lookup, no fact query ran.
OUTCOMES = ("path", "memory", "not_in_graph", "unknown_entity")


def hop(f):
    """One fact as one hop of a path: subject -REL-> object, with both clocks' dates and its writers."""
    return {"from": f["subject"], "rel": R.rel_type(f["predicate"]) if f["predicate"] in R.PREDICATES or R.is_open(f["predicate"])
            else f["predicate"].upper(),
            "to": f["object"], "fact_id": f["fact_id"], "active": f["active"], "since": to_date(f["valid_from"]),
            "until": to_date(f["valid_to"]), "learned": to_date(f["recorded_at"]), "by": f["agents"]}


def fact_path(r, f):
    """The hops from a linked entity to fact f, rebuilt from the expansion that reached it (recall's parent map)."""
    dist, parent = r.get("dist", {}), r.get("parent", {})
    # the endpoint nearer a linked entity; a vector seed (no parent) only when no traversal reached the fact
    n = min((f["subject"], f["object"]), key=lambda e: (dist.get(e, 99) > 0 and e not in parent, dist.get(e, 99)))
    hops = [hop(f)]
    while n in parent and dist.get(n, 0) > 0 and len(hops) < 6:
        pf, n = parent[n]
        hops.insert(0, hop(pf))
    return hops


def contract(r, a):
    """-> {outcome, paths, learned, note} for an answer `a` over recall result `r` (see OUTCOMES)."""
    if r["unknown"] and not r["facts"]:
        who = ", ".join(r["unknown"])
        return {"outcome": "unknown_entity", "paths": [], "learned": [],
                "note": f"No fact query ran: {who} is not in the graph."}
    cited = [f for f in r["facts"] if f["fact_id"] in a["cited_ids"]]
    if a.get("unknown") or not cited:
        linked = r.get("linked") or []
        note = (f"{', '.join(linked)} {'is' if len(linked) == 1 else 'are'} in the graph, but nothing connects "
                f"{'it' if len(linked) == 1 else 'them'} the way the question assumes." if linked
                else "Nothing in the graph matches what the question asks about.")
        return {"outcome": "not_in_graph", "paths": [], "learned": [], "note": note}
    paths = [fact_path(r, f) for f in cited]
    learned = [{"fact_id": f["fact_id"], "fact": f"{f['subject']} {f['predicate']} {f['object']}",
                "at": to_date(f["recorded_at"]), "by": f["agents"], "since": to_date(f["valid_from"])} for f in cited]
    multi = any(len(p) > 1 for p in paths)
    return {"outcome": "path" if multi else "memory", "paths": paths, "learned": learned,
            "note": "Reached by traversal: the hops are below." if multi else
                    f"From memory: on file since {learned[0]['at']}, written by {', '.join(learned[0]['by'])}."}


def grounding(tenant, customer, reply, before, log=None):
    """The customer's own facts (from earlier turns) that a reply states back to them, as one-hop paths: the
    "how I know" line under a reply. Only facts whose subject is this customer, never anyone else's;
    only facts on file before this turn, so what they just said is not dressed up as memory."""
    text = " " + re.sub(r"[^a-z0-9]+", " ", str(reply).lower()) + " "
    out = []
    for f in customer_facts(tenant, customer, log):
        if (f["active"] and f["predicate"] not in ("awaiting", "has_ticket") and (f["recorded_at"] or 0) < before
                and f["subject"] == norm(customer)
                and f" {re.sub(r'[^a-z0-9]+', ' ', str(f['object']).lower()).strip()} " in text):
            out.append(f)
    return [hop(f) for f in out[:3]]


def ask(tenant, question, *, mode="full", agent=None, log=None):
    """agent: who is asking; when given, the facts the answer cites are recorded as CONSULTED by that agent.
    (The benchmark leaves it None so measuring never writes to the graph it measures.)"""
    r = recall(tenant, question, mode=mode, log=log)
    if r["unknown"] and not r["facts"]:  # names someone memory doesn't hold: abstain, no model call to talk round it
        who = ", ".join(n.upper() if any(c.isdigit() for c in n) else n.title() for n in r["unknown"])
        a = {"answer": f"I don't have anything on file about {who}.", "values": [], "cited_ids": [],
             "conflict": False, "unknown": True}
    else:
        a = llm.answer(question, r["lines"])
    known = {f["fact_id"] for f in r["facts"]}
    a = {**a, "cited_ids": [i for i in a["cited_ids"] if i in known], "recall": r}
    a |= contract(r, a)
    if agent:
        from . import sharing  # lazy: sharing -> memory -> ... keeps import order simple
        sharing.consult(tenant, agent, a["cited_ids"], log=log)
    events.emit(tenant, "answer", {k: a[k] for k in ("answer", "cited_ids", "conflict", "unknown", "outcome")} | {"question": question})
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
