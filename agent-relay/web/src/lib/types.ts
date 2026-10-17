// Shapes from api/CONTRACT.md. Keep this file the single source of truth on the web side.

export type EntityKind =
  | 'customer' | 'city' | 'plan' | 'router' | 'channel' | 'device' | 'issue' | 'fix'
  | 'outage' | 'ticket' | 'status' | 'agent'
export type Kind = EntityKind | 'fact' | 'episode' | 'session' | 'agent_node' | 'community'

export interface GNode { id: string; kind: Kind | string; label: string; salience?: number; community?: number | string }
export interface GEdge { id: string; source: string; target: string; label: string; active: boolean; conflict?: boolean; at?: number | null; until?: number | null }
export interface Graph { nodes: GNode[]; edges: GEdge[] }

export interface CypherEntry { name: string; query: string; params: Record<string, unknown>; rows: number; ms: number }
export interface FactChange {
  fact_id: string; subject: string; predicate: string; object: string
  status: 'new' | 'corroborated' | 'updated' | 'retired'; replaced?: { fact_id: string; object: string }[]
}

export interface Stats {
  current_facts: number; superseded_facts: number; episodes: number; entities: number
  customers: number; open_tickets: number; conflicts: number
}
export interface Customer {
  key: string; name: string; city?: string | null; plan?: string | null; router?: string | null
  channel?: string | null; devices: string[]; open_ticket?: string | null; last_seen?: string | null
}
export interface Card {
  id: string; kind: string; title: string; subtitle?: string; lines: string[]; summary?: string | null
  active?: boolean
  sections: { title: string; rows: [string, string][] }[]
}

export interface KbPlan { key: string; name: string; price: number; price_label: string; currency: string; speed_mbps: number; upload_mbps: number; devices: number; router: string; includes: string[]; notes: string; lock_in: number }
export interface Kb {
  region: string; region_name: string; country: string; currency: string; tax: string | null; payments: string[]
  countries: { iso: string; name: string; currency: string }[]
  plans: KbPlan[]
  addons: { key: string; name: string; price: number; price_label: string; notes: string }[]
  services: { key: string; name: string; price: number; price_label: string; turnaround: string; notes: string }[]
  policies: { key: string; title: string; text: string }[]
  coverage: { city: string; key: string; areas: string[] }[]
  support: { channels: string[]; hours: string }
  stats: { countries: number; cities: number; areas: number; regions: number }
}
export interface DbHealth {
  ok: boolean; error?: string; ping_ms?: number; running?: number; waiting?: number; running_queries?: string[]
  config?: Record<string, number | string>; memory_mb?: number; limit_mb?: number; graphs?: { tenant: string; mb: number | null }[]; at?: string
}
export interface SlowQuery { at: number; command: string; query: string; ms: number; params?: string | null }
export interface Snapshot { name: string; at: string; label: string }
export interface Region { code: string; tenant: string; name: string; countries: string[]; cities: number; graph: string; loaded: boolean; stats: { customers: number; facts: number; nodes: number } | null; memory_mb?: number | null }
export interface Isolation { customer: string; query: string; regions: { region: string; name: string; graph: string; found: boolean; facts: number }[] }

export interface Expert { technician: string; city: string; tickets: number; resolved: number; last_at: string | null; via: string[] }
export interface Sharing {
  agents: { agent: string; role: string; trust: number; wrote: number; consulted: number; consulted_from_others: number; uses: number; reuse_pct: number }[]
  flows: { from: string; to: string; facts: number }[]
  top_shared: { fact_id: string; sentence: string; writer: string; readers: string[]; uses: number }[]
}

export interface ConversationMessage { episode_id: string; speaker: Speaker; text: string; at: string }
export interface ConversationSession { session_id: string; started_at?: string | null; summary?: string | null; messages: ConversationMessage[] }
export interface Conversation { customer: string; sessions: ConversationSession[] }

export interface Usage {
  model: string; provider: 'groq' | 'gemini' | string; jobs: string[]
  limits: { rpm: number | null; rpd: number | null; tpm: number | null; tpd: number | null }
  used: { requests: number; tokens_in: number; tokens_out: number; tokens: number; cache_hits: number; rate_limited: number }
  remaining: { requests: number | null; tokens: number | null }
  live: { limit_requests_day?: number | null; remaining_requests_day?: number | null; reset_requests?: string | null
    limit_tokens_minute?: number | null; remaining_tokens_minute?: number | null; reset_tokens?: string | null; at?: string | null } | null
  exhausted: boolean; last_error?: string | null
  /** what the provider last actually said: never a guess held for a fixed time */
  state?: 'available' | 'rate limited' | 'exhausted' | 'recovering' | 'not checked yet' | 'no key' | string
  checked_at?: string | null; ok_at?: string | null; latency_ms?: number | null; back_at?: string | null; back_in_s?: number | null
}
export interface UsagePayload { date: string; routes: Record<string, string[]>; models: Usage[]; at?: string }
export interface TrailStep { agent: string; action: string; at: string; to?: string | null; note?: string | null }
export interface Ticket {
  ticket: string; customer: string; status: string; assigned_to?: string | null; issues: string[]
  opened_at?: string | null; trail: TrailStep[]
}
export interface ChatResponse {
  reply: string; speaker?: string; session_id: string; learned: FactChange[]; ticket_opened?: string | null; cypher: CypherEntry[]
  episode_id?: string; reply_episode_id?: string | null
  images?: ChatImages | null  // games or streaming came up: pictures for the reply bubble
  how?: Hop[]  // "how I know": this customer's own earlier facts the reply rests on
}
export interface ChatImages { query: string; images: { src: string; title: string; link?: string | null }[] }
export interface PickupResponse {
  observations: string[]
  suggestions: { issue: string; fix: string; worked_before: number; for_issue?: string; distance?: number }[]
  cypher: CypherEntry[]
}
export interface FixResponse { learned: FactChange[]; cypher: CypherEntry[] }
/** One hop of an answer's path: subject -REL-> object, with both clocks' dates and who wrote it (relay/retrieve.py hop). */
export interface Hop { from: string; rel: string; to: string; fact_id?: string; active?: boolean; since?: string | null; until?: string | null; learned?: string | null; by?: string[] }
/** The answer contract: exactly one shape per answer (relay/retrieve.py OUTCOMES). */
export type Outcome = 'path' | 'memory' | 'not_in_graph' | 'unknown_entity'
export interface Learned { fact_id: string; fact: string; at: string | null; by: string[]; since: string | null }
export interface AskResponse {
  answer: string; values: string[]; conflict: boolean; unknown: boolean; cited_ids: string[]
  path: Graph; lines: string[]; cypher: CypherEntry[]
  outcome?: Outcome; paths?: Hop[][]; learned?: Learned[]; note?: string
}
/** One call of the fixed tool catalogue (relay/tools_catalog.py), as recorded and streamed. */
export interface ToolCall { tool: string; args: Record<string, unknown>; ms: number; rows: number; outcome: Outcome; queries: string[]; at: number }
export interface ToolResult extends ToolCall { result: any[]; paths: Hop[][]; extra: Record<string, any>; note?: string | null; cypher: CypherEntry[] }
export interface DemoPicks {
  clock: { name: string; predicate: string; question: string; before: string; old: string | null; new: string; changed: boolean } | null
  conflict: { name: string; predicate: string; question: string } | null
  exchange: { node: string; label: string; customers: number } | null
}
export interface ClockRow { predicate: string; value: string; fact_id: string }
export interface Clock { world: ClockRow[]; belief: ClockRow[] }
export interface HistoryRow {
  fact_id: string; predicate: string; value: string; active: boolean
  valid_from?: string | null; valid_to?: string | null; recorded_at?: string | null; expired_at?: string | null
  agents: string[]
}
export interface Community { id: string | number; size: number; top: string[]; salience: number; summary?: string | null }
export interface SimStatus { running: boolean; sim_time?: string | null; speed?: number; customers?: string[] }

export interface BenchRow {
  i: number; type: string; question: string; gold: string[]; values: string[]; correct: boolean
  evidence?: boolean | null; retrieval_ms?: number; error?: boolean
}
export interface Benchmark {
  results?: { systems?: Record<string, { rows: BenchRow[] }>; n_questions?: number; dataset?: string; answer_model?: string; pending?: unknown[] }
  bench?: {
    note?: string
    concurrency?: { graphs: number; writer_threads: number; writes_per_s: number; write_p50_ms: number; write_p95_ms: number;
      read_p50_ms: number; read_p95_ms: number; duplicate_entities: number; duplicate_active_facts: number }[]
    scale?: { customers: number; facts?: number; recall_p50_ms?: number; recall_p95_ms?: number; error?: string }[]
  }
}

// ---- WebSocket events
interface Ev<T extends string, D> { type: T; sim_time?: string | null; wall?: number; data: D }
export type Speaker = 'customer' | 'intake' | 'resolver' | 'noc' | 'action' | `tool:${string}` | `mcp:${string}`
export interface NetNode { id: string; kind: 'backbone' | 'pop' | 'olt'; label: string; city: string; area?: string | null; status: 'up' | 'down'; betweenness: number; customers: number; harmonic?: number; lat?: number | null; lon?: number | null }
export interface Network { nodes: NetNode[]; edges: { id: string; source: string; target: string; kind: string }[]; region?: string; countries?: { iso: string; name: string }[] }
export interface FailResult { node: string; label?: string; affected: { customer: string; area?: string | null; path: string[] }[]; tickets?: string[]; notified: string[] }
export type FactEventData = { fact_id: string; subject: string; predicate: string; object: string; agent: string; episode_id?: string }
export type RelayEvent =
  | Ev<'message', { session_id: string; customer: string; speaker: Speaker; text: string; episode_id?: string }>
  | Ev<'fact_created', FactEventData>
  | Ev<'fact_corroborated', FactEventData>
  | Ev<'fact_superseded', { fact_id: string; old_fact_id: string; subject: string; predicate: string; object: string; old_object: string; agent: string
      valid_from?: string; valid_to?: string; expired_at?: string }>
  | Ev<'fact_retired', FactEventData & { valid_to?: string; expired_at?: string }>
  | Ev<'usage', Usage>
  | Ev<'consulted', { agent: string; fact_ids: string[]; writers: Record<string, number> }>
  | Ev<'outage_detected', { node: string; label: string; city?: string | null; area?: string | null; affected: string[]; by: string }>
  | Ev<'outage_resolved', { node: string; label: string }>
  | Ev<'conflict', { subject: string; predicate: string; claims: { fact_id: string; value: string; agent: string; trust: number; preferred: boolean }[] }>
  | Ev<'ticket_opened', { ticket: string; customer: string; issue: string }>
  | Ev<'handoff', { ticket: string; from: string; to: string; note?: string }>
  | Ev<'pickup', { ticket: string; agent: string }>
  | Ev<'ticket_status', { ticket: string; status: string }>
  | Ev<'tool_call', { tool: string; customer?: string; output: string }>
  | Ev<'catalog_call', ToolCall>
  | Ev<'answer', { question: string; answer: string; cited_ids: string[]; conflict: boolean; unknown: boolean }>
  | Ev<'clock', { sim_time: string }>
  | Ev<'sim_status', { running: boolean; speed?: number; skipped?: number | boolean }>
  | Ev<'cypher', { name: string; ms: number; rows: number; query?: string; write?: boolean; seek?: string[]; found?: string[] }>
  | Ev<'kavya_step', { customer: string; step: string }>
  | Ev<'lab_step', { run: string; step?: LabStep; message?: LabMessage }>
  | Ev<'lab_state', { why: string; fault?: string; blind?: boolean }>
  | Ev<'lab_run', { run: string; status: string; customer?: string }>

/** POST /claims/confirm: a person settled a disagreement; each writer's trust on that predicate before and after. */
export interface ConfirmResult { confirmed: { fact_id: string; value: string; asserted_by: string }
  rejected: { fact_id: string; value: string }[]; trust: { agent: string; from: number; to: number }[]; episode_id: string }

// ---- Network lab
export interface LabCypher { name: string; query: string; ms: number; rows: number }
export interface LabStep { i: number; kind: 'memory' | 'check' | 'think' | 'act' | 'wait' | 'verify'; title: string; detail: string
  status: 'ok' | 'bad' | 'info' | 'pending'; at: number; cypher: LabCypher[]; data: Record<string, any> }
/** relay/procedural.py: suggest() returns the full shape; record()/failed() only id + counts. */
export interface LabProcedure { id: string; successes: number; failures: number; action?: string; steps?: string[]; rate?: number
  recency?: number; nearest_hops?: number | null; nearby?: number; places?: { at: string; hops: number; times: number }[]
  confident?: boolean; score?: number }
export interface LabMessage { text: string; at: number; me?: boolean; image?: { src: string; title: string; link?: string } | null }
export interface LabRun { id: string; customer: string; name: string; ticket: string | null; said: string; symptoms: string[]
  started_at: number; ended_at?: number; status: 'running' | 'resolved' | 'unresolved' | 'handed over' | 'waiting on customer' | 'error'
  steps: LabStep[]; messages: LabMessage[]; actions: string[]; fault: string | null; technician?: string | null
  diagnosis: { cause: string; action: string; why: string; by: string; agrees: boolean } | null
  verdict: { truth: string; truth_label: string; said: string; correct: boolean; fixed: boolean } | null
  awaiting?: boolean | 'guided' | 'details' | null  // what the resolver waits for from the customer; true = "is it working now?"
  confirmed?: boolean }
export interface LabPreset { key: string; title: string; layer: string; icon: string; blurb: string; says: string; action: string; customers: string[] }
export interface LabCustomer { key: string; name: string; city: string; area: string; pop: string; pop_label: string; uplinks: number }
export interface LabFault { id: string; active: boolean; mitigated: boolean; blind: boolean; customer: string; injected_at: number
  preset?: string; title?: string; label?: string }
export interface LabHome { id: string; splitter: string; port: number; customer: string | null; name: string; rx: number | null
  box: string; account: string; wifi: number; state: 'ok' | 'dark' | 'flapping' | 'frozen' | 'paused' | 'offline' | 'slow' | 'wifi' | 'reported' }
export interface LabOlt { id: string; label: string; status: string; peak_gbps: number; uplink_gbps: number; flow_gbps: number; free_peak_mbps: number; curve: number[] }
export interface LabLink { id: string; label: string; status: string; role: 'primary' | 'standby'; active: boolean; link: 'up' | 'cut'; gbps: number; flow: number }
export type Led = 'on' | 'off' | 'blink' | 'red'
export interface LabHomeBox { lights: { power: Led; pon: Led; los: Led; internet: Led; wifi: Led }; speed_now: number; speed_9pm: number
  plan: string | null; plan_mbps: number; online: boolean; hour: number; wifi: string; notice: string | null; area: string; cabinet: string; hub: string }
export interface LabView {
  home: LabHomeBox | null
  customers: LabCustomer[]; focus: string | null; presets: LabPreset[]; faults: LabFault[]; runs: LabRun[]
  score: { injected: number; investigated: number; correct: number; fixed: number; first_try: number; avg_seconds: number | null }
  network: { pop: { id: string; label: string; city: string }; links: LabLink[]; olts: LabOlt[]
    splitters: { id: string; label: string; feeder: 'ok' | 'cut'; olt: string }[]; homes: LabHome[] } | null
}
export interface Crossing { reader: string; writer: string; fact_id: string; subject: string; sentence: string; uses: number; last: string | null }
export interface QueryResult { columns: string[]; rows: unknown[][]; count: number; ms: number }
export interface Schema { labels: { label: string; count: number }[]; relationships: { type: string; count: number }[]
  indexes: { label: string; properties: string[]; types: Record<string, string[]>; entity: string; status: string }[] }
export interface CompareSide { answer: string | null; unknown: boolean; conflict: boolean; evidence: string[]; ms: number }
export interface Compare { question: string; graph: CompareSide; vector: CompareSide }
export interface CaseFact { id: string; predicate: string; value: string; writer?: string }
export interface CaseEvent { kind: 'say' | 'write' | 'handoff' | 'read'; who: string; to?: string; note?: string; text?: string; at: string | null; id: string; facts?: CaseFact[] }
export interface CaseStory { ticket: string; customer: string; status: string; issues: string[]; events: CaseEvent[] }
export interface LabManual { action: string; label: string; before: string[]; after: string[]; fixed: boolean }
