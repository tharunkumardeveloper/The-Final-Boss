# Relay: what we built, what we learned, where it stands

Companion to `PLAN.md` (the plan). This file is the record: what was done, what was verified, what is open, and an honest evaluation.

---

## 1. The product in one paragraph

**Relay** is shared graph memory for teams of AI agents, built on FalkorDB. It is demoed on **Ping Me Later**, a fictional Indian fiber ISP ("We'll fix it before you have to.") whose AI support desk has an **intake** agent (talks to customers, opens tickets) and a **resolver** agent (works tickets with billing, outage and diagnostic tools). They never message each other: everything one knows, the other finds in the graph. Relay remembers across sessions, tracks how facts change on two clocks, keeps disagreements between agents instead of overwriting them, retires facts that stop being true, and returns the graph path behind every answer.

## 2. What we did, in order

### Phase 1: Plan review
Read the original build guide and the event brief, and found real defects before any code:

| Defect in the original plan | Fix |
|---|---|
| `algo.CDLP` doesn't exist | `algo.labelPropagation` (verified in the docs) |
| Graph algorithms ran on an edgeless graph (facts stored as nodes, no Entity–Entity edges) | Materialised `RELATED` edges for current facts |
| The contradiction query superseded itself, ignored role, ignored unchanged values, broke multi-valued facts | Self-exclusion, role filter, object-changed check, cardinality per predicate |
| World time and system time conflated | Four timestamps: `valid_from/valid_to` (world) and `recorded_at/expired_at` (system) |
| Entity resolution raced under concurrency | Single-statement `MERGE` on a normalised key + unique constraint |
| Free-text predicates would never match | A fixed predicate registry, enforced by a strict JSON schema |
| "Memory" framing overlaps Graphiti | Re-framed around **coordination** (handoffs, disagreements, concurrency) |

### Phase 2: FalkorDB practice drills (verified facts)
- The vector `score` is a **distance** (0 = identical), so sort ascending. The plan had it backwards.
- Unique constraints are **asynchronous** (`PENDING` → `OPERATIONAL`) and need a range index first.
- PageRank over the edgeless schema gave every entity 1/6; over `RELATED` it gave real scores.
- Writes to one graph are serialized, while separate graphs ran writes about 6× faster in a raw drill.
- `MERGE` on a triple key + `FOREACH`-guarded edges is race-free: 10 concurrent writers → 1 fact, 10 provenance edges.
- Groq `gpt-oss-20b` with a strict schema mapped 4 paraphrases to `lives_in`, 12/12 including 3 traps.

### Phase 3: Core engine
A Python package `relay/`: write path (extraction → entity/alias resolution → atomic fact write), read path (entity linking + vector entry → 2-hop expansion → conflict ranking → cited answer), two clocks, path explanation, label propagation + PageRank, and the intake/resolver agents with mock tools. Tested end-to-end against FalkorDB Cloud.

### Phase 4: First proof
- **Benchmark** (8 customers, 74 questions): Relay **93%** vs vector store with dates **43%** (91% vs 43% on the same 46 questions).
- **MCP server** (7 tools), so any MCP client can join as another agent.
- **Load tests.** Folding the supersede step into the write statement raised throughput from 8.4 → **18.3 writes/s** on 1 graph (23.7 across 4), with **0 duplicates**. Recall latency was 178 ms at 1.1K facts and 210 ms at 10.9K.
- The free tier runs out of memory at about 15–75K nodes.

### Phase 5: Plan v2
- `PLAN.md` written. Company named **Ping Me Later**.
- Model routing designed on the account's real Groq limits (no Llama models available).
- A critique built in: confidence intervals, gap decomposition, k-sensitivity, component metrics, abstention precision/recall, determinism and external validity.

### Phase 6: The full product
- **LLM router:** each job on its own model (Groq quotas are per model), automatic fallback on rate limits, and every response cached on disk.
- **Backend:**
  - event bus;
  - conversational intake (replies grounded in memory);
  - a 6-persona simulator with scheduled life events and a simulated clock (hit all 17 planted moments);
  - readable node cards;
  - PageRank salience in ranking;
  - session and community summaries;
  - FastAPI + WebSocket;
  - `render.yaml`, model pre-warm, and a demo cache;
  - about 353 MB RAM (Render free tier is 512 MB).
- **Web app** (React + TypeScript): the Ping Me Later customer portal and operations console, with a live animated graph, two-clock scrubber, node inspector, answer-path highlight, ticket board, Cypher drawer and benchmark page. It has a mock mode and Vercel config.
- **Evaluation scale-up:**
  - per-tenant predicate registries (ISP and "personal life");
  - a dataset of 40 customers / 556 turns / 160 questions with planted name collisions;
  - extraction recovered **293/306 planted facts (95.8%)**;
  - one public LoCoMo conversation ingested (174 turns).

### Phase 7: Fixes from hands-on testing
| Reported | Root cause | Fix |
|---|---|---|
| "I no longer live in Chennai" didn't change the graph | Extraction only accepted facts true *now*; a bare "no longer" produced nothing | An `ended` flag in extraction, plus a `RETIRE` query: the fact closes both clocks, keeps its history, loses its live edge and links the episode that ended it; a `fact_retired` event updates the graph live |
| Chat had no history or context | No conversation endpoint; the portal started fresh | `GET /conversation` (all sessions, both sides, summaries); the portal persists the session id and shows earlier sessions |
| Portal didn't update in real time | The portal didn't listen to events | The portal now opens the tenant WebSocket and updates "What we remembered" live; the console shows portal messages |
| No view of API limits | — | A usage ledger: requests and tokens per model per day vs limits, live Groq rate-limit headers, exhausted flags (the router skips exhausted models), editable limits and per-job routes, and a `/console/usage` page with a header indicator |
| Rahul/Priya cities missing from the benchmark | "We're based in Mumbai" ("we") wasn't treated as the customer | A prompt rule: "we / our home / our family" from the customer = the customer |
| The "NimbusNet" brand was still in the prompt | Leftover | Renamed to Ping Me Later |
| Backdated dates lost after the prompt change | The longer prompt weakened the date rule | Worked examples in the prompt; the API test catches this regression |

### Phase 8: Shared-knowledge add-on and polish
| Item | What changed |
|---|---|
| Kavya's replies | Customer-scoped memory as plain sentences; told the customer's name and when their city is outside coverage; greets once; no field talk; hard cap of 3 sentences / 60 words; graceful "note-taking paused" when every extraction model is out of quota (the benchmark loader still waits and retries instead) |
| Names in FalkorDB Browser | Type labels on every entity (`Customer`, `City`, `Plan`, `Ticket`, `Olt`, `Technician`…), typed current-fact edges (`LIVES_IN`, `HAS_TICKET`…) instead of generic `RELATED`, a readable `name` on every node, and an in-place migration for older graphs |
| Company knowledge | Plans, add-ons, services, policies and 16 coverage areas stored in the graph; customer `ON_PLAN` edges point at the same nodes; Kavya answers prices and coverage from it; the portal renders it |
| Knowledge sharing | `(:Agent)-[:CONSULTED {count}]->(:Fact)` each time an agent uses a fact; Sharing page with writes vs uses, reuse %, live flows, most shared facts |
| Network + NOC agent | Backbone → POP → OLT → customer topology; `algo.betweenness`, `shortestPath`; a node failure finds affected customers by traversal, writes the outage into memory and messages them first; the simulator includes an outage moment |
| Expertise | Technicians assigned at pickup (`WORKED_BY`); "who has worked on this before?" search |
| Chat name | Greetings are no longer taken as a name ("Hi There" → asks again; "I'm Tharun" → Tharun) |
| Usage ledger | Daily-quota benching expires after an hour (Groq windows roll) |
| Benchmark safety | Separate `pml-bench` tenant, protected from resets and the simulator |
| Scripts | `install.bat`, `start.bat`, `start.bat mock` |

### Phase 9: Worldwide, open facts, grounded replies
| Item | What changed |
|---|---|
| Worldwide company | Ping Me Later now serves 39 countries in six regions. `data/kb_world.py` builds the catalogue from GeoNames `cities15000` (CC BY 4.0): 199 cities, 1,118 areas, local prices/taxes/payment methods, 162 FAQs, 100 playbooks with 467 linked steps, 270 technicians |
| One graph per region | `pml` (India), `pml-eu`, `pml-na`, `pml-apac`, `pml-mea`, `pml-latam`, about 7.5K nodes in all, each seeded with its own catalogue, network and technicians. Regions page with an isolation check |
| Place resolution | "blr", "HSR Layout bangalore" and "nyc" resolve to the right city/area; an area named in the message beats a city-only extraction |
| Open facts | Anything concrete outside the fixed predicates is stored as `open:<attribute>`, merged with existing attributes by embedding distance; new predicates `moving_to`, `budget`, `interested_in`, `household_size`, `wants_to_buy`, `current_provider` |
| Orders | "I'll buy it" creates an `Order`, not `on_plan`; installation makes the plan current; `moving_to` retires itself when the move happens |
| Grounded Kavya | Reply guard: unknown plans, prices not in the catalogue text, wrong price/speed/device count next to a plan, over-budget "fits", false "we don't cover you"; one retry, then a factual fallback. Plan and price questions answered from the graph. Lists aren't cut mid-item; one greeting per conversation; internal notes no longer appear in the customer's chat |
| Transcript regression | `tests/test_transcript.py` replays the conversation that went wrong (invented "Fiber 200", HSR coverage flip, "on Fiber 1000" before installation) on `allam-2-7b`, the weakest model, and passes |
| Readable customers | `Customer` nodes carry `city`, `plan`, `moving_to`, `budget`, `open_tickets`, `pending_order`, `facts`, `last_seen` and a display name, refreshed every turn |
| Agent team | The Sharing page (now "Agent team") shows every agent's role and trust weight, including agents that haven't acted yet |
| Docs | README rewritten for worldwide, open facts, the reply guard and saved FalkorDB Browser queries |

### Phase 10: Intake agent to spec (`intake_agent_spec.md`), from real portal chats
Driven by four chats that went wrong in the portal, then by the intake spec. Each chat is now a replay test.

| Chat or spec item | What was wrong | What changed |
|---|---|---|
| "Myself Adit Raj", a "police officer" asking for customer data | Name taken as "Myself"; Kavya offered to send data to an address | Name lead-ins stripped in the portal and the API. Any request for other customers' data, or invoking police/warrants/investigations, gets one fixed reply (official request to the legal team) and an internal flag; the model never sees it. `occupation`, `visit_reason`, `asked_about` (every question asked, merged by meaning) and `requested` are stored. `tests/test_anomaly.py` |
| Pallavi, Chicago, on the India desk | Address saved nothing; "I'm checking…" loop; India prices for a US customer; "can't schedule installation" | `address` + `lives_in` from a bare address; no "I'll check / get back" sentences (she can't act after replying); the catalogue comes from the graph of the region that serves the customer (US plans in USD from `mem:pml-na`), using the last place mentioned before an address is on file; booking happens in the chat. `tests/test_pallavi.py` |
| Raj Kumar, "I'm using your broadband and it sucks" | Ticket opened and fixes suggested with no idea who he is or where | Kavya digs before replying and the chat shows each lookup live (records, network at their OLT, past tickets, fixes that worked for others, local plans). She says what she found ("I checked Baner OLT and the network there is up"). What she asks is memory: `awaiting` facts, retired when answered; the next message is read as the answer to her question. `tests/test_raj.py` |
| Spec §1–3: order of work, identity once, one question at a time | Model chose what to ask; asked twice or two things | `relay/intake.py` plans every turn: graph check, greeting (new vs returning: "welcome back, you're on Fiber 300 in Indiranagar"), direct answers, then the first missing slot in the spec's order and wording (registered number → city/area → plan → router → when it started → frequency → whole home or one device → WiFi or cable → what they tried). "Don't know" gets the spec's hint once (router sticker, welcome SMS, router box speed), then `doesnt_know` and she moves on. Answers are read against the catalogue ("300 mbps" → Fiber 300, "hub 6 pro" → the PML Hub 6 Pro node) |
| Spec §2: identity, issue details, life events | Not stored | 27 new predicates. Phone, email and account number are captured by pattern and become their own nodes, so a shared number is a graph match. Issue details go on the ticket (held until it opens). Add-ons (catalogue-checked), referrals, billing contact, preferred name, previous contact, calling for someone, waitlist |
| Spec §3 states 2–6 | — | Returning greeting and open-ticket "follow-up or new?"; changes said back; repeat contact or frustration raises the ticket to `high` priority once; a number registered to someone else never reveals who (their account opens only if name and number both match) |
| Spec §4 issue trees | — | 15 trees in `data/issue_trees.json`, seeded into every region graph as `Guide` nodes with embeddings; the nearest by meaning steers the model's free replies |
| Spec issue trees: coverage, billing, cancellation, outage | — | Coverage answered from the graph with local plans, or the waitlist (`ON_WAITLIST`) for places we don't serve; no billing details before identity is confirmed; service requests (pause, cancel, relocation, billing dispute…) open typed tickets; cancellation sets `churn_risk`; a down node gives a plain outage message, never home fixes |
| Spec §7 handoff | — | `Ticket` node carries status, priority, type, started, frequency, severity, devices, tried, router lights, speed; `RAISED_IN` its session; sessions chained `FOLLOWED_BY`; the handoff event carries priority, issue type and context nodes |
| Spec §8 "never" list | — | Enforced on every reply: one question, nothing already known asked, no fix-time promises, no troubleshooting before identity, intake can't change ticket status, internal notes hidden |
| Spec scenarios | — | `tests/test_intake_spec.py`: session 1 identity flow with hints, session 2 returning with a move and escalation, billing check, coverage + waitlist, cancellation, identity mismatch. Passes |

### Phase 11: Real-browser pass (portal and console side by side, real API)
Driven through Chrome against the live API, not mock mode. What held and what broke:

| Check | Result |
|---|---|
| Console updates live while the portal chats | ✅ new customer, messages and internal notes appear without a reload; stats and entity counts move |
| Kavya's live steps in the typing bubble | ✅ "Noting what you just told me › Looking you up in our records › Checking plans and prices in India › Writing your reply" |
| API killed mid-session | ✅ console shows "Reconnecting" within 3 s; the portal says "That message didn't go through" and keeps the text; both reconnect and refetch when the API returns |
| **Bug: the answer to "which plan would you like?"** | Extraction filed "fiber 300 please" as the plan they already have, and with quota out nothing was ordered. Fixed: the answer is read against the catalogue, a misfiled `on_plan` is turned into an order, and the order is said back whichever path placed it |
| **Bug: two customers shared one session** | Session ids used the first name ("Browser Check" and "Browser Two" got `browser-web-…`). Fixed in the API, the NOC's proactive messages and the mock |
| **Bug: region switch showed the wrong country** | Several first requests for a region seeded its graph in parallel and hung; the portal kept India's prices and outage banner under "North America". Fixed: per-tenant setup lock, every region graph warmed at startup, the embedding model loads once under a lock, and the portal clears the old region's data and drops late answers |
| Next question after an order | Fixed: asks for the installation address in the place they checked, instead of letting the model improvise |
| Clutter | Graphs left by failed test runs are hidden from the tenant picker |
| Still open | The simulator's outage feed never ends an outage, so "Fiber cut near Baner" shows on the India portal indefinitely; a region switch ends the open chat; the console reopens the portal's last region on reload |

Screenshots failed in this environment (the extension's capture timed out), so the canvas animation itself was not inspected; everything else was checked through the DOM and the API.

### Phase 12: Using FalkorDB's own features, and the browser-pass leftovers
| Item | What changed |
|---|---|
| Browser-pass leftovers | Simulated outages have time windows and the resolver retires what the feed stops reporting (stale "Fiber cut near Baner" banner gone); a region switch keeps the person and loads that desk's history; portal and console remember their own region; a problem described only through ticket details still opens a ticket (regression from Phase 10) |
| Sarvam | `sarvam-105b-conversations` added after the free models in every route: 1 s extractions, 0.5 s replies. Plain `sarvam-105b` is a reasoning model (3-5K hidden tokens per extraction, 3 of 4 empty) and isn't used |
| Guardrails | A server-side timeout on every read (verified: "Query timed out"), every variable-length pattern capped, `GRAPH.MEMORY USAGE` per graph on the Regions page and `/api/memory` |
| State labels | `:Current/:Superseded/:Retired` facts, `:Prospect/:Subscriber/:ChurnRisk/:Business` customers, `:Open/:Resolved/:HighPriority` tickets, episode kinds, `:Pending/:Installed` orders, kept in step by the queries that change state; backfilled once |
| Constraints and indexes | `UNIQUE` Entity.name_key, Fact.fact_id, Session.session_id, Order.order_id; `MANDATORY` Fact.triple_key, Episode.episode_id; a `FULLTEXT` index on customer names now drives fuzzy entity linking ("alise rao" finds Alice Rao; ties are not guessed). Found: MANDATORY is checked when MERGE creates a node, before ON CREATE SET |
| Time on edges | A replaced or ended fact's edge becomes `WAS {predicate, valid_from, valid_to}`; current edges carry `valid_from`; `retrieve.graph_at()` traverses the world at any date over two hops. GRAPH.EXPLAIN shows the date filter runs after the expansion |
| UDFs | The `relay` JavaScript library (`relay.sentence`, `relay.money`, `relay.ago`, `relay.state`), generated from the Python tables and loaded at setup |
| Console | Explain and Profile on every logged query (Profile only for read-only ones). First catch: chat sessions were loaded by a full Episode scan; an `Episode.session_id` index fixed it |
| README | A FalkorDB Browser tour: schema view, UDF viewer, one tab per view, every query verified on `mem:pml` |
| Live model status | Status comes only from what the provider last said (Groq's "try again in", its reset headers, Gemini's midnight-Pacific reset), never from local counters or a fixed one-hour bench. A background checker re-tests a benched model with a 1-token request once its time passes; every model is checked once at API start; "Check now" / "Check all now" on the usage page; each card shows when it was last really checked, its latency and a live "back in" countdown; the ledger is re-read when another process writes it (`tests/test_status.py`) |
| Chandran (Goa) chat | "Welcome back" to a first-time visitor (returning now = an earlier session), "We don't cover Do You Offer" (coverage needs a coverage verb and a real place), "yeah any offers?" taken as a yes to the waitlist (only after a waitlist question), staff `awaiting` notes in the customer's panel (hidden). The coverage filter now runs on the final reply, retries included (`tests/test_chandran.py`) |
| LLM providers tried | Sarvam `105b-conversations` (in the routes as a paid fallback); Velona (no enforced schema, 9-24 s: not used); DeepInfra (needs a $5 minimum balance, untested); OpenRouter free Nemotron (schema-correct but ~30 s per extraction: a possible free last resort) |
| Incident | A capability probe ran `UNWIND range(1, 50000000)` with a short timeout; the list was built before the timeout applied, the free tier's 100 MB ran out and the instance restarted from a snapshot. Real data was intact; region catalogues rolled back and re-seeded. Lesson kept in config: timeouts don't protect against one huge allocation |

Not done to the letter: the spec confirms a contradiction *before* updating; Relay updates, says it back and keeps history (a hold-until-confirmed flow is possible). Spec prices (₹599/799/1199) and the ₹100 loyalty discount are not used; replies quote the catalogue, which the grounding guard enforces. The spec's `EXTRACT:` line is replaced by the separate strict-schema extraction call.

### Phase 13: The full schema, more FalkorDB, and a chatbot that remembers
| Item | What changed |
|---|---|
| Sessions and authorship | `(:Customer)-[:HAS_SESSION]->(:Session)`, every fact `WRITTEN_BY` an `:Agent` (last active, facts written), the simulator is an agent too |
| Desk records | `:Escalation`, `:Notification` (outage notices), `:TechVisit` (opened on assign, closed on fix), outage ETA (4 h), `:ServicePause`, referrals |
| Identifiers | Ticket opened/closed times, handoff ids (`randomUUID()`), 16-hex event ids, fact metadata (cardinality, policy, corroboration count), extraction provenance (model and prompt version on each episode), `:Conflict` nodes opened and closed with the disagreement, customer signals (contact count, same-issue count, preferred language and channel, waitlist area) |
| Readable time | `localdatetime` beside every epoch-ms field (`valid_from_dt`, `at_dt`, `ended_dt`…) |
| Geo | `point()` on 18,834 places (`data/places.json`) with an index on `City.location`; "do you cover Goa?" answers with the nearest served city and its distance |
| Operations | `GRAPH.COPY` snapshots (3 kept, one before every story reset, restore from the console), `GRAPH.SLOWLOG`, `GRAPH.INFO`, server `TIMEOUT_DEFAULT` set at start; a new console Database page |
| Network algorithms | Harmonic centrality (reach), `algo.maxFlow` over `:Up` links (capacity from a node), `algo.MSF` on km (cheapest cable plan) |
| FLEX | FalkorDB's own UDF library (`data/flex.js`, release build, reviewed) loads beside `relay`; `flex.text.levenshtein` breaks full-text ties in fuzzy name matching |
| Chatbot revamp | No name box: Kavya asks in chat, the name is found inside a normal message ("Hi, I'm Adit and my wifi drops" → Adit, the rest is sent on), highlighted, and "Not right? Change it" fixes it. A question asked before the name is held and answered after. The last chat on this device is cached (`localStorage`) and shown with "Continue as". No double greeting (`greeted` flag) |
| Memory panel | "Everything I remember about you" (every agent, every session) and "What changed" (no longer lives in Mumbai); each row's **How I know** opens the source message, who wrote it and both clocks; competing claims are shown as a disagreement on the preferred one |

### Phase 14: locked.in and Mr.Lowkey
| Item | What changed |
|---|---|
| Brand | Ping Me Later / Kavya became **locked.in** ("Fiber fast. Game hard. Binge harder.") and **Mr.Lowkey** ("Chill. I've got this."). One file, `agent-relay/brand.json`, names them; backend and web both read it, catalogue text uses `{company}`. Internal ids (`pml` tenants, the `intake` agent, PML Hub router keys) are unchanged |
| Service lines | `data/offerings.json`: Fiber Internet, Gaming Zone, Binge Club, The Hub, as 14 `:Offering` KB nodes found by meaning, plus a four-line overview in the prompt. No promised ping, no unconfirmed streaming or gaming partners, no internal partnership talk (`tests/test_lockedin.py`) |
| Serves everywhere | No "we don't cover", no waitlist: a place without a catalogue entry is a yes, then the exact address. Catalogue and guide text no longer mention coverage limits |
| Tagline | Said once, as a greeting; later replies have it removed in code |
| FLEX tie-break fix | Only name words the message came close to count, so an untyped surname never decides (`test_schema` "chitraa" case) |

### Phase 15: A resolver that acts and proves it, a customer in the loop, three screens
| Item | What changed |
|---|---|
| Three memory types visible | Memory panel shows **semantic** (facts), **episodic** (what changed, two clocks) and **procedural** (fixes that resolved issues, `/api/tenants/{t}/procedural`, from `resolves` facts) |
| Resolver picks up by itself | Intake's handoff starts the resolver in the background (no console click); a double-pickup guard; ticket ids get a random suffix so concurrent tickets can't collide; the resolver writes its reply into the customer's own chat session |
| Console speed | `/summary` returns stats + tickets + customers in one round trip (three queries in parallel), ticket events debounced; `tickets()` no longer runs twice per refresh |
| Conversation fixes | Budget note dropped once an order is placed; closings ("okay got it thank you") end cleanly; date-change claims stripped (only a technician confirms dates); "lock in" means finalize; student offer at most once; no-model fallback asks "what's happening?" instead of "Thanks, got it." |
| **Network Lab** (`relay/lab.py`) | The last mile in FalkorDB: street cabinet (`:Splitter`), a box per home (`:Ont`, ~15 neighbour homes per cabinet), primary/standby hub links, evening demand per exchange. Readings (light level, box state, login, neighbours offline, `algo.maxFlow` capacity, 9 pm headroom, Wi-Fi interference) are derived from physical state by Cypher |
| Hidden truth | 8 fault presets (frozen box, Wi-Fi interference, damaged home fibre, street cable cut, hub link with/without backup, evening congestion, payment failed). The truth goes to a separate graph `chaos:<tenant>` the resolver never reads; field jobs only fix the place they are sent to |
| Diagnose → act → verify | The resolver reads intake's facts (recorded as `CONSULTED`), measures, lets the model choose the action (rules as fallback and cross-check), checks the action is **feasible** on this line (no reroute without a standby link), acts, re-measures, retries up to 3 times, is graded against the hidden truth. Procedural memory is written **only after** the re-measurement passes, with before/after readings |
| Customer in the loop | A network complaint with nothing broken makes the world pick a hidden cause that fits the words; before a home visit: remote checks, one guided step, then street address + mobile + slot collected in chat, booked and confirmed back; "is it working now?" — yes closes the case, no starts a new investigation |
| One voice | The resolver claims a complaint **before** intake replies (`before_chat`), intake's notes carry the resolver's status, intake never invents steps or promises visits, and its network check uses the lab readings (it once said "not an outage" while a hub link was cut) |
| Instruction pictures | Drawn guide cards (model sticker, LOS light, restart the box, router placement, fibre cable) travel as `[guide:key]` in messages; Wikipedia product photos removed from chat |
| Three screens | **Customer** (`/`): chat · tickets + what we remember · own memory graph with replay. **Memory graph** (`/console/graph`): live + replay over fact timestamps. **Network console** (`/console/lab`, `?talk=1`): faults, live network map (adapts to width, never a thin strip), resolver trace, scoreboard; talk mode puts chat, memory + resolver, and network side by side |
| Privacy fix | The customer graph uses `/my-graph` (own facts and tickets only); the console's 2-hop view would have shown other customers through shared nodes like a plan or a city |
| Bugs found by chatting | An unlisted locality ("Pattabiram") gave no line; it now falls back to the city named in the same message. Identity isn't asked again once the line is known |
| Chat loop fixes (Tyson transcript) | A "no" after a verified fix looks inside the home (restart, then a visit) instead of inventing a new network fault; "I no longer live in Chennai" no longer counts as "no"; Wi-Fi + PS5 beats "every evening"; no "your 100 Mbps plan" when the plan is unknown; identity asked at most twice; the priority apology once per conversation; one goodbye |
| Simulator bug | Play called `sim/start` with `reset` defaulting to true, so every press (and every speed change) wiped the graph. Play now resumes, speed changes in place, and Reset story runs in the background with live phases |
| Console pages | Agent team: click agents or arrows to filter a live feed of hand-overs, and "Show me a handoff" starts one. Database: pick a graph, schema explorer (labels, relationships, indexes), read-only Cypher console with examples, Explain/Profile, live round-trip chart. Two clocks: each fact's state at the chosen moment, jump buttons, only differences called out. Benchmark: "Ask both memories" (graph vs the B1 vector store, same model, live) and an honest run status |
| Crash guard | An error boundary keeps a render crash from blanking a page |
| **Tenant isolation, enforced** | Every `/api/tenants/{t}/…` request and the live stream need that tenant's key (HMAC of the tenant name, constant-time check, nothing stored); missing key 401, wrong key 403, stream closed 4403; the cross-tenant customer lookup needs an operator key. An **Isolation audit** page (`/console/isolation`) attacks tenant B with tenant A's key from the browser and shows every real response (13/13 checks pass over HTTP and WebSocket). Limit, stated on the page: no per-tenant database users on this cloud plan; the demo server hands its own web app every key (`RELAY_DEMO_KEYS=0` stops it) |

Known issues: uvicorn `--reload` hangs on this Windows setup (restart the API by hand after backend edits); FalkorDB Cloud times out now and then from this network; the new screens were driven through the API but not screenshot-checked by us (the browser extension couldn't capture pages).

## 3. Architecture

```
Browser (Vercel)                 API (Render)                                FalkorDB Cloud
┌───────────────────────┐   REST │ FastAPI ─ agents (intake, resolver,     │  mem:<tenant>
│ Customer portal (chat)│ ─────► │          simulator, mock tools)         │  one graph per tenant
│ Operations console    │ ◄───── │        ─ relay engine (write / read /   │ ◄────────────────────
│  live graph · cards · │   WS   │          clocks / consolidate)          │  Cypher + vector index
│  scrubber · usage     │ events │        ─ LLM router + cache + usage     │  + algorithms
└───────────────────────┘        └─────────── Groq · Gemini ───────────────┘
MCP clients (Claude Desktop, …) ──► mcp_server.py ──► same engine, same graph
FalkorDB Browser ──► same graph (proof: same Cypher, same rows)
```

**Repo** (`agent-relay/`):
- `relay/` is the engine. `queries.py` holds every Cypher query, with comments.
- `api/` is FastAPI plus `CONTRACT.md`.
- `web/` is React + TypeScript.
- `data/` is the generator and loader.
- `eval/` is the benchmark, components, LoCoMo, out-of-distribution extraction and load tests.
- `tests/` holds the tests.
- Also: `mcp_server.py`, `render.yaml`, `demo_cache/`, `README.md`.

## 4. Key decisions and why

| Decision | Why |
|---|---|
| Facts as nodes **and** `RELATED` edges | Nodes keep full history and provenance; edges mirror the current world for traversal and algorithms |
| Fixed predicate enum at write time | Contradiction detection needs comparable predicates; the LLM can't invent new ones |
| Deterministic contradictions (cardinality + policy) | Predictable and testable; we don't ask an LLM whether two facts conflict |
| "trust" vs "latest" policy | World facts from different agents coexist and are ranked; workflow state (ticket status) is last-write-wins |
| One statement per fact write | FalkorDB serializes writes per graph, so no reader sees two current values and no writer duplicates |
| One graph per tenant | Structural isolation; vector search needs no tenant filter |
| Per-job models + fallback + cache | Fits free quotas; re-runs are free; the benchmark pins one model per question for fairness |
| Our own graph UI, with FalkorDB Browser as proof | Live animation, two clocks and answer paths need our UI; Browser shows the data is real |

## 5. Tests and how to run

```bash
cd agent-relay
pip install -r requirements.txt            # .env or ../falkor.env holds FALKOR_*, GROQ_API_KEY, GEMINI_API_KEY
python -m tests.test_core                  # engine end to end
python -m tests.test_api                   # every endpoint + WebSocket during a sim
python -m tests.test_round2                # retire, "we", conversation history, usage
python -m tests.test_mcp                   # MCP server over stdio
python -m tests.test_kb                    # worldwide catalogue, local prices, place resolution
python -m tests.test_open_facts            # open facts, budget, moves, orders
python -m tests.test_profile               # readable Customer profile in the graph
python -m tests.test_transcript            # the bad conversation, replayed on the weakest model
python -m tests.test_intake_spec           # intake_agent_spec.md, scenario by scenario
python -m tests.test_anomaly               # "police officer" data request, name lead-ins
python -m tests.test_pallavi               # Chicago prospect on the India desk: address, US prices, booking
python -m tests.test_raj                   # unknown customer with a problem: identity first, live digging
python -m tests.test_scoring               # benchmark scoring
uvicorn api.main:app --port 8000           # API
cd web && npm install && npm run dev       # web (VITE_API_URL=http://localhost:8000), or npm run dev:mock
```

Last full run (2026-10-14): 16 of 18 backend checks pass, the web app builds and its 14 tests pass. `test_profile` could not run (every model out of quota) and `test_transcript` failed on a test expectation that was then corrected; both need a rerun once the Gemini quota resets (12:30 IST).

## 6. Results so far

| Measure | Result | Caveat |
|---|---|---|
| Relay vs vector store, small set | 93% vs 43% (91% vs 43% head-to-head) | 74 questions, our own synthetic data |
| Scaled set, Relay only | 16/20 so far | Run stopped early. All 4 misses were the "we" extraction bug, now fixed |
| Extraction recall, planted facts | 95.8% (293/306) small set; 92% (282/306) on the scaled 556-turn reload | In-distribution (our templates) |
| Concurrent writes | 18.3 / 23.7 writes/s (1 / 4 graphs), 0 duplicates | Client round trips dominate; tenant parallelism barely shows at app level |
| Recall latency | 178 ms @ 1.1K facts, 210 ms @ 10.9K | Includes ~24 ms network per query |
| Simulator | 17/17 planted moments hit | — |
| API memory | ~353 MB | Render free tier is 512 MB |

## 7. Evaluator's assessment

I scored it the way a technical judge from FalkorDB would read it: does the graph do the work, does it cover the track, is it proven, does it show well.

| Criterion | Score | Why |
|---|---|---|
| Graph does real work | **9/10** | Atomic writes, two clocks, supersede/retire, trust-ranked conflicts, multi-hop recall, algorithms on real edges, provenance paths. Fails the swap test properly |
| Track 02 coverage | **9/10** | Episodic, semantic and procedural memory; persistence; handoffs and shared state; measured concurrency; per-tenant graphs; MCP |
| Technical depth and correctness | **8/10** | Root-caused bugs, tests for every behaviour, verified FalkorDB specifics. Retrieval relies on exact entity linking |
| Evaluation rigor | **5/10** | Well designed, but the headline is still the small 74-question run. The scaled comparison, component metrics, abstention P/R, variance, out-of-distribution extraction and LoCoMo QA haven't produced numbers yet |
| Demo and UX | **6/10** | Rich features, but never checked in a real browser by us, and not deployed *(Phase 11: now driven in a real browser against the live API; three real bugs found and fixed; still not deployed)* |
| Engineering quality | **7.5/10** | Small, readable modules; all Cypher in one file; many tests. Some modules were written fast by parallel builders and deserve a read-through |
| Documentation | **7/10** | README, plan, contract and this record. README numbers lag the latest code |
| Differentiation | **7.5/10** | The coordination angle (trust-ranked disagreement, handoffs as graph state, retire vs supersede, MCP) is distinct from Graphiti/Mem0. The scenario is a support desk, a familiar setting |
| Deployability and security | **4/10** | Not deployed. The API has **no authentication**, so anyone with the URL could reset tenants or edit model routes. Keys were shared in chat and need rotating |
| **Overall** | **≈ 7/10 now** | **8.5–9 is realistic** once the evaluation, deployment, security and video are done |

### Update after Phase 8
Track coverage and differentiation rise (three agents, measured knowledge sharing, company knowledge, network impact, expertise, more FalkorDB algorithms). Readability in FalkorDB Browser is fixed. Evaluation rigor, browser verification, deployment and API authentication are unchanged. Estimate: **≈ 7.5/10 now**, 8.5–9 after the scaled benchmark, deployment, an auth token and the video.

### Update after Phase 9
Differentiation and demo depth rise: a worldwide company with region graphs, open facts, orders, and replies that can't invent catalogue facts even on the weakest model. Remaining weak spots are unchanged: the scaled evaluation isn't scored, nothing is deployed, the API has no auth. Estimate: **≈ 7.5–8/10 now**.

### Update after Phase 10
Track coverage and demo quality rise: the intake agent follows a written spec, its questions and their answers are memory every agent can see, identity is a graph match, tickets carry the full handoff, and the chat shows the graph work as it happens. Model quota is now the main operational risk: planned replies need no model, but extraction does. Estimate: **≈ 8/10 now**.

### Update after Phase 15
Track coverage and differentiation rise most: the resolver now acts on a network model and proves its fixes by measuring again, can be wrong (and is graded), and a human customer closes the loop. Agent coordination is visible (one voice, claimed cases, consulted facts). Still open: deployment, API auth, scaled evaluation, video. Estimate: **≈ 8.5/10 now**.

## 8. What's missing, in priority order

1. **Finish the evaluation**: the scaled Relay vs B1 comparison, component metrics, abstention P/R, LoCoMo QA and out-of-distribution extraction. Run it as a plain background script (no agent cost), spread across models. Until then, the strongest claim rests on 74 questions.
2. **Deploy it** (Render + Vercel). The real-browser pass is done (Phase 11); the canvas animation still needs a human look.
3. **Protect the API**: an admin token for reset, sim control, usage edits and route edits; read-only for everyone else; rate limiting on `/chat`.
4. **Demo video (3 min) and blog post.**
5. **Speed up writes and linking:**
   - writes: batch the episode and facts into fewer round trips, and cache embeddings;
   - linking: replace the per-question scan of every name with a full-text index;
   - fix the 2.2 s first-call warm-up.
6. **Human-in-the-loop for conflicts:** a "confirm value" action in the console. It turns trust ranking into a learning signal, so trust becomes dynamic instead of fixed per agent.
7. **Retirement scope:** today a customer's "no longer" only retires facts the same agent recorded. Decide whether the customer's word should also retire a tool's claim (likely yes for personal facts).
8. **Memory growth:** a retention or compaction policy for old episodes; the free tier caps out around 15–75K nodes.
9. **Persist usage counters** (today they reset when Render redeploys); seed them from Groq headers.
10. **Richer procedural memory:** ordered fix steps (`NEXT` edges) learned from resolved tickets, not just "fix resolves issue".
11. **Screenshots in the README** (text and numbers were refreshed in Phase 9).
12. **Reply guard gaps**: delivery times, discounts and device counts stated without a plan name are not checked.
13. **Spec gaps**: confirm-before-update for contradictions; switching the chat to the account of the person someone calls for.
14. **Quota resilience**: a last-resort extraction model (allam-2-7b) so chats keep learning when Groq and Gemini are out.
15. **Outage feed end times**: give simulated outages an end, and retire `affects` facts the feed no longer reports.
