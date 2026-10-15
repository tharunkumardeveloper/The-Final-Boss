// Mock backend (VITE_MOCK=1): a scripted Ping Me Later story replayed as live events, with REST answers
// computed from the same state. Lets the UI run and be demoed with no API.
import { PREDICATE_KINDS, applyEvent, emptyGraph, entityId, factId, type GraphState } from './graph'
import { predicateLabel, retiredLabel, titleCase, when } from './format'
import type {
  AskResponse, Benchmark, BenchRow, Card, ChatResponse, Conversation, CypherEntry, FactChange, RelayEvent, Ticket, Usage, UsagePayload,
} from './types'

const HOUR = 3_600_000
const START = Date.parse('2026-09-01T09:30:00+05:30')
const SINGLE = new Set(['lives_in', 'on_plan', 'has_router', 'prefers_channel', 'has_status', 'assigned_to'])
const TRUST: Record<string, number> = { intake: 0.9, resolver: 0.6 }

interface Meta {
  fact_id: string; subject: string; predicate: string; object: string; agent: string; session: string
  active: boolean; valid_from: number; valid_to?: number; recorded_at: number; expired_at?: number; replaced?: string; retired?: boolean
}
interface Msg { episode_id: string; session: string; customer: string; speaker: string; text: string; at: number }
type Raw = { type: RelayEvent['type']; data: Record<string, unknown> }

// [hours from start, event, optional valid_from offset in hours (backdated facts)]
type Step = [number, Raw, number?]
const msg = (customer: string, speaker: string, text: string, session: string): Raw =>
  ({ type: 'message', data: { session_id: session, customer, speaker, text } })
const fact = (id: string, s: string, p: string, o: string, agent: string): Raw =>
  ({ type: 'fact_created', data: { fact_id: id, subject: s, predicate: p, object: o, agent, episode_id: `ep-${id}` } })
const sup = (id: string, old: string, s: string, p: string, o: string, oldO: string, agent: string): Raw =>
  ({ type: 'fact_superseded', data: { fact_id: id, old_fact_id: old, subject: s, predicate: p, object: o, old_object: oldO, agent } })

const SCRIPT: Step[] = [
  [0, msg('bob mehta', 'customer', 'Wifi keeps dropping every evening around 8, mostly on my laptop. I am in Kothrud, Pune.', 'bob-s1')],
  [0, fact('f-b1', 'bob mehta', 'lives_in', 'pune', 'intake')],
  [0, fact('f-b2', 'bob mehta', 'owns_device', 'laptop', 'intake')],
  [0, fact('f-b3', 'bob mehta', 'reported_issue', 'evening wifi drops', 'intake')],
  [0, { type: 'ticket_opened', data: { ticket: 'PML-2038', customer: 'bob mehta', issue: 'evening wifi drops' } }],
  [0, fact('f-b4', 'bob mehta', 'has_ticket', 'pml-2038', 'intake')],
  [0, fact('f-b5', 'pml-2038', 'ticket_about', 'evening wifi drops', 'intake')],
  [0, fact('f-b6', 'pml-2038', 'has_status', 'open', 'intake')],
  [0, { type: 'handoff', data: { ticket: 'PML-2038', from: 'intake', to: 'resolver', note: 'evening wifi drops' } }],
  [0, msg('bob mehta', 'intake', 'Thanks Bob. I have logged the evening drops as PML-2038 and passed it to our resolver.', 'bob-s1')],
  [3, { type: 'pickup', data: { ticket: 'PML-2038', agent: 'resolver' } }],
  [3, { type: 'tool_call', data: { tool: 'diagnostic', customer: 'bob mehta', output: 'Channel 6 congestion 82% between 19:00 and 23:00' } }],
  [4, fact('f-b7', 'pml-2038', 'tried_fix', 'change wifi channel', 'resolver')],
  [4, fact('f-b8', 'change wifi channel', 'resolves', 'evening wifi drops', 'resolver')],
  [4, sup('f-b9', 'f-b6', 'pml-2038', 'has_status', 'resolved', 'open', 'resolver')],
  [4, { type: 'ticket_status', data: { ticket: 'PML-2038', status: 'resolved' } }],
  [4, msg('bob mehta', 'resolver', 'Moved your router to channel 11 remotely. Evening congestion should be gone.', 'work-pml-2038')],

  [26, msg('alice rao', 'customer', 'Hi, I live in Andheri, Mumbai. My PS5 drops off wifi every evening, it is driving me nuts.', 'alice-s1')],
  [26, fact('f-a1', 'alice rao', 'lives_in', 'mumbai', 'intake')],
  [26, fact('f-a2', 'alice rao', 'owns_device', 'ps5', 'intake')],
  [26, fact('f-a3', 'alice rao', 'reported_issue', 'evening wifi drops', 'intake')],
  [26, { type: 'ticket_opened', data: { ticket: 'PML-2041', customer: 'alice rao', issue: 'evening wifi drops' } }],
  [26, fact('f-a4', 'alice rao', 'has_ticket', 'pml-2041', 'intake')],
  [26, fact('f-a5', 'pml-2041', 'ticket_about', 'evening wifi drops', 'intake')],
  [26, fact('f-a6', 'pml-2041', 'has_status', 'open', 'intake')],
  [26, { type: 'handoff', data: { ticket: 'PML-2041', from: 'intake', to: 'resolver', note: 'evening wifi drops on PS5' } }],
  [26, msg('alice rao', 'intake', 'Sorry about that, Alice. I have opened PML-2041 for the PS5 drops and handed it to our resolver.', 'alice-s1')],
  [30, msg('carol dsouza', 'customer', 'Please reach me on WhatsApp for any updates. I am on Fiber 1000 in Bengaluru.', 'carol-s1')],
  [30, fact('f-c1', 'carol dsouza', 'prefers_channel', 'whatsapp', 'intake')],
  [30, fact('f-c2', 'carol dsouza', 'on_plan', 'fiber 1000', 'intake')],
  [30, fact('f-c3', 'carol dsouza', 'lives_in', 'bengaluru', 'intake')],
  [30, msg('carol dsouza', 'intake', 'Noted, Carol: WhatsApp for updates, Fiber 1000 in Bengaluru.', 'carol-s1')],

  [266, msg('alice rao', 'customer', 'Quick update: I moved to Pune on the 10th. Same plan, Fiber 300. Laptop is also dropping now.', 'alice-s2')],
  [266, sup('f-a7', 'f-a1', 'alice rao', 'lives_in', 'pune', 'mumbai', 'intake'), 216],
  [266, fact('f-a8', 'alice rao', 'on_plan', 'fiber 300', 'intake')],
  [266, fact('f-a9', 'alice rao', 'owns_device', 'laptop', 'intake')],
  [266, msg('alice rao', 'intake', 'Got it: updated your address to Pune (was Mumbai) and noted the laptop. Your ticket stays with our resolver.', 'alice-s2')],
  [268, { type: 'pickup', data: { ticket: 'PML-2041', agent: 'resolver' } }],
  [268, sup('f-a10', 'f-a6', 'pml-2041', 'has_status', 'in progress', 'open', 'resolver')],
  [268, { type: 'ticket_status', data: { ticket: 'PML-2041', status: 'in progress' } }],
  [268, { type: 'tool_call', data: { tool: 'billing', customer: 'alice rao', output: 'Billing system: alice rao is on plan fiber 100' } }],
  [268, fact('f-r1', 'alice rao', 'on_plan', 'fiber 100', 'resolver')],
  [268, { type: 'conflict', data: { subject: 'alice rao', predicate: 'on_plan', claims: [
    { fact_id: 'f-a8', value: 'fiber 300', agent: 'intake', trust: 0.9, preferred: true },
    { fact_id: 'f-r1', value: 'fiber 100', agent: 'resolver', trust: 0.6, preferred: false }] } }],
  [268, { type: 'tool_call', data: { tool: 'outage', customer: 'alice rao', output: 'Outage feed: pune east fiber cut affects pune' } }],
  [268, fact('f-r2', 'pune east fiber cut', 'affects', 'pune', 'resolver')],
  [269, msg('alice rao', 'resolver', 'Known fix from PML-2038 for evening drops: change wifi channel. Also flagged: Pune East fiber cut since 07:40.', 'work-pml-2041')],
  [269, { type: 'answer', data: { question: 'Which plan is Alice Rao on?', answer: 'Fiber 300, though billing shows Fiber 100.', cited_ids: ['f-a8', 'f-r1'], conflict: true, unknown: false } }],
  [292, msg('carol dsouza', 'customer', 'Actually email works better for me now, WhatsApp is too noisy. Also I am no longer in Bengaluru, moving abroad for a few months.', 'carol-s2')],
  [292, sup('f-c4', 'f-c1', 'carol dsouza', 'prefers_channel', 'email', 'whatsapp', 'intake')],
  [292, { type: 'fact_retired', data: { fact_id: 'f-c3', subject: 'carol dsouza', predicate: 'lives_in', object: 'bengaluru', agent: 'intake', episode_id: 'ep-c4' } }],
  [292, msg('carol dsouza', 'intake', 'Done. We will email you from now on, and I have noted you are no longer in Bengaluru.', 'carol-s2')],
]

const SUMMARIES: Record<string, string> = {
  'bob-s1': 'Evening wifi drops on the laptop in Pune. PML-2038 opened and handed to the resolver.',
  'alice-s1': 'PS5 drops off wifi every evening in Mumbai. PML-2041 opened.',
  'alice-s2': 'Moved to Pune on the 10th, on Fiber 300, laptop now dropping too.',
  'carol-s1': 'Prefers WhatsApp, Fiber 1000 in Bengaluru.',
  'carol-s2': 'Switched to email; no longer in Bengaluru.',
}

// ---------------------------------------------------------------- usage (LLM quota)
const day = () => new Date(simTime).toISOString().slice(0, 10)
function initUsage(): UsagePayload {
  const m = (model: string, provider: string, jobs: string[], limits: Usage['limits'], requests: number, tokens: number, extra: Partial<Usage> = {}): Usage => ({
    model, provider, jobs, limits, used: { requests, tokens_in: Math.round(tokens * 0.85), tokens_out: Math.round(tokens * 0.15), tokens, cache_hits: Math.round(requests * 1.7), rate_limited: 0 },
    remaining: { requests: limits.rpd == null ? null : limits.rpd - requests, tokens: limits.tpd == null ? null : limits.tpd - tokens },
    live: null, exhausted: false, last_error: null, ...extra })
  const groq = { rpm: 30, rpd: 1000, tpm: 8000, tpd: 200_000 }
  return {
    date: '2026-09-01',
    routes: { extract: ['openai/gpt-oss-20b', 'gemini:gemini-3.5-flash-lite', 'qwen/qwen3.8-27b'], answer: ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b'],
      reply: ['gemini:gemini-3.5-flash-lite', 'allam-2-7b'], persona: ['allam-2-7b', 'gemini:gemini-3.5-flash-lite'], summary: ['allam-2-7b', 'gemini:gemini-3.5-flash-lite'] },
    models: [
      m('openai/gpt-oss-20b', 'groq', ['extract'], groq, 412, 118_400, { live: { limit_requests_day: 1000, remaining_requests_day: 586, reset_requests: '9h12m', limit_tokens_minute: 8000, remaining_tokens_minute: 6120, reset_tokens: '14s', at: new Date(START).toISOString() } }),
      m('openai/gpt-oss-120b', 'groq', ['answer'], groq, 1000, 199_820, { exhausted: true, last_error: 'Rate limit reached for model openai/gpt-oss-120b: tokens per day (TPD): Limit 200000, Used 199820', used: { requests: 1000, tokens_in: 171_300, tokens_out: 28_520, tokens: 199_820, cache_hits: 2310, rate_limited: 7 } }),
      m('qwen/qwen3.8-27b', 'groq', ['extract', 'answer'], groq, 188, 61_050),
      m('allam-2-7b', 'groq', ['persona', 'summary', 'reply'], { rpm: 30, rpd: 7000, tpm: 6000, tpd: 500_000 }, 640, 96_300),
      m('gemini:gemini-3.5-flash-lite', 'gemini', ['reply', 'extract', 'persona', 'summary'], { rpm: null, rpd: null, tpm: null, tpd: null }, 233, 54_900),
    ],
  }
}

// ---------------------------------------------------------------- state
let graph: GraphState
let facts: Map<string, Meta>
let tickets: Map<string, Ticket>
let messages: Msg[]
let cursor: number
let simTime: number
let usage: UsagePayload
let running = true
let speed = 1
let timer: ReturnType<typeof setTimeout> | undefined
const subscribers = new Set<(e: RelayEvent) => void>()

function resetState() {
  graph = emptyGraph(); facts = new Map(); tickets = new Map(); messages = []; cursor = 0; simTime = START; usage = initUsage()
}
resetState()

const iso = (ms: number) => new Date(ms).toISOString()
let epSeq = 0

function record(raw: Raw, vfOffset?: number) {
  const d = raw.data as Record<string, string>
  const now = simTime
  const add = (id: string, s: string, p: string, o: string, agent: string, session: string, vf = now) =>
    facts.set(id, { fact_id: id, subject: s, predicate: p, object: o, agent, session, active: true, valid_from: vf, recorded_at: now })
  const session = [...messages].reverse().find((m) => m.customer === d.subject)?.session ?? ''
  switch (raw.type) {
    case 'message':
      messages.push({ episode_id: d.episode_id, session: d.session_id, customer: d.customer, speaker: d.speaker, text: d.text, at: now })
      break
    case 'fact_created': if (!facts.has(d.fact_id)) add(d.fact_id, d.subject, d.predicate, d.object, d.agent, session); break
    case 'fact_superseded': {
      const vf = vfOffset !== undefined ? START + vfOffset * HOUR : now
      if (!facts.has(d.fact_id)) add(d.fact_id, d.subject, d.predicate, d.object, d.agent, session, vf)
      facts.get(d.fact_id)!.valid_from = vf
      facts.get(d.fact_id)!.replaced = d.old_object
      const old = facts.get(d.old_fact_id)
      if (old) Object.assign(old, { active: false, valid_to: vf, expired_at: now })
      raw.data = { ...raw.data, valid_from: iso(vf), valid_to: iso(vf), expired_at: iso(now) }
      break
    }
    case 'fact_retired': {
      const f = facts.get(d.fact_id)
      if (f) Object.assign(f, { active: false, valid_to: now, expired_at: now, retired: true })
      raw.data = { ...raw.data, valid_to: iso(now), expired_at: iso(now) }
      break
    }
    case 'ticket_opened':
      tickets.set(d.ticket, { ticket: d.ticket, customer: d.customer, status: 'open', assigned_to: 'intake',
        issues: [d.issue], opened_at: iso(now), trail: [{ agent: 'intake', action: 'opened', at: iso(now) }] })
      break
    case 'handoff': {
      const tk = tickets.get(d.ticket)
      if (tk) { tk.assigned_to = d.to; tk.trail.push({ agent: d.from, action: 'handed off', at: iso(now), to: d.to, note: d.note }) }
      break
    }
    case 'pickup': tickets.get(d.ticket)?.trail.push({ agent: d.agent, action: 'picked up', at: iso(now) }); break
    case 'ticket_status': {
      const tk = tickets.get(d.ticket)
      if (tk) { tk.status = d.status; tk.trail.push({ agent: 'resolver', action: `status → ${d.status}`, at: iso(now) }) }
      break
    }
  }
}

function send(raw: Raw) {
  const ev = { ...raw, sim_time: iso(simTime), wall: Date.now() } as RelayEvent
  applyEvent(graph, ev)
  subscribers.forEach((fn) => fn(ev))
}

function emit(raw: Raw, vfOffset?: number) {
  if (raw.type === 'message' && !raw.data.episode_id) raw = { ...raw, data: { ...raw.data, episode_id: `ep-m${++epSeq}` } }
  // Contract: every new fact gets fact_created; replacements follow as fact_superseded.
  if (raw.type === 'fact_superseded' && !facts.has(raw.data.fact_id as string)) {
    const d = raw.data as Record<string, string>
    emit(fact(d.fact_id, d.subject, d.predicate, d.object, d.agent), vfOffset)
  }
  record(raw, vfOffset)
  send(raw)
}

function spend(model: string, tokens: number, cached = false) {
  const u = usage.models.find((m) => m.model === model)
  if (!u) return
  if (cached) u.used.cache_hits++
  else {
    u.used.requests++; u.used.tokens += tokens; u.used.tokens_in += Math.round(tokens * 0.85); u.used.tokens_out += Math.round(tokens * 0.15)
    if (u.limits.rpd != null) u.remaining.requests = Math.max(0, u.limits.rpd - u.used.requests)
    if (u.limits.tpd != null) u.remaining.tokens = Math.max(0, u.limits.tpd - u.used.tokens)
    if (u.live) u.live = { ...u.live, remaining_requests_day: Math.max(0, (u.live.remaining_requests_day ?? 0) - 1), at: iso(simTime) }
  }
  send({ type: 'usage', data: { ...u } as unknown as Record<string, unknown> })
}

function tick() {
  if (!running || cursor >= SCRIPT.length) return
  const [h, raw, vf] = SCRIPT[cursor++]
  simTime = START + h * HOUR
  emit(structuredClone(raw), vf)
  if (raw.type === 'message' && raw.data.speaker === 'customer') { spend('allam-2-7b', 380); spend('openai/gpt-oss-20b', 760) }
  if (raw.type !== 'message' || cursor === 1) emit({ type: 'clock', data: { sim_time: iso(simTime) } })
  const next = SCRIPT[cursor]
  const gap = next && next[0] > h ? 2600 : raw.type === 'message' ? 1500 : 650
  timer = setTimeout(tick, gap / speed)
}

export function subscribeMock(fn: (e: RelayEvent) => void) {
  subscribers.add(fn)
  if (!timer && cursor === 0) timer = setTimeout(tick, 900)
  return () => { subscribers.delete(fn) }
}

// ---------------------------------------------------------------- derived views
const live = () => [...facts.values()]
const cypher = (name: string, query: string, rows: number): CypherEntry =>
  ({ name, query, params: {}, rows, ms: Math.round(18 + Math.random() * 40) })

function customerKeys() {
  return [...graph.nodes.values()].filter((n) => n.kind === 'customer').map((n) => n.label)
}

function customers() {
  return customerKeys().map((key) => {
    const mine = live().filter((f) => f.subject === key && f.active)
    const one = (p: string) => mine.filter((f) => f.predicate === p).sort((a, b) => (TRUST[b.agent] ?? 0) - (TRUST[a.agent] ?? 0))[0]?.object ?? null
    const open = [...tickets.values()].find((t) => t.customer === key && t.status !== 'resolved')
    return { key, name: titleCase(key), city: one('lives_in'), plan: one('on_plan'), router: one('has_router'),
      channel: one('prefers_channel'), devices: mine.filter((f) => f.predicate === 'owns_device').map((f) => f.object),
      open_ticket: open?.ticket ?? null, last_seen: iso(Math.max(...mine.map((f) => f.recorded_at), START)) }
  })
}

function conflicts() {
  const groups = new Map<string, Set<string>>()
  for (const f of live()) if (f.active && SINGLE.has(f.predicate)) {
    const k = `${f.subject}|${f.predicate}`
    groups.set(k, (groups.get(k) ?? new Set()).add(f.object))
  }
  return [...groups.values()].filter((v) => v.size > 1).length
}

function stats() {
  const all = live()
  return { current_facts: all.filter((f) => f.active).length, superseded_facts: all.filter((f) => !f.active).length,
    episodes: messages.length, entities: graph.nodes.size, customers: customerKeys().length,
    open_tickets: [...tickets.values()].filter((t) => t.status !== 'resolved').length, conflicts: conflicts() }
}

function snapshot(focus?: string | null, depth = 2) {
  const nodes = [...graph.nodes.values()].map(({ id, kind, label, salience, community }) => ({ id, kind, label, salience, community }))
  const edges = [...graph.edges.values()].map(({ id, source, target, label, active, conflict }) => ({
    id, label, active, conflict,
    source: typeof source === 'string' ? source : (source as { id: string }).id,
    target: typeof target === 'string' ? target : (target as { id: string }).id }))
  if (!focus) return { nodes, edges }
  // Like GET /graph?focus=e:<key>&depth=N: everything within N hops of the focused entity.
  const keep = new Set([focus])
  let frontier = [focus]
  for (let d = 0; d < depth; d++) {
    const next: string[] = []
    for (const e of edges) for (const [a, b] of [[e.source, e.target], [e.target, e.source]])
      if (frontier.includes(a) && !keep.has(b)) { keep.add(b); next.push(b) }
    frontier = next
  }
  return { nodes: nodes.filter((n) => keep.has(n.id)), edges: edges.filter((e) => keep.has(e.source) && keep.has(e.target)) }
}

function card(id: string): Card {
  if (id.startsWith('f:')) {
    const f = facts.get(id.slice(2))
    if (!f) return { id, kind: 'fact', title: 'Unknown fact', lines: [], sections: [] }
    const since = f.active ? `Current since ${when(iso(f.valid_from), false)}` : `True ${when(iso(f.valid_from), false)} to ${when(iso(f.valid_to!), false)}`
    const lines = [`${since}, learned by ${f.agent} in session ${f.session || 'a work session'}.`]
    if (f.replaced) lines.push(`Replaced ${titleCase(f.replaced)}.`)
    if (f.retired) lines.push(`No longer true: ${titleCase(f.subject)} ${retiredLabel(f.predicate)} ${titleCase(f.object)}, and nothing replaced it.`)
    else if (!f.active) lines.push(`On file until ${when(iso(f.expired_at!))}, then superseded.`)
    return { id, kind: 'fact', active: f.active, title: `${titleCase(f.subject)} ${predicateLabel(f.predicate)} ${titleCase(f.object)}`,
      subtitle: f.active ? 'Current fact' : f.retired ? 'No longer true' : 'Superseded fact', lines,
      sections: [{ title: 'Two clocks', rows: [
        ['True in the world', `${when(iso(f.valid_from))} → ${f.valid_to ? when(iso(f.valid_to)) : 'now'}`],
        ['On file', `${when(iso(f.recorded_at))} → ${f.expired_at ? when(iso(f.expired_at)) : 'now'}`],
        ['Source', `${f.agent} (trust ${TRUST[f.agent] ?? '—'})`]] }] }
  }
  const key = id.replace(/^e:/, '')
  const node = graph.nodes.get(id)
  const about = live().filter((f) => f.subject === key || f.object === key)
  const cur = about.filter((f) => f.active), old = about.filter((f) => !f.active)
  if (node?.kind === 'ticket') {
    const t = tickets.get(key.toUpperCase())
    return { id, kind: 'ticket', title: key.toUpperCase(), subtitle: `Ticket for ${titleCase(t?.customer ?? '')}`,
      lines: [`Status ${t?.status ?? 'unknown'}, assigned to ${t?.assigned_to ?? '—'}.`],
      sections: [{ title: 'Handoff trail', rows: (t?.trail ?? []).map((s) => [when(s.at), `${s.agent} ${s.action}${s.to ? ` → ${s.to}` : ''}`]) }] }
  }
  const open = [...tickets.values()].filter((t) => t.customer === key && t.status !== 'resolved').length
  const sessions = new Set(messages.filter((m) => m.customer === key).map((m) => m.session)).size
  const summary = [...messages].reverse().find((m) => m.customer === key && SUMMARIES[m.session])
  return { id, kind: node?.kind ?? 'entity', title: titleCase(key), subtitle: node?.kind,
    summary: summary ? SUMMARIES[summary.session] : null,
    lines: [node?.kind === 'customer'
      ? `${cur.length} current facts, ${old.length} superseded, ${open} open ticket${open === 1 ? '' : 's'}, ${sessions} session${sessions === 1 ? '' : 's'}.`
      : `Connected to ${cur.length} current fact${cur.length === 1 ? '' : 's'}.`],
    sections: [
      { title: 'Current', rows: cur.map((f) => [predicateLabel(f.predicate), f.subject === key ? titleCase(f.object) : titleCase(f.subject)]) },
      ...(old.length ? [{ title: 'History', rows: old.map((f) => [f.retired ? retiredLabel(f.predicate) : predicateLabel(f.predicate),
        `${titleCase(f.object)} (until ${when(iso(f.valid_to!), false)})`] as [string, string]) }] : []),
    ] }
}

function clock(subject: string, at: string) {
  const t = Date.parse(at)
  const mine = live().filter((f) => f.subject === subject)
  const row = (f: Meta) => ({ predicate: f.predicate, value: f.object, fact_id: f.fact_id })
  return {
    world: mine.filter((f) => f.valid_from <= t && (f.valid_to === undefined || f.valid_to > t)).map(row),
    belief: mine.filter((f) => f.recorded_at <= t && (f.expired_at === undefined || f.expired_at > t)).map(row),
  }
}

function history(subject: string) {
  const d = (ms?: number) => (ms === undefined ? null : iso(ms))
  return live().filter((f) => f.subject === subject).map((f) => ({ fact_id: f.fact_id, predicate: f.predicate, value: f.object,
    active: f.active, valid_from: d(f.valid_from), valid_to: d(f.valid_to), recorded_at: d(f.recorded_at),
    expired_at: d(f.expired_at), agents: [f.agent] }))
}

function conversation(customer: string): Conversation {
  const mine = messages.filter((m) => m.customer === customer)
  const bySession = new Map<string, Msg[]>()
  for (const m of mine) bySession.set(m.session, [...(bySession.get(m.session) ?? []), m])
  return { customer, sessions: [...bySession.entries()].map(([session_id, ms]) => ({
    session_id, started_at: iso(ms[0].at), summary: SUMMARIES[session_id] ?? null,
    messages: ms.map((m) => ({ episode_id: m.episode_id, speaker: m.speaker as Conversation['sessions'][0]['messages'][0]['speaker'], text: m.text, at: iso(m.at) })) })) }
}

function ask(question: string): AskResponse {
  spend('openai/gpt-oss-120b', 0, true)
  const q = question.toLowerCase()
  const pick = (ids: string[], answer: string, values: string[], conflict = false): AskResponse => {
    const nodes: AskResponse['path']['nodes'] = [], edges: AskResponse['path']['edges'] = []
    for (const id of ids) {
      const f = facts.get(id)
      if (!f) continue
      const [sk, ok] = PREDICATE_KINDS[f.predicate] ?? ['entity', 'entity']
      nodes.push({ id: factId(id), kind: 'fact', label: `${f.predicate}: ${f.object}` },
        { id: entityId(f.subject), kind: sk, label: f.subject }, { id: entityId(f.object), kind: ok, label: f.object },
        { id: `ep:ep-${id}`, kind: 'episode', label: `${f.agent} · ${when(iso(f.recorded_at))}` },
        { id: `s:${f.session || 'work'}`, kind: 'session', label: f.session || 'work session' },
        { id: `a:${f.agent}`, kind: 'agent_node', label: f.agent })
      edges.push({ id: `${id}-s`, source: factId(id), target: entityId(f.subject), label: 'subject', active: f.active },
        { id: `${id}-o`, source: factId(id), target: entityId(f.object), label: 'object', active: f.active },
        { id: `${id}-d`, source: `ep:ep-${id}`, target: factId(id), label: 'DERIVED', active: true },
        { id: `${id}-i`, source: `ep:ep-${id}`, target: `s:${f.session || 'work'}`, label: 'IN', active: true },
        { id: `${id}-w`, source: `a:${f.agent}`, target: `ep:ep-${id}`, label: 'WROTE', active: true })
    }
    const uniq = <T extends { id: string }>(xs: T[]) => [...new Map(xs.map((x) => [x.id, x])).values()]
    return { answer, values, conflict, unknown: false, cited_ids: ids, path: { nodes: uniq(nodes), edges: uniq(edges) },
      lines: ids.map((id) => { const f = facts.get(id)!; return `[${id}] ${f.subject} | ${f.predicate} | ${f.object} | ${f.active ? 'CURRENT' : 'SUPERSEDED'}` }),
      cypher: [cypher('known entities', 'MATCH (e:Entity) WHERE e.type IN [...] RETURN e.name_key, e.type', 14),
        cypher('vector seeds', "CALL db.idx.vector.queryNodes('Episode','embedding',$k,vecf32($qvec)) YIELD node AS ep, score ...", 8),
        cypher('retrieve facts', 'MATCH (seed:Entity) WHERE seed.name_key IN $seeds OPTIONAL MATCH (seed)-[:RELATED*1..2]-(n:Entity) ...', 22)] }
  }
  if (q.includes('plan') && facts.has('f-r1')) return pick(['f-a8', 'f-r1'], 'Alice Rao is on Fiber 300 (she told intake). Billing shows Fiber 100, so this is flagged as a conflict.', ['fiber 300'], true)
  if ((q.includes('live') || q.includes('city') || q.includes('where')) && facts.has('f-a7')) return pick(['f-a7'], 'Alice Rao lives in Pune. She moved from Mumbai on 10 Sep.', ['pune'])
  if (q.includes('outage') && facts.has('f-r2')) return pick(['f-a7', 'f-r2', 'f-a4'], 'The Pune East fiber cut affects Pune, where Alice Rao lives, so it may explain PML-2041.', ['pune east fiber cut'])
  if (q.includes('fix') && facts.has('f-b8')) return pick(['f-a5', 'f-b8'], "Change wifi channel: it resolved the same evening drops on Bob Mehta's ticket PML-2038.", ['change wifi channel'])
  return { answer: "I don't have that in memory yet.", values: [], conflict: false, unknown: true, cited_ids: [],
    path: { nodes: [], edges: [] }, lines: [], cypher: [cypher('known entities', 'MATCH (e:Entity) RETURN e.name_key, e.type', 14)] }
}

function chat(customer: string, text: string, sessionId?: string): ChatResponse {
  const key = customer.trim().toLowerCase()
  simTime += HOUR
  const session = sessionId || `${key.replace(/ /g, '-')}-web-${day().replace(/-/g, '')}`
  const t = text.toLowerCase()
  emit(msg(key, 'customer', text, session))
  const episodeId = messages[messages.length - 1].episode_id
  const learned: FactChange[] = []
  const id = () => `f-w${facts.size + 1}`
  const say = (p: string, o: string) => {
    const prev = live().find((f) => f.subject === key && f.predicate === p && f.active && f.agent === 'intake')
    if (prev?.object === o) {
      learned.push({ fact_id: prev.fact_id, subject: key, predicate: p, object: o, status: 'corroborated' })
      emit({ type: 'fact_corroborated', data: { fact_id: prev.fact_id, subject: key, predicate: p, object: o, agent: 'intake' } })
      return
    }
    const fid = id()
    if (prev && SINGLE.has(p)) {
      emit(sup(fid, prev.fact_id, key, p, o, prev.object, 'intake'))
      learned.push({ fact_id: fid, subject: key, predicate: p, object: o, status: 'updated', replaced: [{ fact_id: prev.fact_id, object: prev.object }] })
    } else {
      emit(fact(fid, key, p, o, 'intake'))
      learned.push({ fact_id: fid, subject: key, predicate: p, object: o, status: 'new' })
    }
  }
  const retire = (p: string, o: string) => {
    const prev = live().find((f) => f.subject === key && f.predicate === p && f.object === o && f.active)
    if (!prev) return
    emit({ type: 'fact_retired', data: { fact_id: prev.fact_id, subject: key, predicate: p, object: o, agent: 'intake', episode_id: `ep-m${epSeq}` } })
    learned.push({ fact_id: prev.fact_id, subject: key, predicate: p, object: o, status: 'retired' })
  }
  for (const city of ['pune', 'mumbai', 'bengaluru', 'hyderabad', 'chennai']) if (t.includes(city)) (/no longer|not in|moved out of/.test(t) ? retire : say)('lives_in', city)
  for (const ch of ['email', 'whatsapp', 'phone', 'sms']) if (t.includes(ch)) say('prefers_channel', ch)
  for (const plan of ['100', '300', '1000']) if (t.includes(`fiber ${plan}`)) say('on_plan', `fiber ${plan}`)
  for (const dev of ['ps5', 'laptop', 'tv', 'phone']) if (t.includes(`my ${dev}`)) say('owns_device', dev)

  // A problem report opens a ticket and hands it to the resolver (so the portal shows the ticket toast).
  let opened: string | null = null
  if (/drop|slow|not working|disconnect|buffer|keeps going/.test(t)) {
    const issue = t.includes('evening') ? 'evening wifi drops' : 'wifi drops'
    say('reported_issue', issue)
    const open = [...tickets.values()].find((x) => x.customer === key && x.status !== 'resolved')
    if (!open) {
      opened = `PML-${2050 + tickets.size}`
      const low = opened.toLowerCase()
      const tid = id()
      emit({ type: 'ticket_opened', data: { ticket: opened, customer: key, issue } })
      emit(fact(tid, key, 'has_ticket', low, 'intake'))
      emit(fact(id(), low, 'ticket_about', issue, 'intake'))
      emit(fact(id(), low, 'has_status', 'open', 'intake'))
      emit({ type: 'handoff', data: { ticket: opened, from: 'intake', to: 'resolver', note: issue } })
      learned.push({ fact_id: tid, subject: key, predicate: 'has_ticket', object: low, status: 'new' })
    }
  }

  const first = titleCase(key.split(' ')[0])
  const plans = live().filter((f) => f.subject === key && f.predicate === 'on_plan' && f.active)
  let reply: string
  if (/which plan|what plan|my plan/.test(t)) {
    reply = plans.length > 1
      ? `You told me ${titleCase(plans.find((p) => p.agent === 'intake')?.object ?? plans[0].object)}, but billing shows ${titleCase(plans.find((p) => p.agent !== 'intake')?.object ?? plans[1].object)}. I've flagged it so the resolver sorts out which one is right.`
      : plans.length ? `You're on ${titleCase(plans[0].object)}, ${first}. Want me to check if an upgrade makes sense for evenings?`
      : `I don't have your plan on file yet, ${first}. Tell me and I'll remember it.`
  } else if (/moved|new house|new address/.test(t) && !learned.some((l) => l.predicate === 'lives_in')) {
    reply = `New place, nice! Which city did you move to, ${first}? I'll update your address so nobody sends a technician to the old one.`
  } else if (learned.length) {
    reply = `Got it, ${first}. ${learned.filter((l) => l.predicate !== 'has_ticket').map((l) => l.status === 'updated'
        ? `I've updated ${predicateLabel(l.predicate)} to ${titleCase(l.object)} (was ${titleCase(l.replaced![0].object)})`
        : l.status === 'retired' ? `noted you ${retiredLabel(l.predicate).replace(/^is /, 'are ').replace(/lives/, 'live')} ${titleCase(l.object)}`
        : l.status === 'corroborated' ? `${titleCase(l.object)} matches what I have` : `I've noted ${predicateLabel(l.predicate)} ${titleCase(l.object)}`).join('; ')}.`
      + (opened ? ` Evenings are prime time for drops in Pune, so I've opened ${opened} and handed it to our resolver.` : '')
  } else {
    reply = `Thanks, ${first}. Anything else acting up? Wifi, bills, moves, I've got time (and chai).`
  }
  emit(msg(key, 'intake', reply, session))
  const replyEpisodeId = messages[messages.length - 1].episode_id
  spend('openai/gpt-oss-20b', 790); spend('gemini:gemini-3.5-flash-lite', 520)
  const entries = [cypher('write episode', 'MERGE (a:Agent {agent_id:$agent}) MERGE (s:Session {session_id:$sid}) CREATE (a)-[:WROTE]->(ep:Episode {...})-[:IN]->(s)', 1),
    ...learned.map(() => cypher('write fact', 'MATCH (ep:Episode {episode_id:$eid}) MERGE (s:Entity {name_key:$s}) ... MERGE (f:Fact {triple_key:$tk, active:true}) ...', 1))]
  for (const e of entries) send({ type: 'cypher', data: { name: e.name, ms: e.ms, rows: e.rows, query: e.query } })
  return { reply, session_id: session, learned, ticket_opened: opened, cypher: entries, episode_id: episodeId, reply_episode_id: replyEpisodeId }
}

const BENCH: [string, number, number, number, number][] = [
  // type, n, FULL correct, B1 run, B1 correct (from eval/results.md)
  ['current', 16, 16, 16, 10], ['world_time', 7, 7, 7, 4], ['belief_time', 6, 4, 6, 2], ['completeness', 8, 7, 8, 0],
  ['disagreement', 4, 3, 4, 0], ['handoff', 8, 8, 5, 4], ['multi_hop', 10, 10, 0, 0], ['procedural', 7, 6, 0, 0], ['unknown', 8, 8, 0, 0],
]
function benchmark(): Benchmark {
  const rows = (sys: 'FULL' | 'B1') => BENCH.flatMap(([type, n, full, run, b1]) =>
    Array.from({ length: sys === 'FULL' ? n : run }, (_, i): BenchRow => ({ i, type, question: `${type} #${i + 1}`, gold: [], values: [],
      correct: i < (sys === 'FULL' ? full : b1), evidence: true, retrieval_ms: sys === 'FULL' ? 150 : 27 })))
  return { results: { systems: { FULL: { rows: rows('FULL') }, B1: { rows: rows('B1') } }, n_questions: 74, answer_model: 'openai/gpt-oss-120b' },
    bench: { note: 'FalkorDB Cloud free tier, ~24 ms round trip from the client.',
      concurrency: [
        { graphs: 1, writer_threads: 8, writes_per_s: 18.3, write_p50_ms: 352.8, write_p95_ms: 700.7, read_p50_ms: 310.1, read_p95_ms: 484.2, duplicate_entities: 0, duplicate_active_facts: 0 },
        { graphs: 4, writer_threads: 8, writes_per_s: 23.7, write_p50_ms: 346.8, write_p95_ms: 411.4, read_p50_ms: 272.5, read_p95_ms: 355.0, duplicate_entities: 0, duplicate_active_facts: 0 }],
      scale: [{ customers: 200, facts: 1090, recall_p50_ms: 178.2, recall_p95_ms: 254.5 }, { customers: 2000, facts: 10903, recall_p50_ms: 210.4, recall_p95_ms: 278.5 },
        { customers: 10000, error: 'free-tier memory ceiling' }] } }
}

// ---------------------------------------------------------------- router
const delay = <T>(v: T, ms = 220) => new Promise<T>((r) => setTimeout(() => r(v), ms))
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v))

export async function mockRequest(path: string, init?: RequestInit): Promise<unknown> {
  const url = new URL(path, 'http://mock')
  const body = init?.body ? JSON.parse(String(init.body)) : {}
  const parts = url.pathname.split('/').map(decodeURIComponent)
  const sub = parts.slice(4).join('/') // after /api/tenants/{t}/
  if (url.pathname === '/health') return delay({ ok: true, falkordb: true })
  if (url.pathname === '/api/benchmark') return delay(benchmark())
  if (url.pathname === '/api/usage') return delay(clone(usage))
  if (url.pathname === '/api/usage/limits') {
    const u = usage.models.find((m) => m.model === body.model)
    if (u) for (const k of ['rpm', 'rpd', 'tpm', 'tpd'] as const) if (k in body) u.limits[k] = body[k]
    if (u) { u.remaining.requests = u.limits.rpd == null ? null : Math.max(0, u.limits.rpd - u.used.requests)
      u.remaining.tokens = u.limits.tpd == null ? null : Math.max(0, u.limits.tpd - u.used.tokens)
      u.exhausted = (u.remaining.requests ?? 1) <= 0 || (u.remaining.tokens ?? 1) <= 0 }
    return delay(clone(usage))
  }
  if (url.pathname === '/api/usage/routes') {
    usage.routes[body.job] = body.models
    for (const m of usage.models) m.jobs = Object.entries(usage.routes).filter(([, ms]) => ms.includes(m.model)).map(([j]) => j)
    return delay(clone(usage))
  }
  if (url.pathname === '/api/tenants') return delay(init?.method === 'POST' ? { name: body.name } : ['pml'])
  switch (true) {
    case sub === 'stats': return delay(stats())
    case sub === 'customers': return delay(customers())
    case sub === 'graph': return delay(snapshot(url.searchParams.get('focus')?.toLowerCase(), Number(url.searchParams.get('depth')) || 2))
    case sub.startsWith('card/'): return delay(card(sub.slice(5)))
    case sub === 'tickets': return delay([...tickets.values()])
    case sub === 'conversation': return delay(conversation((url.searchParams.get('customer') ?? '').toLowerCase()))
    // Like the real API: events stream out just before the reply returns; 1.6 s is long enough to see Kavya typing.
    case sub === 'chat': return new Promise((r) => setTimeout(() => r(chat(body.customer, body.text, body.session_id)), 1600))
    case sub.endsWith('/pickup'): return delay({ observations: ['billing says plan = fiber 100', 'outage feed: pune east fiber cut affects pune'],
      suggestions: [{ issue: 'evening wifi drops', fix: 'change wifi channel', worked_before: 1, for_issue: 'evening wifi drops', distance: 0 }], cypher: [] }, 600)
    case sub.endsWith('/fix'): return delay({ learned: [], cypher: [] }, 500)
    case sub === 'ask': return delay(ask(body.question ?? ''), 900)
    case sub.startsWith('clock'): return delay(clock(url.searchParams.get('subject') ?? '', url.searchParams.get('at') ?? iso(simTime)))
    case sub.startsWith('history'): return delay(history(url.searchParams.get('subject') ?? ''))
    case sub === 'consolidate': return delay({ communities: [
      { id: 1, size: 7, top: ['alice rao', 'pune', 'pml-2041'], salience: 0.21, summary: 'Pune: Alice Rao, a fiber cut and one open ticket for evening drops.' },
      { id: 2, size: 6, top: ['bob mehta', 'change wifi channel', 'evening wifi drops'], salience: 0.17, summary: 'Evening drops resolved by changing the wifi channel.' },
      { id: 3, size: 4, top: ['carol dsouza', 'fiber 1000', 'email'], salience: 0.09, summary: 'Carol prefers email; moving abroad.' }] }, 800)
    case sub === 'sim/start': running = true; speed = Number(body.speed) || 1; if (!timer || cursor >= SCRIPT.length) { clearTimeout(timer); timer = setTimeout(tick, 300) } return delay({ running, speed })
    case sub === 'sim/stop': running = false; clearTimeout(timer); timer = undefined; return delay({ running, speed })
    case sub === 'sim': return delay({ running, speed, sim_time: iso(simTime), customers: customerKeys() })
    case sub === 'reset': clearTimeout(timer); timer = undefined; resetState(); running = body.scenario !== 'empty'
      if (running) timer = setTimeout(tick, 600)
      return delay({ ok: true })
  }
  throw new Error(`mock: no route for ${path}`)
}
