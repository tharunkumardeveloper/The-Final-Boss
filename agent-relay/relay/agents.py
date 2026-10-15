"""Two agents sharing one tenant graph. Intake talks to customers; resolver works tickets with tools.
Neither keeps private state: everything they know comes from, and goes back to, the graph."""
import re
import threading
import uuid
from . import config, converse, db, events, intake, memory, queries as Q, registry as R, retrieve, sharing, tools
from .memory import norm, to_ms


def tickets(tenant, log=None):
    rows = db.run(tenant, "tickets", Q.TICKETS, log=log, ro=True)
    return [{"ticket": t, "status": st, "assigned_to": a, "customer": c, "issues": iss} for t, st, a, c, iss in rows]


def open_ticket_for(tenant, customer, log=None):
    for t in tickets(tenant, log):
        if t["customer"] == norm(customer) and t["status"] != "resolved":
            return t["ticket"]
    return None


def next_ticket_id(tenant, log=None):
    # Short uuid suffix makes concurrent intakes produce distinct ids even at the same count.
    return f"pml-{2041 + len(tickets(tenant, log))}-{uuid.uuid4().hex[:4]}"


def sweep_outages(tenant, at, city=None, log=None):
    """Retire outages the resolver recorded from the feed that the feed no longer reports (fixed, or a story that
    ended). NOC outages are retired by the NOC on restore, so they're left alone."""
    retired = []
    at_ms = to_ms(at)
    for outage, place in db.run(tenant, "feed outages", Q.FEED_OUTAGES, {"city": city}, log, ro=True):
        if outage not in tools.outages_in(place, tenant, at_ms):
            ep = memory.remember(tenant, agent="resolver", session_id=f"outage-{norm(outage).replace(' ', '-')}",
                                 customer=None, at=at, speaker="tool:outage", facts=[],
                                 text=f"Outage feed: {outage} is no longer reported for {place}", log=log)["episode_id"]
            retired += memory.retire_fact(tenant, agent="resolver", episode_id=ep, subject=outage, predicate="affects",
                                          obj=place, at=at, log=log)
            db.run(tenant, "outage state", Q.OUTAGE_STATE, {"o": outage, "active": False, "at": at_ms,
                                                            "at_dt": memory.dt(at_ms), "eta": None, "eta_dt": None}, log)
            events.emit(tenant, "outage_resolved", {"node": outage, "label": outage.title()}, at_ms)
    return retired


def handoff_trail(tenant, ticket, log=None):
    return db.run(tenant, "handoff trail", Q.HANDOFF_TRAIL, {"ticket": ticket}, log, ro=True)


def _learned(facts, retired=()):
    """What changed, as plain phrases ("now lives in Madurai, was Chennai"): this text reaches the reply model."""
    from .cards import VERB
    verb = lambda p: VERB.get(p, R.attribute(p))
    out = []
    for f in facts:
        s, p, o = f["triple"]
        if f["superseded"]:
            out.append(f"now {verb(p)} {o} (was {', '.join(x['object'] for x in f['superseded'])})")
        elif f["status"] == "new":
            out.append(f"{verb(p)} {o}")
    out += [f"no longer {verb(r['triple'][1])} {r['triple'][2]}" for r in retired]
    return out


class Intake:
    id = "intake"

    def handle(self, tenant, *, customer, session_id, text, at, ticket_id=None, reply_llm=False, greeted=False,
               country=None, log=None):
        """One customer message. Learns facts; opens a ticket and hands it to the resolver on a new issue.
        reply_llm: write the reply with the LLM, grounded in memory (otherwise a template, no LLM call)."""
        ticket = open_ticket_for(tenant, customer, log)
        intake.step(tenant, customer, "Noting what you just told me", at)
        asked = next((tx for sp, tx, _, _ in reversed(converse.session_turns(tenant, session_id, log))
                      if sp == "agent" and "?" in tx), None)
        res = memory.ingest_turn(tenant, agent=self.id, session_id=session_id, customer=customer, text=text,
                                 at=at, ticket=ticket, log=log, tolerate_outage=reply_llm, asked=asked)
        new = lambda p: [f["triple"][2] for f in res["facts"] if f["triple"][1] == p and f["status"] == "new"]
        from . import kb, network
        for place in new("lives_in"):  # a locality we don't list ("Pattabiram"): the city they named gets them a line
            if not kb.resolve_place(place) and (city := kb.resolve_place(text)):
                network.attach(tenant, norm(customer), city["key"], log)
        # a problem, or a request our team has to action (pause, cancel, billing dispute...), opens a ticket
        held = res.get("held", [])
        issues = new("reported_issue") + [r.replace("_", " ") for r in new("service_request")]
        if not issues and not ticket:  # the model gave only ticket details ("issue_type: wifi drops"): still a problem
            issues = [o for p, o, _ in held if p == "issue_type"][:1]
        if not issues and not ticket and (m := intake.PROBLEM.search(text)):  # ...or nothing at all ("my net isnt working")
            issues = [intake.problem_name(m)]
            memory.remember(tenant, agent=self.id, session_id=session_id, customer=norm(customer), at=at,
                            facts=[(norm(customer), "reported_issue", issues[0])],
                            text=f"intake noted a problem the model didn't extract: {issues[0]}", log=log)
        opened = None
        c = norm(customer)
        if issues and not ticket:
            opened = norm(ticket_id or next_ticket_id(tenant, log))
            kind = next((o for p, o, _ in held if p == "issue_type"),
                        next(iter(new("service_request")), None))
            facts = [(c, "has_ticket", opened), (opened, "ticket_about", issues[0]),
                     (opened, "has_status", "open"), (opened, "assigned_to", "resolver")]
            facts += [(opened, "issue_type", kind)] if kind and not any(p == "issue_type" for p, _, _ in held) else []
            memory.remember(tenant, agent=self.id, session_id=session_id, customer=c, at=at,
                            text=f"intake opened {opened.upper()} for {c} about {issues[0]} and handed it to resolver",
                            facts=facts + [(opened, p, o, vf) for p, o, vf in held], log=log)
            db.run(tenant, "handoff", Q.HANDOFF, {"from_agent": self.id, "ticket": opened, "at": to_ms(at),
                                                  "to_agent": "resolver", "note": issues[0]}, log)
            db.run(tenant, "ticket raised in", Q.TICKET_RAISED_IN, {"t": opened, "sid": session_id}, log)
            if "service_pause" in new("service_request"):
                db.run(tenant, "service pause", Q.SERVICE_PAUSE, {"c": c, "t": opened, "id": memory._id("pause"),
                                                                 "reason": text, "at": to_ms(at), "at_dt": memory.dt(at)}, log)
            db.run(tenant, "ticket profile", Q.TICKET_PROFILE, {"t": opened}, log)
            events.emit(tenant, "ticket_opened", {"ticket": opened.upper(), "customer": c, "issue": issues[0]}, to_ms(at))
            events.emit(tenant, "handoff", {"ticket": opened.upper(), "from": self.id, "to": "resolver", "note": issues[0],
                                            "customer": c, "issue_type": kind, "priority": "normal",
                                            "context_nodes": [f"Customer:{c}", f"Session:{session_id}"]}, to_ms(at))
            if reply_llm:
                _at, _tenant, _opened, _sid = to_ms(at), tenant, opened, session_id
                def _auto_pickup():
                    try:
                        converse.summarize_session(_tenant, _sid, log=[])
                    except Exception as e:
                        print(f"session summary after handoff: {e}")
                    try:
                        Resolver().pick_up(_tenant, ticket=_opened, at=_at + 3000, log=[],
                                           chat_session_id=_sid)
                    except Exception as e:
                        print(f"auto-pickup {_opened}: {e}")
                threading.Thread(target=_auto_pickup, daemon=True).start()
        learned = _learned(res["facts"], res.get("retired", []))
        learned += [f"order {o['order_id']} for {o['plan']} is {o['status']} (installation within {o['eta_hours']} hours"
                    + ")" for o in res.get("orders", [])]
        reply = None
        if converse.is_data_request(text):  # the team sees the attempt; the customer only sees the policy
            memory.remember(tenant, agent="intake", session_id=session_id, customer=customer, at=at, facts=[],
                            text=f"intake declined a request for customer data and pointed to the legal team: {text}",
                            log=log)
        if reply_llm:
            reply = converse.intake_reply(tenant, customer=norm(customer), session_id=session_id, text=text,
                                          learned=learned, ticket=ticket, opened=opened, at=at, greeted=greeted,
                                          country=country, log=log)
        reply = reply or self._template(learned, opened, text)
        if ticket or opened:  # the ticket node carries what intake learned this turn (priority, details)
            db.run(tenant, "ticket profile", Q.TICKET_PROFILE, {"t": ticket or opened}, log)
        db.run(tenant, "link sessions", Q.LINK_SESSIONS, {"c": c}, log)
        if res.get("extraction_failed"):
            reply += " (Heads up: my note-taking is paused for a few minutes, so I may ask you to repeat that later.)"
        reply_eid = None
        if reply_llm:  # the agent's side of the conversation is episodic memory too
            reply_eid = memory.record_episode(tenant, agent=self.id, session_id=session_id, customer=customer,
                                              text=reply, at=to_ms(at) + 1000, speaker="agent", log=log)
        return {**res, "ticket_opened": opened, "reply": reply, "reply_episode_id": reply_eid}

    @staticmethod
    def _template(learned, opened, text=""):
        """The reply when no model is available: still a useful next step, never a bare 'got it'."""
        if opened:
            return f"I've opened ticket {opened.upper()} and our resolver is on it. They'll message you right here."
        if intake.PROBLEM.search(text or "") or re.search(r"\b(issue|problem|not working|broken|help)\b", text or "", re.I):
            return "Sorry to hear that. Tell me what's happening in your own words, and I'll get it looked at straight away."
        return "Got it, thanks. What can I help you with today?" if learned else "Got it. What can I help you with today?"


class Resolver:
    id = "resolver"

    def pick_up(self, tenant, *, ticket, at, log=None, chat_session_id=None):
        """Take a ticket, consult tools, write observations back to shared memory, suggest known fixes."""
        ticket = norm(ticket)
        all_tickets = tickets(tenant, log)
        info = next((t for t in all_tickets if t["ticket"] == ticket), None)
        if info is None or info["status"] in ("in progress", "resolved"):
            return {"ticket": ticket, "customer": info["customer"] if info else "", "observations": [], "suggestions": [], "technician": None}
        customer, sid, at_ms = info["customer"], f"work-{ticket}", to_ms(at)
        db.run(tenant, "pick up", Q.PICKUP, {"agent": self.id, "ticket": ticket, "at": at_ms}, log)
        events.emit(tenant, "pickup", {"ticket": ticket.upper(), "agent": self.id}, at_ms)
        memory.remember(tenant, agent=self.id, session_id=sid, customer=customer, at=at,
                        text=f"resolver picked up {ticket.upper()}", facts=[(ticket, "has_status", "in progress")],
                        log=log)
        from . import lab  # lazy: lab imports network, which imports this module
        if lab.lab_on(tenant) and lab.has_line(tenant, customer):  # diagnose, act and verify on the network graph
            rid = lab.start(tenant, customer, ticket=ticket, chat_sid=chat_session_id, picked=True)
            return {"ticket": ticket, "customer": customer, "observations": [], "suggestions": [], "technician": None,
                    "lab_run": rid}
        observations = []

        def observe(tool, text, facts):
            memory.remember(tenant, agent=self.id, session_id=sid, customer=customer, at=at, speaker=f"tool:{tool}",
                            text=text, facts=facts, log=log)
            events.emit(tenant, "tool_call", {"tool": tool, "customer": customer, "output": text}, at_ms)
            observations.append(text)

        plan = tools.billing_plan(customer, tenant)
        if plan:
            observe("billing", f"Billing system: {customer} is on plan {plan}", [(customer, "on_plan", plan)])
        city = retrieve.claims(tenant, customer, "lives_in", log)
        if city:  # the resolver knows where the customer lives because intake wrote it down
            sharing.consult(tenant, self.id, [city[0][0]], at=at, log=log)
        city = city[0][1] if city else None
        from . import experts, kb  # lazy: experts imports memory
        place = kb.resolve_place(city) if city else None
        home = place["city"] if place else None
        technician = experts.assign(tenant, ticket, home, at, log)
        for outage in tools.outages_in(city, tenant, at_ms) if city else []:
            observe("outage", f"Outage feed: {outage} affects {city}", [(outage, "affects", city)])
            db.run(tenant, "outage state", Q.OUTAGE_STATE, {"o": outage, "active": True, "at": at_ms,
                                                            "at_dt": memory.dt(at_ms), "eta": None, "eta_dt": None}, log)
        if city:
            sweep_outages(tenant, at, city=city, log=log)
        diag = tools.diagnostic(customer, tenant)
        if diag:
            observe("diagnostic", f"Router diagnostic for {customer}: {diag}", [(customer, "reported_issue", diag)])
        suggestions = {}
        for issue in info["issues"]:
            for fx, similar, dist, n in db.run(tenant, "fixes for similar issues", Q.FIXES_FOR_SIMILAR,
                                               {"issue": issue, "max_dist": config.SIMILAR_ISSUE_MAX_DIST}, log, ro=True):
                suggestions.setdefault(fx, {"issue": issue, "fix": fx, "worked_before": n, "for_issue": similar,
                                            "distance": round(dist, 3)})
        reply_text = converse.resolver_reply(customer, ticket, observations, suggestions)
        if reply_text is None:
            first_name = customer.split()[0].title()
            best = next(iter(suggestions.values()), None) if suggestions else None
            reply_text = (f"Hey {first_name}, I've picked up ticket {ticket.upper()}. "
                          + (f"Based on past cases '{best['fix']}' fixed this {best['worked_before']} time(s) — trying that first."
                             if best else "Looking into this now — I'll update you shortly."))
        # Write the reply into the customer's active chat session when known, else the work session
        reply_sid = chat_session_id or sid
        memory.remember(tenant, agent=self.id, session_id=reply_sid, customer=customer,
                        text=reply_text, at=to_ms(at) + 500, facts=[], speaker="agent", log=log)
        # Summarise the work session so it gets a human-readable label in conversation history
        try:
            converse.summarize_session(tenant, sid, log=[])
        except Exception:
            pass
        return {"ticket": ticket, "customer": customer, "observations": observations,
                "suggestions": list(suggestions.values()), "technician": technician}

    def try_fix(self, tenant, *, ticket, fix, worked, at, log=None, chat_session_id=None):
        ticket = norm(ticket)
        info = next(t for t in tickets(tenant, log) if t["ticket"] == ticket)
        customer = info["customer"]
        facts = [(ticket, "tried_fix", fix)]
        if worked:
            facts += [(fix, "resolves", i) for i in info["issues"]] + [(ticket, "has_status", "resolved")]
        out = memory.remember(tenant, agent=self.id, session_id=f"work-{ticket}", customer=customer, at=at,
                              text=f"resolver tried '{fix}' on {ticket.upper()}: {'worked' if worked else 'did not work'}",
                              facts=facts, log=log)
        db.run(tenant, "ticket profile", Q.TICKET_PROFILE, {"t": ticket}, log)
        # Notify the customer in their chat about the outcome
        first_name = customer.split()[0].title()
        if worked:
            customer_msg = (f"Good news, {first_name} — {fix.capitalize()} worked. "
                            f"Ticket {ticket.upper()} is closed. Let me know if anything comes back.")
            from .experts import VISIT_DONE
            db.run(tenant, "visit done", VISIT_DONE, {"ticket": ticket, "outcome": f"resolved by {fix}", "at": to_ms(at),
                                                      "at_dt": memory.dt(at)}, log)
        else:
            customer_msg = (f"Hey {first_name}, {fix.capitalize()} didn't fix it. "
                            f"I'm still on it — trying another approach for ticket {ticket.upper()}.")
        reply_sid = chat_session_id or f"work-{ticket}"
        memory.remember(tenant, agent=self.id, session_id=reply_sid, customer=customer,
                        text=customer_msg, at=to_ms(at) + 500, facts=[], speaker="agent", log=log)
        return out

    def ask(self, tenant, question, *, mode="full", log=None):
        return retrieve.ask(tenant, question, mode=mode, agent=self.id, log=log)


def consolidate(tenant, log=None, *, summaries=False):
    """Semantic consolidation with graph algorithms over current-world RELATED edges.
    summaries: also write an LLM one-liner on each top community (GraphRAG-style)."""
    present = [r for (r,) in db.run(tenant, "relationship types", Q.REL_TYPES_PRESENT, log=log, ro=True)]
    if not any(r in R.REL_TYPES for r in present):
        return []
    db.run(tenant, "label propagation", Q.communities(present), log=log)
    db.run(tenant, "pagerank", Q.SALIENCE, log=log)
    db.run(tenant, "community nodes", Q.BUILD_COMMUNITY_NODES, log=log)
    top = db.run(tenant, "top communities", Q.TOP_COMMUNITIES, {"n": 10}, log, ro=True)
    if summaries:
        top = [(cid, size, members, sal, converse.summarize_community(tenant, cid, members, log) or summ)
               for cid, size, members, sal, summ in top]
    return top
