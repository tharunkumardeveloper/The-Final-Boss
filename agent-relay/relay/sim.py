"""Persona simulator on a simulated clock, plus the scripted demo story.

Each persona has a hidden schedule of life events. The persona LLM chooses the words; the schedule guarantees
the moment happens (backdated move, device purchase, billing disagreement, recurring drops -> ticket -> handoff,
outage, a fix that worked for one customer suggested for another, channel change, paraphrased re-mention).
Everything runs through the real agents and the real graph. At temperature 0 with the disk cache, a re-run on a
reset tenant replays without new LLM calls."""
import threading
import time
from datetime import datetime

from . import agents, converse, db, events, llm, network, queries as Q, tools
from .memory import norm, to_ms

HOUR = 3_600_000
START = to_ms(datetime.fromisoformat("2026-09-01T09:00:00+05:30"))

WORLD = {  # the company's back office (synthetic)
    "billing": {"alice rao": "fiber 100", "bob menon": "fiber 300", "chitra iyer": "fiber 1000",
                "dev malhotra": "fiber 300", "esha kulkarni": "fiber 100", "farhan shaikh": "fiber 300"},
    # outages have a window: the feed stops reporting them when they're fixed, and the resolver retires them then
    "outages": [{"name": "fiber cut near baner", "cities": ["pune"],
                 "from": START + 3 * 24 * HOUR, "until": START + 5 * 24 * HOUR},
                {"name": "substation failure in gachibowli", "cities": ["hyderabad"],
                 "from": START + 6 * 24 * HOUR - 3 * HOUR, "until": START + 7 * 24 * HOUR}],
    "diagnostics": {"alice rao": "channel congestion on 2.4 ghz", "bob menon": "channel congestion on 2.4 ghz",
                    "esha kulkarni": "dns timeouts"},
    "working_fixes": {"alice rao": ["change wifi channel"], "bob menon": ["change wifi channel"],
                      "esha kulkarni": ["switch dns to 1.1.1.1"], "dev malhotra": ["replace fiber patch cable"]},
}
PLAYBOOK = ["restart router"]  # tried after known fixes from procedural memory, before the customer-specific fix

# The demo story in every region: the same storyline (a customer gives her details; a neighbour's evening Wi-Fi drops
# are fixed after one failed try, so the fix becomes procedural memory; she moves to his city; billing disagrees about
# her plan) with local names, two covered cities and the local time zone. India is the original cast.
CASTS = {
    "pml": {"a": "Alice Rao", "b": "Bob Menon", "from": "Mumbai", "to": "Pune", "tz": "+05:30"},
    "pml-eu": {"a": "Emma Clarke", "b": "Oliver Hughes", "from": "London", "to": "Manchester", "tz": "+01:00"},
    "pml-na": {"a": "Olivia Bennett", "b": "Ethan Walker", "from": "New York City", "to": "Chicago", "tz": "-04:00"},
    "pml-apac": {"a": "Chloe Nguyen", "b": "Liam Carter", "from": "Sydney", "to": "Melbourne", "tz": "+10:00"},
    "pml-mea": {"a": "Layla Haddad", "b": "Omar Farouk", "from": "Dubai", "to": "Abu Dhabi", "tz": "+04:00"},
    "pml-latam": {"a": "Sofia Almeida", "b": "Mateo Souza", "from": "Sao Paulo", "to": "Rio de Janeiro", "tz": "-03:00"},
}
for _c in CASTS.values():  # each cast's back office: billing disagrees with what she says; the same Wi-Fi fix works
    _a, _b = _c["a"].lower(), _c["b"].lower()
    WORLD["billing"].setdefault(_a, "fiber 100")
    WORLD["billing"].setdefault(_b, "fiber 300")
    for _n in (_a, _b):
        WORLD["diagnostics"].setdefault(_n, "channel congestion on 2.4 ghz")
        WORLD["working_fixes"].setdefault(_n, ["change wifi channel"])

# The rest of each region's neighbourhood, so every desk opens on a lived-in graph: (name, where, plan, case).
# Cases: dns (slow pages, fixed after one failed try), cable (red light, a field fix), sales (an upgrade question),
# billing (a double charge), tv (a new device that won't join; left open for the resolver's queue).
RESIDENTS = {
    "pml": [("Chitra Iyer", "Koramangala, Bengaluru", "1000", "sales"), ("Dev Malhotra", "Gachibowli, Hyderabad", "300", "cable"),
            ("Esha Kulkarni", "Andheri, Mumbai", "100", "dns"), ("Farhan Shaikh", "Adyar, Chennai", "300", "tv")],
    "pml-eu": [("Amelia Wright", "Camden, London", "300", "dns"), ("Harry Patel", "Coventry, Birmingham", "100", "cable"),
               ("Grace Taylor", "Islington, London", "300", "billing"), ("Jack Wilson", "Bradford, Leeds", "100", "tv")],
    "pml-na": [("Ava Martinez", "Brooklyn, New York City", "300", "dns"), ("Noah Kim", "Santa Monica, Los Angeles", "1000", "tv"),
               ("Mia Johnson", "Lincoln Park, Chicago", "100", "sales"), ("Lucas Brown", "Pasadena, Los Angeles", "300", "cable")],
    "pml-apac": [("Ruby Tan", "Bondi, Sydney", "300", "dns"), ("Jack Thompson", "Parramatta, Sydney", "100", "billing"),
                 ("Isla Wong", "Surry Hills, Sydney", "1000", "tv"), ("Noah Singh", "Logan City, Brisbane", "300", "cable")],
    "pml-mea": [("Fatima Al Mansoori", "Dubai Marina, Dubai", "1000", "tv"), ("Yusuf Rahman", "Deira, Dubai", "300", "cable"),
                ("Noor Saleh", "Jumeirah, Dubai", "300", "dns"), ("Khalid Nasser", "Al Ain", "100", "sales")],
    "pml-latam": [("Beatriz Costa", "Pinheiros, Sao Paulo", "300", "dns"), ("Lucas Pereira", "Contagem, Belo Horizonte", "100", "cable"),
                  ("Ana Ribeiro", "Moema, Sao Paulo", "1000", "billing"), ("Gabriel Lima", "Colombo, Curitiba", "300", "tv")],
}
CASES = {  # what the resident says (session 1), the back office's diagnosis, and the fix that works (after a failed one)
    "dns": (["Websites take ages to load, but YouTube and games are fine. It's been like this since yesterday."],
            "dns timeouts", "switch dns to 1.1.1.1"),
    "cable": (["No internet since this morning, and the light on the router is red.", "Every device, wifi and cable."],
              "fiber patch cable damaged", "replace fiber patch cable"),
    "sales": (["We both work from home now. Is it worth moving to a faster plan for video calls?"], None, None),
    "billing": (["I was charged twice for this month. Can you check my bill?"], None, None),
    "tv": (["My new smart TV in the living room can't find the wifi. Everything else works."], None, None),
}
for _rs in RESIDENTS.values():
    for _n, _w, _plan, _case in _rs:
        WORLD["billing"].setdefault(_n.lower(), f"fiber {_plan}")
        if CASES[_case][1]:
            WORLD["diagnostics"].setdefault(_n.lower(), CASES[_case][1])
            WORLD["working_fixes"].setdefault(_n.lower(), [CASES[_case][2]])

# (day offset, "HH:MM", session number, what the message must get across)
PERSONAS = [
    {"name": "Alice Rao", "profile": "34, product designer, lives in Mumbai, on the Fiber 300 plan, has a PS5 and a work "
                                     "laptop, likes updates on WhatsApp. Friendly but busy.",
     "events": [(0, "09:30", 1, "you live in Mumbai, you're on the Fiber 300 plan, and you prefer updates on WhatsApp"),
                (0, "09:40", 1, "you own a PS5 and a work laptop; ask if Fiber 300 is enough for gaming and video calls"),
                (11, "10:00", 2, "you moved to Pune on 10 September, two days ago, and need the service moved there"),
                (13, "18:30", 3, "your PS5 and laptop keep dropping wifi every evening at the new Pune flat"),
                (15, "11:00", 4, "confirm you're settled in Pune now, and ask to be contacted by email instead of WhatsApp")]},
    {"name": "Bob Menon", "profile": "41, school teacher in Pune, Fiber 300 plan, PML Hub 6 router. Polite and brief.",
     "events": [(3, "19:00", 1, "you live in Pune, use a PML Hub 6 router, and your wifi drops every evening around 8 pm"),
                (6, "10:00", 2, "thank them: the evening wifi has been stable since their fix")]},
    {"name": "Chitra Iyer", "profile": "29, startup founder in Bengaluru, works from home, on Fiber 100, owns a MacBook.",
     "events": [(2, "12:00", 1, "you live in Bengaluru, you're on Fiber 100 and you want to upgrade to Fiber 1000"),
                (8, "15:00", 2, "you're on Fiber 1000 now and just bought a smart TV; ask if 4K streaming will be fine")]},
    {"name": "Dev Malhotra", "profile": "52, accountant in Hyderabad, Fiber 300, PML Hub 6 router. Direct, a little impatient.",
     "events": [(6, "08:30", 1, "you live in Hyderabad, use a PML Hub 6 router, and there has been no internet at all "
                                "since this morning"),
                (9, "09:00", 2, "your router was swapped for a PML Hub 6 Pro yesterday and the connection is back")]},
    {"name": "Esha Kulkarni", "profile": "26, competitive gamer in Mumbai, believes she is on Fiber 300. Casual, types fast.",
     "events": [(4, "21:00", 1, "you live in Mumbai, you're on Fiber 300, and online games lag while websites take ages "
                                "to load"),
                (7, "20:00", 2, "you also bought an Xbox and gaming feels smooth now")]},
    {"name": "Farhan Shaikh", "profile": "38, chef, lives in Mumbai on Fiber 300, prefers phone calls. Warm, chatty.",
     "events": [(1, "10:00", 1, "you live in Mumbai, you're on Fiber 300, and you prefer a phone call over chat"),
                (14, "10:00", 2, "you relocated to Bengaluru last week and need the connection shifted")]},
]


# Network incidents on the same clock: the NOC finds who is affected through the graph and warns them first.
# Baner's OLT serves Pune customers (Alice after her move, Bob), so both get a proactive message mid-run.
NETWORK_EVENTS = [(12, "20:00", "fail", "olt-pune-baner"), (12, "23:30", "restore", "olt-pune-baner")]
NOC = "__noc__"


def _at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return START + day * 24 * HOUR + h * HOUR + m * 60_000 - 9 * HOUR


class Sim:
    def __init__(self, tenant, customers=6, speed=6.0):
        self.tenant, self.speed = tenant, float(speed)
        self.personas = PERSONAS[:max(1, min(int(customers), len(PERSONAS)))]
        self.timeline = sorted([(_at(d, t), p["name"], s, intent)
                                for p in self.personas for d, t, s, intent in p["events"]]
                               + [(_at(d, t), NOC, action, node) for d, t, action, node in NETWORK_EVENTS],
                               key=lambda e: e[0])
        self.now = START
        self.running = False
        self.done = False
        self.work = {}  # ticket -> {"due": ms, "fixes": [..], "tried": int, "customer": key}
        self.open_sessions = {}  # customer key -> session id
        self.intake, self.resolver = agents.Intake(), agents.Resolver()
        self._thread = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        tools.WORLDS[self.tenant] = WORLD
        self.running = True
        events.emit(self.tenant, "sim_status", {"running": True, "speed": self.speed}, self.now)
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"sim-{self.tenant}")
        self._thread.start()

    def stop(self):
        self.running = False
        events.emit(self.tenant, "sim_status", {"running": False, "speed": self.speed}, self.now)

    def status(self):
        return {"running": self.running, "sim_time": events.iso(self.now), "speed": self.speed,
                "customers": [p["name"] for p in self.personas], "done": self.done}

    def run_sync(self):
        """Run every event immediately (tests, cache export)."""
        tools.WORLDS[self.tenant] = WORLD
        self.running = True
        while self.running and self._pending():
            self.now = self._next_due()
            self._step()
        self._finish()

    def _loop(self):
        tick, last_hour = 0.25, self.now // HOUR
        try:
            while self.running and self._pending():
                time.sleep(tick)
                self.now += int(self.speed * tick * HOUR)
                if self.now // HOUR != last_hour:
                    last_hour = self.now // HOUR
                    events.emit(self.tenant, "clock", {"sim_time": events.iso(self.now)}, self.now)
                self._step()
            if self.running:
                self._finish()
        finally:
            self.running = False
            events.emit(self.tenant, "sim_status", {"running": False, "speed": self.speed}, self.now)

    # ------------------------------------------------------------ simulation
    def _pending(self):
        return bool(self.timeline) or any(w["due"] is not None for w in self.work.values())

    def _next_due(self):
        dues = [self.timeline[0][0]] if self.timeline else []
        dues += [w["due"] for w in self.work.values() if w["due"] is not None]
        return max(self.now, min(dues))

    def _step(self):
        while self.timeline and self.timeline[0][0] <= self.now and self.running:
            at, name, session, intent = self.timeline.pop(0)
            if name == NOC:  # no LLM involved: pure graph traversal + memory writes
                (network.fail if session == "fail" else network.restore)(self.tenant, intent, at=at)
                continue
            try:
                self._customer_turn(at, name, session, intent)
            except llm.Unavailable as e:  # every model busy: skip this turn, keep the simulation alive
                events.emit(self.tenant, "sim_status", {"running": True, "speed": self.speed, "skipped": str(e)[:200]}, at)
        for ticket, w in sorted(self.work.items()):
            if self.running and w["due"] is not None and w["due"] <= self.now:
                try:
                    self._resolver_turn(ticket, w)
                except llm.Unavailable:
                    w["due"] += 3 * HOUR

    def _customer_turn(self, at, name, session, intent):
        persona = next(p for p in self.personas if p["name"] == name)
        key = norm(name)
        sid = f"{key.split()[0]}-s{session}"
        prev = self.open_sessions.get(key)
        if prev and prev != sid:
            converse.summarize_session(self.tenant, prev)
        self.open_sessions[key] = sid
        history = [(sp, tx) for sp, tx, _, _ in converse.session_turns(self.tenant, sid)]
        text = converse.persona_message(name=name, profile=persona["profile"], intent=intent, history=history)
        out = self.intake.handle(self.tenant, customer=name, session_id=sid, text=text, at=at, reply_llm=True)
        db.run(self.tenant, "simulator played", Q.PLAYED, {"sid": sid})
        if out["ticket_opened"]:
            self.work[out["ticket_opened"]] = {"due": at + 2 * HOUR, "fixes": None, "tried": 0, "customer": key}

    def _resolver_turn(self, ticket, w):
        at = w["due"]
        if w["fixes"] is None:  # first visit: pick up, run tools, answer from intake's memory (handoff)
            pick = self.resolver.pick_up(self.tenant, ticket=ticket, at=at)
            known = [s["fix"] for s in pick["suggestions"]]
            w["fixes"] = list(dict.fromkeys(known + PLAYBOOK + WORLD["working_fixes"].get(w["customer"], [])))
            self.resolver.ask(self.tenant, f"What router and plan does {display_name(w['customer'])} have, "
                                           f"and which city do they live in now?")
            w["due"] = at + 3 * HOUR
            return
        if w["tried"] >= len(w["fixes"]):
            w["due"] = None
            return
        fix = w["fixes"][w["tried"]]
        w["tried"] += 1
        worked = tools.fix_works(w["customer"], fix, self.tenant)
        self.resolver.try_fix(self.tenant, ticket=ticket, fix=fix, worked=worked, at=at)
        w["due"] = None if worked else at + 3 * HOUR

    def _finish(self):
        for sid in self.open_sessions.values():
            converse.summarize_session(self.tenant, sid)
        self.open_sessions.clear()
        agents.consolidate(self.tenant, summaries=True)
        self.done, self.running = True, False


def display_name(key):
    return " ".join(w.capitalize() for w in key.split())


SIMS: dict[str, Sim] = {}


def start(tenant, customers=6, speed=6.0, reset=False):
    """Play. Without reset, a paused run resumes where it was (pressing play must never wipe the graph)."""
    old = SIMS.get(tenant)
    if old and not reset and not old.done:
        old.speed = float(speed)
        if not old.running:
            old.start()
        return old
    if old and old.running:
        old.stop()
    if reset:
        db.reset(tenant)
    SIMS[tenant] = sim = Sim(tenant, customers, speed)
    sim.start()
    return sim


def set_speed(tenant, speed):
    s = SIMS.get(tenant)
    if s:
        s.speed = float(speed)
        events.emit(tenant, "sim_status", {"running": s.running, "speed": s.speed}, s.now)
    return {"running": bool(s and s.running), "speed": float(speed)}


def stop(tenant):
    if tenant in SIMS:
        SIMS[tenant].stop()


def status(tenant):
    return SIMS[tenant].status() if tenant in SIMS else {"running": False, "sim_time": None, "speed": None,
                                                         "customers": [], "done": False}


# ---------------------------------------------------------------- scripted demo story

def load_story(tenant, log=None):
    """Deterministic demo storyline through the real agents (LLM replies, cached)."""
    from . import lab
    lab.SCRIPTED.add(tenant)
    try:
        return _story(tenant, log)
    finally:
        lab.SCRIPTED.discard(tenant)


def _story(tenant, log=None):
    tools.WORLDS[tenant] = WORLD
    cast = CASTS.get(tenant, CASTS["pml"])  # any other tenant (tests, a new workspace) gets the original cast
    a, b, here, there, tz = cast["a"], cast["b"], cast["from"], cast["to"], cast["tz"]
    sa, sb = f"{a.split()[0].lower()}-s1", f"{b.split()[0].lower()}-s1"
    intake, resolver = agents.Intake(), agents.Resolver()
    say = lambda c, s, at, text: intake.handle(tenant, customer=c, session_id=s, text=text, at=f"{at}{tz}", reply_llm=True,
                                              log=log)
    say(a, sa, "2026-09-01T09:30:00",
        f"Hi, I'm {a.split()[0]}. I live in {here}, I'm on the Fiber 300 plan, and WhatsApp is the best way to reach me.")
    say(a, sa, "2026-09-01T09:35:00", "My PS5 and my laptop both keep dropping wifi every evening.")
    say(b, sb, "2026-09-05T19:00:00", f"Hello, {b.split()[0]} here, I live in {there}. My wifi drops every evening.")
    b_t = agents.open_ticket_for(tenant, b, log)
    if b_t:
        resolver.pick_up(tenant, ticket=b_t, at=f"2026-09-06T10:00:00{tz}", log=log)
        resolver.try_fix(tenant, ticket=b_t, fix="restart router", worked=False, at=f"2026-09-06T11:00:00{tz}", log=log)
        resolver.try_fix(tenant, ticket=b_t, fix="change wifi channel", worked=True, at=f"2026-09-06T14:00:00{tz}", log=log)
    say(a, f"{a.split()[0].lower()}-s2", "2026-09-12T10:00:00", f"Quick update: I moved to {there} on the 10th.")
    a_t = agents.open_ticket_for(tenant, a, log)
    pick = resolver.pick_up(tenant, ticket=a_t, at=f"2026-09-13T10:00:00{tz}", log=log) if a_t else None
    residents = _residents(tenant, intake, resolver, tz, log)
    converse.summarize_session(tenant, sa, log)
    converse.summarize_session(tenant, sb, log)
    agents.consolidate(tenant, log, summaries=True)
    from . import lab  # after the scripted story: live chats from here on get the street-level network
    lab.ensure(tenant, log)
    return {"alice_ticket": a_t, "bob_ticket": b_t, "pickup": pick,  # keys kept: callers and tests read them
            "residents": residents}


def _residents(tenant, intake, resolver, tz, log=None):
    """The region's other customers, one case each, spread over the story's two weeks. Returns {name: ticket}."""
    out = {}
    for i, (name, where, plan, case) in enumerate(RESIDENTS.get(tenant, [])):
        lines, _, fix = CASES[case]
        day, sid = 2 + 3 * i, f"{name.split()[0].lower()}-s1"
        first = (f"Hi, I'm {name.split()[0]}, I live in {where} and I'm on the Fiber {plan} plan. " + lines[0])
        for k, text in enumerate([first] + lines[1:]):
            intake.handle(tenant, customer=name, session_id=sid, text=text, at=f"2026-09-{day:02d}T1{k}:00:00{tz}",
                          reply_llm=True, log=log)
        t = agents.open_ticket_for(tenant, name, log) if case not in ("sales",) else None
        if t and fix:
            resolver.pick_up(tenant, ticket=t, at=f"2026-09-{day + 1:02d}T09:00:00{tz}", log=log)
            resolver.try_fix(tenant, ticket=t, fix="restart router", worked=False, at=f"2026-09-{day + 1:02d}T10:00:00{tz}",
                             log=log)
            resolver.try_fix(tenant, ticket=t, fix=fix, worked=True, at=f"2026-09-{day + 1:02d}T13:00:00{tz}", log=log)
        out[name] = t
        converse.summarize_session(tenant, sid, log)
    return out
