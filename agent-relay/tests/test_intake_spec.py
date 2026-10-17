"""The intake spec (relay/intake.py), scenario by scenario, through the real /chat endpoint.
Run: python -m tests.test_intake_spec"""
import re

from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import db, intake, retrieve

T = "test-intake-spec"
c = TestClient(app)


def chat(customer, text, sid, at):
    r = c.post(f"/api/tenants/{T}/chat", json={"customer": customer, "text": text, "session_id": sid, "at": at}).json()
    print(f"YOU:   {text}\nKAVYA: {r['reply']}\n")
    assert r["reply"].count("?") <= 1, "more than one question"
    assert not intake.FIX_TIME.search(r["reply"]), "promised a fix time"
    return r


def active(subject):
    return {(p, o) for _, p, o, on, *_ in retrieve.history(T, subject) if on}


def node(label, key, *props):
    return db.graph(T).query(f"MATCH (n:{label} {{name_key:$k}}) RETURN " + ", ".join(f"n.{p}" for p in props),
                             {"k": key}).result_set[0]


def session_one():
    """Spec section 10, session 1: identity first (with the hints), then the problem, one question at a time."""
    sid, at = "tharun-s1", lambda m: f"2026-10-15T10:{m:02d}:00+05:30"
    r = chat("Tharun Kumar", "hi my net isnt working", sid, at(0))
    assert intake.SLOTS["identifier"].words.search(r["reply"]) and "?" in r["reply"], "asks for the registered number"
    assert not intake.FIX_ADVICE.search(r["reply"]), "no troubleshooting before we know who it is"
    r = chat("Tharun Kumar", "idk which number i used honestly", sid, at(1))
    assert "sticker" in r["reply"].lower(), "the spec's hint"
    r = chat("Tharun Kumar", "oh found it, 9876543210", sid, at(2))
    assert ("phone", "9876543210") in active("tharun kumar")
    assert re.search(r"city|area", r["reply"], re.I), r["reply"]
    r = chat("Tharun Kumar", "bengaluru, koramangala", sid, at(3))
    assert ("lives_in", "koramangala") in active("tharun kumar")
    assert not re.search(r"which plan|which router", r["reply"], re.I), "plan and router aren't asked any more"
    ticket = next(o for p, o in active("tharun kumar") if p == "has_ticket")
    r = chat("Tharun Kumar", "completely down since this morning, router lights are all off, whole house", sid, at(7))
    tk = active(ticket)
    assert any(p == "router_lights" for p, _ in tk) and any(p == "issue_started" for p, _ in tk), tk
    status, lights = node("Ticket", ticket, "status", "router_lights")
    assert status == "open" and lights, (status, lights)
    waiting = {o for p, o in active("tharun kumar") if p == "awaiting"}
    assert not waiting & {"identifier", "area", "plan", "router"}, waiting
    return ticket


def session_two(ticket):
    """Spec section 10, session 2: returning customer, a move, nothing asked again."""
    sid = "tharun-s2"
    r = chat("Tharun Kumar", "follow up, also i moved to indiranagar now", sid, "2026-10-16T09:00:00+05:30")
    assert r["reply"].startswith("Hey Tharun, welcome back!"), r["reply"]
    assert "indiranagar" in r["reply"].lower(), "the change is said back"
    assert ("lives_in", "indiranagar") in active("tharun kumar")
    assert not re.search(r"registered mobile|which plan|which router", r["reply"], re.I), "asked for what we know"
    linked = db.graph(T).query("MATCH (:Session {session_id:'tharun-s1'})-[:FOLLOWED_BY]->(:Session {session_id:'tharun-s2'}) "
                               "RETURN count(*)").result_set[0][0]
    assert linked == 1, "sessions chained"
    r = chat("Tharun Kumar", "this is the third time im contacting you about this", sid, "2026-10-16T09:01:00+05:30")
    assert ("has_priority", "high") in active(ticket), active(ticket)
    assert "priority" in r["reply"].lower(), r["reply"]


def billing():
    """Never answers billing amounts before identity is confirmed."""
    r = chat("Meena Iyer", "why is my bill higher this month", "meena-s1", "2026-10-15T11:00:00+05:30")
    assert intake.SLOTS["identifier"].words.search(r["reply"]), r["reply"]
    assert not re.search(r"₹|\brs\.?\s?\d|\binr\b", r["reply"], re.I), "an amount before identity"


def coverage_everywhere():
    """We serve everywhere (a demo company): a place with no city entry is a yes, then the exact address."""
    r = chat("Ravi", "do you cover madurai?", "ravi-s1", "2026-10-15T12:00:00+05:30")
    assert "we serve madurai" in r["reply"].lower() and "exact address" in r["reply"].lower(), r["reply"]
    assert "waitlist" not in r["reply"].lower() and "don't cover" not in r["reply"].lower(), r["reply"]
    r = chat("Asha", "do you provide service in koramangala bangalore", "asha-s1", "2026-10-15T12:05:00+05:30")
    assert "Good news, we serve Koramangala" in r["reply"], r["reply"]
    # naming a plan after "which plan would you like?" is a purchase: an order, never "is on" (found in the browser)
    r = chat("Asha", "fiber 300 please", "asha-s1", "2026-10-15T12:06:00+05:30")
    orders = c.get(f"/api/tenants/{T}/orders", params={"customer": "asha"}).json()
    assert orders and orders[0]["plan"] == "fiber 300", orders
    assert not any(p == "on_plan" for p, _ in active("asha")), active("asha")
    assert "order" in r["reply"].lower(), r["reply"]


def cancellation():
    chat("Kiran Shah", "i want to cancel my connection", "kiran-s1", "2026-10-15T13:00:00+05:30")
    facts = active("kiran shah")
    ticket = next((o for p, o in facts if p == "has_ticket"), None)
    assert ticket, facts
    assert ("issue_type", "cancellation request") in active(ticket), active(ticket)
    assert node("Customer", "kiran shah", "churn_risk")[0] is True


def identity_match():
    """A number that belongs to someone else: never reveals who."""
    chat("Pooja Nair", "my number is 9123456789", "pooja-s1", "2026-10-15T14:00:00+05:30")
    r = chat("Sunil", "my internet is slow, my number is 9123456789", "sunil-s1", "2026-10-15T14:05:00+05:30")
    assert "different name" in r["reply"] and "pooja" not in r["reply"].lower(), r["reply"]


def sessions_per_person():
    """Two people with the same first name on the same day get separate sessions (found in the browser)."""
    a = c.post(f"/api/tenants/{T}/chat", json={"customer": "Browser Check", "text": "do you cover koramangala bangalore?",
                                                "at": "2026-10-15T15:00:00+05:30"}).json()
    b = c.post(f"/api/tenants/{T}/chat", json={"customer": "Browser Two", "text": "do you cover koramangala bangalore?",
                                                "at": "2026-10-15T15:01:00+05:30"}).json()
    assert a["session_id"] != b["session_id"], (a["session_id"], b["session_id"])


def main():
    db.reset(T)
    sessions_per_person()
    ticket = session_one()
    session_two(ticket)
    billing()
    coverage_everywhere()
    cancellation()
    identity_match()
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_intake_spec: all checks passed")
