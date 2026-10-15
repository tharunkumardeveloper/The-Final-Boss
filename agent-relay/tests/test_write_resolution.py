"""Write-path fixes from the scaled benchmark. No LLM calls. Run: python -m tests.test_write_resolution
1. a resolver pick-up on the network-lab path still reads billing and the outage feed into memory
2. misspelt places resolve to the place on file; "navi mumbai" stays navi mumbai
4. a customer's legacy plan ("basic 50") is kept; plans to buy still need the catalogue
5. an open invoice request doesn't swallow a new fault: the fault opens its own ticket
6. a topic word in a name slot ("for slow speeds") is not an unknown person; "for Kevin" still is
3. recall's fact cap drops the farthest facts first, never a 1-hop fact for a far one
7. the fix that worked is its own edge (ticket fixed_by fix), apart from everything tried; lab fixes use the team's names"""
from relay import queries as Q
from relay import agents, db, lab, llm, memory, retrieve, tools

T = "test-writeres"
AT = "2026-10-01T10:00:00+05:30"


def active(name, pred):
    return {o for _, p, o, act, *_ in retrieve.history(T, name) if act and p == pred}


def say(c, *facts, at=AT):
    return memory.remember(T, agent="intake", session_id=f"s-{c}", customer=c, at=at, text="test", facts=list(facts))


def pickup_reads_billing():
    c = "neha kapoor"
    say(c, (c, "lives_in", "thane"), (c, "has_ticket", "t-1"), ("t-1", "has_status", "open"),
        ("t-1", "ticket_about", "wifi drops"))
    assert lab.has_line(T, c), "lives_in attaches a line, so pick_up takes the lab path"
    tools.WORLDS[T] = {"billing": {c: "basic 50"}, "outages": [{"name": "fiber cut in thane", "cities": ["thane"]}]}
    started, real = [], lab.start
    lab.start = lambda *a, **k: started.append(a) or "run-x"  # the lab itself calls an LLM
    try:
        out = agents.Resolver().pick_up(T, ticket="t-1", at="2026-10-01T11:00:00+05:30", log=[])
    finally:
        lab.start = real
    assert started and out.get("lab_run") == "run-x"
    assert out["observations"] == [f"Billing system: {c} is on plan basic 50",
                                   "Outage feed: fiber cut in thane affects thane"], out
    assert active(c, "on_plan") == {"basic 50"}
    assert active("fiber cut in thane", "affects") == {"thane"}


def typos_and_long_names():
    say("jaya reddy", ("jaya reddy", "lives_in", "thane"))
    say("pooja bhat", ("pooja bhat", "lives_in", "nashik"))
    for c, said, want in [("jaya reddy", "Tahne", "thane"), ("pooja bhat", "Nasik", "nashik")]:
        out = say(c, (c, "lives_in", said), at="2026-10-02T10:00:00+05:30")
        assert out["facts"][0]["triple"][2] == want and out["facts"][0]["status"] == "corroborated", out["facts"]
        assert active(c, "lives_in") == {want}, "a typo must not supersede the place on file"
    assert db.run(T, "alias", "MATCH (e:Entity {name_key:'thane'}) RETURN e.aliases", ro=True) == [[["tahne"]]]
    say("priya nair", ("priya nair", "lives_in", "Navi Mumbai"))
    assert active("priya nair", "lives_in") == {"navi mumbai"}
    say("rahul shah", ("rahul shah", "lives_in", "mumbai"))
    assert active("rahul shah", "lives_in") == {"mumbai"}
    say("dev malhotra", ("dev malhotra", "on_plan", "fiber 100"))
    say("dev malhotra", ("dev malhotra", "on_plan", "fiber 300"), at="2026-10-02T10:00:00+05:30")
    assert active("dev malhotra", "on_plan") == {"fiber 300"}, "a real plan change is not a typo"
    say("zoya mirza", ("zoya mirza", "lives_in", "hyderabad"))
    say("zoya mirza", ("zoya mirza", "lives_in", "secunderabad"), at="2026-10-02T10:00:00+05:30")
    assert active("zoya mirza", "lives_in") == {"secunderabad"}, "a real move to a similar name still moves"


def caps_cut_far_facts_first():
    say("omar ali", ("omar ali", "lives_in", "pimpri"), ("omar ali", "reported_issue", "no internet"))
    for i in range(6):  # a hub one hop out ("no internet") with facts two hops away
        say(f"cust {i}", (f"cust {i}", "reported_issue", "no internet"), (f"cust {i}", "on_plan", f"fiber {i}"))
    say("road works", ("road works", "affects", "pimpri"))
    near = {r[0] for r in db.run(T, "x", Q.retrieve_facts(2), {"seeds": ["omar ali"], "max_entities": 100,
                                                               "max_facts": 400}, ro=True)
            if {r[1], r[3]} & {"omar ali", "pimpri", "no internet"}}
    got = db.run(T, "x", Q.retrieve_facts(2), {"seeds": ["omar ali"], "max_entities": 100, "max_facts": len(near)},
                 ro=True)
    assert {r[0] for r in got} == near, "with the cap at the 0-1 hop count, exactly those facts come back"
    assert any(r[2] == "affects" for r in got)


def legacy_plan_kept():
    real = llm.extract
    fact = lambda p, o: {"subject": "lata joshi", "predicate": p, "object": o, "attribute": None,
                         "about_customer": True, "valid_from": None, "ended": False}
    try:
        for p, o, kept in [("on_plan", "Basic 50", True), ("wants_to_buy", "Fiber 200", False),
                           ("on_plan", "the cheap one", False)]:
            llm.extract = lambda *a, **k: [fact(p, o)]
            out = memory.ingest_turn(T, agent="intake", session_id="s-lata", customer="lata joshi", text="x", at=AT)
            assert bool(out["facts"]) == kept and bool(out["dropped"]) != kept, (p, o, out)
    finally:
        llm.extract = real
    assert active("lata joshi", "on_plan") == {"basic 50"}


def fault_after_request_gets_its_own_ticket():
    real, c = llm.extract, "sanjay patil"
    fact = lambda p, o: [{"subject": c, "predicate": p, "object": o, "attribute": None, "about_customer": True,
                          "valid_from": None, "ended": False}]
    seen = []  # the ticket the extractor is told about: never the invoice request when a fault comes in
    turn = lambda facts, tid, at: (setattr(llm, "extract", lambda *a, **k: seen.append(k["ticket"]) or facts),
                                   agents.Intake().handle(
        T, customer=c, session_id="s-sp", text="x", at=at, ticket_id=tid))[1]
    try:
        assert turn(fact("service_request", "invoice_resend"), "PML-2041", AT)["ticket_opened"] == "pml-2041"
        assert turn(fact("reported_issue", "evening wifi drops"), "PML-2055",
                    "2026-10-02T10:00:00+05:30")["ticket_opened"] == "pml-2055"
        assert turn(fact("reported_issue", "slow speeds"), "PML-2060",
                    "2026-10-03T10:00:00+05:30")["ticket_opened"] is None, "the fault ticket is open: no third"
    finally:
        llm.extract = real
    assert seen == [None, None, "pml-2055"], seen
    assert agents.open_ticket_for(T, c) == "pml-2055"


def topic_words_are_not_names():
    say("pml-9", ("reset line profile", "resolves", "slow speed"))
    assert retrieve.recall(T, "Which fix has worked before for slow speeds?")["unknown"] == []
    r = retrieve.recall(T, "Which fix worked for Kevin?")
    assert r["unknown"] == ["kevin"] and r["lines"] == []


def fixed_by_names_the_fix_that_worked():
    c = "ravi menon"
    say(c, (c, "has_ticket", "t-7"), ("t-7", "has_status", "open"), ("t-7", "ticket_about", "evening wifi drops"))
    r = agents.Resolver()
    r.try_fix(T, ticket="t-7", fix="restart router", worked=False, at="2026-10-01T12:00:00+05:30")
    assert active("t-7", "fixed_by") == set(), "a fix that didn't work is tried, not fixed_by"
    r.try_fix(T, ticket="t-7", fix="change wifi channel", worked=True, at="2026-10-01T13:00:00+05:30")
    assert active("t-7", "tried_fix") == {"restart router", "change wifi channel"}
    assert active("t-7", "fixed_by") == {"change wifi channel"}
    assert lab.FIX_NAME["change_wifi_channel"] == "change wifi channel"  # one name per fix, lab and team alike
    assert lab.FIX_NAME["dispatch_technician_home"] == "replace fiber cable"


if __name__ == "__main__":
    db.reset(T)
    try:
        pickup_reads_billing()
        typos_and_long_names()
        caps_cut_far_facts_first()
        legacy_plan_kept()
        fault_after_request_gets_its_own_ticket()
        topic_words_are_not_names()
        fixed_by_names_the_fix_that_worked()
        print("test_write_resolution: all passed")
    finally:
        db.graph(T).delete()
