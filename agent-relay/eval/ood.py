"""Out-of-distribution extraction: a different model (Gemini) writes customer messages for planted facts in its own
style; we measure whether Relay's extraction recovers them. No graph writes."""
import json
import os
import random
from pathlib import Path

from relay import llm
from relay.memory import norm

DATA = Path(__file__).resolve().parent.parent / "data"
WRITER = os.environ.get("RELAY_OOD_WRITER", "gemini:gemini-3.5-flash-lite")  # any model other than the extractor
PHRASE = {"lives_in": "the customer lives in {x}", "on_plan": "the customer is subscribed to the {x} plan",
          "has_router": "the customer's router model is {x}", "prefers_channel": "the customer wants to be contacted by {x}",
          "owns_device": "the customer has a {x} at home that uses the wifi",
          "reported_issue": "the customer is having this internet problem: {x}"}
SYSTEM = ("You write realistic chat messages from customers of Ping Me Later, an Indian fiber broadband provider. "
          "Write ONE message of 1-3 sentences, in your own words, as the customer. Vary the tone; you may add unrelated "
          "small talk, casual typos or Indian English. Output only the message.")


def _match(a, b):
    a, b = norm(a), norm(b)
    return bool(a) and (a == b or b in a or a in b)


def items():
    gold = json.loads((DATA / "gold.json").read_text())
    rng = random.Random(7)
    out = []
    for pred in ["lives_in", "on_plan", "has_router", "prefers_channel", "owns_device"]:
        facts = [f for f in gold["facts"] if f["pred"] == pred]
        out += rng.sample(facts, min(12, len(facts)))
    labels = ["my wifi drops every evening", "speeds are far below what I pay for", "the internet is completely down",
              "my router restarts by itself", "online games lag badly", "wifi doesn't reach the far rooms"]
    out += [{"customer": "zara test", "pred": "reported_issue", "value": None, "label": lbl} for lbl in labels * 2]
    return out


def _retry(fn, tries=12, wait=30):
    """Per-minute 429s pass; a limit that outlasts ~6 minutes is treated as the daily quota."""
    import time
    for t in range(tries):
        try:
            return fn()
        except llm.Unavailable:
            if t == tries - 1:
                raise
            time.sleep(wait)


def measure():
    res, partial = [], False
    for n, it in enumerate(items()):
        try:
            ask = PHRASE[it["pred"]].format(x=it.get("label") or it["value"])
            msg = _retry(lambda: llm.chat_text("reply", SYSTEM, [{"role": "user", "content":
                                                                  f"Message #{n}. It must make clear that: {ask}."}],
                                               "ood_writer", model=WRITER))
            got = _retry(lambda: llm.extract(msg, customer=it["customer"], ticket=None, date="2026-10-01",
                                             speaker="customer"))
        except llm.Unavailable as e:
            print(f"ood: stopped, {str(e)[:120]}")
            partial = True
            break
        got = [f for f in got if f["predicate"] != "none" and f["about_customer"]]
        if it["pred"] == "reported_issue":
            hit, obj_hits = any(f["predicate"] == "reported_issue" for f in got), [f for f in got if f["predicate"] == "reported_issue"]
        else:
            obj_hits = [f for f in got if _match(f["object"], it["value"])]
            hit = any(f["predicate"] == it["pred"] for f in obj_hits)
        res.append({"pred": it["pred"], "value": it.get("value") or it.get("label"), "message": msg, "hit": hit,
                    "value_found": bool(obj_hits), "predicate_ok": any(f["predicate"] == it["pred"] for f in obj_hits),
                    "got": [(f["predicate"], f["object"]) for f in got]})
        print(f"ood {'OK ' if hit else 'BAD'} {it['pred']:15} {msg[:70]!r} -> {res[-1]['got']}", flush=True)
    if not res:
        return None
    from eval.run_eval import wilson
    k, n = sum(r["hit"] for r in res), len(res)
    found = [r for r in res if r["value_found"]]
    by = {}
    for r in res:
        by.setdefault(r["pred"], []).append(r["hit"])
    return {"writer": WRITER, "n": n, "recall": round(k / n, 4), "ci95": wilson(k, n),
            "predicate_accuracy": round(sum(r["predicate_ok"] for r in found) / len(found), 4) if found else None,
            "by_predicate": {p: f"{sum(v)}/{len(v)}" for p, v in by.items()}, "partial": partial, "rows": res}
