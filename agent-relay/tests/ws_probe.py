"""Live probe against a running API: start a simulation, count WebSocket events for N seconds.
Run: python -m tests.ws_probe http://127.0.0.1:8600 rss-test 60"""
import asyncio
import json
import sys
import time
from collections import Counter

import httpx
import websockets


async def main(base, tenant, seconds):
    for _ in range(60):
        try:
            if httpx.get(f"{base}/health", timeout=5).json()["ok"]:
                break
        except httpx.HTTPError:
            await asyncio.sleep(1)
    counts, t0 = Counter(), time.time()
    async with websockets.connect(base.replace("http", "ws") + f"/ws/{tenant}", max_size=2**22) as ws:
        httpx.post(f"{base}/api/tenants/{tenant}/sim/start", json={"customers": 6, "speed": 24}, timeout=120)
        while time.time() - t0 < seconds:
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            counts[ev["type"]] += 1
            if ev["type"] == "message":
                print(f"{ev['sim_time']} {ev['data']['speaker']:>12}: {ev['data']['text'][:90]}", flush=True)
    print("status:", httpx.get(f"{base}/api/tenants/{tenant}/sim").json())
    print("events:", dict(counts))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], float(sys.argv[3])))
