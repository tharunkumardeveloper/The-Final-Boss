"""The simulator's network incident: Baner OLT fails mid-run and Pune customers are warned. No LLM.
Run: python -m scripts.check_sim_noc"""
from relay import db, events, memory, sim

T = "test-sim-noc"
db.reset(T)
memory.remember(T, agent="intake", session_id="alice-s2", customer="Alice Rao", at=sim._at(11, "10:00"),
                text="moved to Pune", facts=[("alice rao", "lives_in", "pune")])
got = []
off = events.subscribe(T, got.append)
s = sim.Sim(T)
s.timeline = [e for e in s.timeline if e[1] == sim.NOC]
assert [e[2] for e in s.timeline] == ["fail", "restore"]
s.running, s.now = True, sim._at(13, "00:00")
s._step()
noc = [e["data"]["text"] for e in got if e["type"] == "message" and e["data"]["speaker"] == "noc" and e["data"]["customer"] == "alice rao"]
assert len(noc) == 2 and "Baner exchange" in noc[0] and "fixed" in noc[1], noc
assert {e["type"] for e in got} >= {"outage_detected", "outage_resolved"}
off()
db.graph(T).delete()
print("check_sim_noc: ok")
