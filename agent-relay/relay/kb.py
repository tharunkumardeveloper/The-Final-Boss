"""The company's knowledge, worldwide, stored in each region's tenant graph.

Built from data/kb_world.json (python -m data.kb_world). One graph per region (India, Europe, North America,
Asia-Pacific, Middle East & Africa, Latin America); each holds its own countries, cities, areas, local prices,
policies, FAQs, troubleshooting playbooks and technicians:

  (:City)-[:IN_COUNTRY]->(:Country)      (:Area)-[:IN_CITY]->(:City)
  (:Plan)-[:PRICED_IN {amount, currency}]->(:Country)      (:Plan)-[:INCLUDES]->(:Router)
  (:Faq)-[:EXPLAINS]->(:Plan|:Addon|:Service)     (:Playbook)-[:FOR_ISSUE]->(:Issue)
  (:Playbook)-[:FIRST_STEP]->(:Step)-[:NEXT]->(:Step)        (:Technician)-[:BASED_IN]->(:City)

Customer memory connects to the same nodes: a customer's ON_PLAN edge points at the 'fiber 300' node that holds its
prices, and LIVES_IN points at the canonical area or city.
"""
import hashlib
import json
import re
from functools import lru_cache

from . import config, db, embed

WORLD_FILE = config.ROOT / "data" / "kb_world.json"
TREES_FILE = config.ROOT / "data" / "issue_trees.json"  # intake's issue trees (what to ask next, when to open a ticket)
OFFERINGS_FILE = config.ROOT / "data" / "offerings.json"  # locked.in's service lines (Fiber, Gaming Zone, Binge Club, Hub)
SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "AUD": "A$", "CAD": "C$", "SGD": "S$", "NZD": "NZ$",
          "BRL": "R$", "KRW": "₩", "CHF": "CHF ", "AED": "AED ", "ZAR": "R"}
SPECIAL = {"pml": "in", "pml-bench": "in", "nimbus": "in"}


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9 .'-]", " ", str(s).lower()).split())


@lru_cache
def world():
    # catalogue text says {company}; the name comes from brand.json
    return json.loads(WORLD_FILE.read_text(encoding="utf-8").replace("{company}", config.BRAND["company"]))


def region_of(tenant):
    """pml -> India; pml-eu -> Europe; any other tenant -> India (the default demo region)."""
    if tenant in SPECIAL:
        return SPECIAL[tenant]
    code = str(tenant).removeprefix("pml-")
    return code if code in world()["regions"] else "in"


def money(amount, currency):
    if amount in (None, 0):
        return "free"
    sym = SYMBOL.get(currency, currency + " ")
    return f"{sym}{amount:,.2f}" if isinstance(amount, float) and amount % 1 else f"{sym}{int(amount):,}"


# ---------------------------------------------------------------- places

COMMON_WORDS = {"nice", "cork", "the loop", "central"}  # place names that are also everyday words


@lru_cache
def _place_index():
    """phrase -> (region, iso, city key, area key or None), longest phrases first."""
    idx = {}
    for c in world()["cities"]:
        for phrase in [c["key"], *c["aliases"]]:
            if phrase in COMMON_WORDS:
                continue
            idx.setdefault(phrase, (c["region"], c["country"], c["key"], None))
        for a in c["areas"]:
            for phrase in [a["key"], *a.get("aliases", [])]:  # a locality inside an area's exchange counts as that area
                idx.setdefault(phrase, (c["region"], c["country"], c["key"], a["key"]))
    return sorted(idx.items(), key=lambda kv: -len(kv[0]))


def resolve_place(text):
    """'hsr layout bangalore' -> {area: 'hsr layout', city: 'bengaluru', ...}; None if we don't serve it."""
    # a full stop ends a sentence, not a name: "...Pattabiram, Chennai." must still find Chennai (a dot after a single
    # letter stays, it's part of a name: "T. Nagar")
    t = f" {norm(re.sub(r'(\w{2,})\.+(?=\s|$)', r'\1', str(text)))} "
    found = None
    for phrase, (region, iso, city, area) in _place_index():
        if len(phrase) >= 3 and f" {phrase} " in t:
            if area:  # an area is the most specific answer; take the longest one
                return {"region": region, "country": iso, "city": city, "area": area, "key": area, "phrase": phrase}
            found = found or {"region": region, "country": iso, "city": city, "area": None, "key": city,
                              "phrase": phrase}
    return found


def covered_city(name):
    return resolve_place(name) is not None


def coverage(region):
    return {c["key"]: [a["key"] for a in c["areas"]] for c in world()["cities"] if c["region"] == region}


def cities(region):
    return [c for c in world()["cities"] if c["region"] == region]


def country_name(iso):
    return world()["countries"][iso]["name"]


def default_country(region):
    return world()["regions"][region]["countries"][0]


# ---------------------------------------------------------------- seeding

SEED_COUNTRIES = """
UNWIND $rows AS r
MERGE (e:Entity {name_key:r.key}) ON CREATE SET e.type='country', e.created_at=0
SET e:Country, e.kb=true, e.name=r.name, e.iso=r.iso, e.currency=r.currency, e.tax=r.tax, e.tax_pct=r.tax_pct,
    e.payments=r.payments, e.kb_text=r.text
"""
SEED_CITIES = """
UNWIND $rows AS r
MATCH (k:Country {iso:r.iso})
MERGE (c:Entity {name_key:r.key}) ON CREATE SET c.type='city', c.created_at=0
SET c:City, c.kb=true, c.name=r.name, c.country=r.iso, c.tz=r.tz, c.population=r.population, c.aliases=r.aliases,
    c.kb_text=r.text
MERGE (c)-[:IN_COUNTRY]->(k)
WITH c, r
UNWIND r.areas AS a
MERGE (x:Entity {name_key:a.key}) ON CREATE SET x.type='area', x.created_at=0
SET x:Area, x.kb=true, x.name=a.name, x.city=r.key, x.kb_text='We serve ' + a.name + ' in ' + r.name + '.'
MERGE (x)-[:IN_CITY]->(c)
"""
SEED_ITEMS = """
UNWIND $rows AS r
MERGE (e:Entity {name_key:r.key}) ON CREATE SET e.type=r.type, e.created_at=0
SET e.kb=true, e.name=r.name, e.kb_text=r.text, e.embedding=vecf32(r.vec), e.props=r.props
"""
SEED_PRICES = """
UNWIND $rows AS r
MATCH (i:Entity {name_key:r.key}), (k:Country {iso:r.iso})
MERGE (i)-[p:PRICED_IN]->(k)
SET p.amount=r.amount, p.currency=r.currency
"""
SEED_LINK = "UNWIND $rows AS r MATCH (a:Entity {name_key:r.a}), (b:Entity {name_key:r.b}) MERGE (a)-[:{REL}]->(b)"
SEED_ISSUES = """
UNWIND $rows AS r
MERGE (i:Entity {name_key:r.issue}) ON CREATE SET i.type='issue', i.name=r.issue, i.created_at=0, i.embedding=vecf32(r.vec)
SET i:Issue
"""
SEED_STEPS = """
UNWIND $rows AS r
MATCH (p:Entity {name_key:r.playbook})
MERGE (s:Step {step_id:r.id}) SET s.name=r.text, s.text=r.text, s.order=r.order
WITH p, s, r
FOREACH (_ IN CASE WHEN r.order = 1 THEN [1] ELSE [] END | MERGE (p)-[:FIRST_STEP]->(s))
WITH s, r WHERE r.prev IS NOT NULL
MATCH (prev:Step {step_id:r.prev})
MERGE (prev)-[:NEXT]->(s)
"""
META = "MERGE (m:Meta {key:'kb'}) RETURN m.version"
SET_META = "MERGE (m:Meta {key:'kb'}) SET m.version=$v, m.name='catalogue ' + $v"


def _version(region):
    return hashlib.sha1((WORLD_FILE.read_bytes() + TREES_FILE.read_bytes() + OFFERINGS_FILE.read_bytes() + config.BRAND_FILE.read_bytes() + region.encode())).hexdigest()[:12]


def seed(tenant):
    """Idempotent, and skipped when this region's catalogue is already loaded at the current version."""
    region = region_of(tenant)
    g = db.graph(tenant)
    v = _version(region)
    if g.query(META).result_set[0][0] == v:
        return
    w = world()
    isos = w["regions"][region]["countries"]
    g.query(SEED_COUNTRIES, {"rows": [
        {"key": norm(c["name"]), "iso": iso, "name": c["name"], "currency": c["currency"], "tax": c["tax"],
         "tax_pct": c["tax_pct"], "payments": c["payments"],
         "text": f"In {c['name']} prices are in {c['currency']}; pay by {', '.join(c['payments'])}."}
        for iso, c in w["countries"].items() if iso in isos]})
    region_cities = [c for c in w["cities"] if c["region"] == region]
    for i in range(0, len(region_cities), 40):
        g.query(SEED_CITIES, {"rows": [
            {**{k: c[k] for k in ("key", "name", "tz", "population", "aliases", "areas")}, "iso": c["country"],
             "text": f"We serve {c['name']}, {country_name(c['country'])}: {', '.join(a['name'] for a in c['areas'])}."}
            for c in region_cities[i:i + 40]]})

    items = []  # (type, key, name, text, props)
    for r in w["routers"]:
        items.append(("router", r["key"], r["name"], f"{r['name']}: {r['wifi']}, {r['ports']}, covers about {r['range_sqm']} square metres.", {}))
    plans = [p for p in w["plans"] if region in p["regions"]]
    for p in plans:
        items.append(("plan", p["key"], p["name"],
                      f"{p['name']}: {p['down']} Mbps down / {p['up']} Mbps up, unlimited data, handles about {p['devices']} devices, "
                      f"includes {', '.join(p['includes'])}; {'no lock-in' if not p['lock_in'] else str(p['lock_in']) + '-month lock-in'}. "
                      f"Built for {p['good_for']}.", {}))
    for a in w["addons"]:
        items.append(("addon", a["key"], a["name"], f"Add-on {a['name']}: {a['notes']}", {}))
    for s in w["services"]:
        items.append(("service", s["key"], s["name"], f"{s['name']} ({s['turnaround']}): {s['notes']}", {}))
    for p in w["policies"]:
        if region in p["regions"]:
            items.append(("policy", p["key"], p["title"], f"{p['title']}: {p['text']}", {}))
    for f in w["faqs"]:
        if region in f["regions"]:
            items.append(("faq", "faq: " + f["key"], f["q"], f"Q: {f['q']} A: {f['a']}", {}))
    for o in json.loads(OFFERINGS_FILE.read_text(encoding="utf-8")):
        items.append(("offering", "offering: " + o["key"], o["title"], f"{o['pillar']}, {o['title']}: {o['text']}", {}))
    for t in json.loads(TREES_FILE.read_text(encoding="utf-8")):
        items.append(("guide", "guide: " + t["key"], t["title"], f"Intake guide, {t['title']}: {t['text']}", {}))
    for pb in w["playbooks"]:
        items.append(("playbook", "playbook: " + pb["key"], pb["key"],
                      f"How we fix {pb['issue']}" + (f" on the {pb['router']}" if pb["router"] else "") + ": "
                      + "; ".join(f"{i + 1}. {s}" for i, s in enumerate(pb["steps"])), {}))
    vecs = embed.embed([t for _, _, _, t, _ in items])
    for i in range(0, len(items), 60):
        g.query(SEED_ITEMS, {"rows": [{"type": typ, "key": key, "name": name, "text": text, "vec": v, "props": json.dumps(props)}
                                      for (typ, key, name, text, props), v in zip(items[i:i + 60], vecs[i:i + 60])]})
    for typ in ("router", "plan", "addon", "service", "policy", "faq", "playbook", "guide", "offering"):
        g.query(f"MATCH (e:Entity {{kb:true, type:'{typ}'}}) SET e:{typ.capitalize()}")

    prices = []
    for p in plans:
        prices += [{"key": p["key"], "iso": iso, "amount": amt, "currency": w["countries"][iso]["currency"]}
                   for iso, amt in p["prices"].items() if iso in isos]
    for x in w["addons"] + w["services"]:
        prices += [{"key": x["key"], "iso": iso, "amount": amt, "currency": w["countries"][iso]["currency"]}
                   for iso, amt in x["prices"].items() if iso in isos]
    for i in range(0, len(prices), 200):
        g.query(SEED_PRICES, {"rows": prices[i:i + 200]})
    link = lambda rel, rows: rows and g.query(SEED_LINK.replace("{REL}", rel), {"rows": rows})
    link("INCLUDES", [{"a": p["key"], "b": p["router"]} for p in plans])
    link("EXPLAINS", [{"a": "faq: " + f["key"], "b": k} for f in w["faqs"] if region in f["regions"] for k in f["about"]])

    issues = sorted({pb["issue"] for pb in w["playbooks"]})
    g.query(SEED_ISSUES, {"rows": [{"issue": i, "vec": v} for i, v in zip(issues, embed.embed(issues))]})
    link("FOR_ISSUE", [{"a": "playbook: " + pb["key"], "b": pb["issue"]} for pb in w["playbooks"]])
    link("FOR_ROUTER", [{"a": "playbook: " + pb["key"], "b": pb["router"]} for pb in w["playbooks"] if pb["router"]])
    steps = [{"playbook": "playbook: " + pb["key"], "id": f"{pb['key']}#{n}", "text": s, "order": n,
              "prev": f"{pb['key']}#{n - 1}" if n > 1 else None}
             for pb in w["playbooks"] for n, s in enumerate(pb["steps"], 1)]
    for i in range(0, len(steps), 200):
        g.query(SEED_STEPS, {"rows": steps[i:i + 200]})
    g.query(SET_META, {"v": v})


# ---------------------------------------------------------------- answering from the catalogue

KB_SIMILAR = """
CALL db.idx.vector.queryNodes('Entity', 'embedding', 16, vecf32($vec)) YIELD node, score
WITH node, score WHERE node.kb = true AND node.type IN ['faq', 'policy', 'service', 'addon', 'plan', 'playbook', 'router', 'guide', 'offering']
RETURN node.name_key, node.kb_text, score ORDER BY score ASC LIMIT $k
"""
KB_BY_KEY = "MATCH (e:Entity) WHERE e.kb = true AND e.name_key IN $keys RETURN e.name_key, e.kb_text"
PRICES = """
MATCH (i:Entity)-[p:PRICED_IN]->(:Country {iso:$iso}) WHERE i.type IN $types
RETURN i.type, i.name_key, i.name, p.amount, p.currency, i.kb_text ORDER BY i.type, p.amount
"""
KB_ALL = "MATCH (e:Entity {kb:true}) WHERE e.type IN ['policy'] RETURN e.name_key, e.name, e.kb_text"
PLAN_WORDS = re.compile(r"\b(plan|plans|price|prices|cost|costs|how much|budget|cheap|cheapest|rs|rupees|inr|usd|eur|"
                        r"pound|dollar|euro|per month|monthly|offer|fiber|fibre|package|buy|subscribe|book|sign up|"
                        r"install|installation|connection|broadband)\b")


# an interest -> the add-on or service a salesperson would offer for it
OFFER_FOR = {
    "gaming boost": re.compile(r"\b(gam(e|es|er|ers|ing)|valorant|bgmi|gta|fortnite|ping|lag|esports?|ps5|xbox|console)\b"),
    "ott bundle": re.compile(r"\b(ott|stream(ing)?|binge|netflix|prime|hotstar|series|movies?|shows?|anime)\b"),
    "speed boost day": re.compile(r"\b(download|downloads|update|launch|upload|uploads|creator|youtube|yt)\b"),
    "mesh extender": re.compile(r"\b(dead zone|weak signal|big house|large home|upstairs|another room)\b"),
}


GUIDE = """
CALL db.idx.vector.queryNodes('Entity', 'embedding', 100, vecf32($vec)) YIELD node, score
WITH node, score WHERE node.type = 'guide'
RETURN node.kb_text, score ORDER BY score ASC LIMIT 1
"""


def guide(tenant, text, log=None):
    """The intake guide (issue tree) closest in meaning to what the customer said, if one is close enough."""
    rows = db.run(tenant, "kb: intake guide", GUIDE, {"vec": embed.embed_one(text)}, log, ro=True)
    return rows[0][0] if rows and rows[0][1] < 0.45 else None


GEO = """
UNWIND $rows AS r
MATCH (c:City {name_key:r.key})
SET c.location = point({latitude:r.lat, longitude:r.lon})
WITH c
MATCH (a:Area)-[:IN_CITY]->(c)
SET a.location = c.location
"""
NEAREST = """
MATCH (c:City) WHERE c.location IS NOT NULL
WITH c, distance(c.location, point({latitude:$lat, longitude:$lon})) AS m
RETURN c.name, c.country, round(m / 1000) AS km ORDER BY m ASC LIMIT 1
"""
PLACES_FILE = config.ROOT / "data" / "places.json"


@lru_cache
def _places():
    """Every GeoNames town in the countries we serve (served or not), with coordinates, plus state names."""
    return json.loads(PLACES_FILE.read_text(encoding="utf-8")) if PLACES_FILE.exists() else {}


def locate(name, region=None):
    """(lat, lon, country) of a place, preferring the region's countries: 'goa' is Panaji, India, not Goa, Philippines."""
    hits = _places().get(norm(name)) or {}
    isos = world()["regions"][region]["countries"] if region else []
    iso = next((i for i in isos if i in hits), None) or next(iter(hits), None)
    return (*hits[iso], iso) if iso else None


def nearest_served(tenant, name, log=None):
    """The closest city we serve to a place we don't, by FalkorDB distance() over City.location points."""
    at = locate(name, region_of(tenant))
    if not at:
        return None
    rows = db.run(tenant, "kb: nearest served city", NEAREST, {"lat": at[0], "lon": at[1]}, log, ro=True)
    return {"city": rows[0][0], "country": rows[0][1], "km": int(rows[0][2])} if rows else None


def geo(tenant):
    """City and area points for graphs seeded before they had them (idempotent, cheap)."""
    region = region_of(tenant)
    rows = [{"key": c["key"], "lat": c["lat"], "lon": c["lon"]} for c in world()["cities"] if c["region"] == region]
    g = db.graph(tenant)
    if g.query("MATCH (c:City) WHERE c.location IS NULL RETURN count(c)").result_set[0][0]:
        for i in range(0, len(rows), 100):
            g.query(GEO, {"rows": rows[i:i + 100]})


def price_list(tenant, iso, types=("plan",), log=None):
    return [{"type": t, "key": k, "name": n, "amount": a, "currency": c, "label": money(a, c), "text": txt}
            for t, k, n, a, c, txt in db.run(tenant, "kb: prices", PRICES, {"iso": iso, "types": list(types)}, log, ro=True)]


def relevant(tenant, text, k=4, log=None, iso=None):
    """Catalogue sentences for a message: local prices when plans or money come up, exact mentions of add-ons and
    services with their local price, where we serve a mentioned place, then the nearest FAQs/policies by meaning."""
    region = region_of(tenant)
    iso = iso or default_country(region)
    t = f" {norm(text)} "
    out = []
    if PLAN_WORDS.search(t):
        plans = price_list(tenant, iso, ("plan",), log)
        out.append(f"Plans in {country_name(iso)} (exactly these, no others exist): "
                   + "; ".join(f"{p['name']} {p['label']}/month" for p in plans) + ".")
        out += [p["text"] for p in plans if f" {p['key']} " in t]
    extras = price_list(tenant, iso, ("addon", "service"), log)
    # named add-ons, and the one an interest calls for (so the bot can offer it with its local price, unasked)
    hinted = {key for key, words in OFFER_FOR.items() if words.search(t)}
    out += [f"{x['text']} Price in {country_name(iso)}: {x['label']}." for x in extras
            if f" {x['key']} " in t or x["key"] in hinted]
    place = resolve_place(text)
    if place:
        where = (f"{place['area'].title()} in " if place["area"] else "") + f"{place['city'].title()}, {country_name(place['country'])}"
        team = "" if place["region"] == region else f" (served by our {world()['regions'][place['region']]['name']} team)"
        out.append(f"Coverage: we serve {where}{team}.")
    near = db.run(tenant, "kb: similar", KB_SIMILAR, {"vec": embed.embed_one(text), "k": k}, log, ro=True)
    out += [txt for _, txt, dist in near if dist < 0.5][:k]
    return list(dict.fromkeys(out))


def catalogue(tenant, iso=None, log=None):
    """GET /kb: what the portal shows, read back from the tenant graph in the requested country's currency."""
    w = world()
    region = region_of(tenant)
    iso = iso if iso in w["regions"][region]["countries"] else default_country(region)
    c = w["countries"][iso]
    by_key = {p["key"]: p for p in w["plans"]}
    rows = price_list(tenant, iso, ("plan", "addon", "service"), log)
    plans = [{**{k: by_key[r["key"]][k] for k in ("key", "name", "router", "includes", "lock_in")},
              "price": r["amount"], "price_label": r["label"], "currency": r["currency"],
              "speed_mbps": by_key[r["key"]]["down"], "upload_mbps": by_key[r["key"]]["up"],
              "devices": by_key[r["key"]]["devices"], "notes": "Built for " + by_key[r["key"]]["good_for"] + "."}
             for r in rows if r["type"] == "plan"]
    info = {x["key"]: x for x in w["addons"] + w["services"]}
    return {"region": region, "region_name": w["regions"][region]["name"],
            "countries": [{"iso": i, "name": w["countries"][i]["name"], "currency": w["countries"][i]["currency"]}
                          for i in w["regions"][region]["countries"]],
            "country": iso, "currency": c["currency"], "tax": f"{c['tax']} {c['tax_pct']}%" if c["tax_pct"] else None,
            "payments": c["payments"], "plans": plans,
            "addons": [{"key": r["key"], "name": r["name"], "price": r["amount"], "price_label": r["label"], "notes": info[r["key"]]["notes"]}
                       for r in rows if r["type"] == "addon"],
            "services": [{"key": r["key"], "name": r["name"], "price": r["amount"], "price_label": r["label"],
                          "turnaround": info[r["key"]]["turnaround"], "notes": info[r["key"]]["notes"]}
                         for r in rows if r["type"] == "service"],
            "policies": [{"key": k, "title": n, "text": t} for k, n, t in db.run(tenant, "kb: policies", KB_ALL, log=log, ro=True)],
            "coverage": [{"city": x["name"], "key": x["key"], "areas": [a["name"] for a in x["areas"]]}
                         for x in w["cities"] if x["country"] == iso],
            "support": {"channels": ["web chat", "messaging", "email", "phone"], "hours": "chat 24x7; phone 8 am to 10 pm local time"},
            "stats": {"countries": len(w["countries"]), "cities": len(w["cities"]),
                      "areas": sum(len(x["areas"]) for x in w["cities"]), "regions": len(w["regions"])}}


def region_summary():
    w = world()
    return [{"code": code, "tenant": r["tenant"], "name": r["name"],
             "countries": [w["countries"][i]["name"] for i in r["countries"]],
             "cities": sum(1 for c in w["cities"] if c["region"] == code)} for code, r in w["regions"].items()]


@lru_cache
def _zone_countries():
    """IANA timezone -> ISO country, from the system's zone.tab (or the tzdata package on Windows)."""
    text = None
    for path in ("/usr/share/zoneinfo/zone.tab", "/usr/share/zoneinfo/zone1970.tab"):
        try:
            text = open(path, encoding="utf-8").read()
            break
        except OSError:
            pass
    if text is None:
        try:
            import importlib.resources as res
            text = res.files("tzdata").joinpath("zoneinfo/zone.tab").read_text(encoding="utf-8")
        except Exception:
            return {}
    out = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and not line.startswith("#"):
            out[cols[2]] = cols[0].split(",")[0]
    return out


def _read_tz(name):
    for path in (f"/usr/share/zoneinfo/{name}",):
        try:
            return open(path, encoding="utf-8").read()
        except OSError:
            pass
    try:
        import importlib.resources as res
        return res.files("tzdata").joinpath(f"zoneinfo/{name}").read_text(encoding="utf-8")
    except Exception:
        return ""


@lru_cache
def _tz_aliases():
    """Old timezone names browsers still report ("Asia/Calcutta") -> today's name ("Asia/Kolkata"), from tzdata.zi."""
    out = {}
    for line in _read_tz("tzdata.zi").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "L":
            out[parts[2]] = parts[1]
    return out


def locate_visitor(tz=None, lang=None):
    """Where a visitor probably is, from the browser's timezone (then its language region). No IP lookup."""
    w = world()
    zones = _zone_countries()
    tz = _tz_aliases().get(tz or "", tz or "")
    iso = zones.get(tz)
    if iso is None and lang and "-" in lang:  # the language only when the timezone says nothing ("en-US" is everywhere)
        iso = lang.split("-")[-1].upper()
    if iso not in w["countries"]:
        return None
    region = next((code for code, r in w["regions"].items() if iso in r["countries"]), None)
    return {"country": iso, "name": country_name(iso), "region": region, "tenant": w["regions"][region]["tenant"]} if region else None
