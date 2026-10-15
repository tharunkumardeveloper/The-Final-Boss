"""Replay data/scenario.json through the two agents into one tenant graph.

python -m data.load --tenant nimbus
"""
import argparse
import json
from pathlib import Path

from relay import agents, db
from relay.memory import norm

HERE = Path(__file__).parent


def with_retry(fn, tries=20, wait=30):
    """Per-minute rate limits on every model: wait and retry. Safe because extraction runs before any write."""
    import time
    from relay import llm
    for t in range(tries):
        try:
            return fn()
        except llm.Unavailable as e:
            if t == tries - 1:
                raise
            time.sleep(wait)


def _hit(expect, got):
    pred, obj = expect
    return any(p == pred and (obj is None or obj == o or obj in o or o in obj) for _, p, o in got)


def load_scenario(tenant, reset=True, progress=None):
    """Returns per-event report; also writes data/load_report.json with extraction quality."""
    events = json.loads((HERE / "scenario.json").read_text())["events"]
    if reset:
        db.reset(tenant)
    intake, resolver = agents.Intake(), agents.Resolver()
    report = []
    from relay import lab
    lab.SCRIPTED.add(tenant)  # the benchmark replays a scripted world: the lab must not improvise faults and fixes on top
    try:
        return _load(tenant, events, intake, resolver, report, progress)
    finally:
        lab.SCRIPTED.discard(tenant)


def _load(tenant, events, intake, resolver, report, progress):
    for i, ev in enumerate(events):
        row = {k: ev[k] for k in ("type", "customer", "at")}
        if ev["type"] == "turn":
            out = with_retry(lambda: intake.handle(tenant, customer=ev["customer"], session_id=ev["session_id"],
                                                   text=ev["text"], at=ev["at"], ticket_id=ev["ticket_id"]))
            got = [f["triple"] for f in out["facts"]]
            row |= {"text": ev["text"], "expect": ev["expect"], "got": got, "dropped": out["dropped"],
                    "ticket_opened": out["ticket_opened"],
                    "missed": [e for e in ev["expect"] if not _hit(e, got)]}
        elif norm(ev["ticket"]) not in {t["ticket"] for t in agents.tickets(tenant)}:
            row |= {"ticket": ev["ticket"], "error": "ticket was never opened"}
        elif ev["type"] == "pick_up":
            row |= {"ticket": ev["ticket"], **{k: v for k, v in resolver.pick_up(tenant, ticket=norm(ev["ticket"]),
                                                                                  at=ev["at"]).items()
                                               if k in ("observations", "suggestions")}}
        else:
            resolver.try_fix(tenant, ticket=norm(ev["ticket"]), fix=ev["fix"], worked=ev["worked"], at=ev["at"])
            row |= {"ticket": ev["ticket"], "fix": ev["fix"], "worked": ev["worked"]}
        report.append(row)
        if progress:
            progress(i + 1, len(events), row)
    agents.consolidate(tenant)
    turns = [r for r in report if r["type"] == "turn"]
    planted = sum(len(r["expect"]) for r in turns)
    missed = sum(len(r["missed"]) for r in turns)
    extra = sum(max(0, len(r["got"]) - len(r["expect"])) for r in turns)
    summary = {"turns": len(turns), "planted": planted, "recovered": planted - missed, "missed": missed,
               "extra_facts": extra, "dropped": sum(len(r["dropped"]) for r in turns),
               "errors": [r for r in report if "error" in r]}
    (HERE / "load_report.json").write_text(json.dumps({"summary": summary, "events": report}, indent=1))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="pml-bench")  # benchmark tenant, protected from resets in the API
    args = ap.parse_args()
    print(load_scenario(args.tenant, progress=lambda i, n, r: print(
        f"[{i}/{n}] {r['type']:8} {r.get('text', r.get('ticket', ''))[:60]:60} "
        f"{'MISSED ' + str(r['missed']) if r.get('missed') else ''}{r.get('error', '')}", flush=True)))
