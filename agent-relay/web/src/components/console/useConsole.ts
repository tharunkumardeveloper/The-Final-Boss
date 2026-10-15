import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { applyEvent, emptyGraph, loadGraph, relevantToFocus, speakerCustomer } from '../../lib/graph'
import { useRelayStream } from '../../lib/stream'
import type { CypherEntry, Customer, RelayEvent, SimStatus, Stats, Ticket, ToolCall, Usage, UsagePayload } from '../../lib/types'

export type LoggedCypher = CypherEntry & { action: string; at: number }
const FEED_TYPES = new Set(['message', 'tool_call', 'handoff', 'ticket_opened', 'ticket_status', 'fact_superseded', 'fact_retired', 'conflict', 'answer', 'pickup'])

/** Merge one live `usage` event into the payload (by model). */
export const mergeUsage = (p: UsagePayload | undefined, u: Usage): UsagePayload | undefined =>
  p && { ...p, models: p.models.some((m) => m.model === u.model) ? p.models.map((m) => (m.model === u.model ? u : m)) : [...p.models, u] }

/** How many models are out for the day or within 15% of a daily limit (console header + usage page). */
export function quotaState(p?: UsagePayload) {
  const models = p?.models ?? []
  const frac = (used: number, limit: number | null) => (limit ? used / limit : 0)
  // out = the provider said so and its "back at" time hasn't passed yet (the API re-checks it then)
  const exhausted = models.filter((m) => m.exhausted && (!m.back_at || new Date(m.back_at).getTime() > Date.now())).length
  const near = models.filter((m) => !m.exhausted && Math.max(frac(m.used.requests, m.limits.rpd), frac(m.used.tokens, m.limits.tpd)) >= 0.85).length
  return { exhausted, near, known: models.length > 0 }
}
const TICKET_TYPES = new Set(['ticket_opened', 'handoff', 'pickup', 'ticket_status'])

/** What the graph shows, per viewer: everyone or one customer's neighbourhood, and whether to follow live chats. */
export interface GraphView { focus: string | null; depth: 1 | 2; follow: boolean }
const VIEW_KEY = 'pml.console.graph.v1'
const FOLLOW_MS = 1500
function readView(): GraphView {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY) ?? 'null')
    return { focus: typeof v?.focus === 'string' ? v.focus : null, depth: v?.depth === 1 ? 1 : 2, follow: Boolean(v?.follow) }
  } catch { return { focus: null, depth: 2, follow: false } }
}

export function useConsole(tenant: string) {
  const store = useRef(emptyGraph())
  const [view, setViewState] = useState<GraphView>(readView)
  const [following, setFollowing] = useState<string | null>(null)
  const viewRef = useRef(view)
  viewRef.current = view
  const followTimer = useRef<ReturnType<typeof setTimeout>>()
  const setView = useCallback((patch: Partial<GraphView>, byFollow = false) => {
    setViewState((v) => {
      const next = { ...v, ...patch }
      try { localStorage.setItem(VIEW_KEY, JSON.stringify(next)) } catch { /* private mode */ }
      return next
    })
    if (!byFollow && 'focus' in patch) setFollowing(null)
    if ('follow' in patch && !patch.follow) { clearTimeout(followTimer.current); setFollowing(null) }
  }, [])
  useEffect(() => () => clearTimeout(followTimer.current), [])
  const [version, setVersion] = useState(0)
  const [feed, setFeed] = useState<RelayEvent[]>([])
  const [stats, setStats] = useState<Stats>()
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [sim, setSim] = useState<SimStatus>({ running: false })
  const [simTime, setSimTime] = useState<string>()
  const [cypher, setCypher] = useState<LoggedCypher[]>([])
  const [calls, setCalls] = useState<ToolCall[]>([])
  const [error, setError] = useState<string>()
  const [usage, setUsage] = useState<UsagePayload>()
  const pending = useRef<ReturnType<typeof setTimeout>>()

  const logCypher = useCallback((action: string, entries: CypherEntry[] = []) => {
    if (!entries.length) return
    const at = Date.now()
    setCypher((c) => [...entries.map((e) => ({ ...e, action, at })), ...c].slice(0, 80))
  }, [])

  const refreshLists = useCallback(() => {
    api.summary(tenant).then((r) => { setStats(r.stats); setTickets(r.tickets); setCustomers(r.customers) }).catch(() => {
      // fallback to individual calls if summary endpoint isn't available yet
      api.stats(tenant).then(setStats).catch(() => {})
      api.tickets(tenant).then(setTickets).catch(() => {})
      api.customers(tenant).then(setCustomers).catch(() => {})
    })
  }, [tenant])

  const refreshAll = useCallback((fresh = false) => {
    const { focus, depth } = viewRef.current
    api.graph(tenant, focus ? `e:${focus}` : undefined, focus ? depth : undefined)
      .then((g) => {
        if (viewRef.current.focus !== focus) return // a newer focus was picked meanwhile
        store.current = loadGraph(fresh ? emptyGraph() : store.current, g, focus && fresh ? Date.now() : undefined)
        setVersion((v) => v + 1); setError(undefined)
      })
      .catch((e) => setError(String(e.message ?? e)))
    api.sim(tenant).then((s) => { setSim(s); if (s.sim_time) setSimTime(s.sim_time) }).catch(() => {})
    api.usage().then(setUsage).catch(() => {}) // on load and every reconnect: model status straight from the API
    refreshLists()
  }, [tenant, refreshLists])

  useEffect(() => { setFeed([]) }, [tenant])
  // Tenant, focus or depth changed: start the layout fresh from that snapshot.
  useEffect(() => { refreshAll(true) }, [refreshAll, view.focus, view.depth])

  const status = useRelayStream(tenant, (e) => {
    const v = viewRef.current
    // In focus mode only events about the shown neighbourhood (or the focused customer and their tickets) apply.
    if (relevantToFocus(store.current, e, v.focus) && applyEvent(store.current, e)) setVersion((n) => n + 1)
    const talker = v.follow ? speakerCustomer(e) : null
    if (talker && talker !== v.focus) {
      clearTimeout(followTimer.current) // debounce: a burst of messages settles on the latest speaker
      followTimer.current = setTimeout(() => { setView({ focus: talker }, true); setFollowing(talker) }, FOLLOW_MS)
    }
    if (FEED_TYPES.has(e.type)) setFeed((f) => [...f, e].slice(-400))
    if (e.type === 'clock') setSimTime(e.data.sim_time)
    else if (e.sim_time) setSimTime(e.sim_time)
    if (e.type === 'sim_status') setSim((s) => ({ ...s, ...e.data }))
    if (e.type === 'cypher') setCypher((c) => [{ name: e.data.name, ms: e.data.ms, rows: e.data.rows, query: e.data.query ?? '', params: {}, action: 'live', at: Date.now() }, ...c].slice(0, 80))
    if (e.type === 'usage') setUsage((p) => mergeUsage(p, e.data))
    if (e.type === 'catalog_call') { setCalls((c) => [e.data, ...c].slice(0, 40)); return }
    // Throttle snapshot refetches: one per burst of events.
    if (e.type !== 'cypher' && e.type !== 'clock' && e.type !== 'usage') {
      clearTimeout(pending.current)
      pending.current = setTimeout(refreshLists, TICKET_TYPES.has(e.type) ? 500 : 900)
    }
  }, () => refreshAll())

  return { store: store.current, version, feed, stats, tickets, customers, sim, setSim, simTime, cypher, calls, logCypher, status, error, usage,
    view, setView, following,
    refreshAll, refreshLists, clearFeed: () => setFeed([]) }
}
