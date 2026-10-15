"""LLM usage ledger: requests and tokens per model per day vs. limits, live Groq rate-limit headers, and each model's
real status: when it last answered or failed, and when the provider says it will be back.

Status is never a guess held for a fixed time: a 429 carries the provider's own "try again in 18m58s" (Groq) or a
daily reset (Gemini: midnight Pacific), and a background checker (api/main.py) re-tests a benched model with a
1-token request once that time passes. Several processes (API, tests, scripts) share one ledger file; each re-reads
it when another one has written."""
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, events

IST = timezone(timedelta(hours=5, minutes=30))

# Free-tier limits as shown in the provider consoles. Editable from the UI (saved to limits.json).
DEFAULT_LIMITS = {
    "openai/gpt-oss-120b": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000},
    "openai/gpt-oss-20b":  {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000},
    "qwen/qwen3.8-27b":    {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000},
    "allam-2-7b":          {"rpm": 30, "rpd": 7000, "tpm": 6000, "tpd": 500000},
}
# Groq says "... per day (RPD/TPD)"; Gemini's free tier says "You exceeded your current quota" / RESOURCE_EXHAUSTED.
DAILY_HINTS = ("per day", "(rpd)", "(tpd)", "perday", "per_day", "daily", "exceeded your current quota",
               "resource_exhausted")

RETRY_AFTER_S = 3600  # only when a provider gives no hint
_DIR = config.CACHE_DIR / "usage"
_lock = threading.Lock()
_state = {"date": None, "models": {}, "mtime": None}
_AGAIN = re.compile(r"try again in\s+(?:(\d+)h)?\s*(?:(\d+)m(?!s))?\s*(?:([\d.]+)s)?", re.I)


def _now():
    return datetime.now(IST).timestamp()


def back_at(model, message, daily):
    """When the provider says this model will answer again (epoch seconds)."""
    m = _AGAIN.search(message or "")
    if m and any(m.groups()):
        h, mi, s = (float(x) if x else 0 for x in m.groups())
        return _now() + h * 3600 + mi * 60 + s + 5
    if model.startswith("gemini:") and daily:  # Gemini's free daily quota resets at midnight Pacific
        pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        return (pt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp() + 60
    return _now() + (RETRY_AFTER_S if daily else 60)
_hits_unsaved = [0]


def today():
    return datetime.now(IST).strftime("%Y-%m-%d")


def _load(name, default):
    try:
        return json.loads((_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(name, data):
    _DIR.mkdir(parents=True, exist_ok=True)
    tmp = _DIR / f"{name}.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, _DIR / name)


def _day():
    """Today's ledger, re-read whenever another process (a test, a script) has written it since."""
    d = today()
    path = _DIR / f"{d}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _state["date"] != d or (mtime and mtime != _state["mtime"]):
        _state["date"], _state["models"], _state["mtime"] = d, _load(f"{d}.json", {}), mtime
    return _state["models"]


def _persist():
    _save(f"{_state['date']}.json", _day())
    try:
        _state["mtime"] = (_DIR / f"{_state['date']}.json").stat().st_mtime
    except OSError:
        pass


def _m(model):
    return _day().setdefault(model, {"requests": 0, "tokens_in": 0, "tokens_out": 0, "cache_hits": 0,
                                     "rate_limited": 0, "exhausted": False, "last_error": None, "live": None})


def limits():
    return {**DEFAULT_LIMITS, **_load("limits.json", {})}


def set_limits(model, **vals):
    with _lock:
        saved = _load("limits.json", {})
        saved[model] = {**limits().get(model, {}), **{k: int(v) for k, v in vals.items() if v is not None}}
        _save("limits.json", saved)


def set_route(job, models):
    if job not in config.ROUTES or not models:
        raise ValueError(f"unknown job {job!r} or empty route")
    with _lock:
        config.ROUTES[job] = config.pooled(models)
        _save("routes.json", config.ROUTES)


def _live(headers):
    h = {k.lower(): v for k, v in headers.items()}
    num = lambda k: int(float(h[k])) if h.get(k) not in (None, "") else None
    return {"limit_requests_day": num("x-ratelimit-limit-requests"),
            "remaining_requests_day": num("x-ratelimit-remaining-requests"),
            "reset_requests": h.get("x-ratelimit-reset-requests"),
            "limit_tokens_minute": num("x-ratelimit-limit-tokens"),
            "remaining_tokens_minute": num("x-ratelimit-remaining-tokens"),
            "reset_tokens": h.get("x-ratelimit-reset-tokens"),
            "at": datetime.now(IST).isoformat(timespec="seconds")}


def record(model, tokens_in=0, tokens_out=0, headers=None, latency_ms=None):
    with _lock:
        m = _m(model)
        m["requests"] += 1
        m["exhausted"] = False  # it answered, so it isn't out of quota
        m["limited_until"] = None
        m["checked_at"], m["ok_at"] = _now(), _now()
        m["latency_ms"] = latency_ms
        m["tokens_in"] += tokens_in or 0
        m["tokens_out"] += tokens_out or 0
        if headers and any(k.lower().startswith("x-ratelimit") for k in headers):
            m["live"] = _live(headers)
            if m["live"]["remaining_requests_day"] == 0:  # Groq: that was the last request of the window
                m["limited_until"] = back_at(model, f"try again in {m['live']['reset_requests'] or ''}", True)
        _persist()
    events.emit_all("usage", one(model))


def record_cache_hit(model):
    with _lock:
        _m(model)["cache_hits"] += 1
        _hits_unsaved[0] += 1
        if _hits_unsaved[0] >= 25:  # benchmark re-runs hit the cache thousands of times; save in batches
            _hits_unsaved[0] = 0
            _persist()


def record_unavailable(model, message):
    with _lock:
        m = _m(model)
        m["rate_limited"] += 1
        m["last_error"] = message[:300]
        m["checked_at"] = _now()
        daily = any(x in message.lower() for x in DAILY_HINTS)
        if daily:
            m["exhausted"] = True
            m["exhausted_at"] = _now()
        m["limited_until"] = back_at(model, message, daily)
        _persist()
    events.emit_all("usage", one(model))


def exhausted(model):
    """Out until the time the provider gave. Only the provider decides: our own token counters reset at IST
    midnight while Groq's daily windows roll, so they are shown as usage, never used to bench a model."""
    m = _day().get(model)
    if not m:
        return False
    until = m.get("limited_until") or (m.get("exhausted_at", 0) + RETRY_AFTER_S if m["exhausted"] else 0)
    return bool((m["exhausted"] or m.get("limited_until")) and _now() < until)


def soonest_back(models):
    """Seconds until the first of these models is back by the provider's own word, or None if none said when."""
    times = [m.get("limited_until") for m in (_day().get(x) or {} for x in models) if m.get("limited_until")]
    return max(0.0, min(times) - _now()) if times else None


def one(model):
    lim = limits().get(model) or limits().get(config.same_model(model)) or {}
    m = dict(_day().get(model) or _m(model))
    tokens = m["tokens_in"] + m["tokens_out"]
    live = m.get("live") or {}
    rem_req = live.get("remaining_requests_day")
    if rem_req is None and lim.get("rpd"):
        rem_req = max(lim["rpd"] - m["requests"], 0)
    provider = model.split(":", 1)[0] if ":" in model else "groq"
    until = m.get("limited_until") or (m.get("exhausted_at", 0) + RETRY_AFTER_S if m.get("exhausted") else None)
    out = exhausted(model)
    state = ("no key" if not has_key(provider) else
             "exhausted" if out and m.get("exhausted") else "rate limited" if out else
             "available" if m.get("ok_at") and (not m.get("checked_at") or m["ok_at"] >= m["checked_at"]) else
             "recovering" if until else "not checked yet")
    iso = lambda t: datetime.fromtimestamp(t, IST).isoformat(timespec="seconds") if t else None  # noqa: E731
    return {"model": model, "provider": provider, "state": state,
            "checked_at": iso(m.get("checked_at")), "ok_at": iso(m.get("ok_at")), "latency_ms": m.get("latency_ms"),
            "back_at": iso(until) if out else None, "back_in_s": max(0, int(until - _now())) if out and until else None,
            "jobs": [j for j, ms in config.ROUTES.items() if model in ms],
            "limits": {k: lim.get(k) for k in ("rpm", "rpd", "tpm", "tpd")},
            "used": {"requests": m["requests"], "tokens_in": m["tokens_in"], "tokens_out": m["tokens_out"],
                     "tokens": tokens, "cache_hits": m["cache_hits"], "rate_limited": m["rate_limited"]},
            "remaining": {"requests": rem_req, "tokens": max(lim["tpd"] - tokens, 0) if lim.get("tpd") else None},
            "live": m.get("live"), "exhausted": exhausted(model), "last_error": m.get("last_error")}


def has_key(provider):
    if provider.startswith("groq"):
        return int(provider[4:] or 1) in config.GROQ_SLOTS
    return bool({"gemini": config.GEMINI_API_KEY, "sarvam": config.SARVAM_API_KEY}.get(provider, True))


def due_for_check():
    """Benched models whose provider-stated recovery time has passed: worth one real 1-token check."""
    with _lock:
        day = dict(_day())
    return [n for n, m in day.items() if (m.get("exhausted") or m.get("limited_until")) and not exhausted(n)
            and any(n in ms for ms in config.ROUTES.values())]


def snapshot():
    with _lock:
        names = set(limits()) | set(_day()) | {m for ms in config.ROUTES.values() for m in ms}
    return {"date": today(), "routes": config.ROUTES, "models": [one(n) for n in sorted(names)],
            "at": datetime.now(IST).isoformat(timespec="seconds")}


# Route order edited from the UI survives restarts.
for _job, _models in _load("routes.json", {}).items():
    if _job in config.ROUTES and _models:
        config.ROUTES[_job] = config.pooled(_models)  # keys added since the save join the route
