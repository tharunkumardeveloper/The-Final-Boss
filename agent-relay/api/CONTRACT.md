# API contract (backend ⇄ web)

Base URL: `VITE_API_URL` (e.g. `https://relay-api.onrender.com`). All JSON. Times: simulated time as ISO strings (`2026-09-12T10:30:00+05:30`), wall time as epoch ms.

## Graph ids and kinds

| Thing | id | kind |
|---|---|---|
| Entity | `e:<name_key>` | its type: `customer` `city` `plan` `router` `channel` `device` `issue` `fix` `outage` `ticket` `status` `agent` |
| Fact (drawn as an **edge** subject→object) | `f:<fact_id>` | `fact` |
| Episode | `ep:<episode_id>` | `episode` |
| Session | `s:<session_id>` | `session` |
| Agent | `a:<agent_id>` | `agent_node` |
| Community | `c:<community_id>` | `community` |

The live graph = entity nodes + fact edges (`active` false → dashed/faded). Episodes, sessions and agents appear only in answer paths and cards.

## REST

| Method & path | Body | Returns |
|---|---|---|
| `GET /health` | | `{ok, falkordb: bool, models: {...routes}}` |
| `GET /api/tenants` | | `[name]` |
| `POST /api/tenants` | `{name}` | `{name}` (creates empty) |
| `POST /api/tenants/{t}/reset` | `{scenario: "empty"\|"story"\|"benchmark"}` | `{ok}` (story = the region's scripted neighbourhood: its moving customer, her neighbour and four residents, about two minutes) |
| `GET /api/tenants/{t}/stats` | | `{current_facts, superseded_facts, episodes, entities, customers, open_tickets, conflicts}` |
| `GET /api/tenants/{t}/customers` | | `[{key, name, city, plan, router, channel, devices[], open_ticket, last_seen}]` |
| `GET /api/tenants/{t}/graph?focus=<e:key>&depth=2` | | `{nodes:[{id, kind, label, salience?, community?}], edges:[{id, source, target, label, active, conflict?}]}` (whole tenant if no focus, capped ~400 edges) |
| `GET /api/tenants/{t}/card/{id}` | | `{id, kind, title, subtitle, lines:[string], summary?, sections:[{title, rows:[[k,v]]}]}` — readable node card, no LLM |
| `GET /api/tenants/{t}/tickets` | | `[{ticket, customer, status, assigned_to, issues[], opened_at, trail:[{agent, action, at, to?, note?}]}]` |
| `POST /api/tenants/{t}/chat` | `{customer, text, session_id?, at?}` | `{reply, session_id, learned:[FactChange], ticket_opened?, cypher:[CypherEntry]}` — you/a judge as a customer |
| `POST /api/tenants/{t}/tickets/{id}/pickup` | | `{observations[], suggestions:[{issue, fix, worked_before}], cypher}` |
| `POST /api/tenants/{t}/tickets/{id}/fix` | `{fix, worked}` | `{learned:[FactChange], cypher}` |
| `POST /api/tenants/{t}/ask` | `{question, agent?: "resolver"}` | `{answer, values[], conflict, unknown, cited_ids[], path:{nodes, edges}, lines[], cypher}` |
| `GET /api/tenants/{t}/clock?subject=<key>&at=<iso>` | | `{world:[{predicate, value, fact_id}], belief:[...]}` |
| `GET /api/tenants/{t}/history?subject=<key>` | | `[{fact_id, predicate, value, active, valid_from, valid_to, recorded_at, expired_at, agents[]}]` |
| `POST /api/tenants/{t}/consolidate` | | `{communities:[{id, size, top[], salience, summary?}]}` |
| `POST /api/tenants/{t}/sim/start` | `{customers?: int, speed?: float}` | `{running: true}` (speed = simulated hours per real second) |
| `POST /api/tenants/{t}/sim/stop` | | `{running: false}` |
| `GET /api/tenants/{t}/sim` | | `{running, sim_time, speed, customers[]}` |
| `GET /api/benchmark` | | `{results: eval/results.json, bench: eval/bench.json}` |

`FactChange = {fact_id, subject, predicate, object, status: "new"|"corroborated"|"updated", replaced?: [{fact_id, object}]}`
`CypherEntry = {name, query, params, rows, ms}`

## WebSocket `GET /ws/{tenant}`

Server → client, one JSON object per event: `{type, sim_time, wall, data}`.

| type | data |
|---|---|
| `message` | `{session_id, customer, speaker: "customer"\|"intake"\|"resolver"\|"tool:billing"\|"tool:outage"\|"tool:diagnostic"\|"mcp:<client>", text}` |
| `fact_created` | `{fact_id, subject, predicate, object, agent, episode_id}` |
| `fact_corroborated` | `{fact_id, subject, predicate, object, agent, episode_id}` |
| `fact_superseded` | `{fact_id, old_fact_id, subject, predicate, object, old_object, agent}` |
| `conflict` | `{subject, predicate, claims:[{fact_id, value, agent, trust, preferred}]}` |
| `ticket_opened` | `{ticket, customer, issue}` |
| `handoff` | `{ticket, from, to, note}` |
| `pickup` | `{ticket, agent}` |
| `ticket_status` | `{ticket, status}` |
| `tool_call` | `{tool, customer, output}` |
| `answer` | `{question, answer, cited_ids, conflict, unknown}` |
| `clock` | `{sim_time}` (about once per simulated hour) |
| `sim_status` | `{running, speed}` |
| `cypher` | `{name, ms, rows}` (throttled; for the activity feed) |

Client → server: nothing required (REST for actions). Reconnect on close; on reconnect, refetch `/graph` and `/stats`.

## Additions (backend, additive)

- **Ticket ids** are `PML-####` (e.g. `PML-2041`) in every API response and event. Inputs are case-insensitive; the graph stores the lowercase key, so the entity id is `e:pml-2041`.
- **Fact cards** carry `active: bool`.
- **`cypher` events** carry `query` (truncated to 2000 chars): `{name, ms, rows, query}`. Every query against the tenant is emitted while a socket is connected.
- **`fact_superseded` events** carry `valid_from` (when the new value became true), `valid_to` (= that same time: when the old value stopped being true) and `expired_at` (when the system retired the old value), all ISO.
- `fact_created` is emitted for every new fact; when it replaces older values, one `fact_superseded` per old fact follows. Clients should treat events idempotently by id.
- `message` events also carry `episode_id`. `sim_status` may carry `skipped` (a turn skipped because every model was busy).
- `cited_ids` (in `/ask` and `answer` events) are raw fact ids; the graph edge id is `f:` + that.
- `/ask` `conflict` is true if the model says so **or** any cited fact is disputed in the graph.
- `POST /sim/start` also accepts `reset` (default true). Fix suggestions from `/pickup` also carry `for_issue` and `distance` (fixes for *similar* issues, by embedding distance).

## Additions (round 2)

- **Retired facts** ("I no longer live in Chennai": ended, nothing replaces it). WS event `fact_retired` `{fact_id, subject, predicate, object, agent, episode_id, valid_to, expired_at}`: the edge becomes inactive exactly like a superseded one, but no new edge appears. `FactChange.status` may be `"retired"` (in `/chat` `learned`). Fact cards for these say "no longer true".
- `GET /api/tenants/{t}/conversation?customer=<key>&limit=400` → `{customer, sessions:[{session_id, started_at, summary, messages:[{episode_id, speaker, text, at, derived:[{fact_id, predicate, object, active}]}]}]}`, oldest first. `derived` is what that message's episode produced (facts from hidden action notes are shown on the message before them). `speaker` is `customer`, `intake`, `resolver` or `tool:*`. `/chat` without `session_id` uses `<first-name>-web-<YYYYMMDD>`; send the returned `session_id` back to continue the same session.
- `GET /api/usage` → `{date, routes:{job:[model]}, models:[Usage]}` where
  `Usage = {model, provider: "groq"|"gemini", jobs:[job], limits:{rpm, rpd, tpm, tpd} (null = unknown), used:{requests, tokens_in, tokens_out, tokens, cache_hits, rate_limited}, remaining:{requests, tokens} (null = unknown), live:{limit_requests_day, remaining_requests_day, reset_requests, limit_tokens_minute, remaining_tokens_minute, reset_tokens, at} | null, exhausted: bool, last_error}`.
  "Used" counts real calls since the start of the day (IST) on this server; `live` comes from Groq's rate-limit headers on the latest call and is the most accurate "remaining". Exhausted models are skipped by the router until the day rolls over.
- `PUT /api/usage/limits` `{model, rpm?, rpd?, tpm?, tpd?}` → the `/api/usage` payload. `PUT /api/usage/routes` `{job, models:[...]}` reorders/limits a job's fallback chain → the `/api/usage` payload.
- WS event `usage` (sent on every tenant socket) `{...Usage}` after each real LLM call or rate-limit hit.

## Additions (round 3): shared knowledge add-on

**Company knowledge** (in every tenant graph, seeded on setup/reset; Entity nodes with `kb: true` and descriptive props, connected by structural edges):
- `GET /api/tenants/{t}/kb` → `{plans:[{key, name, price_inr, speed_mbps, data, router, includes[], notes}], addons:[{key, name, price_inr, notes}], services:[{key, name, price_inr?, turnaround, notes}], policies:[{key, title, text}], coverage:[{city, areas[]}], support:{channels[], hours}}`
- Mr.Fix-It (intake) answers company questions ("How much is Fiber 300?", "Do you do static IPs?", "Can you shift my connection to Baner?") from these nodes; `/chat` `cypher` shows the KB lookup.

**Network + NOC agent** (topology: backbone → POP per city → OLT per area; customers `CONNECTED_VIA` an OLT once their area/city is known; third agent `noc`, trust 0.8):
- `GET /api/tenants/{t}/network` → `{nodes:[{id, kind: "backbone"|"pop"|"olt", label, city, area?, status: "up"|"down", betweenness, customers}], edges:[{id, source, target, kind: "UPLINK"}]}` (`betweenness` from `algo.betweenness`: how critical a node is).
- `POST /api/tenants/{t}/network/{node_id}/fail` → `{node, affected:[{customer, area, path:[node ids]}], tickets:[ticket], notified:[customer]}`: the NOC agent finds every customer downstream (graph traversal), writes the outage into memory, links/opens tickets and has intake message affected customers proactively ("We'll fix it before you have to"). `POST .../restore` → `{node, resolved_tickets:[...], notified:[...]}`.
- WS: `outage_detected {node, label, city, area?, affected:[customer], by: "noc"}`, `outage_resolved {node, label}`. Proactive messages arrive as normal `message` events with `speaker: "noc"` or `"intake"`.

**Knowledge sharing made visible:**
- Every time an agent uses facts (intake reply, resolver answer, NOC impact check) it records `(:Agent)-[:CONSULTED {count, last}]->(:Fact)`.
- `GET /api/tenants/{t}/sharing` → `{agents:[{agent, wrote, consulted, consulted_from_others, reuse_pct}], flows:[{from, to, facts}], top_shared:[{fact_id, sentence, writer, readers[]}]}` (`flows`: facts written by `from` and consulted by `to`).
- WS `consulted {agent, fact_ids[], writers:{agent: count}}` (for live "knowledge flowing" animation).

**Expertise** ("who has worked on this before?"): field technicians are entities (`kind: "technician"`); tickets get `worked_by` facts.
- `GET /api/tenants/{t}/experts?topic=<issue or router>` → `[{technician, tickets, resolved, last_at, via:[ticket]}]`.

New graph kinds: `backbone`, `pop`, `olt`, `area`, `technician`, `service`, `addon`, `policy`.

## Additions (round 4): worldwide, open facts, orders

- **Regions = tenants.** `pml` India, `pml-eu`, `pml-na`, `pml-apac`, `pml-mea`, `pml-latam`. `GET /api/regions` → `[{code, tenant, name, countries[], cities, graph, loaded, stats:{customers, facts, nodes}}]`. `GET /api/isolation?customer=` → `{customer, query, regions:[{region, name, graph, found, facts}]}`.
- `GET /api/tenants/{t}/kb?country=ISO` → `{region, region_name, countries:[{iso, name, currency}], country, currency, tax, payments[], plans:[{key, name, price, price_label, currency, speed_mbps, upload_mbps, devices, router, includes[], lock_in, notes}], addons:[{key, name, price, price_label, notes}], services:[{..., turnaround}], policies, coverage:[{city, key, areas[]}], support, stats:{countries, cities, areas, regions}}`.
- `GET /api/tenants/{t}/network?country=ISO` (nodes now carry `country`; response adds `region`, `countries[]`).
- **New predicates:** `moving_to`, `interested_in`, `budget`, `household_size`, `wants_to_buy`, `current_provider`; **open facts** `open:<attribute>` (e.g. `open:works_from_home`), shown as "works from home: yes".
- **Orders:** `/chat` returns `orders:[{order_id, status, plan, install_at, eta_hours, covered}]`; `GET /api/tenants/{t}/orders?customer=`; `POST /api/tenants/{t}/orders/{id}/install` (puts the customer on the plan). WS `order {order_id, status, plan, customer, ...}`.

## Additions (round 5): intake to spec
- `POST /chat`: `customer` is cleaned of lead-ins ("Myself Adit Raj" → "Adit Raj"); an empty name is a 422.
- **WS `kavya_step {customer, step}`**: what Mr.Fix-It is doing right now ("Looking you up in our records", "Checking the network at Baner OLT", "Looking through your past tickets", "Finding fixes that worked for others with this problem", "Checking plans and prices in India", "Writing your reply"). The portal shows the latest one in the typing bubble while a reply is pending.
- **WS `handoff`** adds `customer`, `issue_type`, `priority`, `context_nodes[]`.
- Internal notes (`speaker: "action"`) now include "intake asked … for: area", "intake got the area it asked … for", "intake declined a request for customer data …"; hidden from `/conversation` unless `include_actions=true`.
- **New predicates:** `occupation`, `visit_reason`, `asked_about`, `requested`, `address`, `awaiting`, `doesnt_know`, `phone`, `email`, `account_id`, `alt_phone`, `installed_at`, `connection_type`, `preferred_name`, `billing_contact`, `has_addon`, `referred`, `previous_contact`, `service_request`, `calling_for`, `on_waitlist`; on tickets `issue_type`, `issue_started`, `frequency`, `severity`, `affected_device`, `error_message`, `router_lights`, `speed_reported`, `connection_medium`, `affected_users`, `distance_from_router`, `has_priority`.
- Graph: `Customer` nodes add `router`, `phone`, `email`, `account_id`, `connection_type`, `installed_at`, `addons[]`, `churn_risk`, `address`; `Ticket` nodes carry `status`, `priority`, `issue_type`, `issues[]`, `started`, `frequency`, `severity`, `devices[]`, `tried[]`, `router_lights`, `speed_reported`, `connection_medium`, `error_message`; `(Ticket)-[:RAISED_IN]->(Session)`, `(Session)-[:FOLLOWED_BY]->(Session)`; `Guide` nodes (issue trees) in every region graph.

## Additions (round 6): live model status, FalkorDB-native views
- `GET /api/usage` models add `state` (`available` | `rate limited` | `exhausted` | `recovering` | `not checked yet` | `no key`), `checked_at`, `ok_at`, `latency_ms`, `back_at`, `back_in_s`; payload adds `at`. Status comes only from what the provider last said (a 429's "try again in", Gemini's midnight-Pacific reset, Groq headers), never from local counters or a fixed bench time.
- `POST /api/usage/check {model?}` sends one tiny real request (a few tokens) to that model, or to every model in the routes, and returns the fresh snapshot. The API also checks every model once at start, and every minute re-checks any model whose provider-stated recovery time has passed. Every check pushes a `usage` WS event.
- `POST /api/tenants/{t}/plan {query, params, profile}` → `{plan: [lines]}` (GRAPH.EXPLAIN, or GRAPH.PROFILE for read-only queries).
- `GET /api/memory` → `{limit_mb, total_mb, graphs:[{tenant, mb}]}`; `/api/regions` rows add `memory_mb`.

## Additions (round 7): schema, operations, chatbot
- `POST /api/tenants/{t}/chat` body adds `greeted: bool` (default false): the client already greeted by name, so the reply doesn't greet again.
- `GET /api/db/health` → server info (`GRAPH.INFO`, config, memory) or `{ok:false, error}`.
- `GET /api/tenants/{t}/slowlog` → `{tenant, queries}` (`GRAPH.SLOWLOG`).
- `GET /api/tenants/{t}/snapshots` → `{tenant, snapshots, kept}`; `POST` `{label}` → `{name, snapshots}` (`GRAPH.COPY` to `snap:` keys, 1 per tenant; skipped above 60% of the instance's memory, a manual one then answers 507); `POST /api/tenants/{t}/snapshots/{name}/restore` → `{ok, restored}`. A snapshot is taken before every story reset.
- `GET /api/tenants/{t}/network/{node_id}/capacity` → `algo.maxFlow` from that node over links that are `:Up`.
- `GET /api/tenants/{t}/network-cable-plan` → `algo.MSF` over link km (the cheapest way to connect every site).
- `/api/tenants/{t}/network` nodes add `harmonic` (reach).
- `/api/tenants` hides `test-*` graphs.
- `POST /api/tenants/{t}/chat` response adds `images: {query, images:[{src, title, link}]} | null`: when a game, show/film, streaming platform or physical device comes up (message, extracted `plays_game`/`watches`/`owns_device` facts, or the reply), the lead image of its Wikipedia article (`src` is a wikimedia URL), at most 2 per reply and once per topic per session; cached on disk per topic.
- Groq key pool: `GROQ_API_KEY`, `GROQ_API_KEY_2` … `_5`; `/api/usage` models include `groq2:<model>` … rows (provider `groq2` …), one per key.

## Additions (round 8): public demo protection, confirm value, Judge mode support
- **Reset key.** With `RELAY_RESET_KEY` set, `POST /api/tenants/{t}/reset`, `POST /api/tenants/{t}/lab/reset`, `POST /api/tenants/{t}/snapshots/{name}/restore`, `PUT /api/usage/limits`, `PUT /api/usage/routes` and `POST /api/tenants/{t}/sim/start` with `reset: true` need header `X-Reset-Key`; without it → `403 {detail, need: "reset_key"}`. The web app asks for the key once per tab and retries. Unset: nothing is locked.
- **Rate limits.** With `RELAY_CHAT_PER_MIN` / `RELAY_WRITES_PER_MIN` set, writes (`POST`/`PUT`/`DELETE` under `/api/`) are counted per visitor address (first `X-Forwarded-For` entry) per minute, chat turns separately → `429 {detail}` with `Retry-After: 60`. Reads are never limited. Unset: no limits.
- **Server errors** come back as `500 {detail: "Server error: <type>: <message>"}` from inside the CORS middleware, so the browser shows them (not "blocked by CORS policy").
- `POST /api/tenants/{t}/claims/confirm` `{subject, predicate, fact_id, by?: "operator"}` → `{confirmed: {fact_id, value, asserted_by}, rejected: [{fact_id, value}], trust: [{agent, from, to}], episode_id}`. A person settles a disagreement on a single-valued "trust" predicate: the chosen claim gets `:Confirmed` and a `CONFIRMED` edge from a review episode (agent `operator`, speaker `action`); the other claims are retired (both clocks close, `:Rejected`, kept in history); the `Conflict` closes with `resolution: "confirmed by <by>: <value>"`. `400` for a predicate agents can't disagree on, `409` if the claim is no longer active, `403` on benchmark tenants. WS **`conflict_resolved {subject, predicate, value, by, rejected, trust}`**.
- **Learned trust.** Claims are ranked by each writer's trust on that predicate moved by its track record (`+0.05` per confirmed claim, `−0.05` per rejected one, within 0.05–0.99). `POST /api/tenants/{t}/tools/claims` rows add `base_trust` (the fixed per-agent trust) and `record` (confirmed minus rejected); `trust` is the learned value. With no confirmations nothing changes.
- **Agents** add `mcp` (trust 0.7: Claude Code, Claude Desktop or any MCP client; `mcp_server.py` accepts it as `agent`) and `operator` (a person confirming claims; writes no facts).
- `POST /api/tenants/{t}/compare` on a graph with no episodes yet → `409 {detail}` (what to do) instead of a crash.
- Lab runs: `awaiting` is `"guided" | "details" | true | null` (what the resolver waits for from the customer; `true` = "is it working now?"). A home's `state` adds `reported`: the customer says it's broken while every reading is healthy; it's drawn as faulty until a technician has been. Queries made while drawing the lab view are named `lab view: …`, so the live-query glow ignores them.
- **Write-time value checks.** A fact whose value can't be real for its type (a router "wifi", a city "home", a phone without 7 digits, an email without a domain) is dropped before the write, like an unknown status.
- **Location from the address.** `POST /api/tenants/{t}/chat` adds `desk: {tenant, region, city, country, move} | null` when the address the customer just gave (a `lives_in` or `address` fact) is served elsewhere: `move: true` for another region's desk (the portal moves the case there and re-tells the customer's messages), `move: false` for another country of this region (the portal switches the country). Places are resolved by `relay/geo.py`: the catalogue, then the offline GeoNames list, then OpenCage (`OPENCAGE_API_KEY`, optional), matched to the nearest city we serve; a customer's line uses the same resolver, so a suburb or PIN code we don't list still gets a line.
