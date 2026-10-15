"""Deterministic synthetic Ping Me Later scenario. Fictional company, fictional people.

python -m data.generate  ->  data/scenario.json, world.json, questions.json, gold.json

Every customer gets a seeded storyline (intro facts, moves, plan/router/channel changes, devices, tickets,
re-assertions, typos). Gold answers come from the storyline itself, so scoring is exact-match.
"""
import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent
SEED = 2041

NAMES = ["Bob Menon", "Carol Dsouza", "Dev Malhotra", "Esha Iyer", "Farhan Khan", "Gita Pillai", "Hari Kumar",
         "Ishaan Verma", "Jaya Reddy", "Kabir Singh", "Lata Joshi", "Manav Gupta", "Neha Kapoor", "Omar Siddiqui",
         "Pooja Bhat", "Qasim Ali", "Ritu Saxena", "Sanjay Patil", "Tara Banerjee", "Uday Rao", "Vikram Desai",
         "Wasim Akhtar", "Yamini Krishnan", "Zoya Mirza", "Aditi Kulkarni", "Bhavna Shetty", "Chirag Jain",
         "Divya Menon", "Eshan Ghosh", "Fatima Sheikh", "Gaurav Chawla", "Hema Subramanian"]
COLLISIONS = [("Alice Rao", "Alice Roy"), ("Rahul Shah", "Rahul Sharma"), ("Priya Nair", "Priya Naik"),
              ("Arjun Mehta", "Arjun Mehra")]
ALL_NAMES = NAMES + [n for pair in COLLISIONS for n in pair]

AREAS = ["Pune", "Mumbai", "Bengaluru", "Hyderabad", "Thane", "Nashik", "Mysuru", "Secunderabad", "Navi Mumbai",
         "Pimpri"]
TYPOS = {"Pune": "Puen", "Mumbai": "Mumbia", "Bengaluru": "Bengalru", "Hyderabad": "Hydrabad", "Thane": "Tahne",
         "Nashik": "Nasik", "Mysuru": "Mysru", "Secunderabad": "Secundrabad", "Navi Mumbai": "Navi Mumbia",
         "Pimpri": "Pimpri"}
OUTAGE_NAMES = {"pune": "fiber cut on fc road", "mumbai": "flooded junction box in andheri",
                "bengaluru": "fiber cut on outer ring road", "hyderabad": "substation failure in gachibowli",
                "thane": "power maintenance in ghodbunder", "nashik": "backhaul fault in college road",
                "mysuru": "cabinet fire in vijayanagar", "secunderabad": "cable theft near paradise circle",
                "navi mumbai": "olt failure in vashi", "pimpri": "road works cut in chinchwad"}
PLANS = ["Basic 50", "Fiber 100", "Fiber 300", "Fiber 1000"]
ROUTERS = ["PML Hub 6", "PML Hub 6 Pro", "AX1800", "AX3000", "AX5400"]
CHANNELS = ["WhatsApp", "email", "phone", "SMS"]
DEVICES = ["PS5", "Xbox", "laptop", "smart TV", "iPhone", "iPad", "desktop PC", "Android phone", "Echo Dot"]

# issue cluster: (phrasings, effective fix, wrong fix, diagnostic). Phrasings of one cluster should merge into
# one entity; different clusters (slow vs latency is the hard pair) should stay apart.
ISSUES = {
    "evening_drops": (["My wifi keeps dropping every evening.", "The connection cuts out at night, it's really annoying.",
                       "Every evening the internet disconnects for a few minutes."],
                      "change wifi channel", "restart router", "channel congestion on 2.4 ghz"),
    "slow": (["My internet has been really slow for two days.", "Speeds are crawling, pages take forever to load.",
              "I'm getting a fraction of the speed I pay for."],
             "reset line profile", "restart router", "high line attenuation"),
    "no_internet": (["There's no internet at all since this morning.", "The internet is completely down at my place.",
                     "Nothing connects, the internet is totally dead."],
                    "replace fiber cable", "restart router", "optical signal loss"),
    "reboots": (["My router keeps restarting by itself.", "The router reboots on its own every few hours.",
                 "My router randomly switches off and comes back on."],
                "firmware update", "factory reset", "firmware crash loop"),
    "latency": (["Online games lag terribly, the ping is through the roof.", "Video calls freeze and games lag constantly.",
                 "Latency spikes make online gaming impossible."],
                "enable qos", "restart router", "bufferbloat under load"),
    "weak_range": (["Wifi barely reaches my bedroom.", "The signal is weak in the far rooms of the flat.",
                    "Rooms away from the router get almost no wifi."],
                   "add mesh extender", "move router", "weak signal in far rooms"),
}
ISSUE_LABEL = {"evening_drops": "evening wifi drops", "slow": "slow speeds", "no_internet": "no internet at all",
               "reboots": "the router rebooting by itself", "latency": "gaming lag and high latency",
               "weak_range": "weak wifi in far rooms"}

T = {
    "lives_in": ["I live in {x}.", "We're based in {x}.", "Our flat is in {x}.", "My place is in {x}."],
    "moved": ["I moved to {x} today.", "We've just shifted to {x}, today actually.", "As of today we live in {x}."],
    "moved_on": ["Forgot to mention, I've been living in {x} since {d}.",
                 "Quick update: I actually moved to {x} on {d}, sorry for not telling you earlier.",
                 "We relocated to {x} back on {d}, should have told you then."],
    "plan": ["I'm on the {x} plan.", "My plan is {x}.", "We pay for {x}."],
    "plan_change": ["I switched my plan to {x} today.", "I changed to the {x} plan this morning.",
                    "Moved my plan to {x} today."],
    "router": ["My router is an {x}.", "I use the {x} router.", "The router at home is the {x} model."],
    "router_change": ["Your technician swapped my router for a {x} today.", "I got a new {x} router today.",
                      "We replaced the router with a {x} this morning."],
    "channel": ["Please reach me by {x}.", "{X} is the best way to reach me.", "{X} works best for me."],
    "channel_change": ["Actually, please use {x} from now on instead.", "From now on please reach me by {x}, not the old way.",
                       "Switch my contact preference to {x}, please."],
    "device": ["I also have a {x} on the wifi.", "My {x} is connected too.", "We use a {x} at home as well."],
    "devices": ["My {x} and {y} both lose connection sometimes.", "We have a {x} and a {y} on the network.",
                "Both my {x} and my {y} use the wifi."],
    "re_city": ["Like I said, I'm in {x} now.", "Again, we're still in {x}.", "Still living in {x}, same as before."],
    "re_plan": ["Again, it's {x} I'm paying for.", "As I told you, my plan is {x}.", "My plan is still {x}."],
}
NOISE = ["Hi there!", "Thanks for the quick reply.", "When is my bill due this month?", "I work from home most days.",
         "Okay, I'll wait for your update.", "Can you send me last month's invoice?", "I'm usually free after 6pm.",
         "Sorry, I was away for a bit.", "Do you have any offers on annual plans?", "Good morning!",
         "My sister in Delhi uses Ping Me Later too.", "Is there a way to check my data usage?", "Great, appreciate it.",
         "pls send the bill asap", "ok thx", "My neighbour just switched to Ping Me Later as well."]


def key(s):
    return " ".join(s.lower().split())


def fmt_day(d):
    return f"{d:%B} {d.day}"


class Customer:
    def __init__(self, name):
        self.name, self.key = name, key(name)
        self.sessions = []        # [date, [turn dicts]]
        self.steps = []           # resolver steps
        self.log = []             # (pred, value, valid_from, told_at) as intake hears it
        self.devices = []
        self.tickets = []         # dicts
        self.changes = []         # component gold for contradiction handling


def build(rng):
    names = ALL_NAMES[:]
    customers = [Customer(n) for n in names]
    idx = list(range(len(customers)))
    collide = {c.key for c in customers if any(c.name in p for p in COLLISIONS)}

    def pick(n, pool=None):
        return set(rng.sample(sorted(pool if pool is not None else idx), n))

    ticket = pick(26)
    second_ticket = pick(6, ticket)
    mismatch = pick(16, ticket)
    movers = pick(14)
    backdated = pick(9, movers)
    plan_change = pick(10, set(idx) - mismatch)
    router_change = pick(8)
    channel_change = pick(8)
    device_add = pick(16)
    reassert = pick(14)
    typo = pick(8, reassert)
    wrong_first = pick(16, ticket)
    unresolved = pick(6, ticket - second_ticket)
    ticket_no = [2040]
    plants = []  # per-turn plant annotations are inside turns

    for i, c in enumerate(customers):
        d1 = datetime(2026, 9, 1, 10) + timedelta(days=rng.randint(0, 6))
        dates = [d1]
        for _ in range(3):
            dates.append(dates[-1] + timedelta(days=rng.randint(7, 10)))
        dates = [d for d in dates if d < datetime(2026, 10, 14)]
        sess = [[d, []] for d in dates]
        city = rng.choice(AREAS)
        # collision pairs get deliberately different values
        plan, router = rng.choice(PLANS), (rng.choice(ROUTERS) if rng.random() < 0.6 or c.key in collide else None)
        channel = rng.choice(CHANNELS) if rng.random() < 0.75 or i in channel_change else None
        s1 = sess[0][1]

        def say(s, kind, x, pred, at_day=None, plant=None, **fmtkw):
            text = rng.choice(T[kind]).format(x=x, X=x[0].upper() + x[1:], **fmtkw)
            s.append({"text": text, "expect": [[pred, key(x)]], "plants": [plant] if plant else []})
            return text

        say(s1, "lives_in", city, "lives_in")
        c.log.append(("lives_in", key(city), d1, d1))
        say(s1, "plan", plan, "on_plan")
        c.log.append(("on_plan", key(plan), d1, d1))
        if router:
            say(s1, "router", router, "has_router")
            c.log.append(("has_router", key(router), d1, d1))
        if channel:
            say(s1, "channel", channel, "prefers_channel")
            c.log.append(("prefers_channel", key(channel), d1, d1))
        for dev in rng.sample(DEVICES, rng.choice([0, 1, 2, 2])):
            say(s1, "device", dev, "owns_device")
            c.devices.append(key(dev))

        later = sess[1:]

        def later_session(k):
            return later[min(k, len(later) - 1)]

        # tickets: first in session 2, second in the last session (after the first is resolved)
        if i in ticket:
            for t_n, s in enumerate([later_session(0)] + ([later_session(2)] if i in second_ticket and len(later) >= 3 else [])):
                # a repeat of the same issue would corroborate the old reported_issue fact, not open a ticket
                cluster = rng.choice(sorted(set(ISSUES) - {t["cluster"] for t in c.tickets}))
                phrases, fix, wrong, _ = ISSUES[cluster]
                ticket_no[0] += 1
                tid = f"PML-{ticket_no[0]}"
                s[1].append({"text": rng.choice(phrases), "expect": [["reported_issue", None]], "ticket_id": tid,
                             "plants": [{"kind": "issue", "cluster": cluster}]})
                d = s[0]
                tk = {"id": tid, "cluster": cluster, "opened": d, "tried": [], "fix": None}
                c.steps.append({"type": "pick_up", "ticket": tid, "at": (d + timedelta(days=1)).replace(hour=15)})
                if i in wrong_first:
                    c.steps.append({"type": "try_fix", "ticket": tid, "fix": wrong, "worked": False,
                                    "at": (d + timedelta(days=2)).replace(hour=16)})
                    tk["tried"].append(wrong)
                if not (i in unresolved and t_n == 0):
                    c.steps.append({"type": "try_fix", "ticket": tid, "fix": fix, "worked": True,
                                    "at": (d + timedelta(days=3)).replace(hour=16)})
                    tk["tried"].append(fix)
                    tk["fix"] = fix
                tk["pickup"] = (d + timedelta(days=1)).replace(hour=15)
                c.tickets.append(tk)
            if len(c.tickets) == 2 and c.tickets[0]["fix"] is None:
                c.tickets.pop()  # can't open a second ticket while the first is still open
                c.steps = [s for s in c.steps if s["ticket"] == c.tickets[0]["id"]]
                for s in later:
                    s[1] = [t for t in s[1] if t.get("ticket_id") in (None, c.tickets[0]["id"])]

        def change(pred, kind, values, current, store_as):
            s = later_session(1)
            new = rng.choice([v for v in values if key(v) != current])
            say(s[1], kind, new, pred, plant={"kind": "change", "pred": pred, "old": current, "new": key(new)})
            c.log.append((pred, key(new), s[0], s[0]))
            c.changes.append({"case": "change", "pred": pred, "old": current, "new": key(new)})
            return key(new)

        if i in movers:
            s = later_session(1)
            new = rng.choice([a for a in AREAS if a != city])
            if i in backdated:
                prev_day = sess[sess.index(s) - 1][0]
                moved = (s[0] - timedelta(days=rng.randint(3, (s[0] - prev_day).days - 1))).replace(hour=0)
                say(s[1], "moved_on", new, "lives_in", d=fmt_day(moved),
                    plant={"kind": "change", "pred": "lives_in", "old": key(city), "new": key(new), "backdated": True})
                c.log.append(("lives_in", key(new), moved, s[0]))
            else:
                say(s[1], "moved", new, "lives_in", plant={"kind": "change", "pred": "lives_in", "old": key(city), "new": key(new)})
                c.log.append(("lives_in", key(new), s[0], s[0]))
            c.changes.append({"case": "change", "pred": "lives_in", "old": key(city), "new": key(new)})
            city = new
        if i in plan_change:
            plan = change("on_plan", "plan_change", PLANS, key(plan), "plan")
        if i in router_change and router:
            router = change("has_router", "router_change", ROUTERS, key(router), "router")
        if i in channel_change and channel:
            channel = change("prefers_channel", "channel_change", CHANNELS, key(channel), "channel")
        if i in device_add:
            s = later_session(rng.randint(1, 2))
            dev = rng.choice([d for d in DEVICES if key(d) not in c.devices])
            say(s[1], "device", dev, "owns_device", plant={"kind": "multi", "pred": "owns_device", "new": key(dev)})
            c.devices.append(key(dev))
            c.changes.append({"case": "multi", "pred": "owns_device", "old": c.devices[0] if len(c.devices) > 1 else None,
                              "new": key(dev)})
        if i in reassert:
            s = later[-1]
            if rng.random() < 0.5 or i in typo:
                val = city
                shown = TYPOS.get(city, city) if i in typo else city
                text = rng.choice(T["re_city"]).format(x=shown)
                s[1].append({"text": text, "expect": [["lives_in", key(val)]],
                             "plants": [{"kind": "unchanged", "pred": "lives_in", "value": key(val),
                                         **({"typo": key(shown)} if i in typo else {})}]})
                c.changes.append({"case": "unchanged", "pred": "lives_in", "new": key(val), "typo": i in typo})
            else:
                text = rng.choice(T["re_plan"]).format(x=plan if isinstance(plan, str) and plan[0].isupper() else plan)
                s[1].append({"text": text, "expect": [["on_plan", key(plan)]],
                             "plants": [{"kind": "unchanged", "pred": "on_plan", "value": key(plan)}]})
                c.changes.append({"case": "unchanged", "pred": "on_plan", "new": key(plan), "typo": False})
        for s in sess:
            for _ in range(rng.randint(1, 2)):
                s[1].insert(rng.randint(0, len(s[1])), {"text": rng.choice(NOISE), "expect": [], "plants": []})
        c.sessions = sess
        c.final = {"lives_in": key(city), "on_plan": key(plan) if isinstance(plan, str) else plan,
                   "has_router": key(router) if router else None, "prefers_channel": key(channel) if channel else None}
        c.mismatch = i in mismatch
    return customers


def city_on_file(c, when):
    vals = [(told, v) for p, v, _, told in c.log if p == "lives_in" and told <= when]
    return max(vals)[1] if vals else None


def value_at(c, pred, t, clock):
    """world: valid_from <= t (as known by the end); belief: told <= t."""
    entries = sorted((vf, told, v) for p, v, vf, told in c.log if p == pred)
    if clock == "world":
        cur = [v for vf, _, v in entries if vf <= t]
    else:
        cur = [v for _, told, v in sorted(entries, key=lambda e: e[1]) if told <= t]
    return cur[-1] if cur else None


def q(type_, text, gold, asked_by="resolver", conflict=False, unknown=False, collision=False):
    return {"type": type_, "question": text, "gold": gold, "asked_by": asked_by,
            "expect_conflict": conflict, "expect_unknown": unknown, "collision": collision}


def questions(customers, world, rng):
    out = []
    collide = {key(n) for p in COLLISIONS for n in p}
    by = {c.key: c for c in customers}
    outage_areas = {o["area"] for o in world["outages"]}
    changed = lambda pred: [c for c in customers if any(ch["pred"] == pred and ch["case"] == "change" for ch in c.changes)]

    def add(n, items):
        rng.shuffle(items)
        out.extend(items[:n])

    # current truth (prefer customers whose value changed; plus collision pairs)
    cur = [q("current", f"Where does {c.name} live now?", [c.final["lives_in"]], "intake", collision=c.key in collide)
           for c in changed("lives_in")]
    cur += [q("current", f"Which plan is {c.name} on?", [c.final["on_plan"]], "intake") for c in changed("on_plan")]
    cur += [q("current", f"What router does {c.name} have now?", [c.final["has_router"]]) for c in changed("has_router")]
    cur += [q("current", f"How does {c.name} want to be contacted now?", [c.final["prefers_channel"]], "intake")
            for c in changed("prefers_channel")]
    cur += [q("current", f"What is the status of {c.name}'s ticket {t['id']}?",
              ["resolved" if t["fix"] else "in progress"], "intake") for c in customers for t in c.tickets]
    coll = [q("current", f"Which city does {c.name} live in?", [c.final["lives_in"]], collision=True)
            for c in customers if c.key in collide]
    add(10, cur)
    out.extend(coll[:8])

    # world clock and system clock
    wt, bt = [], []
    for c in customers:
        for ch in c.changes:
            if ch["case"] != "change":
                continue
            entries = sorted((vf, told, v) for p, v, vf, told in c.log if p == ch["pred"])
            (vf0, told0, v0), (vf1, told1, v1) = entries[0], entries[-1]
            label = {"lives_in": "Where did {n} actually live on {d}?", "on_plan": "Which plan was {n} on on {d}?",
                     "has_router": "Which router did {n} have on {d}?",
                     "prefers_channel": "Which contact channel did {n} prefer on {d}?"}[ch["pred"]]
            before = vf0 + (vf1 - vf0) / 2
            after = told1 + timedelta(days=2)
            wt.append(q("world_time", label.format(n=c.name, d=f"{before:%Y-%m-%d}"), [value_at(c, ch["pred"], before, "world")]))
            if after < datetime(2026, 10, 20):
                wt.append(q("world_time", label.format(n=c.name, d=f"{after:%Y-%m-%d}"), [value_at(c, ch["pred"], after, "world")]))
            if told1 > vf1:  # backdated: between the real move and when we were told, world and records disagree
                mid = vf1 + (told1 - vf1) / 2
                bt.append(q("belief_time", f"On {mid:%Y-%m-%d}, which city did our records list for {c.name}?",
                            [value_at(c, "lives_in", mid, "belief")]))
                wt.append(q("world_time", f"Where did {c.name} actually live on {mid:%Y-%m-%d}?",
                            [value_at(c, "lives_in", mid, "world")]))
                bt.append(q("belief_time", f"On {after:%Y-%m-%d}, which city did our records list for {c.name}?",
                            [value_at(c, "lives_in", after, "belief")]))
            elif ch["pred"] != "lives_in":
                mid = vf0 + (vf1 - vf0) / 2
                field = {"on_plan": "plan", "has_router": "router", "prefers_channel": "contact channel"}[ch["pred"]]
                bt.append(q("belief_time", f"On {mid:%Y-%m-%d}, which {field} did our records list for {c.name}?",
                            [value_at(c, ch["pred"], mid, "belief")]))
    add(18, wt)
    add(18, bt)

    add(18, [q("completeness", f"Which devices does {c.name} own?", sorted(c.devices)) for c in customers
             if len(c.devices) >= 2])
    add(16, [q("disagreement", f"Which plan is {c.name} on, and is it disputed?", [c.final["on_plan"]], conflict=True)
             for c in customers if c.mismatch and c.tickets])

    ho = [q("handoff", f"What router does {c.name} have?", [c.final["has_router"]]) for c in customers
          if c.final["has_router"] and not any(ch["pred"] == "has_router" for ch in c.changes)]
    ho += [q("handoff", f"How should I contact {c.name}?", [c.final["prefers_channel"]]) for c in customers
           if c.final["prefers_channel"] and not any(ch["pred"] == "prefers_channel" for ch in c.changes)]
    add(18, ho)

    mh = [q("multi_hop", f"Which outage might be affecting {c.name}?", [world["outage_by_area"][c.final["lives_in"]]])
          for c in customers if c.final["lives_in"] in outage_areas]
    mh2 = [q("multi_hop", f"Which customers might be affected by the {o['name']}?",
             sorted(c.key for c in customers if c.final["lives_in"] == o["area"])) for o in world["outages"]]
    tq = []
    for c in customers:
        for t in c.tickets:
            tq.append(q("multi_hop", f"Which city does the customer with ticket {t['id']} live in?", [c.final["lives_in"]]))
            if not c.mismatch:
                tq.append(q("multi_hop", f"Which plan is the customer with ticket {t['id']} on?", [c.final["on_plan"]]))
            if c.final["has_router"]:
                tq.append(q("multi_hop", f"What router does the owner of ticket {t['id']} have?", [c.final["has_router"]]))
    rng.shuffle(mh)
    rng.shuffle(tq)
    out.extend(mh[:7] + mh2 + tq[:18 - 7 - len(mh2)])

    pr = [q("procedural", f"Which fix has worked before for {ISSUE_LABEL[cl]}?", [ISSUES[cl][1]])
          for cl in sorted({t["cluster"] for c in customers for t in c.tickets if t["fix"]})]
    pr2 = [q("procedural", f"What fixed {c.name}'s ticket {t['id']}?", [t["fix"]]) for c in customers for t in c.tickets if t["fix"]]
    pr3 = [q("procedural", f"Which fixes were tried on ticket {t['id']}?", sorted(t["tried"])) for c in customers
           for t in c.tickets if len(t["tried"]) >= 1]
    rng.shuffle(pr2)
    rng.shuffle(pr3)
    out.extend(pr + pr2[:(18 - len(pr)) // 2] + pr3[:18 - len(pr) - (18 - len(pr)) // 2])

    un = [q("unknown", f"What router does {c.name} have?", [], unknown=True) for c in customers if not c.final["has_router"]][:5]
    un += [q("unknown", f"What is the status of {c.name}'s ticket?", [], unknown=True) for c in customers if not c.tickets][:3]
    un += [q("unknown", f"Which city does {n} live in?", [], unknown=True)
           for n in ["Alice Rai", "Ivan Shah", "Rahul Shetty", "Meera Iyer"]]
    un += [q("unknown", f"Which outage affects {a}?", [], unknown=True) for a in AREAS if key(a) not in outage_areas][:2]
    un += [q("unknown", f"What is {c.name}'s email address?", [], unknown=True) for c in customers[:2]]
    un += [q("unknown", f"What fixed ticket {t['id']}?", [], unknown=True) for c in customers for t in c.tickets if not t["fix"]][:2]
    un += [q("unknown", f"How does {c.name} prefer to be contacted?", [], unknown=True) for c in customers
           if not c.final["prefers_channel"]][:2]
    out.extend(un[:18])
    for i, item in enumerate(out):
        item["i"] = i
    return out


def main():
    rng = random.Random(SEED)
    customers = build(rng)
    events = []
    for c in customers:
        for n, (d, turns) in enumerate(c.sessions, 1):
            for j, t in enumerate(turns):
                events.append({"type": "turn", "customer": c.key, "session_id": f"{c.key.replace(' ', '-')}-s{n}",
                               "at": (d + timedelta(minutes=2 * j)).isoformat(), "text": t["text"], "expect": t["expect"],
                               "ticket_id": t.get("ticket_id"), "plants": t["plants"]})
        for s in c.steps:
            events.append({**s, "customer": c.key, "at": s["at"].isoformat()})
    events.sort(key=lambda e: e["at"])

    # outages live in the 4 areas where most tickets are picked up (the resolver's outage tool fires at pickup)
    pick_city = Counter(city_on_file(c, t["pickup"]) for c in customers for t in c.tickets)
    areas = [a for a, _ in pick_city.most_common(4)]
    world = {"billing": {c.key: key(rng.choice([p for p in PLANS if key(p) != c.final["on_plan"]]))
                         for c in customers if c.mismatch and c.tickets},
             "outages": [{"name": OUTAGE_NAMES[a], "area": a, "cities": [a]} for a in areas],
             "diagnostics": {c.key: ISSUES[c.tickets[0]["cluster"]][3] for c in customers if c.tickets}}
    world["outage_by_area"] = {o["area"]: o["name"] for o in world["outages"]}
    qs = questions(customers, world, rng)
    gold = {"collisions": [[key(a), key(b)] for a, b in COLLISIONS],
            "changes": [{"customer": c.key, **ch} for c in customers for ch in c.changes]
                       + [{"customer": c.key, "case": "cross_agent", "pred": "on_plan", "new": c.final["on_plan"],
                           "old": world["billing"][c.key]} for c in customers if c.key in world["billing"]],
            "issue_clusters": {k: v[0] for k, v in ISSUES.items()},
            "facts": [{"customer": c.key, "pred": p, "value": v} for c in customers for p, v in c.final.items() if v]
                     + [{"customer": c.key, "pred": "owns_device", "value": d} for c in customers for d in c.devices]}
    (OUT / "scenario.json").write_text(json.dumps({"company": "Ping Me Later", "customers": [c.key for c in customers],
                                                    "events": events}, indent=1))
    (OUT / "world.json").write_text(json.dumps(world, indent=1))
    (OUT / "questions.json").write_text(json.dumps(qs, indent=1))
    (OUT / "gold.json").write_text(json.dumps(gold, indent=1))
    turns = [e for e in events if e["type"] == "turn"]
    print(f"{len(customers)} customers, {len(turns)} customer turns, {len(events) - len(turns)} resolver steps, "
          f"{sum(len(e['expect']) for e in turns)} planted facts, {len(qs)} questions: {dict(Counter(x['type'] for x in qs))}")
    print("changes:", dict(Counter(ch["case"] for ch in gold["changes"])), "outage areas:", areas)


if __name__ == "__main__":
    main()
