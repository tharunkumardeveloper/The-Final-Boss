import { titleCase } from '../lib/format'
import type { Hop, Outcome } from '../lib/types'

const SHORT = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
export const shortDate = (d?: string | null) => (d ? SHORT.format(new Date(`${d}T00:00:00Z`)) : '')

/** The answer contract's four shapes, as the chip shown with every answer. */
export const OUTCOME: Record<Outcome, { label: string; cls: string; hint: string }> = {
  path: { label: 'Answered with a path', cls: 'chip-new', hint: 'A multi-hop traversal reached the answer: the hops are below.' },
  memory: { label: 'Answered from memory', cls: 'chip-corroborated', hint: 'A fact an agent wrote in an earlier session, with when and by whom.' },
  not_in_graph: { label: 'Not in the graph', cls: 'chip bg-sunk text-ink-2', hint: 'The names are known, but nothing connects them the way the question assumes: not modelled, which is not "nothing".' },
  unknown_entity: { label: 'Unknown name · no query ran', cls: 'chip-retired', hint: 'A name the graph does not hold: abstained after name lookup.' },
}

export function OutcomeChip({ outcome }: { outcome?: Outcome }) {
  if (!outcome) return null
  const o = OUTCOME[outcome]
  return <span className={o.cls} title={o.hint} data-outcome={outcome}>{o.label}</span>
}

/** One path: Alice → LIVES_IN → Thane · since 3 Sep · by intake, one row per hop. */
export function Hops({ hops }: { hops: Hop[] }) {
  return (
    <ol className="space-y-1">
      {hops.map((h, i) => (
        <li key={i} className={`flex flex-wrap items-baseline gap-x-1.5 text-xs ${h.active === false ? 'text-ink-3 line-through' : 'text-ink-2'}`}>
          <span className="font-medium text-ink">{titleCase(h.from)}</span>
          <span className="font-mono text-[10.5px] text-signal-deep">→ {h.rel} →</span>
          <span className="font-medium text-ink">{titleCase(h.to)}</span>
          {h.since && <span className="num text-ink-3">· since {shortDate(h.since)}{h.until ? ` until ${shortDate(h.until)}` : ''}</span>}
          {h.by && h.by.length > 0 && <span className="text-ink-3">· by {h.by.join(', ')}</span>}
        </li>
      ))}
    </ol>
  )
}
