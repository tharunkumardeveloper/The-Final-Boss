"""Performance benchmarks (no LLM). Run: python -m eval.bench  ->  eval/bench.json + eval/bench.md
Numbers include the ~24 ms internet round trip to FalkorDB Cloud (ap-south-1) per query."""
import json
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from relay import config, db, embed, memory, registry as R, retrieve

OUT = Path(__file__).resolve().parent
CITIES = [f"city {i}" for i in range(50)]
PLANS = [f"fiber {n}" for n in (50, 100, 300, 500, 1000)]
ROUTERS = [f"router r{i}" for i in range(10)]
DEVICES = [f"device d{i}" for i in range(20)]


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))] * 1000, 1) if xs else None


def one(tenant, q):
    return db.graph(tenant).ro_query(q).result_set[0][0]


def drop(tenant):
    if db.key(tenant) in db.client().list_graphs():
        db.graph(tenant).delete()


# ---------------------------------------------------------------- (a) concurrency

INTEGRITY = {
    "duplicate_entities": "MATCH (e:Entity) WITH e.name_key AS k, count(*) AS c WHERE c > 1 RETURN count(k)",
    "duplicate_active_facts": "MATCH (f:Fact {active:true}) WITH f.triple_key AS k, count(*) AS c WHERE c > 1 RETURN count(k)",
    "customers_with_0_active_city": """MATCH (c:Entity {type:'customer'})
        OPTIONAL MATCH (f:Fact {predicate:'lives_in', active:true})-[:ABOUT {role:'subject'}]->(c)
        WITH c, count(f) AS n RETURN sum(CASE WHEN n = 0 THEN 1 ELSE 0 END)""",
    "customers_with_2plus_active_city": """MATCH (c:Entity {type:'customer'})
        OPTIONAL MATCH (f:Fact {predicate:'lives_in', active:true})-[:ABOUT {role:'subject'}]->(c)
        WITH c, count(f) AS n RETURN sum(CASE WHEN n > 1 THEN 1 ELSE 0 END)""",
}


def concurrency(n_graphs, threads=8, writes=200, customers=20, readers=2):
    tenants = [f"bench-c{n_graphs}-{i}" for i in range(n_graphs)]
    for t in tenants:
        drop(t)
        db.setup(t)
    rnd = random.Random(7)
    jobs = [(tenants[i % n_graphs], f"cust {i % customers:03d}", rnd.choice(CITIES[:8]), rnd.choice(DEVICES[:6]), i)
            for i in range(writes)]
    w_lat, r_lat, done = [], [], threading.Event()

    def write(job):
        t, cust, city, dev, i = job
        t0 = time.perf_counter()
        memory.remember(t, agent="intake", session_id=f"s{i}", customer=cust, at=1_790_000_000_000 + i * 1000,
                        text=f"{cust} says they live in {city} and use a {dev}",
                        facts=[(cust, "lives_in", city), (cust, "owns_device", dev)])
        w_lat.append(time.perf_counter() - t0)

    def read():
        r = random.Random(threading.get_ident())
        while not done.is_set():
            t0 = time.perf_counter()
            retrieve.recall(r.choice(tenants), f"Where does cust {r.randrange(customers):03d} live?")
            r_lat.append(time.perf_counter() - t0)

    with ThreadPoolExecutor(readers) as rp:
        rfuts = [rp.submit(read) for _ in range(readers)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(threads) as wp:
            list(wp.map(write, jobs))
        wall = time.perf_counter() - t0
        done.set()
        for f in rfuts:
            f.result()
    integrity = {k: sum(one(t, q) or 0 for t in tenants) for k, q in INTEGRITY.items()}
    for t in tenants:
        drop(t)
    return {"graphs": n_graphs, "writer_threads": threads, "reader_threads": readers, "writes": writes,
            "writes_per_s": round(writes / wall, 1), "write_p50_ms": pct(w_lat, .5), "write_p95_ms": pct(w_lat, .95),
            "reads": len(r_lat), "read_p50_ms": pct(r_lat, .5), "read_p95_ms": pct(r_lat, .95), **integrity}


# ---------------------------------------------------------------- (b) scale

SHARED = """
UNWIND $rows AS r
CREATE (:Entity {name_key:r.k, name:r.k, type:r.t, embedding:vecf32(r.v), created_at:0})
"""

# One episode per customer deriving 5 current facts (+ an old, superseded city for half of them).
BULK = """
UNWIND $rows AS r
MATCH (a:Agent {agent_id:'intake'})
CREATE (c:Entity {name_key:r.c, name:r.c, type:'customer', embedding:vecf32(r.cv), created_at:r.at})
CREATE (a)-[:WROTE]->(ep:Episode {episode_id:r.c, text:r.text, speaker:'customer', embedding:vecf32(r.ev),
                                  recorded_at:r.at, session_id:r.c, source_agent:'intake', customer:r.c})
CREATE (ep)-[:MENTIONS]->(c)
WITH r, c, ep
UNWIND r.facts AS fx
MATCH (o:Entity {name_key:fx.o})
CREATE (f:Fact {fact_id:fx.id, triple_key:r.c + '|' + fx.p + '|' + fx.o, predicate:fx.p, subject:r.c,
                object_value:fx.o, active:fx.active, valid_from:r.at, recorded_at:r.at, asserted_by:'intake'})
CREATE (ep)-[:DERIVED]->(f), (f)-[:ABOUT {role:'subject'}]->(c), (f)-[:ABOUT {role:'object'}]->(o),
       (ep)-[:MENTIONS]->(o)
""" + "\n".join(  # typed current-world edge per predicate (types can't be parameters)
    f"FOREACH (_ IN CASE WHEN fx.active AND fx.p = '{p}' THEN [1] ELSE [] END |"
    f" CREATE (c)-[:{R.rel_type(p)} {{predicate:fx.p, fact_id:fx.id}}]->(o))" for p in R.ISP)


def unit_vecs(rng, n):
    v = rng.standard_normal((n, config.DIM)).astype(np.float32)
    return np.round(v / np.linalg.norm(v, axis=1, keepdims=True), 4).tolist()


def load(tenant, n_customers, batch=200):
    rng, rnd = np.random.default_rng(1), random.Random(1)
    shared = [(k, t) for t, ks in (("city", CITIES), ("plan", PLANS), ("router", ROUTERS), ("device", DEVICES))
              for k in ks]
    db.graph(tenant).query(SHARED, {"rows": [{"k": k, "t": t, "v": v}
                                             for (k, t), v in zip(shared, unit_vecs(rng, len(shared)))]})
    facts = 0
    for start in range(0, n_customers, batch):
        n = min(batch, n_customers - start)
        cv, ev = unit_vecs(rng, n), unit_vecs(rng, n)
        rows = []
        for j in range(n):
            c = f"cust-{start + j:06d}"
            city = rnd.choice(CITIES)
            fx = [("lives_in", city, True), ("on_plan", rnd.choice(PLANS), True), ("has_router", rnd.choice(ROUTERS), True),
                  ("owns_device", rnd.choice(DEVICES), True), ("owns_device", rnd.choice(DEVICES), True)]
            if j % 2:
                fx.append(("lives_in", rnd.choice([x for x in CITIES if x != city]), False))
            fx = list({(p, o): a for p, o, a in fx}.items())
            rows.append({"c": c, "cv": cv[j], "ev": ev[j], "at": 1_790_000_000_000 + start + j,
                         "text": f"{c} lives in {city}",
                         "facts": [{"id": f"f-{c}-{i}", "p": p, "o": o, "active": a} for i, ((p, o), a) in enumerate(fx)]})
            facts += len(fx)
        db.graph(tenant).query(BULK, {"rows": rows})
    return facts


def scale(sizes=(200, 2_000, 10_000, 20_000), questions=30):
    results = []
    for n_customers in sizes:
        tenant = f"bench-scale-{n_customers}"
        drop(tenant)
        db.setup(tenant)
        t0 = time.perf_counter()
        try:
            facts = load(tenant, n_customers)
        except Exception as e:
            results.append({"customers": n_customers, "error": str(e)[:200]})
            drop(tenant)
            break
        load_s = time.perf_counter() - t0
        rnd, lat, parts = random.Random(3), [], {}
        for _ in range(questions):
            log = []
            t1 = time.perf_counter()
            r = retrieve.recall(tenant, f"Which plan is cust-{rnd.randrange(n_customers):06d} on?", log=log)
            lat.append(time.perf_counter() - t1)
            assert r["lines"], "recall returned nothing"
            for q in log:
                parts.setdefault(q["name"], []).append(q["ms"] / 1000)
        nodes = one(tenant, "MATCH (n) RETURN count(n)")
        results.append({"customers": n_customers, "facts": facts, "nodes": nodes, "load_s": round(load_s, 1),
                        "recall_p50_ms": pct(lat, .5), "recall_p95_ms": pct(lat, .95),
                        "breakdown_p50_ms": {k: pct(v, .5) for k, v in parts.items()}})
        drop(tenant)
    return results


def main():
    embed.embed_one("warm up")
    out = {"note": "FalkorDB Cloud free tier, ap-south-1; client in India, ~24 ms RTT per query; "
                   "writes include local fastembed embedding of message + entities.",
           "concurrency": [concurrency(1), concurrency(4)], "scale": scale()}
    (OUT / "bench.json").write_text(json.dumps(out, indent=2))
    md = ["# Relay benchmarks", "", out["note"], "", "## Concurrent writes + reads", "",
          "| graphs | writes/s | write p50 | write p95 | reads during writes | read p50 | read p95 | dup entities | dup active facts | 0 active city | 2+ active city |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in out["concurrency"]:
        md.append(f"| {c['graphs']} | {c['writes_per_s']} | {c['write_p50_ms']} ms | {c['write_p95_ms']} ms | {c['reads']} | "
                  f"{c['read_p50_ms']} ms | {c['read_p95_ms']} ms | {c['duplicate_entities']} | {c['duplicate_active_facts']} | "
                  f"{c['customers_with_0_active_city']} | {c['customers_with_2plus_active_city']} |")
    md += ["", "## Recall latency vs graph size (no LLM)", "",
           "| customers | facts | nodes | load | recall p50 | recall p95 | p50 per query |", "|---|---|---|---|---|---|---|"]
    for s in out["scale"]:
        if "error" in s:
            md.append(f"| {s['customers']} | ceiling hit: {s['error']} | | | | | |")
        else:
            md.append(f"| {s['customers']} | {s['facts']} | {s['nodes']} | {s['load_s']} s | {s['recall_p50_ms']} ms | "
                      f"{s['recall_p95_ms']} ms | {', '.join(f'{k} {v}' for k, v in s['breakdown_p50_ms'].items())} |")
    (OUT / "bench.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
