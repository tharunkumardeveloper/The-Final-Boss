# Relay: shared memory for teams of agents

**Two agents that never message each other, yet never contradict each other.**

Track 02, Agent Memory and Coordination · Graph Hacks (WeMakeDevs × FalkorDB)

### ▶ [Watch it work: Judge mode](https://wifight.vercel.app/?judge=1)

One click plays the whole story through the real agents in about two minutes. No sign-up, no typing.
Or open [the site](https://wifight.vercel.app) and chat yourself, the [staff console](https://wifight.vercel.app/console),
or the [benchmark page](https://wifight.vercel.app/console/benchmark).

> The API runs on a free plan that sleeps when idle. The first visit after a quiet spell takes about a minute to wake
> it, and the site shows a wake-up screen meanwhile.

<!-- DEMO VIDEO: put the link here (record it from Judge mode, so the video and the live demo tell the same story) -->

---

## The problem

Teams of agents usually coordinate by passing messages, and each one keeps its own notes. So they drift: the billing
agent still has the old address, the support agent asks the customer again, and a handoff loses half the context.

**Relay gives every agent one memory instead: a FalkorDB graph that all of them read and write.** The agents never
talk to each other. Everything one learns, the others find in the graph, with who wrote it, when it was true, what it
replaced, and the path behind every answer. Relay works for any agent that can make an HTTP call, and for any MCP
client (Claude Desktop, Claude Code and others) through its MCP server.

**WiFight**, a fictional fiber broadband provider, is the demo: one tenant of Relay, with a support desk of three agents.

| Agent | Does |
|---|---|
| **Mr.Fix-It** (intake) | Talks to customers, writes what they say into memory as facts, opens tickets, hands them off |
| **Resolver** | Picks tickets up from the graph, measures the customer's line with Cypher, acts (restart, reroute, send a technician), and re-measures before calling it fixed |
| **Network ops** | Watches the network graph; when a node fails it finds every affected customer by traversal and warns them first |

### What Judge mode shows

| # | Step | What Relay does |
|---|---|---|
| 1 | A new customer says hi | Mr.Fix-It picks the name up from the chat; a `Customer` node and a `Session` appear |
| 2 | They report a fault in plain words | Each detail (phone, area, since when, whole home, WiFi and cable) becomes a typed `Fact`; a `Ticket` opens and is handed off (`HANDED_OFF`) |
| 3 | A second agent fixes it | The resolver reads intake's facts (recorded as `CONSULTED`), measures the line, sends a technician, re-measures, and the customer confirms |
| 4 | A fact stops being true | "I no longer live in Chennai, I've moved to Pune": the new fact `SUPERSEDES` the old one, which is closed on both clocks, not deleted |
| 5 | A brand-new session | Nothing is asked again: "Pune, and your ticket is resolved" comes from memory, with the fact it rests on shown under the reply |

Every message goes through the same chat endpoint a person uses; the script only answers what the agents ask.

## Names, once

| Name | What it is |
|---|---|
| **Relay** | The product: the memory layer (`agent-relay/`) |
| **WiFight** | A fictional ISP: the demo tenant that runs on Relay (brand in [`agent-relay/brand.json`](agent-relay/brand.json)) |
| **Mr.Fix-It** | WiFight's intake agent, the one you chat with |
| `pml`, `PML-…` | Internal ids left from the first prototype: the tenant graphs are `mem:pml`, `mem:pml-eu`, …; tickets look like `PML-2057-EB25` |

## Results

**160 questions over 40 customers and 556 conversation turns.** Both systems get the same answer model (qwen3.8-27b)
and the same prompt for every question; only the memory differs. The baseline (**B1**) is a vector store over the same
conversations: filtered to the customer, top 10 chunks, each one dated, newest first.

| | Relay | Vector store (B1) |
|---|---|---|
| **Accuracy** | **99.4%** (159/160) | 61.2% (98/160) |
| Difference | **+38 points** [+31, +46], exact McNemar p = 1.4 × 10⁻¹⁷ | |
| Gold fact in the context | 100% | 72% |
| Should-refuse questions: precision / recall | 100% / 94% | 50% / 78% |

| Question type | Relay | B1 |
|---|---|---|
| Two agents disagree | 100% | 6% |
| Multi-hop (customer → city ← outage) | 100% | 22% |
| Completeness (every device, every ticket) | 100% | 44% |
| Procedural (what fixed this before?) | 100% | 50% |
| Current truth after changes | 100% | 72% |
| Handoff (what did the other agent learn?) | 100% | 83% |

- **Ablations** (an earlier run on a 63-question subset, same model in every arm): removing the two clocks costs
  about **19 points** (90% → 71%), and removing multi-hop expansion about **9** (90% → 81%).
- **Concurrency**: 8 writer threads against one FalkorDB Cloud graph, 18.3 writes/s (23.7 across 4 graphs), **0
  duplicate facts**. A full recall *while those 8 threads write* takes 310 ms at p50; on an idle graph, retrieval for
  a benchmark question takes about 170–180 ms (the vector baseline: 46 ms).
- **What it doesn't prove**: the benchmark data is synthetic, built from our own templates. On the one external check
  ([LoCoMo](https://github.com/snap-research/locomo), open-ended personal chat) **Relay loses on token F1 (0.08 vs
  0.27)**: it keeps facts, not transcripts, so details that never became facts can't be recalled. It did refuse 15/15
  false-premise questions, against 4/15 for B1.

Full tables, intervals, the fix log and how each number was produced: [`PROGRESS.md` §6](PROGRESS.md#6-results),
[`agent-relay/eval/results.md`](agent-relay/eval/results.md). The benchmark page shows them live.

## Track 2, point by point

| Track 2 focus | Relay feature | Proof |
|---|---|---|
| **Episodic, semantic and procedural memory** | `Episode` nodes (every message, reply, tool reading), `Fact` nodes (subject, predicate, object, both clocks, author), and procedures stored as paths: `(:Procedure)-[:FIRST]->(:ProcStep)-[:NEXT]->…`, scored by successes and failures | [`relay/memory.py`](agent-relay/relay/memory.py), [`relay/procedural.py`](agent-relay/relay/procedural.py); procedural questions 100% vs 50%; `tests/test_procedural.py` |
| **Persistent history** | Two clocks on every fact: world time (`valid_from/valid_to`) and system time (`recorded_at/expired_at`). Nothing is overwritten: `SUPERSEDES` chains, `RETIRED` facts, and `WAS` edges keep the past traversable | `RETIRE` and `WRITE_FACT` in [`relay/queries.py`](agent-relay/relay/queries.py); the `facts_at` tool; console two-clock scrubber; ablation −19 points without it |
| **Shared state and handoffs** | Tickets with `HANDED_OFF` / `PICKED_UP` edges are the only coordination. Every read records `(:Agent)-[:CONSULTED {count}]->(:Fact)`, so knowledge flow between agents is measured, not assumed | [`relay/agents.py`](agent-relay/relay/agents.py), [`relay/sharing.py`](agent-relay/relay/sharing.py); handoff questions 100%; Judge mode; console → Agent team |
| **High-concurrency reads and writes** | One Cypher statement per fact write: it creates, corroborates (no duplicate), or supersedes atomically. FalkorDB serializes writes per graph, so no reader ever sees two current values | [`eval/bench.py`](agent-relay/eval/bench.py): 8 threads, 0 duplicates, reads p50 310 ms during writes |
| **Separate memory per tenant** | One FalkorDB graph per tenant (`mem:<tenant>`); every request needs that tenant's HMAC key; six region graphs in the demo | [`relay/tenancy.py`](agent-relay/relay/tenancy.py); console → Tenants runs the same lookup on every graph and a canary write ([`tests/test_canary.py`](agent-relay/tests/test_canary.py)) |

## Remove FalkorDB and…

Swap the graph for a vector store, or for tables plus a vector index, and these stop working:

- **Two clocks.** "Where did she live on the 5th?" and "What did we have on file on the 5th?" are different
  questions; they diverge when someone tells us late. A vector store has no notion of either.
- **Retire.** "I no longer live in Chennai" must stop matching. In a vector store, the old chunk keeps ranking.
- **Conflict ranking.** When billing and support disagree, both claims stay and are ranked at read time by agent
  trust, then recency, with a `Conflict` node. Otherwise, the last write silently wins.
- **Answer paths.** Every answer comes with the hops that found it (customer → `LIVES_IN` → city ← `AFFECTS` ←
  outage). A list of similar chunks is not a reason.
- **Blast radius.** "Who is affected if this cabinet fails?" is a bounded traversal, plus `algo.maxFlow` for
  capacity. Neither is expressible as similarity.
- **Tenant isolation.** One graph per tenant means a query can't reach another tenant's memory, and vector search
  needs no tenant filter.

The core of it, from [`relay/queries.py`](agent-relay/relay/queries.py) (shortened):

```cypher
// Write a fact: a repeat corroborates, a contradiction supersedes, all in one statement
MERGE (f:Fact {triple_key:$tk, active:true})
  ON CREATE SET f.fact_id=$fid, f.predicate=$p, f.valid_from=$vf, f.recorded_at=$at, f.asserted_by=$agent
WITH f, s
OPTIONAL MATCH (old:Fact {predicate:$p, active:true})-[:ABOUT {role:'subject'}]->(s)
WHERE $single AND old.fact_id <> f.fact_id AND ($any_agent OR old.asserted_by = $agent)  // other agents' claims are kept
WITH f, collect(old) AS olds
FOREACH (o IN olds | SET o.active=false, o.valid_to=f.valid_from, o.expired_at=$at   // world clock, system clock
                     CREATE (f)-[:SUPERSEDES]->(o))
```

```cypher
// A fact ends with no replacement: both clocks close, the live edge becomes a WAS edge
MATCH (ep:Episode {episode_id:$eid})
MATCH (f:Fact {predicate:$p, active:true})-[:ABOUT {role:'subject'}]->(s:Entity {name_key:$s})
SET f.active=false, f.valid_to=$vt, f.expired_at=$at, f.retired_by=$eid
REMOVE f:Current SET f:Retired
CREATE (ep)-[:RETIRED]->(f)
```

```cypher
// What was true in the world at $t (swap valid_* for recorded_at/expired_at: what we had on file at $t)
MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
WHERE f.valid_from <= $t AND (f.valid_to IS NULL OR f.valid_to > $t)
MATCH (f)<-[:DERIVED]-(:Episode)<-[:WROTE]-(a:Agent)
RETURN f.predicate, f.object_value, f.valid_from, f.valid_to, collect(DISTINCT a.agent_id)
```

## Where the LLM is, and where it isn't

**Extraction is the LLM's job. Everything after it (supersede, retire, conflicts, recall paths) is pure Cypher.**

- Extraction uses a strict JSON schema whose `predicate` field is an enum of the tenant's registry, so "moved to",
  "relocated to" and "based in" all arrive as `lives_in`. Contradictions are then decided deterministically, from the
  predicate's cardinality and policy. No model is asked whether two facts conflict.
- The model never writes Cypher. Questions go through a fixed catalogue of typed tools (`recall_customer`, `facts_at`,
  `claims`, `who_handled`, `affected_by`, `capacity`, `past_fixes`), each hand-written, parameterised Cypher with
  checked arguments.
- Replies are worded by a model, then checked against what the graph returned (plan names, prices, speeds) before
  they are sent.
- The demo runs on free model quotas: up to 12 Groq keys are tried in turn, replies are cached, and the scripted
  story's replies ship in `demo_cache/`. If every model is out, planned replies still work; nothing new is learned
  from free text until quota returns.

## Bring your own agent (MCP)

[`agent-relay/mcp_server.py`](agent-relay/mcp_server.py) exposes the same memory to any MCP client: `remember`,
`remember_fact`, `recall`, `ask`, `explain`, `tickets` and `handoff`, plus the typed tool catalogue above. It runs on
your machine and talks to the client over stdio, so there is no extra server or port. Claude Code joins with one command:

```bash
claude mcp add relay-memory -- python /path/to/agent-relay/mcp_server.py
```

Or in Claude Desktop's config:

```json
{"mcpServers": {"relay-memory": {"command": "python", "args": ["/path/to/agent-relay/mcp_server.py"]}}}
```

It needs Python with `requirements.txt` installed and the same `.env` as the API: FalkorDB credentials, plus a Groq key
for `remember` (which extracts facts from text; `remember_fact` stores a structured fact with no model). Outside
clients write as the **`mcp`** agent (trust 0.7), a teammate with its own name: use tenant `pml` and what it writes
lands in the same graph the live demo uses, where Mr.Fix-It and the resolver find it like any other fact, and the
Agent team page draws it once it acts. For example, ask Claude: *"Use relay-memory to remember, as agent mcp in tenant
pml, that customer Asha Menon has a PML Hub 6 Pro router"*, then chat as Asha on the site and ask Mr.Fix-It which
router you have.

## Run it

Setup, tests and the free deploy (Render + Vercel + FalkorDB Cloud) are in
[`agent-relay/README.md`](agent-relay/README.md#setup). The design, graph model, every key query and the FalkorDB
Browser tour are there too.

On the public demo, resets, snapshot restores and model settings need a reset key (`RELAY_RESET_KEY`), and writes are
rate-limited per visitor (`RELAY_CHAT_PER_MIN`, `RELAY_WRITES_PER_MIN`), so nobody can wipe it mid-judging. Chatting,
Judge mode, breaking the network in the lab and every read stay open.

## AI-use disclosure

Built with AI coding assistance (Claude Code) for code generation, review and documentation drafts. The design, graph
model, queries and evaluation were directed, verified and tested by the author, who can explain every component.
Runtime models (the routes the live API reports at `/health`): Groq `gpt-oss-120b` for extraction, answers and
replies, with `gpt-oss-20b` and `qwen3.8-27b` as fallbacks (qwen is also the benchmark's answer model), Gemini
Flash-Lite last; `allam-2-7b` for simulated customers and summaries; embeddings by fastembed `bge-small-en-v1.5`,
run locally. All customer data is synthetic; place names come from GeoNames (CC BY 4.0).

## Repository

| Path | What |
|---|---|
| [`agent-relay/relay/`](agent-relay/relay) | The engine: write path, read path, two clocks, agents, network lab. `queries.py` holds every Cypher query |
| [`agent-relay/api/`](agent-relay/api) | FastAPI + WebSocket events ([`CONTRACT.md`](agent-relay/api/CONTRACT.md)) |
| [`agent-relay/web/`](agent-relay/web) | React + TypeScript: the WiFight site with Judge mode, and the staff console |
| [`agent-relay/eval/`](agent-relay/eval) | Benchmark, ablations, components, LoCoMo, load tests |
| [`agent-relay/mcp_server.py`](agent-relay/mcp_server.py) | MCP server |
| [`PROGRESS.md`](PROGRESS.md) | What was built, in order, with every measurement and fix |
