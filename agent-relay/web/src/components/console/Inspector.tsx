import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import type { Card } from '../../lib/types'
import { KIND_COLOR } from './MemoryGraph'
import { MEMORY_KINDS, MemoryKindPill } from '../portal/MemoryPanel'

export function Inspector({ tenant, id, version }: { tenant: string; id: string | null; version: number }) {
  const [card, setCard] = useState<Card>()
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const shown = useRef<string | null>(null)

  // Refetch on selection, and quietly every few memory changes (the card may have gained facts).
  const tick = Math.floor(version / 5)
  useEffect(() => {
    if (!id) { setCard(undefined); return }
    let live = true
    if (shown.current !== id) setState('loading')
    api.card(tenant, id).then((c) => { if (live) { shown.current = id; setCard(c); setState('idle') } }).catch(() => live && setState('error'))
    return () => { live = false }
  }, [tenant, id, tick])

  if (!id) return (
    <div className="px-5 py-8 text-sm text-ink-3">
      <p className="font-medium text-ink-2">Nothing selected</p>
      <p className="mt-1">Click a customer, place or connection in the graph to read it in plain language.</p>
    </div>
  )
  if (state === 'loading') return (
    <div className="space-y-3 px-5 py-6" aria-busy="true">
      {[60, 90, 75].map((w) => <div key={w} className="h-3 animate-breathe rounded bg-sunk" style={{ width: `${w}%` }} />)}
    </div>
  )
  if (state === 'error' || !card) return <p className="px-5 py-6 text-sm text-danger" role="alert">Couldn't load this card.</p>

  const superseded = card.active === false
  return (
    <article className="animate-rise px-5 py-5">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: KIND_COLOR[card.kind] ?? '#7A8799' }} />
        <span className="eyebrow">{card.subtitle ?? card.kind}</span>
        {card.memory && <MemoryKindPill kind={card.memory} className="ml-auto" />}
      </div>
      {card.memory && <p className="mt-1.5 text-[11px] leading-snug text-ink-3">{MEMORY_KINDS[card.memory].label} memory: {MEMORY_KINDS[card.memory].what}.</p>}
      <h3 className={`mt-2 font-display text-xl font-semibold leading-tight tracking-[-0.01em] ${superseded ? 'text-ink-3 line-through decoration-1' : ''}`}>{card.title}</h3>
      {card.summary && <p className="mt-2 rounded-xl bg-signal-tint/60 px-3 py-2 text-sm text-ink-2">{card.summary}</p>}
      <div className="mt-3 space-y-1.5 text-sm leading-relaxed text-ink-2">{card.lines.map((l, i) => <p key={i}>{l}</p>)}</div>
      {card.sections.filter((s) => s.rows.length).map((s) => (
        <section key={s.title} className="mt-5">
          <h4 className="eyebrow flex items-center gap-1.5">{s.title === 'Sources' ? 'Sources · the messages it came from' : s.title}
            {s.title === 'Sources' && <MemoryKindPill kind="episodic" className="normal-case tracking-normal" />}</h4>
          <dl className="mt-2 divide-y divide-line/[0.06]">
            {s.rows.map(([k, v], i) => (
              <div key={i} className="flex justify-between gap-4 py-1.5 text-sm">
                <dt className="text-ink-3">{k}</dt><dd className="num text-right text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
      <p className="mt-5 font-mono text-[11px] text-ink-3">{card.id}</p>
    </article>
  )
}
