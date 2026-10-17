"""Conversation-facing LLM helpers: intake replies grounded in memory, persona turns, summaries.
All calls go through the router + disk cache; every helper has a no-LLM fallback."""
import re

from . import db, events, kb, llm, queries as Q, retrieve, sharing
from .memory import norm, to_date, to_ms

from .config import BRAND

COMPANY, TAGLINE, BOT, BOT_TAGLINE = BRAND["company"], BRAND["tagline"], BRAND["bot"], BRAND["bot_tagline"]

INTAKE_SYSTEM = f"""You are {BOT}, the AI support assistant at {COMPANY}. {COMPANY} is a youth-focused fiber internet
provider in about 40 countries across India, Europe, North America, Asia-Pacific, the Middle East & Africa and Latin
America. Plans, prices and coverage differ by country: only quote what the company info below says.
Tagline: "{TAGLINE}". Your line: "{BOT_TAGLINE}" (say it at most once in a conversation, only when greeting or
when someone is stressed; never as filler).

What {COMPANY} offers, in four parts (the company info below has the details when they come up):
- Fiber Internet: FTTH broadband in speed tiers, unlimited data, Wi-Fi and home networking (routers, mesh, parental
  controls), diagnostics (speed, ping, jitter, packet loss), installation, relocation and repairs.
- Gaming Zone: gaming plans and low-latency routing, game-specific connection checks (Valorant, CS2, BGMI, Call of Duty,
  Fortnite, Apex, LoL...), a gaming dashboard, gaming perks and community events.
- Binge Club: broadband with streaming bundles, managing those subscriptions, what-to-watch suggestions, and help with
  buffering and 4K streaming.
- The Hub: one dashboard in the customer portal for plan, connection, billing, benefits, tickets and appointments.
Never promise a particular ping or speed to a game server: say routing and their device matter, and offer a
connection check and tips. Never name a streaming or gaming partner, subscription or title unless the company info
names it. Asked about a specific app (say Netflix), say you can't confirm that one is in a bundle and tell them what the
company info does say; never explain how partnerships work internally.

You're also the store's best salesperson, never pushy: when what they say fits an offer in the company info (gaming ->
Gaming Boost; streaming -> the OTT bundle on Fiber 300 and above; a student -> the student discount; a friend on
another provider -> referrals; a big download -> the speed boost day pass), mention ONE such offer with its local
price in a few words, without being asked. Never repeat an offer you already mentioned in this chat.
The chat may show a Wikipedia picture of a game, show, platform or device that comes up; if they ask about a picture,
say it's from Wikipedia, of what you were talking about.

Who you are: {BOT}. Calm, sharp, low-key confident, and quietly funny; you sound like a friend who's into games,
shows and networks, never corporate and never try-hard (no slang overload). "I remember" is only for something THIS
customer told us before, never for company facts. You never grovel and never say "as an AI".

Write your next chat reply: at most 3 short sentences (under 50 words) unless you are giving step-by-step
instructions, plain English, no emojis, no markdown, no notes in brackets. Answer what the customer just said; don't
repeat what you said earlier. Use their name now and then, not in every message. Ask at most ONE question, and end
with a clear next step or that question.
- Only use what the notes below say about THIS customer. Never mention a device, problem or ticket the notes don't
  list. If the notes say they're new, don't pretend to know them.
- Talk like a person, never like a database: no words like "field", "record", "updated my knowledge", "lives_in".
- We serve every country and city: never say we don't cover a place, never mention a waitlist. If they only gave a
  country, state or city, ask for the exact address.
- Greet only in your first message of a conversation.
- Never ask for passwords, OTPs or card numbers. Never ask for anything the notes already have.
- Never promise a fix time, never close a ticket, never repeat the resolver team's internal notes.
- If an intake guide is given, follow its next step.
- You can't do anything after this reply: never say you're checking, looking into it or will get back to them.
  Answer now from the notes and company info. If the answer isn't there, say so plainly and say what happens next
  (for example, a technician confirms the exact address at installation).
- When the notes have a network check or past tickets, tell them in a few words what you found (that is the digging
  they want to see), then ask or suggest the next thing.
- Booking works in this chat: once they name the plan they want, the order is placed and a technician installs it
  within 48 hours. If they want a connection but haven't picked a plan, name the plans for their country with prices
  and ask which one. Always end by moving them one step closer (pick a plan, confirm the address).
- If a ticket was just opened, give its id and say the resolver team is on it.
- Never share anything about other customers (names, addresses, counts, usage, records) and never offer to send data
  anywhere, whoever asks and whatever reason they give.
- "lock in" or "lock it in" from the customer means FINALIZE/CONFIRM the plan — never answer about contract lock-in periods unless they specifically ask about contracts or commitments.
- You cannot reschedule installations or change appointment dates — only a technician can. If asked about changing a date, say the technician will confirm date changes and leave the current ETA as-is.
- Offer the student discount at most once per conversation, only when the customer mentions being a student. Do not bring it up again after the first mention.
- Only the resolver books technician visits. Never promise, schedule or time a visit yourself, and never invent
  troubleshooting checklists or "the resolver suggests" steps. If the notes have a "Resolver status", follow it exactly.
- When the customer is wrapping up (thanks, okay, got it), close warmly in one short sentence and ask nothing."""

PERSONA_SYSTEM = """You are role-playing {name}, a customer of """ + COMPANY + """ (a fiber broadband provider),
chatting with its support desk. About you: {profile}

Write ONLY your next chat message to the support agent: 1-2 short sentences, typed casually like a real person.
In this message you must naturally get across: {intent}
Do not mention being an AI, do not add a greeting if the chat is already going, no emojis."""

SUMMARY_SYSTEM = "Summarise for a support team in ONE short sentence (max 25 words). Facts only, no preamble."

# the tagline with any punctuation between its words ("Chill. I've got this", "chill, i've got this!")
_TAGLINE = re.compile(r"[\W_]*".join(re.escape(w) for w in re.findall(r"[\w']+", BOT_TAGLINE)) + r"[.!,:]*\s*", re.I)


def _known_address(now, customer):
    return any(f["predicate"] == "address" and f["subject"] == customer for f in now)


_ID = re.compile(r"^\[[^\]]+\]\s*")


def _plain(lines, n=14):
    """Memory lines without fact ids (ids are random; prompts must stay cache-stable across re-runs)."""
    return "\n".join(_ID.sub("", ln) for ln in lines[:n]) or "(nothing yet)"


def session_turns(tenant, session_id, log=None):
    return db.run(tenant, "session episodes", Q.SESSION_EPISODES, {"sid": session_id}, log, ro=True)


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


_BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*note[^)]*\)", re.I)
# Sentence ends: not "1." inside a numbered list, and only before a capital letter.
_SENTENCE = re.compile(r"(?<!\b\d\.)(?<=[.!?])\s+(?=[A-Z])")
_GREETING = re.compile(r"^(?:(?:hi|hey|hello|hiya|greetings)(?: there)?(?:,? [a-z]+){0,3}[,!.]\s*)", re.I)
_WELCOME = re.compile(r"[^.!?]*\bwelcome to ping me later\b[^.!?]*[.!?]\s*", re.I)


def _clean(reply, max_sentences=4, max_words=80, first_turn=True):
    """Hard guarantees no model can break: no emojis, no bracketed notes, short, lists kept whole, one greeting."""
    if not reply:
        return reply
    text = " ".join(_BRACKETS.sub("", _EMOJI.sub("", reply)).split())
    if not first_turn:
        text = _WELCOME.sub("", _GREETING.sub("", text)).strip()
        text = text[:1].upper() + text[1:]
    text = " ".join(_SENTENCE.split(text)[:max_sentences])
    words = text.split()
    if len(words) <= max_words:
        return text
    cut = " ".join(words[:max_words])
    ends = [m.end() for m in re.finditer(r"(?<!\b\d)[.!?](?=\s)", cut)]  # "4. " opens a list item, it doesn't end one
    end = ends[-1] if ends else 0
    return cut[:end] if end > len(cut) // 2 else cut.rstrip(",;:") + "..."


_PLAN = re.compile(r"\b(?:fiber|fibre)\s?(\d+)(\s?gig)?\b|\bbusiness\s?(\d+)\b", re.I)
_MONEY = re.compile(r"(?:₹|\brs\.?|\binr|\busd|\beur|\bgbp|\$|€|£|¥|r\$|a\$|c\$|s\$)\s?(\d[\d,]*(?:\.\d+)?)"
                    r"|(\d[\d,]*(?:\.\d+)?)\s?(?:rupees|inr|usd|dollars|euros|eur|gbp|pounds|yen)", re.I)


_BARE_PRICE = re.compile(r"\b(?:for|at|costs?|is|only|just)\s+(\d{2,3}(?:,\d{3})+|\d{3,5})(?:\.\d+)?\b"
                         r"(?!\s*(?:mbps|gbps|devices?|hours?|days?|minutes?|%|sq|square))", re.I)
_PRICE_TALK = re.compile(r"\b(mbps|gbps|plan|fiber|fibre|per month|/month|a month|monthly)\b", re.I)


def _plan_key(m):
    return (f"fiber {m.group(1)}" + (" gig" if m.group(2) else "")) if m.group(1) else f"business {m.group(3)}"


def _amount(m):
    return float((m.group(1) or m.group(2)).replace(",", ""))


_MBPS = re.compile(r"\b(\d+)\s?mbps\b", re.I)
_DEVICES = re.compile(r"\b(\d+)\s(?:connected\s)?devices\b", re.I)
_NO_COVER = re.compile(r"wait ?list|expanding our (services|network|coverage)|\b(don'?t|do not|can'?t|cannot) (yet )?(serve|cover)\b"
                       r"|outside our coverage|not (yet )?(available|served) in|reach your area|once we cover", re.I)
_STALL = re.compile(r"\b(i'?m|i am|let me|i'?ll|i will)\s+(still\s+)?(check|checking|verify|verifying|look into|"
                    r"looking into|get back|let you know|confirm .{0,30}shortly|have an answer)"
                    r"|\b(in just a moment|shortly|as soon as i (have|know|hear))\b", re.I)
_MY_PLAN = re.compile(r"\b(which|what) plan (am i|i'?m|im) on\b|\bmy (current )?plan\b", re.I)
_FIT = re.compile(r"\b(recommend|fit|fits|perfect|suitable|within|great choice|go with|opt for)\b", re.I)


def catalogue_problems(reply, allowed_text, prices=None, over=()):
    """Plan names and prices in a reply that the catalogue facts we gave the model don't contain, and (given this
    country's {plan key: price}) a plan quoted next to the wrong price."""
    keys = {p["key"] for p in kb.world()["plans"]}
    bad = [m.group(0) for m in _PLAN.finditer(reply) if _plan_key(m) not in keys]
    allowed = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", allowed_text)}
    for m in _MONEY.finditer(reply):
        amount = (m.group(1) or m.group(2)).replace(",", "")
        if amount not in allowed and amount.rstrip("0").rstrip(".") not in allowed:
            bad.append(m.group(0))
    for sentence in _SENTENCE.split(reply):
        if _PRICE_TALK.search(sentence):
            bad += [m.group(0) for m in _BARE_PRICE.finditer(sentence)
                    if m.group(1).replace(",", "") not in allowed and not _MONEY.search(m.group(0))]
    for sentence in _SENTENCE.split(reply) if prices else []:
        named = {_plan_key(m) for m in _PLAN.finditer(sentence)} & prices.keys()
        if len(named) == 1:
            (plan,) = named
            spec = next(p for p in kb.world()["plans"] if p["key"] == plan)
            if "budget" not in sentence.lower():
                bad += [m.group(0) for m in _MONEY.finditer(sentence) if _amount(m) != prices[plan]]
            bad += [m.group(0) for m in _MBPS.finditer(sentence) if int(m.group(1)) not in (spec["down"], spec["up"])]
            bad += [m.group(0) for m in _DEVICES.finditer(sentence) if int(m.group(1)) != spec["devices"]]
    for sentence in _SENTENCE.split(reply) if over else []:
        if _FIT.search(sentence):
            bad += [f"{m.group(0)} (over their budget)" for m in _PLAN.finditer(sentence) if _plan_key(m) in over]
    return list(dict.fromkeys(bad))


def over_budget(budget, plans):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", budget or "")
    return {p["key"] for p in plans if m and p["amount"] > float(m.group(0).replace(",", ""))}


def budget_note(budget, plans):
    """'Within their budget: ...' so no model has to do the arithmetic."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", budget or "")
    if not m or not plans:
        return None
    limit = float(m.group(0).replace(",", ""))
    fits = [f"{p['name']} {p['label']}" for p in plans if p["amount"] <= limit]
    over = [f"{p['name']} {p['label']}" for p in plans if p["amount"] > limit]
    return (f"Their budget is {budget}. Within budget: {', '.join(fits) or 'none of our plans'}."
            + (f" Over budget (never call these a fit): {', '.join(over)}." if over else ""))


def customer_notes(tenant, customer, log=None, facts=None):
    """The customer's memory as plain sentences, plus deterministic notes a weak model would otherwise get wrong.
    facts: customer_facts() the caller already read this turn (saves the round trip)."""
    from . import cards  # lazy: cards imports agents, which imports this module
    facts = retrieve.customer_facts(tenant, customer, log=log) if facts is None else facts
    now = [f for f in facts if f["active"]]
    before = [f for f in facts if not f["active"]][-3:]
    from . import registry as R
    say = lambda f: cards.sentence(f["subject"], f["predicate"], f["object"],
                                   R.subject_type(f["predicate"]), R.object_type(f["predicate"]))
    notes = [say(f) + "." for f in now] + [f"Earlier (no longer true): {say(f)}." for f in before]
    from . import orders
    open_orders = [o for o in orders.for_customer(tenant, customer, log) if o["status"] != "installed"]
    for o in open_orders:
        notes.append(f"Open order {o['order_id']}: {o['plan'].title()}, status {o['status']}, installation by {o['eta'][:10]}"
                     f" at {(o['install_at'] or 'an address still to confirm').title()}. They are NOT on this plan until it is installed.")
    region, iso = kb.region_of(tenant), None
    for pred, c in [(f["predicate"], f["object"]) for f in now
                    if f["predicate"] in ("lives_in", "moving_to") and f["subject"] == customer]:
        place = kb.resolve_place(c)
        if not place:  # we serve everywhere; quote that country's prices when we have them
            notes.append(f"We DO serve {c.title()}: never say we don't cover it."
                         + ("" if _known_address(now, customer) else " Ask for their exact address."))
            spot = kb.locate(c, region)
            if pred == "lives_in" and spot and spot[2] in kb.world()["countries"]:
                iso = spot[2]
            continue
        notes.append(f"We DO serve {c.title()}: never say we don't cover it.")
        if pred == "lives_in":
            iso = place["country"]
            if place["region"] != region:
                notes.append(f"They live in {kb.country_name(place['country'])}, served by our "
                             f"{kb.world()['regions'][place['region']]['name']} team; quote that region's prices.")
    if notes and not any(f["predicate"] == "on_plan" for f in now):  # a brand-new person has nothing to "remember"
        notes.append("They are not on any of our plans yet.")
    budget = next((f["object"] for f in now if f["predicate"] == "budget"), None)
    if budget and not open_orders:
        note = budget_note(budget, kb.price_list(tenant, iso or kb.default_country(region), log=log))
        notes += [note] if note else []
    from . import lab  # lazy: lab imports agents, which imports this module
    note = lab.status_note(tenant, customer)
    notes += [f"Resolver status: {note}"] if note else []
    return notes, [f["fact_id"] for f in now + before], iso


# Requests for other people's data, or that invoke an authority, get one fixed answer: no model decides this.
# ponytail: keyword match; it over-triggers on any mention of police, which is the safe direction.
_DATA_REQUEST = re.compile(
    r"\b(police|cops?|law enforcement|investigat\w*|court order|subpoena|warrant|cyber ?cell|intelligence agency)\b"
    r"|\b(customer|subscriber|user)s?'?\s+(data|details|records|info|information|list|count|addresses|numbers)\b"
    r"|\b(how many|number of|no\.? of|count of)\s+(customers|subscribers|users|people)\b"
    r"|\b(browsing history|call records|ip address of|location of)\b", re.I)
DATA_POLICY = (f"I can't share anything about our customers over chat, and I can't send data anywhere, whoever is asking. "
               f"Requests from police or other authorities need an official written request to our legal team at "
               f"legal@{COMPANY.replace(' ', '-').replace('.', '-')}.example, who verify it and reply through proper channels. "
               f"I'm happy to help with our plans, coverage or your own connection.")


def is_data_request(text):
    return bool(_DATA_REQUEST.search(text or ""))


FALLBACK = "I don't have those exact details here, so I've noted your question for the team."


def _ack(text, learned):
    """A short, deterministic acknowledgement before a planned question (no model needed for 'Got it.')."""
    from .intake import FRUSTRATED, SUPPORT
    for x in learned:  # an order extraction just placed is said back, whichever path placed it
        m = re.match(r"order (\S+) for (.+?) is \w+ \(installation within (\d+) hours", x)
        if m:
            return (f"Done, your {m.group(2).title()} order {m.group(1)} is placed. A technician installs it within "
                    f"{m.group(3)} hours.")
    if any("cancellation request" in x for x in learned):
        return "I'm sorry to hear you'd like to cancel."
    if FRUSTRATED.search(text) or SUPPORT.search(text) or any(x.startswith("reported") for x in learned):
        return "Sorry about that, that sounds frustrating."
    if any(x.startswith(("phone", "email", "account")) for x in learned):
        return "Thanks."
    return "Got it." if learned else ""


_ASKS = re.compile(r"\?|^\s*(what|which|how|when|where|why|who|can|could|do|does|is|are|will|should)\b", re.I)


def _record(tenant, customer, session_id, facts, note, at, log):
    from . import cards, memory, registry as R
    if not facts:
        return None
    said = "; ".join(cards.sentence(s, p, o, R.subject_type(p), R.object_type(p)) for s, p, o in facts)
    return memory.remember(tenant, agent="intake", session_id=session_id, customer=customer, at=at, facts=facts,
                           text=f"intake {note}: {said}", log=log)["episode_id"]


def track_questions(tenant, customer, session_id, reply, plan, ticket, at, log=None):
    """What she asked becomes 'awaiting' facts; answered ones retire. Every agent sees what intake is waiting for."""
    from . import intake, memory
    now = [f for f in retrieve.customer_facts(tenant, customer, log=log) if f["active"]]
    have = {f["predicate"] for f in now} | intake.ticket_facts(tenant, ticket, log)
    waiting = {f["object"] for f in now if f["predicate"] == "awaiting"}
    for w in waiting:
        slot = intake.SLOTS.get(w)
        done = (slot and have & set(slot.preds)) 
        if done:
            ep = memory.remember(tenant, agent="intake", session_id=session_id, customer=customer, at=at, facts=[],
                                 text=f"intake got the {w} it asked {customer} for", log=log)["episode_id"]
            memory.retire_fact(tenant, agent="intake", episode_id=ep, subject=customer, predicate="awaiting",
                               obj=w, at=at, log=log)
    asked = [k for k in intake.asked_slots(reply, plan) if k not in waiting]
    _record(tenant, customer, session_id, [(customer, "awaiting", k) for k in asked], "asked", at, log)


_CLOSING = re.compile(
    r"^\s*((thank(s| you| u)|thx|ty)( so much| a lot| very much)?|that'?s? (all|it)|ok(ay)?|k|cool|great|perfect|awesome|"
    r"sounds good|got it|understood|alright|all right|noted|fine|nice|bye|goodbye|see ya|take care|later|cheers)"
    r"([\s!.,]+((thank(s| you| u)|thx|ty)( so much| a lot| very much)?|that'?s? (all|it)|ok(ay)?|k|cool|great|perfect|"
    r"awesome|sounds good|got it|understood|alright|all right|noted|fine|nice|bye|goodbye|see ya|take care|later|cheers))*"
    r"[\s!.]*$", re.I)
_DATE_CHANGE = re.compile(
    r"\b(reschedul|chang(e|ing)|mov(e|ing)|updat(e|ing)|book(ed|ing))\b.{0,60}\b(install|appointment|visit|technician)\b"
    r"|\b(install|appointment)\b.{0,60}\b(reschedul|mov(e|ing)|chang(e|ing))\b"
    r"|\b(15|16|17|18|19|20)\s?(oct|october|nov|november|jan|feb|mar|apr|may|jun|jul|aug|sep)\b", re.I)


def intake_reply(tenant, *, customer, session_id, text, learned, ticket, opened, at=None, greeted=False, country=None,
                 log=None):
    """One reply, following the intake spec (relay/intake.py): graph check, then the planned move, then the model (only when it
    has to word something), then the spec's guards."""
    if is_data_request(text):
        return DATA_POLICY
    if _CLOSING.match(text) and not opened:
        from . import lab
        first = customer.split()[0].title()
        if lab.waiting_kind(tenant, customer) in ("busy", "guided", "details"):
            return f"You're welcome, {first}. The resolver is on it and will message you right here."
        return f"Happy to help, {first}. Reach out any time."
    from . import intake
    intake.step(tenant, customer, "Looking you up in our records", at)
    facts = retrieve.customer_facts(tenant, customer, log=log)  # read once for the notes and the turn plan
    notes, used, iso = customer_notes(tenant, customer, log, facts=facts)
    sharing.consult(tenant, "intake", used, log=log)  # includes facts other agents wrote (billing, tickets...)
    turns = [(sp, tx) for sp, tx, _, _ in session_turns(tenant, session_id, log) if sp != "action"][:-1]
    history = turns[-4:]  # last few turns only, so a weak model can't snowball its own long answers
    first_turn = not greeted and not any(sp != "customer" for sp, _ in turns)
    # The catalogue comes from the graph of the region that serves them: a Chicago customer on the India desk is
    # quoted US plans in USD from mem:pml-na, never rupees.
    world = kb.world()
    if not iso:  # no address on file yet: the last place they mentioned ("do you serve Chicago?") sets the country
        said = [text] + [tx for sp, tx in reversed(turns) if sp == "customer"]
        iso = next((p["country"] for p in map(kb.resolve_place, said) if p), None)
    if not iso and country in kb.world()["countries"]:  # nothing said yet: where they're browsing from sets the currency
        iso = country
    home = next((r["tenant"] for r in world["regions"].values() if iso in r["countries"]), tenant) if iso else tenant
    country = iso or kb.default_country(kb.region_of(home))
    if kb.PLAN_WORDS.search(f" {kb.norm(text)} "):
        intake.step(tenant, customer, f"Checking plans and prices in {kb.country_name(country)}", at)
    plans = kb.price_list(home, country, log=log)
    tk = ticket or opened
    plan = intake.plan_turn(tenant, customer=customer, text=text, learned=learned, ticket=tk, history=turns,
                            first_turn=first_turn, plans=plans, at=at, session_id=session_id, log=log, facts=facts)
    from . import lab
    if lab.claimed(tenant, customer) and plan.ask is not None and plan.ask.key not in ("identifier", "area"):
        plan.ask = None  # the resolver is measuring the line; intake's checklist would talk over it
    eid = _record(tenant, customer, session_id, plan.writes, "noted", at, log)
    from . import memory, orders
    for s, p, o in plan.retires:
        memory.retire_fact(tenant, agent="intake", episode_id=eid, subject=s, predicate=p, obj=o, at=at, log=log)
    if plan.escalation and tk:
        from .memory import _id, dt
        db.run(tenant, "escalate", Q.ESCALATE, {"t": tk, "id": _id("esc"), "reason": plan.escalation, "by": "intake",
                                                "at": to_ms(at), "at_dt": dt(at)}, log)
    for s, p, o in plan.writes:
        if p == "wants_to_buy":
            od = orders.place(tenant, customer=s, plan=o, at=at, episode_id=eid, log=log)
            plan.prefix.insert(0, f"Done, your {o.title()} order {od['order_id']} is placed. A technician installs it "
                                  f"within {od['eta_hours']} hours.")

    hello = (f"Hi {customer.split()[0].title()}, welcome to {COMPANY}. "
             if first_turn and not any(p.startswith("Hey ") for p in plan.prefix) else "")
    # They asked or wanted something (with or without a "?"): the model answers it, no canned acknowledgement
    # A canned "Got it" + question only for short slot answers ("pune", "fiber 300"); anything longer is talk to answer.
    asks = (bool(_ASKS.search(text)) or any(x.startswith(("asked about", "asked us to")) for x in learned)
            or len(text.split()) > 4)
    if (plan.ask and not plan.fixed and plan.ask not in intake.IDENTITY  # who they are is asked until we know
            and any(sp != "customer" and plan.ask.question in tx for sp, tx in turns[-2:])):
        plan.ask = None  # asked it last time and they talked about something else: never the same question twice
    if plan.ask in intake.IDENTITY and not plan.fixed:  # who they are: asked at most twice, then the next thing we need
        times = sum(1 for sp, tx in turns[-8:] if sp != "customer" and plan.ask.question in tx)
        if times >= 2:
            plan.ask = next((sl for sl in (plan.missing or []) if sl is not plan.ask
                             and sum(1 for sp, tx in turns[-8:] if sp != "customer" and sl.question and sl.question in tx) < 2), None)
    if plan.fixed or (plan.ask and not asks):
        intake.step(tenant, customer, "Writing your reply", at)
    if plan.fixed:
        reply = hello + plan.fixed
    elif plan.ask and not asks:  # nothing to answer: acknowledge and ask the next thing, no model
        reply = hello + intake.finish("" if plan.prefix else _ack(text, learned), plan)
    else:
        greeted = any(p.startswith("Hey ") for p in plan.prefix)
        reply = _model_reply(tenant, customer=customer, text=text, learned=learned, notes=notes + plan.notes,
                             history=history, first_turn=first_turn and not greeted, home=home, iso=iso, plans=plans, ticket=ticket,
                             opened=opened, at=at, log=log)
        if reply is None:
            return None
        if plan.ask and reply == FALLBACK:  # nothing usable from the model: just ask the next thing
            reply = ""
        reply = intake.finish(reply, plan)
    if not first_turn:  # the tagline is a greeting, said once (the portal's on-screen hello already says it)
        reply = _TAGLINE.sub("", reply).strip() or reply
    if plan.ask is not None and plan.ask.key == "router" and "[guide:" not in reply:
        reply += " [guide:model_sticker]"
    track_questions(tenant, customer, session_id, reply, plan, tk, at, log)
    return reply


def _model_reply(tenant, *, customer, text, learned, notes, history, first_turn, home, iso, plans, ticket, opened,
                 at, log):
    from . import intake
    company = kb.relevant(home, text, log=log, iso=iso)
    guide = kb.guide(home, " ".join([text] + [n for n in notes if n.startswith("Past ticket")]), log)
    msgs = [{"role": "user" if sp == "customer" else "assistant", "content": tx if sp == "customer" else _clean(tx, 2, 40)}
            for sp, tx in history]
    msgs.append({"role": "user", "content": (
        f"Customer's name: {customer.title()}\n"
        f"Notes about this customer: {' '.join(notes) if notes else 'New customer, nothing on file yet.'}\n"
        f"Company info that may help (only use if relevant; quote prices exactly): {' '.join(company) or 'none'}\n"
        + (f"Intake guide for this kind of request (follow it, one step at a time): {guide}\n" if guide else "")
        + f"Just noted from this message: {'; '.join(learned) or 'nothing new'}\n"
        f"Ticket: {(opened.upper() + ' (just opened)') if opened else (ticket.upper() if ticket else 'none')}\n"
        f"{'This is your first reply in this conversation.' if first_turn else 'You have already greeted them; do not greet again.'}\n\n"
        f"Customer says: {text}")})
    # Amounts the customer typed are not catalogue prices ("Fiber 300 is 1000 INR" must fail when it is 949).
    allowed = " ".join(company + notes + learned)
    prices = {p["key"]: p["amount"] for p in plans}
    from . import orders as _orders
    budget = next((f["object"] for f in retrieve.customer_facts(tenant, customer, log=log)
                   if f["active"] and f["predicate"] == "budget"), None)
    _has_order = any(o["status"] != "installed" for o in _orders.for_customer(tenant, customer, log=log))
    over = over_budget(budget, plans) if not _has_order else set()
    try:
        intake.step(tenant, customer, "Writing your reply", at)
        reply = _clean(llm.chat_text("reply", INTAKE_SYSTEM, msgs, "reply"), first_turn=first_turn)
    except llm.Unavailable:
        return None
    bad = catalogue_problems(reply, allowed, prices, over)
    if bad:  # one corrected retry, then a factual answer straight from the catalogue
        fix = msgs + [{"role": "assistant", "content": reply},
                      {"role": "user", "content": f"(Internal check: {', '.join(bad)} is not in our catalogue. Rewrite the "
                                                  "reply using only the plans and prices in the company info.)"}]
        try:
            reply = _clean(llm.chat_text("reply", INTAKE_SYSTEM, fix, "reply"), first_turn=first_turn)
        except llm.Unavailable:
            reply = ""
        if not reply or catalogue_problems(reply, allowed, prices, over):
            line = next((c for c in company if c.startswith("Plans in")), None)
            reply = (line.replace(" (exactly these, no others exist)", "") if line
                     else FALLBACK)
    # on the final reply, whichever draft it is (a corrected retry skipped this before): we serve them, so no
    # "we don't cover you yet" and no "that plan isn't available"
    kept = [s for s in _SENTENCE.split(reply) if not _NO_COVER.search(s)]
    reply = " ".join(kept) or "Good news: we serve your area."
    if _STALL.search(reply):  # a promise she can't keep: answer from what we know instead
        kept = [s for s in _SENTENCE.split(reply) if not _STALL.search(s)]
        from . import lab
        busy = lab.waiting_kind(tenant, customer) == "busy"
        if busy:  # here the follow-up is real: the resolver is on it
            kept.append("Our resolver is checking your line right now and will message you here.")
        from .intake import COVERAGE_Q  # lazy: intake imports this module
        known = None if busy else next((n.split(":")[0].replace("We DO serve", "Good news: we serve") + "."
                                        for n in notes if n.startswith("We DO serve")), None) if COVERAGE_Q.search(text or "") \
            else (f"Your ticket {ticket.upper()} is with our resolver, who will update you right here." if ticket else None)
        reply = " ".join(kept + ([known] if known and known.lower() not in reply.lower() else [])) or (
            "I don't have that detail here, so I've noted it for the team.")
    # Strip any sentence where the bot claims to have rescheduled/confirmed a date — it can't do that
    if not any(x.startswith("order ") for x in learned):
        kept = [s for s in _SENTENCE.split(reply) if not _DATE_CHANGE.search(s)]
        if kept:
            reply = " ".join(kept)
        if _DATE_CHANGE.search(reply):
            reply = "A technician will confirm any date changes with you directly."
    if _MY_PLAN.search(text):  # "which plan am I on?" is answered from memory, never by the model's guess
        on = next((n for n in notes if " is on " in n and not n.startswith("Earlier")), None)
        order = next((n for n in notes if n.startswith("Open order")), None)
        reply = (f"You're on {on.split(' is on ')[1]}" if on else "I don't have your plan on file yet.") + (
            f" Your {order.split(':')[1].split(',')[0].strip()} order is on its way and goes live once it's installed."
            if order else "")
    if kb.PLAN_WORDS.search(f" {kb.norm(text)} "):  # asked the price of a named plan: the answer carries it
        for m in _PLAN.finditer(text):
            p = next((p for p in plans if p["key"] == _plan_key(m)), None)
            if p and p["label"] not in reply:
                reply += f" {p['name']} is {p['label']}/month."
    return reply


def persona_message(*, name, profile, intent, history):
    """history: [(speaker, text)] of this session so far. Customer turns are 'assistant' from the persona's side."""
    msgs = [{"role": "assistant" if sp == "customer" else "user", "content": tx} for sp, tx in history[-6:]]
    msgs.append({"role": "user", "content": "(Write your next message now.)"})
    return llm.chat_text("persona", PERSONA_SYSTEM.format(name=name, profile=profile, intent=intent), msgs, "persona")


RESOLVER_SYSTEM = f"""You are the resolver, a technical support specialist at {COMPANY}. You have just picked up
a ticket. Write ONE reply to the customer — 2 short sentences max:
- Confirm you have the ticket and what your tools found, in plain human terms (NOT raw log output)
  · "Billing system: alice rao is on plan Fiber 300" → "Your Fiber 300 plan is active"
  · "Router diagnostic: packet loss 8%" → "Your router is showing 8% packet loss"
- If a past fix worked before, name it specifically; otherwise say you're on it
Plain English, no markdown, no emojis, no "I'll get back to you" or "I'll look into this" — say what is happening now."""


def resolver_reply(customer, ticket, observations, suggestions):
    """LLM-written reply from the resolver to the customer."""
    first = customer.split()[0].title()
    lines = [f"Ticket: {ticket.upper()} — customer: {first}"]
    if observations:
        lines.append("Tool results:\n" + "\n".join(f"- {o}" for o in observations))
    if suggestions:
        best = next(iter(suggestions.values()))
        lines.append(f"A past fix worked {best['worked_before']} time(s) for a similar issue: '{best['fix']}'")
    else:
        lines.append("No prior fix on record for this kind of issue.")
    msgs = [{"role": "user", "content": "\n".join(lines)}]
    try:
        raw = llm.chat_text("reply", RESOLVER_SYSTEM, msgs, "resolver")
        return _clean(raw, max_sentences=3, max_words=60, first_turn=False)
    except llm.Unavailable:
        return None


def summarize_session(tenant, session_id, log=None):
    turns = session_turns(tenant, session_id, log)
    if not turns:
        return None
    convo = "\n".join(f"{sp}: {tx}" for sp, tx, _, _ in turns[:30])
    try:
        summary = llm.chat_text("summary", SUMMARY_SYSTEM, [{"role": "user", "content": f"Support conversation on "
                                f"{to_date(turns[0][2])}:\n{convo}"}], "summary")
    except llm.Unavailable:
        summary = f"{len(turns)} messages with {turns[0][3] or 'a customer'}"
    db.run(tenant, "session summary", Q.SET_SESSION_SUMMARY, {"sid": session_id, "summary": summary}, log)
    return summary


def summarize_community(tenant, cid, top, log=None):
    rows = db.run(tenant, "community facts", Q.COMMUNITY_FACTS, {"cid": cid}, log, ro=True)
    if not rows:
        return None
    facts = "\n".join(f"{s} {p.replace('_', ' ')} {o}" for s, p, o in rows)
    try:
        summary = llm.chat_text("summary", SUMMARY_SYSTEM + " Name the theme first, like 'Pune outage: ...'.",
                                [{"role": "user", "content": f"A cluster of related support memory:\n{facts}"}], "summary")
    except llm.Unavailable:
        summary = ", ".join(top[:3])
    db.run(tenant, "community summary", Q.SET_COMMUNITY_SUMMARY, {"cid": cid, "summary": summary}, log)
    return summary
