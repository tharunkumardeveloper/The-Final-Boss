import { keyHeaders, setKeys, setResetKey } from './keys'
import { mockRequest } from './mock'
import type { CaseStory, Compare, Crossing, LabManual, LabView, QueryResult, Schema, AskResponse, Benchmark, Card, ChatResponse, Clock, Community, Conversation, Customer, DbHealth, DemoPicks, ToolResult, Expert, FailResult, FixResponse, Graph, HistoryRow, Isolation, Kb, Network, PickupResponse, Region, Sharing, SimStatus, SlowQuery, Snapshot, Stats, Ticket, UsagePayload } from './types'

export const MOCK = import.meta.env.VITE_MOCK === '1'
export const API_URL = String(import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
export const WS_URL = String(import.meta.env.VITE_WS_URL || API_URL.replace(/^http/, 'ws')).replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

/** Fetch every tenant's key from the demo server (a new tenant needs a fresh list). Ignored where keys aren't issued. */
export async function loadKeys() {
  if (MOCK) return
  try {
    const r = await fetch(`${API_URL}/api/demo/keys`)
    if (r.ok) setKeys(await r.json())
  } catch { /* keys come from elsewhere in production */ }
}

async function req<T>(path: string, init?: RequestInit & { timeoutMs?: number }, retried = false): Promise<T> {
  if (MOCK) return mockRequest(path, init) as Promise<T>
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), init?.timeoutMs ?? 60_000)
  try {
    const r = await fetch(API_URL + path, { ...init, signal: ctrl.signal, headers: { 'Content-Type': 'application/json', ...keyHeaders(path) } })
    if (r.status === 401 && !retried) {  // a tenant created since start: fetch its key once, then retry
      await loadKeys()
      return req<T>(path, init, true)
    }
    if (!r.ok) {
      const body = await r.text().catch(() => '')
      if (r.status === 403 && !retried && /reset key/i.test(body)) {  // a locked reset on the public demo: ask once
        const k = window.prompt('Resets are locked on this public demo so nobody wipes it mid-judging. Reset key:')?.trim()
        if (k) { setResetKey(k); return req<T>(path, init, true) }
      }
      throw new ApiError(r.status, body.slice(0, 300) || r.statusText)
    }
    return (await r.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

const post = <T>(path: string, body?: unknown) => req<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
const put = <T>(path: string, body: unknown) => req<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const t = (tenant: string) => `/api/tenants/${encodeURIComponent(tenant)}`
const q = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const api = {
  health: (timeoutMs = 90_000) => req<{ ok: boolean; falkordb: boolean }>('/health', { timeoutMs }),
  tenants: () => req<string[]>('/api/tenants'),
  createTenant: (name: string) => post<{ name: string }>('/api/tenants', { name }),
  checkModels: (model?: string) => post<UsagePayload>('/api/usage/check', { model: model ?? null }),
  plan: (tenant: string, query: string, params: Record<string, unknown>, profile: boolean) =>
    post<{ plan: string[]; profile: boolean }>(`${t(tenant)}/plan`, { query, params, profile }),
  reset: (tenant: string, scenario: 'empty' | 'story' | 'benchmark') => post<{ ok: boolean; started?: boolean }>(`${t(tenant)}/reset`, { scenario, background: true }),
  stats: (tenant: string) => req<Stats>(`${t(tenant)}/stats`),
  customers: (tenant: string) => req<Customer[]>(`${t(tenant)}/customers`),
  graph: (tenant: string, focus?: string, depth?: number) => req<Graph>(`${t(tenant)}/graph${q({ focus, depth })}`),
  myGraph: (tenant: string, customer: string) => req<Graph>(`${t(tenant)}/my-graph${q({ customer })}`),
  card: (tenant: string, id: string) => req<Card>(`${t(tenant)}/card/${encodeURIComponent(id)}`),
  tickets: (tenant: string) => req<Ticket[]>(`${t(tenant)}/tickets`),
  locate: (tz: string, lang: string) => req<{ country: string | null; name?: string; tenant?: string }>(`/api/locate${q({ tz, lang })}`),
  chat: (tenant: string, body: { customer: string; text: string; session_id?: string; greeted?: boolean; country?: string }) => post<ChatResponse>(`${t(tenant)}/chat`, body),
  pickup: (tenant: string, ticket: string) => post<PickupResponse>(`${t(tenant)}/tickets/${encodeURIComponent(ticket)}/pickup`),
  fix: (tenant: string, ticket: string, fix: string, worked: boolean) =>
    post<FixResponse>(`${t(tenant)}/tickets/${encodeURIComponent(ticket)}/fix`, { fix, worked }),
  tool: (tenant: string, name: string, args: Record<string, string | number>) => post<ToolResult>(`${t(tenant)}/tools/${encodeURIComponent(name)}`, args),
  demos: (tenant: string) => req<DemoPicks>(`${t(tenant)}/demos`),
  ask: (tenant: string, question: string) => post<AskResponse>(`${t(tenant)}/ask`, { question, agent: 'resolver' }),
  clock: (tenant: string, subject: string, at: string) => req<Clock>(`${t(tenant)}/clock${q({ subject, at })}`),
  history: (tenant: string, subject: string) => req<HistoryRow[]>(`${t(tenant)}/history${q({ subject })}`),
  consolidate: (tenant: string) => post<{ communities: Community[] }>(`${t(tenant)}/consolidate`),
  simStart: (tenant: string, speed: number, customers?: number) => post<SimStatus>(`${t(tenant)}/sim/start`, { speed, customers }),
  simSpeed: (tenant: string, speed: number) => post<SimStatus>(`${t(tenant)}/sim/speed`, { speed }),
  resetStatus: (tenant: string) => req<{ phase: string | null }>(`${t(tenant)}/reset`),
  simStop: (tenant: string) => post<SimStatus>(`${t(tenant)}/sim/stop`),
  sim: (tenant: string) => req<SimStatus>(`${t(tenant)}/sim`),
  compare: (tenant: string, question: string) => req<Compare>(`${t(tenant)}/compare`, { method: 'POST', body: JSON.stringify({ question }), timeoutMs: 120_000 }),
  benchmark: () => req<Benchmark>('/api/benchmark'),
  conversation: (tenant: string, customer: string, limit = 400) => req<Conversation>(`${t(tenant)}/conversation${q({ customer, limit })}`),
  kb: (tenant: string, country?: string) => req<Kb>(`${t(tenant)}/kb${q({ country })}`),
  regions: () => req<Region[]>('/api/regions'),
  query: (tenant: string, query: string) => post<QueryResult>(`${t(tenant)}/query`, { query }),
  schema: (tenant: string) => req<Schema>(`${t(tenant)}/schema`),
  dbHealth: () => req<DbHealth>('/api/db/health'),
  slowlog: (tenant: string) => req<{ queries: SlowQuery[] }>(`${t(tenant)}/slowlog`),
  snapshots: (tenant: string) => req<{ snapshots: Snapshot[] }>(`${t(tenant)}/snapshots`),
  takeSnapshot: (tenant: string, label: string) => post<{ name: string; snapshots: Snapshot[] }>(`${t(tenant)}/snapshots`, { label }),
  restoreSnapshot: (tenant: string, name: string) => post<{ ok: boolean }>(`${t(tenant)}/snapshots/${encodeURIComponent(name)}/restore`),
  capacity: (tenant: string, id: string) => req<{ node: string; gbps: number }>(`${t(tenant)}/network/${encodeURIComponent(id)}/capacity`),
  cablePlan: (tenant: string) => req<{ links: number; km: number; all_links: number; all_km: number }>(`${t(tenant)}/network-cable-plan`),
  isolation: (customer: string) => req<Isolation>(`/api/isolation${q({ customer })}`),
  procedural: (tenant: string) => req<{ fixes: Array<{ fix: string; issue: string; times: number; last_used: string | null }> }>(`${t(tenant)}/procedural`),
  lab: (tenant: string, customer?: string) => req<LabView>(`${t(tenant)}/lab${q({ customer })}`),
  labInject: (tenant: string, body: { preset: string; customer?: string; blind?: boolean; complain?: boolean }) =>
    post<{ fault: string; preset: string | null; customer: string; blind: boolean }>(`${t(tenant)}/lab/inject`, body),
  labAction: (tenant: string, action: string, customer: string) => post<LabManual>(`${t(tenant)}/lab/action`, { action, customer }),
  labInvestigate: (tenant: string, customer: string) => post<{ run: string }>(`${t(tenant)}/lab/investigate`, { customer }),
  labTrouble: (tenant: string, customer: string) => post<{ fault: string; notice: string; customer: string }>(`${t(tenant)}/lab/trouble`, { customer }),
  labReset: (tenant: string) => post<{ ok: boolean }>(`${t(tenant)}/lab/reset`),
  summary: (tenant: string) => req<{ stats: Stats; tickets: Ticket[]; customers: Customer[] }>(`${t(tenant)}/summary`),
  story: (tenant: string, ticket: string) => req<CaseStory>(`${t(tenant)}/sharing/story${q({ ticket })}`),
  crossings: (tenant: string, reader?: string, writer?: string) => req<Crossing[]>(`${t(tenant)}/sharing/crossings${q({ reader, writer })}`),
  sharing: (tenant: string) => req<Sharing>(`${t(tenant)}/sharing`),
  network: (tenant: string, country?: string) => req<Network>(`${t(tenant)}/network${q({ country })}`),
  experts: (tenant: string, topic: string) => req<Expert[]>(`${t(tenant)}/experts${q({ topic })}`),
  failNode: (tenant: string, id: string) => post<FailResult>(`${t(tenant)}/network/${encodeURIComponent(id)}/fail`),
  restoreNode: (tenant: string, id: string) => post<FailResult>(`${t(tenant)}/network/${encodeURIComponent(id)}/restore`),
  usage: () => req<UsagePayload>('/api/usage'),
  putLimits: (body: { model: string; rpm?: number | null; rpd?: number | null; tpm?: number | null; tpd?: number | null }) =>
    put<UsagePayload>('/api/usage/limits', body),
  putRoutes: (job: string, models: string[]) => put<UsagePayload>('/api/usage/routes', { job, models }),
}
