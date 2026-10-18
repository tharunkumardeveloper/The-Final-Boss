"""When every extraction model is out of quota: chat still answers, the benchmark loader still raises.
Run: python -m scripts.check_outage"""
from fastapi.testclient import TestClient

import tests.conftest  # noqa: F401  (tenant keys on every request)

from api.main import app
from relay import agents, config, db, llm

T = "test-outage"
config.ROUTES["extract"] = ["gemini:no-such-model-for-test"]  # 404 from Gemini -> raise; use a 429-style stand-in below


def unavailable(*a, **k):
    raise llm.Unavailable("all models unavailable: test (per day)")


llm.extract = unavailable
db.reset(T)
r = TestClient(app).post(f"/api/tenants/{T}/chat", json={"customer": "Asha", "text": "I live in Pune"})
assert r.status_code == 200 and "note-taking is paused" in r.json()["reply"] and r.json()["learned"] == [], r.text
try:
    agents.Intake().handle(T, customer="Asha", session_id="s", text="I live in Pune", at="2026-10-01")
    raise AssertionError("loader path must raise")
except llm.Unavailable:
    pass
db.graph(T).delete()
print("check_outage: ok")
