"""Relay as an MCP server: any MCP-capable AI client can share the same graph memory as Relay's agents.
Run: python mcp_server.py   (stdio transport)"""
import re
from datetime import date as _date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from relay import agents, config, db, memory, queries as Q, registry, retrieve, tools_catalog

server = MCPServer(
    "relay-memory",
    instructions=("Shared, time-aware graph memory for teams of agents (FalkorDB). Each tenant is an isolated graph. "
                  "Write what you learn with remember/remember_fact, read with ask/recall, and use explain to show "
                  "where an answer came from. Agents: " + ", ".join(config.AGENTS)),
)
_ready = set()


def _tenant(tenant):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", tenant or ""):
        raise ToolError("tenant must be 1-40 chars of lowercase letters, digits, '-' or '_'")
    if tenant not in _ready:
        db.setup(tenant)
        _ready.add(tenant)
    return tenant


def _agent(agent):
    if agent not in config.AGENTS:
        raise ToolError(f"unknown agent {agent!r}; use one of {sorted(config.AGENTS)}")
    return agent


def _facts(res):
    return [{"fact_id": f["fact_id"], "triple": list(f["triple"]), "status": f["status"],
             "superseded": f["superseded"]} for f in res["facts"]]


@server.tool()
def remember(tenant: str, agent: str, customer: str, text: str, date: str = "", session_id: str = "mcp") -> dict:
    """Store one conversation message in shared memory. An LLM extracts facts from it; changed facts
    replace older ones (history is kept), repeated facts are corroborated, not duplicated.
    If agent is 'intake' and the customer reports a new issue, a ticket is opened and handed to the resolver.
    date: ISO date the message happened (default today)."""
    tenant, agent = _tenant(tenant), _agent(agent)
    at = date or _date.today().isoformat()
    if agent == "intake":
        res = agents.Intake().handle(tenant, customer=customer, session_id=session_id, text=text, at=at)
        return {"episode_id": res["episode_id"], "facts": _facts(res), "ticket_opened": res["ticket_opened"],
                "reply": res["reply"]}
    ticket = agents.open_ticket_for(tenant, customer)
    res = memory.ingest_turn(tenant, agent=agent, session_id=session_id, customer=customer, text=text, at=at,
                             ticket=ticket)
    return {"episode_id": res["episode_id"], "facts": _facts(res)}


@server.tool()
def remember_fact(tenant: str, agent: str, subject: str, predicate: str, object: str, date: str = "") -> dict:
    """Store one structured fact (no LLM), e.g. a tool result. predicate must be one of the registry:
    lives_in, on_plan, has_router, prefers_channel, has_ticket, owns_device, reported_issue, has_status,
    assigned_to, ticket_about, tried_fix, resolves, affects. Single-valued predicates replace this agent's
    older value; another agent's different value is kept as a visible conflict."""
    tenant, agent = _tenant(tenant), _agent(agent)
    if predicate not in registry.PREDICATES:
        raise ToolError(f"unknown predicate {predicate!r}; use one of {sorted(registry.PREDICATES)}")
    customer = subject if registry.subject_type(predicate) == "customer" else None
    res = memory.remember(tenant, agent=agent, session_id="mcp", customer=customer,
                          at=date or _date.today().isoformat(), speaker=f"mcp:{agent}",
                          text=f"{agent} recorded: {subject} {predicate} {object}",
                          facts=[(subject, predicate, object)])
    return {"episode_id": res["episode_id"], "facts": _facts(res)}


@server.tool()
def recall(tenant: str, question: str) -> dict:
    """Return the memory lines relevant to a question (current and superseded facts, with dates, sources,
    and conflict marks) without generating an answer."""
    r = retrieve.recall(_tenant(tenant), question)
    return {"seeds": r["seeds"], "lines": r["lines"]}


@server.tool()
def ask(tenant: str, question: str) -> dict:
    """Answer a question from shared memory only. Returns the answer, bare values, the fact ids it cites,
    whether two agents' claims conflict, unknown=true when memory does not contain the answer, and the answer
    contract: outcome (path | memory | not_in_graph | unknown_entity), paths (the hops behind the answer) and
    learned (when each cited fact went on file and which agent wrote it)."""
    log = []
    a = retrieve.ask(_tenant(tenant), question, log=log)
    return {k: a[k] for k in ("answer", "values", "cited_ids", "conflict", "unknown", "outcome", "paths", "learned", "note")} | {
        "cypher_ms": round(sum(q["ms"] for q in log), 1)}


@server.tool()
def explain(tenant: str, fact_ids: list[str]) -> dict:
    """Show the path behind facts: subject and object entities, the source message, its session, the agent
    that learned it, and any older fact it replaced."""
    ex = retrieve.explain(_tenant(tenant), fact_ids)
    return {"nodes": ex["nodes"], "edges": [list(e) for e in ex["edges"]]}


@server.tool()
def tickets(tenant: str) -> list[dict]:
    """List support tickets with status, assigned agent, customer and issues."""
    return agents.tickets(_tenant(tenant))


@server.tool()
def handoff(tenant: str, ticket: str, from_agent: str, to_agent: str, note: str = "", date: str = "") -> dict:
    """Hand a ticket from one agent to another. Records the handoff in the graph and reassigns the ticket."""
    tenant, from_agent, to_agent = _tenant(tenant), _agent(from_agent), _agent(to_agent)
    at = date or _date.today().isoformat()
    t = next((x for x in agents.tickets(tenant) if x["ticket"] == ticket), None)
    if not t:
        raise ToolError(f"unknown ticket {ticket!r}")
    db.run(tenant, "handoff", Q.HANDOFF, {"from_agent": from_agent, "ticket": ticket, "at": memory.to_ms(at),
                                          "to_agent": to_agent, "note": note})
    memory.remember(tenant, agent=from_agent, session_id=f"work-{ticket}", customer=t["customer"], at=at,
                    speaker="agent", text=f"{from_agent} handed {ticket} to {to_agent}: {note}",
                    facts=[(ticket, "assigned_to", to_agent)])
    return {"ticket": ticket, "trail": [list(r) for r in agents.handoff_trail(tenant, ticket)]}


# ---------------------------------------------------------------- the fixed tool catalogue (relay/tools_catalog.py)
# Typed, hand-written queries. Names are resolved against the graph first: an unknown one returns
# outcome=unknown_entity and the tool's query never runs.

def _call(tenant, tool, **args):
    try:
        out = tools_catalog.call(_tenant(tenant), tool, args)
    except tools_catalog.BadArg as e:
        raise ToolError(str(e))
    return {k: out[k] for k in ("outcome", "rows", "ms", "result", "paths", "extra", "note")}


@server.tool()
def recall_customer(tenant: str, name: str) -> dict:
    """Everything memory holds about one customer: their facts, their tickets' facts, outages in their city."""
    return _call(tenant, "recall_customer", name=name)


@server.tool()
def facts_at(tenant: str, name: str, at: str) -> dict:
    """Two clocks: what was true of a customer at `at` (ISO date or "now"), with who wrote each fact, and what the
    system had on file then."""
    return _call(tenant, "facts_at", name=name, at=at)


@server.tool()
def claims(tenant: str, name: str, predicate: str) -> dict:
    """Every active claim for a customer + predicate (e.g. on_plan), ranked by writer trust then recency, with the
    Conflict node when agents disagree."""
    return _call(tenant, "claims", name=name, predicate=predicate)


@server.tool()
def who_handled(tenant: str, ticket: str) -> dict:
    """A ticket's owner, customer and the trail of agents that picked it up or handed it off."""
    return _call(tenant, "who_handled", ticket=ticket)


@server.tool()
def affected_by(tenant: str, node: str, depth: int = 2) -> dict:
    """Blast radius of a network node (node_id, e.g. pop-mumbai): everything below it within depth 1..4 hops,
    each row with its path."""
    return _call(tenant, "affected_by", node=node, depth=depth)


@server.tool()
def capacity(tenant: str, node: str) -> dict:
    """Gbps that can still reach the backbone from a network node through working equipment (algo.maxFlow)."""
    return _call(tenant, "capacity", node=node)


@server.tool()
def past_fixes(tenant: str, symptoms: str) -> dict:
    """What fixed this issue before (an issue name from memory): fixes with counts, and procedures as step paths."""
    return _call(tenant, "past_fixes", symptoms=symptoms)


if __name__ == "__main__":
    server.run("stdio")
