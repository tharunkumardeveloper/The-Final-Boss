"""End-to-end check of the memory engine against a live FalkorDB. Run: python -m tests.test_core"""
from relay import agents, db, memory, retrieve

T = "test-core"
ALICE = "alice rao"


def facts_of(pred):
    return [(r[2], r[3]) for r in retrieve.history(T, ALICE) if r[1] == pred]  # (object, active)


def remember(agent, text, at, facts, speaker="customer"):
    return memory.remember(T, agent=agent, session_id="s-test", customer=ALICE, text=text, at=at,
                           facts=facts, speaker=speaker)


def test_all():
    db.reset(T)

    # single-valued change: supersede, history kept, stale RELATED edge dropped
    remember("intake", "I live in Mumbai", "2026-09-01", [(ALICE, "lives_in", "mumbai")])
    r = remember("intake", "I moved to Pune on the 10th", "2026-09-12", [(ALICE, "lives_in", "pune", "2026-09-10")])
    assert r["facts"][0]["superseded"][0]["object"] == "mumbai"
    assert sorted(facts_of("lives_in")) == [("mumbai", False), ("pune", True)]
    assert [n for n in retrieve.neighborhood(T, ALICE)["edges"] if n[2] == "lives_in"] == [(ALICE, "pune", "lives_in")]

    # same value again: corroboration, no duplicate, no bogus supersede
    r = remember("intake", "Yes, Pune", "2026-09-13", [(ALICE, "lives_in", "pune")])
    assert r["facts"][0]["status"] == "corroborated" and not r["facts"][0]["superseded"]
    assert len(facts_of("lives_in")) == 2

    # multi-valued accumulates
    remember("intake", "My PS5 drops", "2026-09-02", [(ALICE, "owns_device", "ps5")])
    remember("intake", "My laptop drops too", "2026-09-03", [(ALICE, "owns_device", "laptop")])
    assert sorted(facts_of("owns_device")) == [("laptop", True), ("ps5", True)]

    # cross-agent disagreement: both kept, intake (trust 0.9) preferred over resolver (0.6)
    remember("intake", "I'm on Fiber 300", "2026-09-04", [(ALICE, "on_plan", "fiber 300")])
    remember("resolver", "Billing: fiber 100", "2026-09-05", [(ALICE, "on_plan", "fiber 100")], speaker="tool:billing")
    claims = retrieve.claims(T, ALICE, "on_plan")
    assert [c[1] for c in claims] == ["fiber 300", "fiber 100"], claims

    # workflow state ('latest' policy): any agent's newer write wins
    remember("intake", "opened ticket", "2026-09-05", [(ALICE, "has_ticket", "tkt-1"), ("tkt-1", "has_status", "open")])
    remember("resolver", "picked up", "2026-09-06", [("tkt-1", "has_status", "in progress")], speaker="agent")
    t = next(t for t in agents.tickets(T) if t["ticket"] == "tkt-1")
    assert t["status"] == "in progress" and t["customer"] == ALICE, t

    # two clocks diverge on 2026-09-11: true in the world = pune (moved on the 10th), on file = mumbai (told on the 12th)
    assert [r[1] for r in retrieve.world_at(T, ALICE, "2026-09-11") if r[0] == "lives_in"] == ["pune"]
    assert [r[1] for r in retrieve.belief_at(T, ALICE, "2026-09-11") if r[0] == "lives_in"] == ["mumbai"]

    # path behind an answer
    pune = next(r[0] for r in retrieve.history(T, ALICE) if r[2] == "pune")
    ex = retrieve.explain(T, [pune])
    assert {"intake", "s-test", ALICE, "pune"} <= set(ex["nodes"]) and any(e[2] == "SUPERSEDES" for e in ex["edges"])

    # retrieval: entity linking + labelled history + conflict marks
    rec = retrieve.recall(T, "Which plan is Alice Rao on and where does she live?")
    text = "\n".join(rec["lines"])
    assert ALICE in rec["seeds"] and "CURRENT" in text and "SUPERSEDED" in text and "CONFLICT: PREFERRED" in text
    assert "SUPERSEDED" not in "\n".join(retrieve.recall(T, "Alice Rao", mode="no_temporal")["lines"])

    # LLM path: extraction -> supersede, then a cited answer
    out = agents.Intake().handle(T, customer=ALICE, session_id="s2", text="I relocated to Bangalore last week.",
                                 at="2026-10-01")
    # "Bangalore" is normalised to the catalogue's canonical city
    assert any(f["triple"] == (ALICE, "lives_in", "bengaluru") and f["superseded"] for f in out["facts"]), out
    a = retrieve.ask(T, "Where does Alice Rao live now?")
    assert a["values"] == ["bengaluru"] and a["cited_ids"], a

    # multi-hop: outage -> city <- customer
    memory.remember(T, agent="resolver", session_id="s-test", customer=None, at="2026-10-02", speaker="tool:outage",
                    text="Outage feed: fiber cut BLR-7 affects bangalore", facts=[("fiber cut blr-7", "affects", "bangalore")])
    a = retrieve.ask(T, "Which outage might be affecting Alice Rao?")
    assert any("blr-7" in v for v in a["values"]) and len(a["cited_ids"]) >= 2, a

    # consolidation runs on RELATED edges
    assert agents.consolidate(T)

    db.graph(T).delete()
    print("test_core: all checks passed")


if __name__ == "__main__":
    test_all()
