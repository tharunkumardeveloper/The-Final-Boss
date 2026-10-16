"""The intake agent spec (intake_agent_spec.md) as code: what intake does on each turn, in order.

1. check the graph (who is this, what do we know), with each lookup shown live in the chat
2. greet new vs returning; confirm changes; escalate repeat contacts
3. answer from the graph when it can (coverage, outages, "which plan am I on")
4. otherwise ask for the first missing piece of information, one question at a time, with the spec's wording and its
   "if you don't know" hints; or let the model reply, guided by the matching issue tree
The model only words the free replies. Everything a weak model gets wrong (asking twice, asking two things, troubleshooting
a stranger, promising fix times) is decided here.
"""
import re
from dataclasses import dataclass

from . import config, db, events, kb, queries as Q, retrieve, tools
from .memory import norm, to_ms


def step(tenant, customer, label, at=None):
    """What intake is doing right now, for the chat's typing bubble. Every label is a real lookup that follows."""
    events.emit(tenant, "kavya_step", {"customer": norm(customer), "step": label}, to_ms(at) if at else None)


@dataclass(frozen=True)
class Slot:
    key: str
    subject: str        # "customer" or "ticket"
    preds: tuple        # facts that answer it
    question: str       # the spec's wording
    words: re.Pattern   # a question that asks for it
    hint: str = ""      # spec 2b: where to find it when they don't know


def _w(p):
    return re.compile(p, re.I)


IDENTITY = [
    Slot("identifier", "customer", ("phone", "email", "account_id"),
         "What's the registered mobile number on your account? Your email or PML-AC account number works too.",
         _w(r"\b(number|mobile|phone|email|account)\b"),
         "No problem. Check the sticker on the back or bottom of your router: it usually has your registered number and "
         "account number. The welcome SMS we sent when your connection was activated has them too."),
    Slot("area", "customer", ("lives_in", "address"),
         "Which city and area is your connection in? That's how I find your line and check the network there.",
         _w(r"\b(area|address|located|location|where|city|locality)\b")),
    Slot("plan", "customer", ("on_plan",), "Which plan are you on: Fiber 100, 300 or 1000?", _w(r"\bplan\b"),
         "That's fine. The sticker on the side of your router box mentions your speed (100 Mbps, 300 Mbps or 1 Gbps)."),
    Slot("router", "customer", ("has_router",),
         "Do you know which router you have? The model name is on the sticker on its base: PML Hub 6, Hub 6 Pro or Hub 7.",
         _w(r"\b(router|hub)\b"),
         "Easy to check: flip the router over, the model name is on the white sticker on the base."),
]
ISSUE = [
    Slot("started", "ticket", ("issue_started",), "When did this start: today, or has it been a few days?",
         _w(r"\b(when|start\w*|since|how long)\b")),
    Slot("frequency", "ticket", ("frequency",), "Is it constant, or does it come and go?",
         _w(r"\b(constant|come and go|how often)\b")),
    Slot("scope", "ticket", ("severity", "affected_device"), "Is it affecting your whole home, or just one device?",
         _w(r"\b(whole home|one device|all devices|everyone|which devices?)\b")),
    Slot("medium", "ticket", ("connection_medium",), "Does it happen on WiFi only, or also when you plug in a cable?",
         _w(r"\b(cable|wired|wifi only|plug)\b")),
    Slot("tried", "ticket", ("tried_fix",), "Have you already tried restarting your router?",
         _w(r"\b(tried|restart\w*)\b")),
]
SALES = [
    Slot("location", "customer", ("lives_in", "address"), "Which city and locality should I check for you?",
         _w(r"\b(area|address|located|location|where|city|locality)\b")),
    Slot("choice", "customer", ("wants_to_buy", "on_plan"), "", _w(r"\bplan\b")),  # question built from local prices
    Slot("connection", "customer", ("connection_type",), "Is this for a home or a business?", _w(r"\b(home|business)\b")),
]
BILLING = [IDENTITY[0]]
ADDRESS = Slot("location", "customer", ("address",), "What's the exact address for the connection (house, street, area)?",
               SALES[0].words)
# What intake actually asks a support customer, kept short so it doesn't feel like a form: who they are, where the
# line is, and the three details the resolver diagnoses from. Plan and router come from billing and the line record;
# frequency and what they tried are still noted when volunteered, never asked.
ASKED_IDENTITY = [s for s in IDENTITY if s.key in ("identifier", "area")]
ASKED_ISSUE = [s for s in ISSUE if s.key in ("started", "scope", "medium")]
SLOTS = {s.key: s for s in IDENTITY + ISSUE + SALES}  # keys are unique per flow (area = support, location = sales)

DONT_KNOW = _w(r"\b(idk|i don'?t know|dont know|don'?t remember|no idea|not sure|can'?t remember|forgot|no clue)\b")
YES = _w(r"^\s*(yes|yeah|yep|yup|sure|ok(ay)?|please|go ahead|do it|cool|alright)\b|\b(add me|sign me up|put me on)\b")
FRUSTRATED = _w(r"\b(again|still not|still isn'?t|third time|second time|called before|nobody|no one|fed up|useless|"
                r"worst|every time|keeps happening)\b")
COVERAGE_Q = _w(r"\b(do|does|d)\s*(you|u|ya)?\s*(guys\s+)?(cover|serve)\b|\bis it (there|available|covered)\b"
                r"|\b(provide|offer)\w*\s+(?:any\s+|your\s+)?(?:(?:service|services|internet|broadband|fiber|fibre|connection)\s+)?(?:in|at|there)\b"
                r"|\b(coverage|serviceable|available in|service in|services in)\b")
# the place itself: after a coverage verb ("cover Madurai") or a preposition ("service in Madurai")
NAMED_PLACE = _w(r"\b(?:cover|serve|in|at)\s+(?:the\s+)?([a-z][a-z .'-]{2,40}?)\s*(?:\?|$|,|\.|area|city|state|district)")
NOT_A_PLACE = {"you", "your", "do", "does", "offer", "offers", "what", "which", "services", "service", "plans", "plan",
               "there", "it", "my", "me", "this", "that", "home", "house", "general", "india", "the country"}
PROBLEM = _w(r"\b(not working|isn'?t working|is not working|no internet|(is|keeps?|goes) (down|dropping|disconnecting)"
              r"|keeps? (dropping|disconnecting|lagging|buffering)|lag\w*|buffer\w*|very slow|so slow|really slow"
              r"|drops? (every|all the time|constantly)|not connecting|can'?t connect|sucks|stopped working)\b")


def problem_name(m):
    """A short issue name from the words the customer used."""
    w = m.group(0).lower()
    if "lag" in w or "buffer" in w:
        return "lag and buffering"
    if "slow" in w:
        return "slow internet"
    if "drop" in w or "disconnect" in w:
        return "connection drops"
    if "connect" in w:
        return "cannot connect"
    return "internet not working"


SUPPORT = _w(r"\b(my (connection|internet|wifi|router|broadband|line|net)|i'?m using|i use your|not working|isn'?t working"
             r"|no internet|keeps? (dropping|disconnecting)|lag\w*|buffer\w*|slow)\b")
BILLING_Q = _w(r"\b(bill|billing|invoice|charged|charges?|payment|paid|refund|deducted|gst|overcharg\w*)\b")
SALES_Q = _w(r"\b(new connection|install\w*|sign up|book|buy|get a connection|connection at my)\b")
FIX_TIME = _w(r"\b(fix|fixed|resolve\w*|sort\w*|restor\w*|back up)\b[^.!?]{0,40}\b(within|in|by)\s+(\d+|a few|an?)\s*"
              r"(minutes?|hours?|days?)|\bby (tonight|tomorrow|today|this evening)\b")
FIX_ADVICE = _w(r"\b(try|restart\w*|reboot\w*|switch\w* (to|your|off)|mov(e|ing) (your|the|closer)|clos(e|ing) (other|any)|"
                r"unplug\w*|reset\w*|updat\w*|chang\w* (the|your)|troubleshoot\w*|forget the network)\b")
REQUEST = _w(r"\b(please|kindly|could you|can you|provide|share|tell me|send|give me|confirm|let me know)\b")
_SENTENCE = re.compile(r"(?<!\b\d\.)(?<=[.!?])\s+(?=[A-Z])")


def sentences(text):
    return [s for s in _SENTENCE.split(text or "") if s.strip()]


# ---------------------------------------------------------------- the graph check (step 1)

def dig(tenant, customer, facts, ticket, at=None, log=None):
    """Lookups behind a problem report, each announced as it runs. Returns (notes, network) where network is
    {'olt', 'down'} when we know their line."""
    now = [f for f in facts if f["active"]]
    issues = [f["object"] for f in now if f["predicate"] == "reported_issue"]
    if not issues and not ticket:
        return [], None
    out, network = [], None
    line = db.run(tenant, "kavya: network", Q.NET_STATUS, {"c": customer}, log, ro=True)
    if line:
        olt, down = line[0]
        step(tenant, customer, f"Checking the network at {olt}", at)
        network = {"olt": olt, "down": down}
        from . import lab  # lazy: lab imports agents, which imports this module
        m = None if down else lab.measure(tenant, customer, log)  # links too, not just equipment status
        if down:
            out.append(f"Network check: {', '.join(down)} is DOWN right now, so this is an outage, not their home setup.")
        elif m and m["flow_gbps"] <= 0:
            out.append("Network check: their area has no route to the internet right now (a link upstream is cut), "
                       "so it is not their home setup. The resolver is handling it.")
        elif m and m["splitter"]["others"] and m["splitter"]["others_down"] / m["splitter"]["others"] >= 0.5:
            out.append("Network check: most homes on their street cabinet are offline too, so it is not their home setup.")
        else:
            out.append(f"Network check: {olt} and the area network are up; the resolver is testing their own line.")
    step(tenant, customer, "Looking through your past tickets", at)
    for t, st, iss, tried in db.run(tenant, "kavya: past tickets", Q.PAST_TICKETS, {"c": customer}, log, ro=True):
        if t != ticket:
            out.append(f"Past ticket {t.upper()} ({st or 'open'}) about {', '.join(iss) or 'an issue'}"
                       + (f"; already tried: {', '.join(tried)}" if tried else "") + ".")
    step(tenant, customer, "Finding fixes that worked for others with this problem", at)
    for issue in issues[:2]:
        fixes = db.run(tenant, "kavya: fixes for similar issues", Q.FIXES_FOR_SIMILAR,
                       {"issue": issue, "max_dist": config.SIMILAR_ISSUE_MAX_DIST}, log, ro=True)
        if fixes:
            out.append(f"Fixes that worked for similar problems ({issue}): "
                       + "; ".join(f"{fx} ({n}x)" for fx, _, _, n in fixes[:3]) + ".")
    return out, network


def ticket_facts(tenant, ticket, log=None):
    return {p for _, p, _, active, *_ in retrieve.history(tenant, ticket, log) if active} if ticket else set()


# ---------------------------------------------------------------- the turn plan

@dataclass
class Plan:
    mode: str                      # support / billing / sales / general
    fixed: str | None = None       # a complete reply decided here (no model)
    prefix: list = None            # sentences that go before the reply
    ask: Slot | None = None        # the one question this turn must ask
    notes: list = None             # extra notes for the model
    writes: list = None            # (subject, predicate, object) facts to record for this turn
    retires: list = None           # (subject, predicate, object) facts to end this turn
    missing: list = None           # slots still missing, in order
    returning: bool = False        # talked to us in an earlier session
    escalation: str | None = None  # why this turn raised the ticket's priority


def _answers(text, waiting, have):
    """(predicate, object) for awaited slots this message answers, when the answer has an exact catalogue form."""
    from .memory import catalogue_plan, catalogue_router
    out = []
    if "plan" in waiting and "on_plan" not in have and (p := catalogue_plan(text)):
        out.append(("on_plan", p))
    if "choice" in waiting and not have & {"wants_to_buy", "on_plan"} and (p := catalogue_plan(text)):
        out.append(("wants_to_buy", p))
    if "router" in waiting and "has_router" not in have:
        r = catalogue_router(text)
        if r in {x["key"] for x in kb.world()["routers"]}:
            out.append(("has_router", r))
    if waiting & {"area", "location"} and not have & {"lives_in", "address"} and (p := kb.resolve_place(text)):
        out.append(("lives_in", p["area"] or p["city"]))
    if "connection" in waiting and "connection_type" not in have:
        m = re.search(r"\b(home|house|flat|business|office|shop)\b", text, re.I)
        if m:
            out.append(("connection_type", "home" if m.group(1).lower() in ("home", "house", "flat") else "business"))
    return out


def _first(customer):
    return customer.split()[0].title()


def _known(now, preds):
    return any(f["predicate"] in preds for f in now)


SUPPORT_SLOTS = {"identifier", "area", "router", "plan", "started", "frequency", "scope", "medium", "tried"}
SALES_SLOTS = {"location", "choice", "connection"}


def _mode(text, now, ticket):
    preds = {f["predicate"] for f in now}
    waiting = {f["object"] for f in now if f["predicate"] == "awaiting"}
    if BILLING_Q.search(text):
        return "billing"
    # "oh found it, 9876543210" has no support words: the open question she asked is what makes it support
    if ticket or "reported_issue" in preds or SUPPORT.search(text) or waiting & SUPPORT_SLOTS:
        return "support"
    if waiting & SALES_SLOTS:
        return "sales"
    if SALES_Q.search(text) or preds & {"wants_to_buy", "interested_in", "requested", "moving_to"}:
        return "sales"
    return "general"


def _place(text, history, now):
    """The place a coverage question is about: this message, then earlier messages, then what's on file."""
    for t in [text] + [tx for sp, tx in reversed(history) if sp == "customer"]:
        p = kb.resolve_place(t)
        if p:
            return p, t
    for f in now:
        if f["predicate"] in ("address", "lives_in", "moving_to"):
            p = kb.resolve_place(f["object"])
            if p:
                return p, f["object"]
    return None, None


def _place_name(p):
    return (f"{p['area'].title()}, " if p["area"] else "") + p["city"].title()


def plan_turn(tenant, *, customer, text, learned, ticket, history, first_turn, plans=(), at=None, session_id=None,
              log=None, facts=None):
    """Decide this turn. history: [(speaker, text)] before this message. plans: local price list for the sales ask.
    facts: customer_facts() already read this turn, if any."""
    facts = retrieve.customer_facts(tenant, customer, log=log) if facts is None else facts
    now = [f for f in facts if f["active"]]
    plan = Plan(mode=_mode(text, now, ticket), prefix=[], notes=[], writes=[], retires=[])
    waiting = {f["object"] for f in now if f["predicate"] == "awaiting"}
    gave_up = {f["object"] for f in now if f["predicate"] == "doesnt_know"}
    last_agent = next((tx for sp, tx in reversed(history) if sp != "customer"), "")

    # she asked which plan they'd like and the model filed the answer as their current plan: it is a purchase
    asked_choice = any(f["predicate"] == "awaiting" and f["object"] == "choice" for f in facts) and \
        re.search(r"which plan would you like", last_agent, re.I)
    bought = next((x[len("is on "):] for x in learned if x.startswith("is on ")), None)
    if asked_choice and bought:
        plan.retires.append((customer, "on_plan", bought))
        plan.writes.append((customer, "wants_to_buy", bought))
        now = [f for f in now if f["predicate"] != "on_plan"]

    # the answer to what she just asked, read straight against the catalogue ("300 mbps" after "which plan?")
    have_now = {f["predicate"] for f in now}
    for got in _answers(text, waiting, have_now):
        plan.writes.append((customer,) + got)
        now = now + [{"predicate": got[0], "object": got[1], "active": True, "subject": customer}]
    plan.mode = _mode(text, now, ticket)  # what this message settled (a purchase) can change the mode

    # who is this? identity match through a shared phone/email/account node (never reveals another customer's name)
    owners = db.run(tenant, "kavya: identifier owner", Q.IDENTIFIER_OWNER, {"c": customer}, log, ro=True)
    calling_for = next((f["object"] for f in now if f["predicate"] == "calling_for"), None)
    for other, ident in owners:
        if calling_for and norm(calling_for) == other:
            step(tenant, customer, f"Pulling up {other.title()}'s account", at)
            from .converse import customer_notes  # lazy: converse imports this module
            plan.notes.append(f"They are calling about {other.title()}'s connection; the name and {ident} match our "
                              f"records. {other.title()}'s account: " + " ".join(customer_notes(tenant, other, log)[0]))
            plan.prefix.append(f"Found it, I've pulled up {other.title()}'s account.")
        elif not calling_for:
            plan.fixed = ("That number is registered under a different name on our side, so I can't open that account "
                          "here. What's the full name on the account?")
            return plan

    # the plan from billing, once we know who they are (spec: "give me your number and I can pull it up")
    if _known(now, ("phone", "email", "account_id")) and not _known(now, ("on_plan",)):
        step(tenant, customer, "Looking up your plan in billing", at)
        billed = tools.billing_plan(customer, tenant)
        if billed:
            plan.writes.append((customer, "on_plan", billed))
            plan.notes.append(f"Billing says they are on {billed.title()}.")
            now = now + [{"predicate": "on_plan", "object": billed, "active": True, "subject": customer}]

    # returning customer (spec state 2): greet with what we know, ask about an open ticket first
    on = next((f["object"] for f in now if f["predicate"] == "on_plan"), None)
    area = next((f["object"] for f in now if f["predicate"] == "lives_in"), None)
    returning = bool(session_id) and db.run(tenant, "kavya: earlier sessions", Q.EARLIER_SESSIONS,
                                            {"c": customer, "sid": session_id}, log, ro=True)[0][0]
    plan.returning = returning
    if first_turn and returning and (on or area) and history == []:
        where = f" in {kb.resolve_place(area) and _place_name(kb.resolve_place(area)) or area.title()}" if area else ""
        plan.prefix.append(f"Hey {_first(customer)}, welcome back!" + (f" I can see you're on {on.title()}{where}." if on
                           else f" I can see you're{where}." if where else ""))
        if ticket and not re.search(r"\b(follow.?up|same|still|again|ticket)\b", text, re.I) and not learned:
            issue = next((f["object"] for f in facts if f["subject"] == ticket and f["predicate"] == "ticket_about"), None)
            plan.fixed = " ".join(plan.prefix + [f"You have an open ticket {ticket.upper()}"
                                                 + (f" about {issue}" if issue else "")
                                                 + ": is this a follow-up, or something new?"])
            return plan

    # a change to something on file (spec states 3 and 4): say it back
    for x in learned:
        m = re.match(r"now (lives in|is on|has router) (.+) \(was (.+)\)$", x)
        if m:
            what = {"lives in": "your location", "is on": "your plan", "has router": "your router"}[m.group(1)]
            plan.prefix.append(f"Got it, I've updated {what} from {m.group(3).title()} to {m.group(2).title()}; tell me if "
                               f"that's a mix-up.")

    # coverage questions are answered from the graph (spec issue 6), never by the model
    if COVERAGE_Q.search(text):
        p, said = _place(text, history, now)
        named = NAMED_PLACE.search(text)
        if named and set(named.group(1).lower().split()) & NOT_A_PLACE:
            named = None  # "do you offer", "in my home": not a place
        if named and not kb.resolve_place(text):  # "do you cover Madurai?": a place we have no node for
            p, said = None, re.sub(r"^((available|in|at|for|the|to)\s+)+|\s+(state|district|region)$", "",
                                   named.group(1).strip(), flags=re.I)
        if not p and said is None:
            plan.ask = SALES[0]
        elif p:  # covered: say so and move them one step on, with the local plans (spec issue 6)
            plan.prefix.append(f"Good news, we serve {_place_name(p)}.")
            if not _known(now, ("on_plan", "wants_to_buy")) and plans:
                plan.ask = _choice(plans)
                plan.fixed = " ".join(plan.prefix + [plan.ask.question])
                return plan
        else:  # we serve everywhere (a demo company): a country, state or town without a city entry still gets a yes
            plan.prefix.append(f"Yes, we serve {kb.norm(said).title()}.")
            plan.ask = ADDRESS
            plan.fixed = " ".join(plan.prefix + [ADDRESS.question])
            return plan

    # the graph check behind a problem, and what it found
    notes, network = dig(tenant, customer, facts, ticket, at, log)
    plan.notes += notes
    if network and network["down"]:  # spec issue 13: an outage is said plainly, no home troubleshooting
        where = ", ".join(network["down"])
        told = any(f"known outage at {where}" in tx for sp, tx in history if sp != "customer")
        if not told:
            plan.fixed = " ".join(plan.prefix + [f"I can see a known outage at {where}, which serves your area, and our "
                                                 "team is on it. You'll get a message here as soon as it's back."])
        else:  # asked again ("fix it", "when?"): the ETA and what to expect, not the same sentence
            plan.fixed = (f"The outage at {where} is still being repaired; outages like this are usually fixed within "
                          "about 4 hours. Nothing to do on your side; your connection comes back on its own and I'll message you here.")
        return plan
    if network and any(x.startswith("lives in") for x in learned):
        plan.prefix.append(f"Found your line on our {network['olt'].replace(' OLT', '')} exchange.")

    # repeat contact or frustration (spec state 5): apologise once, raise the ticket's priority
    tfacts = ticket_facts(tenant, ticket, log)
    repeat = _known(now, ("previous_contact",)) or FRUSTRATED.search(text) or any(n.startswith("Past ticket") for n in notes)
    said_before = any("flagged it as a priority" in tx for sp, tx in history if sp != "customer")
    if ticket and repeat and "has_priority" not in tfacts and not said_before:
        plan.writes.append((ticket, "has_priority", "high"))
        plan.escalation = ("customer says it keeps happening" if FRUSTRATED.search(text) else
                           "contacted us before about it" if _known(now, ("previous_contact",)) else
                           "a past ticket about the same problem")
        plan.prefix.append("I can see you've been in touch about this before, and I'm sorry it isn't sorted yet. I've "
                           "flagged it as a priority for our senior resolver team.")

    # what we still need, in the spec's order, one at a time
    have = {f["predicate"] for f in now} | tfacts
    from . import lab  # lazy: lab imports agents, which imports this module
    if not have & set(IDENTITY[0].preds) and lab.has_line(tenant, customer):
        have.add("account_id")  # their line is in the network graph: that already says whose account this is
    order = {"support": ASKED_IDENTITY + (ASKED_ISSUE if ticket else []), "billing": BILLING, "sales": SALES}.get(plan.mode, [])
    if plan.mode == "sales" and not (SALES_Q.search(text) or _known(now, ("wants_to_buy", "requested", "lives_in"))):
        order = []  # a prospect browsing plans isn't asked for an address
    plan.missing = [s for s in order if not have & set(s.preds) and s.key not in gave_up]
    if plan.mode == "billing" and not _known(now, ("phone", "email", "account_id")):
        if not DONT_KNOW.search(text):  # spec: never answers billing amounts without verifying identity
            plan.ask = IDENTITY[0]
            plan.fixed = ("I can help with your bill. To keep your account safe I need to confirm it's you first. "
                          + IDENTITY[0].question)
            return plan

    # "I don't know" to what she just asked: the spec's hint, once; after that, move on
    asked_last = next((s for s in SLOTS.values() if s.key in waiting and s.words.search(last_agent)), None)
    if asked_last and DONT_KNOW.search(text):
        if asked_last.hint and asked_last.hint not in last_agent:
            plan.fixed = asked_last.hint + (" What does it say?" if asked_last.key in ("plan", "router") else "")
            return plan
        plan.writes.append((customer, "doesnt_know", asked_last.key))
        plan.missing = [s for s in plan.missing if s.key != asked_last.key]
        plan.prefix.append("No problem, we can manage without it.")

    if plan.ask is None and plan.missing:
        plan.ask = plan.missing[0]
    if (plan.mode == "support" and ticket and plan.ask is None and not plan.missing and not plan.fixed
            and asked_last in ASKED_ISSUE and lab.has_line(tenant, customer)):
        # that was the last thing we needed: say the handoff, instead of "what can I help you with?"
        plan.fixed = (f"Thanks, {_first(customer)}, that's everything I need. I've handed {ticket.upper()} to our "
                      f"resolver, who's testing your line now and will message you right here.")
    if plan.ask and plan.ask.key == "choice":
        plan.ask = _choice(plans)
    if plan.ask is SALES[0] and _known(now, ("wants_to_buy",)):  # ordered: the install address, where they asked about
        p, _ = _place(text, history, now)
        where = f" in {_place_name(p)}" if p else ""
        plan.ask = Slot("location", "customer", ("lives_in", "address"),
                        f"What's the full address for the installation{where}?", SALES[0].words)
    return plan


def _choice(plans):
    return Slot("choice", "customer", ("wants_to_buy",),
                "Which plan would you like: " + ", ".join(f"{p['name']} at {p['label']}/month" for p in plans[:4]) + "?",
                _w(r"\bplan\b"))


# ---------------------------------------------------------------- after the reply

_PRICE = re.compile(r"\d[\d,.]*\d|\d")


def finish(reply, plan):
    """The spec's 'never' list on any reply: the planned question asked, never twice, one question only,
    no promised fix times, nothing asked that we already know."""
    parts = [s for s in sentences(reply) if not FIX_TIME.search(s)]
    if plan.mode == "support" and plan.ask in IDENTITY:  # no troubleshooting until we know whose line it is
        parts = [s for s in parts if not FIX_ADVICE.search(s)]
    known = [s for s in SLOTS.values() if plan.missing is not None and s not in plan.missing and s != plan.ask]
    parts = [s for s in parts if not ("?" in s and any(k.words.search(s) for k in known if k.key != "choice"))]
    if plan.ask:  # the planned question is the only ask: model questions and "please provide your ..." go
        asked_prices = set(_PRICE.findall(plan.ask.question))
        parts = [s for s in parts if "?" not in s and not (REQUEST.search(s) and plan.ask.words.search(s))
                 and not re.match(r"(once|when|after) (i|you) (have|get|share|provide)", s, re.I)
                 and len(asked_prices & set(_PRICE.findall(s))) < 2]
        parts += [plan.ask.question]
    else:
        qs = [i for i, s in enumerate(parts) if "?" in s]
        parts = [s for i, s in enumerate(parts) if "?" not in s or i == (qs[0] if qs else -1)]
    out = " ".join(plan.prefix + [s for s in parts if s not in plan.prefix])
    return out.strip() or (plan.ask.question if plan.ask else "")


def asked_slots(reply, plan):
    """Which needed things this reply asked for (they become 'awaiting' facts)."""
    qs = " ".join(s for s in sentences(reply) if "?" in s)
    return [s.key for s in (plan.missing or []) + ([plan.ask] if plan.ask else []) if s.words.search(qs)][:1]
