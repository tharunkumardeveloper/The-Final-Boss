import { BOT } from './brand'
const IST = 'Asia/Kolkata'

export function when(iso?: string | null, withTime = true): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-IN', {
    timeZone: IST, day: 'numeric', month: 'short',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : { year: 'numeric' }),
  })
}

export const titleCase = (s: string) =>
  s.replace(/\b([a-z])/g, (m) => m.toUpperCase()).replace(/\bPs(\d)\b/, 'PS$1').replace(/\bTv\b/, 'TV')

export const ticketLabel = (t: string) => t.toUpperCase()

const PREDICATES: Record<string, string> = {
  lives_in: 'lives in', on_plan: 'is on', has_router: 'has router', prefers_channel: 'prefers',
  has_ticket: 'has ticket', owns_device: 'owns', reported_issue: 'reported', has_status: 'status',
  assigned_to: 'assigned to', ticket_about: 'is about', tried_fix: 'tried', fixed_by: 'was fixed by', resolves: 'resolves', affects: 'affects',
  moving_to: 'moving to', interested_in: 'interested in', budget: 'budget', household_size: 'household of',
  wants_to_buy: 'wants to buy', current_provider: 'currently with',
  awaiting: 'still to tell us their', occupation: 'works as', visit_reason: 'came about', asked_about: 'asked about', requested: 'asked us to', plays_game: 'plays', watches: 'watches', address: 'address:',
  phone: 'phone:', email: 'email:', account_id: 'account:', alt_phone: 'other phone:', installed_at: 'installed',
  connection_type: 'connection:', preferred_name: 'prefers to be called', billing_contact: 'bills go to',
  has_addon: 'has add-on', referred: 'referred', previous_contact: 'contacted us before', service_request: 'requested',
  calling_for: 'calling for', on_waitlist: 'on the waitlist for', doesnt_know: "doesn't know their",
  issue_type: 'type:', issue_started: 'started', frequency: 'happens', severity: 'affects', affected_device: 'affects device',
  error_message: 'error:', router_lights: 'router lights:', speed_reported: 'speed:', connection_medium: 'on',
  affected_users: 'people affected:', distance_from_router: 'distance from router:', has_priority: 'priority',
}
/** Open attributes ("open:works_from_home") read as "works from home:". */
export const predicateLabel = (p: string) =>
  PREDICATES[p] ?? (p.startsWith('open:') ? `${p.slice(5).replace(/_/g, ' ')}:` : p.replace(/_/g, ' '))

const RETIRED: Record<string, string> = {
  lives_in: 'no longer lives in', on_plan: 'is no longer on', has_router: 'no longer has router', prefers_channel: 'no longer prefers',
  owns_device: 'no longer owns', reported_issue: 'no longer reports', has_ticket: 'no longer has ticket', affects: 'no longer affects',
}
/** "Alice Rao no longer lives in Chennai" */
export const retiredLabel = (p: string) => RETIRED[p] ?? `no longer ${predicateLabel(p)}`

export const label = (key: string, kind?: string) =>
  kind === 'ticket' ? ticketLabel(key) : kind === 'customer' || kind === 'city' ? titleCase(key) : key

export function speakerName(speaker: string, customer?: string): string {
  if (speaker === 'customer') return customer ? titleCase(customer) : 'Customer'
  if (speaker === 'intake') return `${BOT} at intake`
  if (speaker === 'resolver') return 'Resolver'
  if (speaker === 'noc') return 'Network ops · we noticed first'
  if (speaker === 'action') return 'Internal note'
  if (speaker.startsWith('tool:')) return `${titleCase(speaker.slice(5))} system`
  if (speaker.startsWith('mcp:')) return `${speaker.slice(4)} (MCP)`
  return speaker
}

/** Wilson score interval for k successes in n trials (95%). */
export function wilson(k: number, n: number): [number, number] {
  if (!n) return [0, 0]
  const z = 1.96, p = k / n
  const den = 1 + (z * z) / n
  const mid = (p + (z * z) / (2 * n)) / den
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / den
  return [Math.max(0, mid - half), Math.min(1, mid + half)]
}

export const pct = (x: number) => `${Math.round(x * 100)}%`

/** 'IN' -> the Indian flag emoji (Windows gets it from the flag polyfill font loaded in main.tsx). */
export const flag = (iso: string) => String.fromCodePoint(...iso.toUpperCase().split('').map((c) => 127397 + c.charCodeAt(0)))
