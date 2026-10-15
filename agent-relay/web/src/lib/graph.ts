import type { GEdge, GNode, Graph, RelayEvent } from './types'

// Subject/object kinds per predicate, mirrored from relay/registry.py so live events can place new nodes.
export const PREDICATE_KINDS: Record<string, [string, string]> = {
  lives_in: ['customer', 'city'], on_plan: ['customer', 'plan'], has_router: ['customer', 'router'],
  prefers_channel: ['customer', 'channel'], has_ticket: ['customer', 'ticket'], owns_device: ['customer', 'device'],
  reported_issue: ['customer', 'issue'], has_status: ['ticket', 'status'], assigned_to: ['ticket', 'agent'],
  ticket_about: ['ticket', 'issue'], tried_fix: ['ticket', 'fix'], fixed_by: ['ticket', 'fix'], resolves: ['fix', 'issue'], affects: ['outage', 'city'],
}

// Entity keys are stored lowercase (tickets arrive as PML-2041, live as e:pml-2041).
export const entityId = (key: string) => `e:${key.toLowerCase()}`
export const factId = (id: string) => (id.startsWith('f:') ? id : `f:${id}`)

/** Mutable graph store. Node/edge objects are kept stable so the force layout keeps positions across updates. */
export interface GraphState {
  nodes: Map<string, GNode & { born?: number; appear?: number }>
  edges: Map<string, GEdge & { born?: number; faded?: number }>
  version: number
}

export const emptyGraph = (): GraphState => ({ nodes: new Map(), edges: new Map(), version: 0 })

function ensureNode(s: GraphState, id: string, kind: string, label: string, now: number) {
  const n = s.nodes.get(id)
  if (n) {
    if (n.kind === 'unknown') n.kind = kind
    return n
  }
  const node = { id, kind, label, born: now }
  s.nodes.set(id, node)
  return node
}

function upsertEdge(s: GraphState, e: GEdge, now: number) {
  const cur = s.edges.get(e.id)
  if (cur) {
    const wasActive = cur.active
    Object.assign(cur, { label: e.label, active: e.active, conflict: e.conflict ?? cur.conflict })
    if (wasActive && !e.active) cur.faded = now
    return cur
  }
  const edge = { ...e, born: now, faded: e.active ? undefined : now }
  s.edges.set(e.id, edge)
  return edge
}

/** Merge a snapshot. `appear` (a timestamp) makes newly added nodes fade in, e.g. a focused neighbourhood. */
export function loadGraph(s: GraphState, g: Graph, appear?: number) {
  for (const n of g.nodes) {
    const cur = s.nodes.get(n.id)
    if (cur) Object.assign(cur, { kind: n.kind, label: n.label, salience: n.salience, community: n.community })
    else s.nodes.set(n.id, { ...n, appear })
  }
  for (const e of g.edges) {
    const cur = s.edges.get(e.id)
    if (cur) Object.assign(cur, { label: e.label, active: e.active, conflict: e.conflict })
    else s.edges.set(e.id, { ...e })
  }
  s.version++
  return s
}

/** Apply one live event. Returns true if the graph changed. */
export function applyEvent(s: GraphState, ev: RelayEvent, now = Date.now()): boolean {
  switch (ev.type) {
    case 'message': {
      // A customer who has only chatted (no facts yet) still appears, so a new conversation is visible at once.
      const c = ev.data.customer
      if (!c || s.nodes.has(entityId(c))) return false
      ensureNode(s, entityId(c), 'customer', c.toLowerCase(), now)
      break
    }
    case 'fact_created':
    case 'fact_corroborated': {
      const d = ev.data
      const [sk, ok] = PREDICATE_KINDS[d.predicate] ?? ['unknown', 'unknown']
      ensureNode(s, entityId(d.subject), sk, d.subject.toLowerCase(), now)
      ensureNode(s, entityId(d.object), ok, d.object.toLowerCase(), now)
      const e = upsertEdge(s, { id: factId(d.fact_id), source: entityId(d.subject), target: entityId(d.object),
        label: d.predicate, active: true }, now)
      if (ev.type === 'fact_corroborated') e.born = now
      break
    }
    case 'fact_superseded': {
      const d = ev.data
      const [sk, ok] = PREDICATE_KINDS[d.predicate] ?? ['unknown', 'unknown']
      ensureNode(s, entityId(d.subject), sk, d.subject.toLowerCase(), now)
      ensureNode(s, entityId(d.object), ok, d.object.toLowerCase(), now)
      ensureNode(s, entityId(d.old_object), ok, d.old_object.toLowerCase(), now)
      upsertEdge(s, { id: factId(d.fact_id), source: entityId(d.subject), target: entityId(d.object),
        label: d.predicate, active: true }, now)
      upsertEdge(s, { id: factId(d.old_fact_id), source: entityId(d.subject), target: entityId(d.old_object),
        label: d.predicate, active: false }, now)
      break
    }
    case 'fact_retired': {
      // Ended with nothing replacing it: the edge goes inactive, no new edge appears.
      const d = ev.data
      const [sk, ok] = PREDICATE_KINDS[d.predicate] ?? ['unknown', 'unknown']
      ensureNode(s, entityId(d.subject), sk, d.subject.toLowerCase(), now)
      ensureNode(s, entityId(d.object), ok, d.object.toLowerCase(), now)
      upsertEdge(s, { id: factId(d.fact_id), source: entityId(d.subject), target: entityId(d.object),
        label: d.predicate, active: false }, now)
      break
    }
    case 'conflict': {
      for (const c of ev.data.claims) {
        const e = s.edges.get(factId(c.fact_id))
        if (e) e.conflict = true
      }
      break
    }
    case 'ticket_opened': {
      ensureNode(s, entityId(ev.data.ticket), 'ticket', ev.data.ticket.toLowerCase(), now)
      ensureNode(s, entityId(ev.data.customer), 'customer', ev.data.customer.toLowerCase(), now)
      break
    }
    default:
      return false
  }
  s.version++
  return true
}

const idOf = (v: unknown) => (typeof v === 'string' ? v : (v as GNode).id)

/** Entity ids an event touches, subject first. */
function touched(ev: RelayEvent): string[] {
  switch (ev.type) {
    case 'message': return ev.data.customer ? [entityId(ev.data.customer)] : []
    case 'fact_created': case 'fact_corroborated': case 'fact_retired':
      return [entityId(ev.data.subject), entityId(ev.data.object)]
    case 'fact_superseded': return [entityId(ev.data.subject), entityId(ev.data.object), entityId(ev.data.old_object)]
    case 'ticket_opened': return [entityId(ev.data.customer), entityId(ev.data.ticket)]
    case 'conflict': return [entityId(ev.data.subject)]
    default: return []
  }
}

/** Focus mode: should this live event change the displayed neighbourhood of `focus` (a customer key)?
 *  Yes if it touches something already shown, or its subject is the focused customer or one of their tickets. */
export function relevantToFocus(s: GraphState, ev: RelayEvent, focus: string | null): boolean {
  if (!focus) return true
  const ids = touched(ev)
  if (!ids.length) return false
  const me = entityId(focus)
  if (ids[0] === me || ids.some((id) => s.nodes.has(id))) return true
  for (const e of s.edges.values()) if (e.label === 'has_ticket' && idOf(e.source) === me && idOf(e.target) === ids[0]) return true
  return false
}

/** Follow-live: the customer a message is from (customers only, not agents or tools). */
export const speakerCustomer = (ev: RelayEvent): string | null =>
  ev.type === 'message' && ev.data.speaker === 'customer' && ev.data.customer ? ev.data.customer.toLowerCase() : null

/** Outages currently affecting a city, read from the graph (used for the portal banner). */
export function activeOutages(s: GraphState): { outage: string; city: string }[] {
  const out: { outage: string; city: string }[] = []
  for (const e of s.edges.values()) {
    if (e.label === 'affects' && e.active) {
      const src = idOf(e.source), dst = idOf(e.target)
      out.push({ outage: s.nodes.get(src)?.label ?? src, city: s.nodes.get(dst)?.label ?? dst })
    }
  }
  return out
}
