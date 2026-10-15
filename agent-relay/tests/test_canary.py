"""The canary test behind the Tenants page: a marker planted in one tenant is visible there (control) and nowhere else,
then removed completely. No LLM calls. Run: python -m tests.test_canary"""
from api import main
from relay import db, events, tools_catalog as TC

A, B = "test-canary-a", "test-canary-b"

if __name__ == "__main__":
    heard = {A: [], B: []}
    for t in heard:
        events.subscribe(t, lambda e, t=t: heard[t].append(str(e["data"])))
    try:
        main.T(B)
        c = main.plant_canary(A)
        tok = c["token"]
        assert c["graph"] == "mem:" + A
        assert any(tok in m for m in heard[A]), "control: the victim's own stream carries the write"
        assert not any(tok in m for m in heard[B]), "another tenant's stream never sees it"
        count = lambda t: db.run(t, "t", "MATCH (n:Entity) WHERE n.name_key CONTAINS $t RETURN count(n)", {"t": tok}, ro=True)[0][0]
        assert count(A) > 0 and count(B) == 0
        assert TC.call(A, "recall_customer", {"name": c["customer"]})["outcome"] == "memory"
        assert TC.call(B, "recall_customer", {"name": c["customer"]})["outcome"] == "unknown_entity"
        assert main.remove_canary(A, tok)["left"] == 0
        for label, prop in [("Fact", "triple_key"), ("Episode", "session_id"), ("Session", "session_id")]:
            assert db.run(A, "t", f"MATCH (n:{label}) WHERE toString(n.{prop}) CONTAINS $t RETURN count(n)", {"t": tok}, ro=True)[0][0] == 0, label
        print("test_canary: all checks passed")
    finally:
        for t in (A, B):
            try:
                db.graph(t).delete()
            except Exception:
                pass
