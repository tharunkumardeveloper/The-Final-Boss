// Memory chips for the portal: what the desk learned about the visitor, with an animation phase.
// pending  = arrived over the socket while our message is in flight (held until Kavya's reply shows)
// flying   = attached to Kavya's reply bubble, about to fly into the memory panel (shared layoutId)
// settled  = in the memory panel; `at` drives the arrival glow
import { predicateLabel, retiredLabel, ticketLabel, titleCase } from './format'
import type { FactChange, RelayEvent } from './types'

export type Phase = 'pending' | 'flying' | 'settled'
// Staff bookkeeping (what intake is waiting for, what they couldn't say, ticket priority): in memory, not in the
// customer's own panel.
const INTERNAL = new Set(['awaiting', 'doesnt_know', 'has_priority', 'assigned_to', 'has_status'])
export type MemoryKind = 'semantic' | 'episodic' | 'procedural'
// A fix that was tried, fixed a ticket or resolves an issue is procedural memory (how to fix); any other fact is semantic.
const PROCEDURAL = new Set(['tried_fix', 'fixed_by', 'resolves', 'worked_fix', 'playbook'])
export const memoryKind = (predicate: string): MemoryKind => (PROCEDURAL.has(predicate) ? 'procedural' : 'semantic')

export interface Chip { key: string; label: string; status: FactChange['status']; note?: string; phase: Phase; line?: string; at: number; kind?: MemoryKind }

export function chipFor(f: { fact_id: string; predicate: string; object: string }, status: FactChange['status'], phase: Phase, note?: string): Chip {
  const obj = f.predicate === 'has_ticket' ? ticketLabel(f.object) : titleCase(f.object)
  return { key: f.fact_id, status, note, phase, at: Date.now(), kind: memoryKind(f.predicate),
    label: status === 'retired' ? `${retiredLabel(f.predicate)} ${obj}` : `${predicateLabel(f.predicate)} ${obj}` }
}

/** Insert or replace by key; an in-place update keeps the list order stable (no layout jump). */
export function upsert(chips: Chip[], c: Chip, remove: string[] = []): Chip[] {
  const kept = chips.filter((x) => !remove.includes(x.key) || x.key === c.key)
  const i = kept.findIndex((x) => x.key === c.key)
  if (i < 0) return [...kept, c]
  const prev = kept[i]
  // A corroboration never downgrades an "updated" chip.
  if (prev.status === 'updated' && c.status === 'corroborated') return kept
  return kept.map((x, j) => (j === i ? { ...c, phase: prev.phase === 'flying' ? 'flying' : c.phase, line: prev.line ?? c.line } : x))
}

/** Translate a socket event about this customer into a chip change. */
export function fromEvent(chips: Chip[], e: RelayEvent, who: string, tickets: Set<string>, phase: Phase): Chip[] {
  if (e.type === 'ticket_opened') {
    if (e.data.customer !== who) return chips
    tickets.add(e.data.ticket.toLowerCase())
    return upsert(chips, { key: `t:${e.data.ticket.toLowerCase()}`, status: 'new', phase, at: Date.now(),
      label: `ticket ${ticketLabel(e.data.ticket)} opened`, note: e.data.issue })
  }
  if (e.type === 'ticket_status') {
    if (!tickets.has(e.data.ticket.toLowerCase())) return chips
    return upsert(chips, { key: `ts:${e.data.ticket.toLowerCase()}`, status: 'updated', phase, at: Date.now(),
      label: `${ticketLabel(e.data.ticket)} is ${e.data.status}` })
  }
  if (e.type !== 'fact_created' && e.type !== 'fact_corroborated' && e.type !== 'fact_superseded' && e.type !== 'fact_retired') return chips
  const d = e.data
  if ((d.subject !== who && !tickets.has(d.subject.toLowerCase())) || INTERNAL.has(d.predicate)) return chips
  if (d.predicate === 'has_ticket') tickets.add(d.object.toLowerCase())
  if (e.type === 'fact_superseded') return upsert(chips, chipFor(e.data, 'updated', phase, `was ${titleCase(e.data.old_object)}`), [e.data.old_fact_id])
  if (e.type === 'fact_retired') return upsert(chips, chipFor(d, 'retired', phase))
  return upsert(chips, chipFor(d, e.type === 'fact_corroborated' ? 'corroborated' : 'new', phase))
}

/** Merge the /chat response's `learned` list (same rules as events). */
export function fromLearned(chips: Chip[], learned: FactChange[], phase: Phase): Chip[] {
  return learned.filter((f) => !INTERNAL.has(f.predicate)).reduce((cs, f) => upsert(cs, chipFor(f, f.status, phase, f.replaced?.length ? `was ${titleCase(f.replaced[0].object)}` : undefined),
    f.replaced?.map((r) => r.fact_id) ?? []), chips)
}

/** Reply is on screen: pending chips (and the reply's own) start flying from that bubble. */
export const launch = (chips: Chip[], line: string, keys: string[]): Chip[] =>
  chips.map((c) => (c.phase === 'pending' || (keys.includes(c.key) && c.phase !== 'settled') ? { ...c, phase: 'flying', line } : c))

/** Land every flying chip from a bubble in the panel, stamped for the arrival glow. */
export const settle = (chips: Chip[], line: string): Chip[] =>
  chips.map((c) => (c.phase === 'flying' && c.line === line ? { ...c, phase: 'settled', at: Date.now() } : c))
