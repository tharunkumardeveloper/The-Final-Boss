"""LLM router: each job on its own model, fallback on rate limits, every response cached on disk."""
import hashlib
import json
import os
import threading
import time
from functools import lru_cache

import httpx

from . import config, registry, usage


class Unavailable(Exception):
    """Rate-limited, out of quota, or provider error: try the next model in the route."""


class SchemaFailure(Unavailable):
    """Strict JSON decoding failed on this model."""


@lru_cache
def _groq(slot=1):
    from groq import Groq
    return Groq(api_key=config.GROQ_SLOTS[slot], max_retries=0)  # a 429 moves on to the next key, no waiting


def _split(model):
    slot, name = config.groq_slot(model)
    return ("groq", name) if slot else model.split(":", 1)


def _call(model, messages, schema=None, name=None, max_tokens=None):
    provider, name_ = _split(model)
    t0 = time.perf_counter()
    ms = lambda: round((time.perf_counter() - t0) * 1000)  # noqa: E731
    cap = {"max_tokens": max_tokens} if max_tokens else {}
    fmt = {"response_format": {"type": "json_schema",
                               "json_schema": {"name": name, "strict": True, "schema": schema}}} if schema else {}
    if provider == "groq":
        import groq
        # Low reasoning effort: ~4x fewer completion tokens on gpt-oss, which the free daily token cap needs.
        extra = {"reasoning_effort": "low"} if name_.startswith("openai/gpt-oss") else {}
        slot = config.groq_slot(model)[0]
        if slot not in config.GROQ_SLOTS:
            raise Unavailable(f"{model}: no key in GROQ_API_KEY{'' if slot == 1 else f'_{slot}'}")
        try:
            raw = _groq(slot).chat.completions.with_raw_response.create(model=name_, temperature=0, messages=messages,
                                                                    **fmt, **extra, **cap)
        except (groq.RateLimitError, groq.InternalServerError, groq.APIConnectionError,
                groq.AuthenticationError, groq.PermissionDeniedError) as e:  # a bad or revoked key: the next key
            raise Unavailable(f"{model}: {e}") from e
        except groq.BadRequestError as e:  # strict decoding produced off-schema JSON: another model may manage
            if "json_validate_failed" not in str(e):
                raise
            raise SchemaFailure(f"{model}: {e}") from e
        r = raw.parse()
        u = r.usage
        usage.record(model, u and u.prompt_tokens, u and u.completion_tokens, dict(raw.headers), latency_ms=ms())
        return r.choices[0].message.content
    if provider in ("gemini", "sarvam"):  # both speak the OpenAI chat-completions format
        url, headers = ((config.GEMINI_URL, {"Authorization": f"Bearer {config.GEMINI_API_KEY}"}) if provider == "gemini"
                        else (config.SARVAM_URL, {"api-subscription-key": config.SARVAM_API_KEY or ""}))
        if provider == "sarvam" and not config.SARVAM_API_KEY:
            raise Unavailable(f"{model}: no SARVAM_API_KEY")
        try:
            r = httpx.post(url, timeout=60, headers=headers,
                           json={"model": name_, "temperature": 0, "messages": messages, **fmt, **cap})
        except httpx.HTTPError as e:
            raise Unavailable(f"{model}: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise Unavailable(f"{model}: HTTP {r.status_code} {r.text[:300]}")
        r.raise_for_status()
        body = r.json()
        u = body.get("usage") or {}
        usage.record(model, u.get("prompt_tokens"), u.get("completion_tokens"), latency_ms=ms())
        return body["choices"][0]["message"]["content"]
    raise ValueError(f"unknown provider in {model!r}")


def check(model):
    """A real, tiny request (a few tokens) to see whether a model answers right now. Updates the ledger either way,
    which pushes the new status to every open console."""
    try:
        _call(model, [{"role": "user", "content": "Reply with the single word: ok"}], max_tokens=16)
        return True
    except Unavailable as e:
        usage.record_unavailable(model, str(e))
        return False
    except Exception as e:  # bad key, unknown model: report it, don't crash the checker
        usage.record_unavailable(model, f"{model}: {e}")
        return False


def _cache_path(kind, payload):
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
    return config.CACHE_DIR / kind / f"{h}.json"


def _store(path, out):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    os.replace(tmp, path)


def _routed(kind, candidates, payload_for, call):
    """Return the first cached answer among candidates, else call them in order, falling through on Unavailable."""
    paths = [(m, _cache_path(kind, payload_for(config.same_model(m)))) for m in candidates]  # one cache per model
    for m, p in paths:
        if p.exists():
            usage.record_cache_hit(m)
            return m, json.loads(p.read_text(encoding="utf-8"))
    errors = []
    for attempt in range(2):
        # Skip models already out of quota; if every model looks out, try them anyway (limits may be stale).
        live = [mp for mp in paths if not usage.exhausted(mp[0])] or paths
        for m, p in live:
            try:
                out = call(m)
            except Unavailable as e:
                usage.record_unavailable(m, str(e))
                if isinstance(e, SchemaFailure) and len(paths) == 1:
                    raise e.__cause__  # pinned model (benchmark): keep the provider's own error
                errors.append(str(e))
                continue
            _store(p, out)
            return m, out
        # Every model and key was busy. A per-minute limit clears in seconds: wait for the first one back, once.
        wait = usage.soonest_back([m for m, _ in paths])
        if attempt or wait is None or wait > MAX_WAIT_S:
            break
        time.sleep(wait + 0.5)
    raise Unavailable("all models unavailable: " + " | ".join(errors))


MAX_WAIT_S = 25  # longer than this (a daily cap), fall through to the template reply instead of making them wait


def chat_json(job, system, user, schema, name, model=None):
    """Strict-schema JSON call. `model` pins one model (the benchmark needs that for fairness)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    # Groq models keep their bare name in the cache key, so earlier cached runs stay valid.
    payload = lambda m: {"model": _split(m)[1] if _split(m)[0] == "groq" else m,
                         "system": system, "user": user, "schema": schema}
    m, out = _routed(name, [model] if model else config.ROUTES[job], payload,
                     lambda m: json.loads(_call(m, messages, schema, name)))
    return {**out, "_model": m}


def chat_text(job, system, messages, name, model=None):
    """Free-text call (replies, personas, summaries). `messages` = [{"role", "content"}] without the system turn."""
    msgs = [{"role": "system", "content": system}, *messages]
    m, out = _routed(name, [model] if model else config.ROUTES[job], lambda m: {"model": m, "messages": msgs},
                     lambda m: {"text": _call(m, msgs).strip()})
    return out["text"]


# ---------------------------------------------------------------- extraction

def _extract_schema(reg):
    return {
        "type": "object", "additionalProperties": False, "required": ["facts"],
        "properties": {"facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["about_customer", "subject", "predicate", "attribute", "object", "valid_from", "ended"],
            "properties": {
                "about_customer": {"type": "boolean"},
                "subject": {"type": "string"},
                "predicate": {"type": "string", "enum": [*registry.REGISTRIES[reg], "other", "none"]},
                "attribute": {"type": ["string", "null"]},
                "object": {"type": "string"},
                "valid_from": {"type": ["string", "null"]},
                "ended": {"type": "boolean"},
            }}}},
    }


EXTRACT_SCHEMA = _extract_schema("isp")

EXTRACT_SYSTEM = f"""You turn one message from a fiber internet provider's support conversation into facts.

Allowed predicates (subject -> object):
{registry.describe("isp")}

Rules:
- Extract facts that are true NOW, as of the message date, with ended = false. Past states ("I used to...") are not facts.
- ended = true when the message says something that WAS true is no longer true and gives no replacement value
  ("I no longer live in Chennai", "I moved out of Pune", "I sold my PS5", "the drops have stopped"). Use the old value as
  object; use "" as object if the message does not name it. When the new value is given ("moved from Chennai to Pune"),
  output only the new fact with ended = false: the old one is replaced automatically.
- about_customer = true when the subject is the customer named in the context. First person from the customer counts,
  including "we", "our home", "our family" and "my household". Facts about other people (a sister, a friend, a
  neighbour) have about_customer = false.
- Ticket predicates (has_status, assigned_to, ticket_about, tried_fix) are about the current ticket.
- object: a short lowercase canonical name, e.g. "pune", "fiber 300", "ax3000", "evening wifi drops", "change wifi channel".
  Keep product and model names as written, lowercase with their spaces ("pml hub 6", "smart tv", "desktop pc").
- A device the customer calls theirs ("my PS5", "my laptop", "I bought a PS5") is owns_device, also inside a problem
  report. reported_issue describes the problem itself ("connection drops"), never a device name.
- has_router only for a specific router model name, never the word "router".
- prefers_channel objects are one of: whatsapp, email, phone, sms ("reach me by email" -> email).
- valid_from: ISO date YYYY-MM-DD whenever the message says when it became true, computed from the message date.
  Examples with message date 2026-09-12: "I moved to Pune on the 10th" -> 2026-09-10; "since the 1st" -> 2026-09-01;
  "last week" -> 2026-09-05; "yesterday" -> 2026-09-11. If no time is mentioned, null.
- Plans, buying and moving (keep what is true now apart from what is wanted or planned):
  on_plan only for the plan they HAVE now. Asking about a plan, liking it or comparing = interested_in.
  "I'll buy it / sign me up / I want Fiber 1000" = wants_to_buy (never on_plan). After support asks "which plan
  would you like?", naming a plan ("fiber 300 please", "ok the 300 one") is wants_to_buy too. Spending limit ("under 2000 rupees",
  "around $50") = budget with object like "2000 inr" or "50 usd". Moves: a move that ALREADY
  happened ("I moved to Pune on the 10th", "we relocated to X last week", "I'm in X now") = lives_in X. Only a FUTURE
  move ("planning to move", "will move", "moving next month", "about to shift") = moving_to X (valid_from = the planned
  date if given). People at home = household_size ("4").
  Their current or previous internet company = current_provider.
- Identity: a phone number = phone (digits only, e.g. "9876543210"); "my other number" / "calling from my wife's
  number" = alt_phone; email = email; an account number like "PML-AC12345" = account_id ("pml-ac12345"). When the
  connection was installed = installed_at; home or business/office connection = connection_type ("home" / "business").
  "Call me Tharu" / "my name is Tharun, not Tarun" = preferred_name. "I prefer Hindi" / "can we talk in Tamil" =
  preferred_language ("hindi", "tamil"). "My landlord pays the bill" = billing_contact.
- Add-ons they have: has_addon with the add-on name ("static ip", "mesh extender", "ott bundle"); "I cancelled the
  mesh extender" = has_addon "mesh extender" with ended = true. "I referred my neighbour Rajesh" = referred "rajesh".
  "I spoke to someone last week", "I raised a ticket before", "this is the third time" = previous_contact with when
  ("last week", "before"). Calling about someone else's connection ("my mother's connection, she's Saroja Devi") =
  calling_for "saroja devi".
- Things they want done that need our team = service_request, object one of: service_pause, cancellation_request,
  relocation_same_city, relocation_intercity, plan_upgrade, plan_downgrade, addon_add, addon_removal, billing_dispute,
  invoice_resend, payment_reconciliation, payment_method_change, gst_invoice_request, billing_date_change,
  contact_update, account_access, router_config. (Buying a new connection is wants_to_buy, not a service_request.)
- A problem they report is ALWAYS reported_issue (the problem in a few words, e.g. "evening wifi drops"), even when
  you also extract ticket details below.
- Problem details are about the current ticket: issue_type (one of: outage, line_fault, hardware_power,
  device_or_line_fault, speed_degradation, congestion, wifi_signal_weak, wifi_drops, connectivity_auth,
  connectivity_capacity, streaming_lag, router_rebooting, app_bug, account_access); when it started =
  issue_started ("today", "yesterday", "3 days ago"); how often = frequency ("constant", "every evening",
  "every few minutes"); whole home vs one device = severity ("whole_home" / "single_device"); which devices =
  affected_device; error text = error_message; router light colours = router_lights ("red internet light",
  "no lights"); a measured speed = speed_reported ("40 mbps"); wifi only or also on cable = connection_medium
  ("wifi" / "wired" / "both"); how many people affected = affected_users; near or far from the router =
  distance_from_router ("near" / "far"); what they already tried = tried_fix ("restart router").
- An address or place they give, even on its own as an answer ("175 North State Street, Chicago, IL 60601",
  "flat 4, HSR Layout") = address with the full street address as written (lowercase) AND lives_in with the area
  or city ("chicago", "hsr layout"), unless they say it is somewhere else (an office, a relative's home, a new home).
- Who they are and why they came: their job or role ("I'm a police officer", "I run a cafe") = occupation
  ("police officer", "cafe owner"). Why they are here ("I'm here for an investigation", "looking for a new connection")
  = visit_reason ("investigation", "new connection"). EVERY question they ask = asked_about with a short topic
  ("cities served", "number of customers in coimbatore", "services offered", "installation time"), also when the
  question reveals another fact. Something they want us to do ("send the data to our HQ", "call me tomorrow",
  "cancel my plan") = requested, with a short description that keeps the destination or details
  ("send customer data to police hq, mg road, coimbatore").
- Anything else concrete and lasting about the customer that support could use later ("works from home", "has two
  kids", "streams on Twitch", "home has thick walls", "is a student") = predicate "other", attribute = a short
  snake_case name ("works_from_home", "children", "streams_on", "wall_type", "occupation"), object = the value.
  For every other predicate, attribute = null.
- Games they play ("i play GTA 5", "mostly valorant on my ps5") = plays_game ("gta 5", "valorant"), plus owns_device
  for the console. Shows, movies or platforms they watch ("we binge on netflix", "watching the boys") = watches
  ("netflix", "the boys"). Something they want from us that we may not offer ("any free games with the plan?", "a game
  for my console") = requested ("free game for their console") AND asked_about ("game offers").
- A bare topic that answers support's question ("gaming" after "which service interests you most?") = interested_in
  that topic ("gaming").
- A question can still reveal a fact about the customer: "what plans do you have for 2000 rupees?" = budget "2000 inr";
  "is Fiber 300 good for gaming?" = interested_in fiber 300. Greetings, thanks and filler ("ummm", "what", "ok cool",
  "who are you") contain no facts: return an empty list. "what are the services you offer?" is not filler: asked_about
  "services offered"."""

LIFE_SYSTEM = f"""You turn one message from a casual conversation between friends into facts about the people in it.

Allowed predicates (subject -> object):
{registry.describe("life")}

Rules:
- The "customer" in the context is the person who wrote the message. about_customer = true for facts about them
  (first person counts); facts about anyone else have about_customer = false and subject = that person's name.
- Extract lasting facts (where they live, work, study, family, pets, hobbies, likes, plans) and notable events
  (visited a place, attended an event). Skip opinions about the conversation and small talk.
- object: a short lowercase canonical phrase, e.g. "adoption agency", "pottery", "sweden", "lgbtq support group".
- valid_from: ISO date YYYY-MM-DD only if the message says when it happened or became true ("yesterday",
  "last week", "in 2022"), computed from the message date. Otherwise null.
- ended = true only when the message says a fact stopped being true without giving a new value; otherwise false.
- attribute = null unless predicate is "other" (then a short snake_case name for what the fact is about).
- If nothing fits, return an empty list."""

_EXTRACT = {"isp": (EXTRACT_SYSTEM, EXTRACT_SCHEMA), "life": (LIFE_SYSTEM, _extract_schema("life"))}


PROMPT_VERSION = {k: hashlib.sha1(v[0].encode()).hexdigest()[:10] for k, v in {
    "isp": (EXTRACT_SYSTEM,), "life": (LIFE_SYSTEM,)}.items()}
_last = threading.local()


def last_extraction():
    """(model, prompt version) of this thread's most recent extraction call."""
    return getattr(_last, "x", (None, None))


def extract(text, *, customer, ticket, date, speaker, registry="isp", asked=None):
    system, schema = _EXTRACT[registry]
    user = (f"Context: customer = {customer}; current ticket = {ticket or 'none'}; "
            f"message date = {date}; speaker = {speaker}."
            + (f"\nSupport just asked: {asked}\n(If the message answers that question, a bare place, plan or model "
               f"name is the answer to it. If it doesn't answer it, ignore the question.)" if asked else "")
            + f"\nMessage: {text}")
    out = chat_json("extract", system, user, schema, "extract")
    _last.x = (out.get("_model"), PROMPT_VERSION[registry])
    return out["facts"]


# ---------------------------------------------------------------- answering

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["answer", "values", "cited_ids", "conflict", "unknown"],
    "properties": {
        "answer": {"type": "string"},
        "values": {"type": "array", "items": {"type": "string"}},
        "cited_ids": {"type": "array", "items": {"type": "string"}},
        "conflict": {"type": "boolean"},
        "unknown": {"type": "boolean"},
    },
}

ANSWER_SYSTEM = """You answer questions for a support team using ONLY the memory lines provided. Never use outside knowledge.

Each line starts with an [id]. Rules:
- If a line is marked SUPERSEDED, it is history: use it only for questions about the past (dates use valid/on-file ranges).
- "true from A to B" is when it was true in the world; "on file from A to B" is when the team's records said so.
- If lines carry dates and no status, newer information overrides older information.
- Cite every line you used in cited_ids, including each step of a multi-hop chain. Cite only ids that appear in the lines.
- If two current lines give different values for the same single-valued fact (marked CONFLICT), set conflict = true,
  answer with the PREFERRED one and mention the other.
- values: the bare answer value(s) as written in memory, lowercase (e.g. ["pune"]). For lists, include every item.
- If the memory does not contain the answer, set unknown = true, values = [], cited_ids = []."""


def answer(question, lines, model=None):
    user = "Memory:\n" + ("\n".join(lines) if lines else "(empty)") + f"\n\nQuestion: {question}"
    return chat_json("answer", ANSWER_SYSTEM, user, ANSWER_SCHEMA, "answer", model=model)
