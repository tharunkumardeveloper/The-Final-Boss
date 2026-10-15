"""Drive mcp_server.py over stdio like any MCP client would. Run: python -m tests.test_mcp"""
import json
import os
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

from relay import db

ROOT = Path(__file__).resolve().parent.parent
T = "mcp-test"


def data(res):
    assert not res.is_error, res
    out = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
    return out.get("result", out) if isinstance(out, dict) and set(out) == {"result"} else out


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")], cwd=str(ROOT),
                                   env=dict(os.environ))
    async with Client(params, read_timeout_seconds=300) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"remember", "remember_fact", "recall", "ask", "explain", "tickets", "handoff"} <= names, names

        await c.call_tool("remember_fact", {"tenant": T, "agent": "intake", "subject": "bob mehta",
                                            "predicate": "lives_in", "object": "chennai", "date": "2026-09-01"})
        r = data(await c.call_tool("remember_fact", {"tenant": T, "agent": "intake", "subject": "bob mehta",
                                                     "predicate": "lives_in", "object": "hyderabad",
                                                     "date": "2026-09-20"}))
        assert r["facts"][0]["superseded"][0]["object"] == "chennai", r

        bad = await c.call_tool("remember_fact", {"tenant": T, "agent": "intake", "subject": "bob mehta",
                                                  "predicate": "favourite_colour", "object": "red"})
        assert bad.is_error

        a = data(await c.call_tool("ask", {"tenant": T, "question": "Where does Bob Mehta live?"}))
        assert a["values"] == ["hyderabad"] and a["cited_ids"], a

        ex = data(await c.call_tool("explain", {"tenant": T, "fact_ids": a["cited_ids"]}))
        assert "intake" in ex["nodes"] and any(e[2] == "SUPERSEDES" for e in ex["edges"]), ex
        print("tools:", sorted(names))
        print("ask ->", a)


if __name__ == "__main__":
    try:
        anyio.run(main)
        print("test_mcp: all checks passed")
    finally:
        if db.key(T) in db.client().list_graphs():
            db.graph(T).delete()
