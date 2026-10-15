"""python -m tests.test_scoring"""
from eval.locomo import token_f1
from eval.run_eval import abstention, pairwise_resolution, round_robin, score, wilson


def a(values, conflict=False, unknown=False):
    return {"values": values, "conflict": conflict, "unknown": unknown}


def q(gold, conflict=False, unknown=False):
    return {"gold": gold, "expect_conflict": conflict, "expect_unknown": unknown}


assert score(q(["pune"]), a(["Pune"]))
assert not score(q(["pune"]), a(["pune", "mumbai"]))            # stale value alongside the current one is wrong
assert score(q(["phone"]), a(["phone call"]))                   # lenient containment
assert score(q(["ps5", "laptop"]), a(["laptop", "ps5"]))
assert not score(q(["ps5", "laptop"]), a(["ps5"]))              # incomplete list
assert score(q(["fiber 300"], conflict=True), a(["fiber 300", "fiber 100"], conflict=True))
assert not score(q(["fiber 300"], conflict=True), a(["fiber 300"]))   # must flag the dispute
assert score(q([], unknown=True), a([], unknown=True))
assert not score(q([], unknown=True), a(["ax1800"]))            # hallucinated answer
assert not score(q(["pune"]), a([], unknown=True))

# Wilson interval: known values (8/10 -> 0.490..0.943), edge cases stay inside [0, 1]
lo, hi = wilson(8, 10)
assert abs(lo - 0.4902) < 1e-3 and abs(hi - 0.9433) < 1e-3, (lo, hi)
assert wilson(0, 10)[0] == 0.0 and wilson(10, 10)[1] == 1.0 and wilson(0, 0) is None

# abstention: 2 should-refuse (1 refused, 1 hallucinated), 2 answerable (1 falsely refused)
rows = [{"unknown": True, "values": [], "expect_unknown": True}, {"unknown": False, "values": ["x"], "expect_unknown": True},
        {"unknown": True, "values": [], "expect_unknown": False}, {"unknown": False, "values": ["y"], "expect_unknown": False}]
ab = abstention(rows)
assert ab == {"precision": 0.5, "recall": 0.5, "hallucinations": 1, "false_refusals": 1, "should_refuse": 2}, ab

# entity resolution: A,A,B mentions; A's merged, B wrongly merged with one A -> precision 1/3? pairs: (0,1) tp, (0,2) fp?, (1,2)
res = pairwise_resolution([("A", "e1"), ("A", "e1"), ("B", "e2")])
assert res["precision"] == 1.0 and res["recall"] == 1.0
res = pairwise_resolution([("A", "e1"), ("A", "e2"), ("B", "e1")])
assert res["precision"] == 0.0 and res["recall"] == 0.0 and res["pairs_merged"] == 1 and res["gold_pairs"] == 1

# stratified order
order = round_robin([{"type": t, "i": i} for i, t in enumerate("aaabbc")])
assert [o["type"] for o in order] == list("abcaba"), order

assert token_f1("adoption agencies", "Adoption agencies") == 1.0 and token_f1("pottery", "painting") == 0.0
print("test_scoring: ok")
