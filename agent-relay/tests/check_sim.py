"""Run the full persona simulation synchronously and check every planted demo moment landed in the graph.
Run: python -m tests.check_sim   (LLM calls are cached; a second run is free)."""
import time

from relay import agents, db, events, retrieve, sim

T = "sim-check"


def facts(subject):
    return {(r[1], r[2]): r[3] for r in retrieve.history(T, subject)}  # (predicate, value) -> active


def main():
    db.reset(T)
    seen = []
    events.subscribe(T, lambda e: seen.append(e["type"]))
    t = time.perf_counter()
    sim.Sim(T).run_sync()
    print(f"simulation done in {time.perf_counter() - t:.0f}s, {len(seen)} events: "
          + ", ".join(f"{k}={seen.count(k)}" for k in sorted(set(seen))))
    a, d, c, f = facts("alice rao"), facts("dev malhotra"), facts("chitra iyer"), facts("farhan shaikh")
    w = {r[0]: r[1] for r in retrieve.world_at(T, "alice rao", "2026-09-11T12:00:00+05:30")}
    b = {r[0]: r[1] for r in retrieve.belief_at(T, "alice rao", "2026-09-11T12:00:00+05:30")}
    tk = {t["customer"]: t for t in agents.tickets(T)}
    checks = {
        "backdated move: alice pune current, mumbai superseded": a.get(("lives_in", "pune")) is True and a.get(("lives_in", "mumbai")) is False,
        "two clocks diverge for alice on 11 Sep": w.get("lives_in") == "pune" and b.get("lives_in") == "mumbai",
        "devices accumulate (ps5 + laptop)": a.get(("owns_device", "ps5")) and any(
            p == "owns_device" and "laptop" in v and act for (p, v), act in a.items()),
        "paraphrased re-mention corroborates, no duplicate": seen.count("fact_corroborated") >= 1,
        "bob's fix suggested for alice and worked first time": [r[0] for r in db.run(
            T, "x", "MATCH (f:Fact {predicate:'tried_fix', subject:$t}) RETURN f.object_value",
            {"t": tk.get("alice rao", {}).get("ticket")})] == ["change wifi channel"],
        "billing disagreement kept (fiber 300 vs fiber 100)": a.get(("on_plan", "fiber 300")) and a.get(("on_plan", "fiber 100")),
        "channel change whatsapp -> email": a.get(("prefers_channel", "email")) is True and a.get(("prefers_channel", "whatsapp")) is False,
        "router swap hub 6 -> hub 6 pro": d.get(("has_router", "pml hub 6 pro")) is True and d.get(("has_router", "pml hub 6")) is False,
        "plan upgrade fiber 100 -> fiber 1000": c.get(("on_plan", "fiber 1000")) is True and c.get(("on_plan", "fiber 100")) is False,
        "farhan moved mumbai -> bengaluru": f.get(("lives_in", "bengaluru")) is True and f.get(("lives_in", "mumbai")) is False,
        "tickets opened for alice, bob, dev, esha": {"alice rao", "bob menon", "dev malhotra", "esha kulkarni"} <= set(tk),
        "bob's ticket resolved": tk.get("bob menon", {}).get("status") == "resolved",
        "outage reached memory": any(r[1] == "affects" for r in db.run(T, "x", "MATCH (f:Fact {predicate:'affects'}) RETURN f.subject, f.predicate")),
        "procedural memory: a fix that worked is stored": bool(db.run(T, "x", "MATCH (f:Fact {predicate:'resolves'}) RETURN f.subject")),
        "handoff answers given": seen.count("answer") >= 2,
        "session summaries written": bool(db.run(T, "x", "MATCH (s:Session) WHERE s.summary IS NOT NULL RETURN s.session_id")),
        "community summaries written": bool(db.run(T, "x", "MATCH (c:Community) WHERE c.summary IS NOT NULL RETURN c.summary")),
    }
    for k, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + k)
    print("alice:", sorted(a.items()))
    print("dev:", sorted(d.items()))
    print("chitra:", sorted(c.items()), "farhan:", sorted(f.items()))
    print("tickets:", {k: (v["ticket"], v["status"], v["issues"]) for k, v in tk.items()})
    return all(checks.values())


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
