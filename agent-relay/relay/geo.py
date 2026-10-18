"""Where any address is, and which of our cities and desks serves it.

Customers don't know our city list: they say "Navajeevan Nagar, Pattabiram", a PIN code, or a landmark. One resolver
for every path that meets a place (the chat's desk routing, a customer's line, MCP writes):

1. our catalogue (199 cities, 1,118 areas, with aliases): free and instant;
2. the offline GeoNames town list (data/places.json) for a single town name;
3. OpenCage geocoding (OPENCAGE_API_KEY) for anything else: suburbs, PIN codes, landmarks.

A position from 2 or 3 is matched to the nearest city we serve (and its nearest listed area). Lookups are cached on
disk, so each address costs at most one OpenCage call (free tier: 2,500 a day, one a second)."""
import json
import math
import os
import threading
import time

import httpx

from . import config, kb

KEY = os.environ.get("OPENCAGE_API_KEY", "")
SERVED_KM = 150   # further than this from every city we serve: we know where it is, but have no network there
_lock = threading.Lock()
_last_call = 0.0
_CACHE_FILE = config.CACHE_DIR / "geocode.json"
_cache: dict | None = None


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save():
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
    except Exception as e:  # a cache that can't be written only costs a repeat lookup
        print(f"geocode cache: {e}")


def geocode(text):
    """OpenCage's best match for free text: {lat, lon, country, formatted, parts}, or None (no key, no match,
    or the service is unreachable; the caller then carries on without a position)."""
    global _last_call
    q = " ".join(str(text or "").split())[:200]
    if not KEY or len(q) < 3 or not any(ch.isalnum() for ch in q):  # words, a PIN code ("600 072"), a landmark
        return None
    with _lock:
        cache = _load()
        if q.lower() in cache:
            return cache[q.lower()]
        wait = 1.05 - (time.time() - _last_call)  # the free tier allows one request a second
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            r = httpx.get("https://api.opencagedata.com/geocode/v1/json", timeout=6,
                          params={"q": q, "key": KEY, "limit": 1, "no_annotations": 1, "language": "en"})
            r.raise_for_status()
            hits = r.json().get("results") or []
        except Exception as e:
            print(f"geocode {q!r}: {e}")
            return None  # not cached: a network blip shouldn't be remembered as "nowhere"
        best = None
        if hits and (hits[0].get("confidence") or 0) >= 1:
            h = hits[0]
            parts = h.get("components") or {}
            best = {"lat": h["geometry"]["lat"], "lon": h["geometry"]["lng"],
                    "country": (parts.get("country_code") or "").upper(), "formatted": h.get("formatted", ""),
                    "parts": {k: v for k, v in parts.items() if isinstance(v, str) and not k.startswith("_")}}
        cache[q.lower()] = best
        _save()
        return best


def _km(a_lat, a_lon, b_lat, b_lon):
    p = math.pi / 180
    h = (math.sin((b_lat - a_lat) * p / 2) ** 2
         + math.cos(a_lat * p) * math.cos(b_lat * p) * math.sin((b_lon - a_lon) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def nearest(lat, lon, country=None):
    """The city we serve nearest to a position (its nearest listed area too, when the offline town list has the areas'
    positions), with the distance, and whether it's close enough to count as served."""
    cities = kb.world()["cities"]
    pool = [c for c in cities if c["country"] == country] or cities  # same country first: a border town stays home
    c = min(pool, key=lambda c: _km(lat, lon, c["lat"], c["lon"]))
    km = _km(lat, lon, c["lat"], c["lon"])
    if km > SERVED_KM and pool is not cities:  # nothing near in that country: maybe across a border
        c2 = min(cities, key=lambda c: _km(lat, lon, c["lat"], c["lon"]))
        if _km(lat, lon, c2["lat"], c2["lon"]) < km:
            c, km = c2, _km(lat, lon, c2["lat"], c2["lon"])
    area, best = None, None
    for a in c.get("areas") or []:
        at = kb.locate(a["key"], c["region"])
        if at and at[2] == c["country"]:
            d = _km(lat, lon, at[0], at[1])
            if best is None or d < best:
                area, best = a["key"], d
    return {"region": c["region"], "country": c["country"], "city": c["key"], "area": area,
            "key": area or c["key"], "km": round(km, 1), "served": km <= SERVED_KM}


def place(text, region=None):
    """Where a free-text address is, as kb.resolve_place shapes it ({region, country, city, area, key}), plus how it
    was found (via) and, from a position, the distance to that city (km) and whether we serve it (served).
    None only when nothing knows the place."""
    if not text:
        return None
    hit = kb.resolve_place(text)
    if hit:
        return {**hit, "via": "catalogue", "served": True}
    at = kb.locate(text, region)  # one town name the offline list knows ("Avadi")
    # a name several countries share, none of them this region's ("Goa": India and the Philippines): the offline list
    # can't tell which is meant, OpenCage ranks the well-known one first
    homes = kb._places().get(kb.norm(text)) or {}
    ambiguous = at and len(homes) > 1 and not (region and set(homes) & set(kb.world()["regions"][region]["countries"]))
    if at and not ambiguous:
        return {**nearest(at[0], at[1], at[2]), "via": "geonames"}
    g = geocode(text)
    if g:
        return {**nearest(g["lat"], g["lon"], g["country"] or None), "via": "opencage", "formatted": g["formatted"]}
    if at:  # no geocoder to ask: the offline list's pick
        return {**nearest(at[0], at[1], at[2]), "via": "geonames"}
    return None


def desk_for(text, region=None):
    """The desk (region) that serves an address, even one far from our cities: a town in Germany belongs to the
    Europe desk (its prices, its language) though no city of ours is near. None when nothing knows the place."""
    p = place(text, region)
    if not p:
        return None
    if not p.get("served") and p.get("via") == "opencage":
        g = geocode(text)
        iso = g and g["country"]
        reg = next((code for code, r in kb.world()["regions"].items() if iso in r["countries"]), None)
        if reg:
            return {**p, "region": reg, "country": iso}
    return p
