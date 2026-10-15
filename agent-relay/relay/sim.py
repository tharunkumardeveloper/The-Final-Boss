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
    tools.WORLDS[tenant] = WORLD
    intake, resolver = agents.Intake(), agents.Resolver()
    say = lambda c, s, at, text: intake.handle(tenant, customer=c, session_id=s, text=text, at=at, reply_llm=True, log=log)
    say("Alice Rao", "alice-s1", "2026-09-01T09:30:00+05:30",
        "Hi, I'm Alice. I live in Mumbai, I'm on the Fiber 300 plan, and WhatsApp is the best way to reach me.")
    say("Alice Rao", "alice-s1", "2026-09-01T09:35:00+05:30", "My PS5 and my laptop both keep dropping wifi every evening.")
    say("Bob Menon", "bob-s1", "2026-09-05T19:00:00+05:30", "Hello, Bob here, I live in Pune. My wifi drops every evening.")
    bob_t = agents.open_ticket_for(tenant, "Bob Menon", log)
    if bob_t:
        resolver.pick_up(tenant, ticket=bob_t, at="2026-09-06T10:00:00+05:30", log=log)
        resolver.try_fix(tenant, ticket=bob_t, fix="restart router", worked=False, at="2026-09-06T11:00:00+05:30", log=log)
        resolver.try_fix(tenant, ticket=bob_t, fix="change wifi channel", worked=True, at="2026-09-06T14:00:00+05:30", log=log)
    say("Alice Rao", "alice-s2", "2026-09-12T10:00:00+05:30", "Quick update: I moved to Pune on the 10th.")
    alice_t = agents.open_ticket_for(tenant, "Alice Rao", log)
    pick = resolver.pick_up(tenant, ticket=alice_t, at="2026-09-13T10:00:00+05:30", log=log) if alice_t else None
    converse.summarize_session(tenant, "alice-s1", log)
    converse.summarize_session(tenant, "bob-s1", log)
    agents.consolidate(tenant, log, summaries=True)
    from . import lab  # after the scripted story: live chats from here on get the street-level network
    lab.ensure(tenant, log)
    return {"alice_ticket": alice_t, "bob_ticket": bob_t, "pickup": pick}
