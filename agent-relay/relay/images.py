"""A picture in the chat when a game, a show or film, a streaming platform or a physical thing (a router, fiber, a
console) comes up: the lead image of its Wikipedia article, full resolution, no key needed. One per topic per chat;
cached on disk per topic; any failure just means no picture."""
import hashlib
import json
import re
import threading

import httpx

from . import config

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "RelayDemo/1.0 (hackathon demo; contact via GitHub)"}
CACHE = config.CACHE_DIR / "images"

# word in the chat -> Wikipedia article. Named titles first; things after.
TITLES = {"valorant": "Valorant", "cs2": "Counter-Strike 2", "counter strike": "Counter-Strike 2", "csgo": "Counter-Strike 2",
          "bgmi": "Battlegrounds Mobile India", "pubg": "PUBG: Battlegrounds", "call of duty": "Call of Duty",
          "warzone": "Call of Duty: Warzone", "fortnite": "Fortnite", "apex legends": "Apex Legends",
          "league of legends": "League of Legends", "minecraft": "Minecraft", "gta 5": "Grand Theft Auto V",
          "gta v": "Grand Theft Auto V", "gta": "Grand Theft Auto V", "dota": "Dota 2", "free fire": "Garena Free Fire",
          "rocket league": "Rocket League", "overwatch": "Overwatch (2023 video game)", "netflix": "Netflix", "prime video": "Amazon Prime Video",
          "amazon prime": "Amazon Prime Video", "hotstar": "JioHotstar", "disney": "Disney+", "jiocinema": "JioCinema",
          "sonyliv": "SonyLIV", "sony liv": "SonyLIV", "zee5": "ZEE5", "hbo": "HBO Max", "apple tv": "Apple TV+",
          "youtube": "YouTube", "crunchyroll": "Crunchyroll", "twitch": "Twitch (service)"}
THINGS = {"ps5": "PlayStation 5", "playstation": "PlayStation 5", "xbox": "Xbox Series X and Series S",
          "nintendo switch": "Nintendo Switch", "router": "Wireless router", "mesh": "Mesh networking",
          "extender": "Wireless repeater", "fiber cable": "Optical fiber", "fibre cable": "Optical fiber",
          "optical fiber": "Optical fiber", "ftth": "Fiber to the x", "ethernet": "Ethernet", "lan cable": "Ethernet",
          "smart tv": "Smart TV", "4g dongle": "USB modem", "dongle": "USB modem", "gaming pc": "Gaming computer"}
KNOWN = {*TITLES.values(), *THINGS.values()}
# facts the extractor found -> what to look up when the name isn't in the tables
SEARCH = {"plays_game": "{} video game", "watches": "{}", "owns_device": "{}"}

_shown: dict[str, set] = {}  # ponytail: per-process memory of what each chat already saw; lost on restart, fine
_lock = threading.Lock()


def _norm(text):
    return f" {re.sub(r'[^a-z0-9 ]', ' ', text.lower())} "


def topics(text, facts=(), reply=""):
    """Wikipedia searches for what this turn is about, most specific first: titles in the message, then games/shows the
    extractor found, then physical things in the message or the reply."""
    t, out = _norm(text), []
    out += [v for k, v in TITLES.items() if f" {k} " in t]
    for pred, obj in facts:
        if pred in SEARCH:
            o = _norm(obj)
            out.append(next((v for k, v in {**TITLES, **THINGS}.items() if f" {k} " in o), SEARCH[pred].format(obj)))
    both = t + _norm(reply)
    out += [v for k, v in THINGS.items() if f" {k} " in both]
    return list(dict.fromkeys(out))


def lookup(topic):
    """{src, title, link} for the lead image of the best-matching article, or None. Cached per topic."""
    path = CACHE / f"wiki-{hashlib.sha256(topic.encode()).hexdigest()[:24]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")) or None
    # a known article by its exact title; free text ("elden ring video game") through search
    which = ({"titles": topic} if topic in KNOWN else {"generator": "search", "gsrsearch": topic, "gsrlimit": 3})
    try:
        r = httpx.get(API, headers=HEADERS, timeout=8, params={
            "action": "query", "format": "json", "formatversion": 2, "redirects": 1, **which,
            "prop": "pageimages|info", "piprop": "thumbnail|original",
            "pithumbsize": 800, "pilicense": "any", "inprop": "url"})  # any: covers and logos are fair-use
        r.raise_for_status()
        pages = sorted(r.json().get("query", {}).get("pages") or [], key=lambda p: p.get("index", 99))
        page = next((p for p in pages if p.get("thumbnail") or p.get("original")), {})  # best hit with a picture
    except (httpx.HTTPError, ValueError):
        return None  # not cached: try again next time
    img = (page.get("thumbnail") or page.get("original") or {}).get("source")
    hit = {"src": img, "title": page.get("title", topic), "link": page.get("fullurl")} if img else {}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hit), encoding="utf-8")
    return hit or None


def warm():
    """Every known title and thing in two requests (Wikipedia takes 50 titles at once; one-by-one gets rate-limited)."""
    want, out = sorted(KNOWN), {}
    for i in range(0, len(want), 50):
        r = httpx.get(API, headers=HEADERS, timeout=20, params={
            "action": "query", "format": "json", "formatversion": 2, "redirects": 1, "titles": "|".join(want[i:i + 50]),
            "prop": "pageimages|info", "piprop": "thumbnail|original", "pithumbsize": 800, "pilicense": "any",
            "inprop": "url"})
        r.raise_for_status()
        q = r.json()["query"]
        alias = {x["from"]: x["to"] for x in q.get("normalized", []) + q.get("redirects", [])}
        pages = {pg["title"]: pg for pg in q.get("pages", [])}
        for t in want[i:i + 50]:
            pg = pages.get(alias.get(alias.get(t, t), alias.get(t, t)), {})
            img = (pg.get("thumbnail") or pg.get("original") or {}).get("source")
            hit = {"src": img, "title": pg.get("title", t), "link": pg.get("fullurl")} if img else {}
            CACHE.mkdir(parents=True, exist_ok=True)
            (CACHE / f"wiki-{hashlib.sha256(t.encode()).hexdigest()[:24]}.json").write_text(json.dumps(hit), encoding="utf-8")
            out[t] = hit or None
    return out


def for_turn(session_id, text, facts=(), reply="", most=2):
    """Pictures for this turn that this chat hasn't seen yet: {query, images:[...]} or None."""
    with _lock:
        seen = _shown.setdefault(session_id, set())
        todo = [x for x in topics(text, facts, reply) if x not in seen][:most]
        seen.update(todo)
    pics = [p for p in map(lookup, todo) if p]
    return {"query": ", ".join(p["title"] for p in pics), "images": pics} if pics else None


if __name__ == "__main__":  # self-check, no network
    assert topics("im a creator and i play GTA 5") == ["Grand Theft Auto V"]
    assert topics("is netflix in the bundle?") == ["Netflix"]
    assert topics("i play elden ring", [("plays_game", "elden ring")]) == ["elden ring video game"]
    assert topics("which router do i get?", reply="Fiber 300 comes with a router.") == ["Wireless router"]
    assert topics("my valorant lags on my ps5") == ["Valorant", "PlayStation 5"]
    assert topics("my wifi drops every evening") == []
    assert topics("gaming") == []
    print("images: ok")
    import sys
    if sys.argv[1:] == ["warm"]:
        for title, hit in warm().items():
            print(title, "->", hit and hit["title"])
