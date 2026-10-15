import { useEffect, useMemo, useRef, useState } from 'react'
import { titleCase } from '../../lib/format'
import type { Customer } from '../../lib/types'
import type { GraphView } from './useConsole'

function CustomerPicker({ customers, focus, onPick }: { customers: Customer[]; focus: string | null; onPick: (k: string | null) => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const search = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    search.current?.focus()
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', away)
    return () => window.removeEventListener('mousedown', away)
  }, [open])

  const options = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const list = customers.filter((c) => !needle || c.key.includes(needle) || (c.city ?? '').includes(needle))
    if (focus && !customers.some((c) => c.key === focus)) list.unshift({ key: focus, name: titleCase(focus), devices: [] })
    return list
  }, [customers, q, focus])

  const pick = (k: string | null) => { onPick(k); setOpen(false); setQ('') }

  return (
    <div ref={box} className="relative">
      <button className="flex items-center gap-2 rounded-full bg-surface px-3 py-1.5 text-xs font-medium text-ink shadow-soft hairline transition duration-300 ease-spring hover:bg-sunk"
        onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}>
        <span className={`h-2 w-2 rounded-full ${focus ? 'bg-signal' : 'bg-ink-3/50'}`} />
        {focus ? titleCase(focus) : 'Everyone'}
        <span className="text-ink-3">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-10 z-20 w-64 rounded-2xl bg-surface p-2 shadow-lift hairline animate-rise"
          onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}>
          <label htmlFor="pick-q" className="sr-only">Search customers</label>
          <input id="pick-q" ref={search} className="field !py-1.5 text-xs" placeholder="Search customers or cities" value={q}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') pick(options[0]?.key ?? null) }} />
          <ul role="listbox" aria-label="Customers" className="scroll-thin mt-1.5 max-h-64 overflow-y-auto">
            {!q && (
              <li><button role="option" aria-selected={!focus} onClick={() => pick(null)}
                className={`w-full rounded-lg px-2.5 py-1.5 text-left text-xs ${!focus ? 'bg-signal-tint text-signal-deep' : 'text-ink hover:bg-sunk'}`}>Everyone</button></li>
            )}
            {options.map((c) => (
              <li key={c.key}>
                <button role="option" aria-selected={focus === c.key} onClick={() => pick(c.key)}
                  className={`flex w-full items-baseline justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs ${focus === c.key ? 'bg-signal-tint text-signal-deep' : 'text-ink hover:bg-sunk'}`}>
                  <span className="truncate">{c.name}</span>
                  {c.city && <span className="shrink-0 text-ink-3">{titleCase(c.city)}</span>}
                </button>
              </li>
            ))}
            {options.length === 0 && <li className="px-2.5 py-2 text-xs text-ink-3">No customer matches "{q}".</li>}
          </ul>
        </div>
      )}
    </div>
  )
}

export function GraphControls({ customers, view, setView, following }: {
  customers: Customer[]; view: GraphView; setView: (p: Partial<GraphView>) => void; following: string | null
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <CustomerPicker customers={customers} focus={view.focus} onPick={(k) => setView({ focus: k })} />
      {view.focus && (
        <div className="flex rounded-full bg-surface p-0.5 text-xs shadow-soft hairline" role="group" aria-label="Neighbourhood depth">
          {([1, 2] as const).map((d) => (
            <button key={d} onClick={() => setView({ depth: d })} aria-pressed={view.depth === d}
              className={`rounded-full px-2.5 py-1 transition duration-300 ease-spring ${view.depth === d ? 'bg-ink text-paper' : 'text-ink-2 hover:bg-sunk'}`}>
              {d} hop{d > 1 ? 's' : ''}
            </button>
          ))}
        </div>
      )}
      <button onClick={() => setView({ follow: !view.follow })} aria-pressed={view.follow}
        className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium shadow-soft hairline transition duration-300 ease-spring ${view.follow ? 'bg-signal-deep text-white' : 'bg-surface text-ink-2 hover:bg-sunk'}`}
        title="Switch focus to whichever customer is talking">
        <span className={`relative h-3.5 w-6 rounded-full transition-colors duration-300 ${view.follow ? 'bg-white/30' : 'bg-ink/15'}`}>
          <span className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white shadow transition-transform duration-300 ease-spring ${view.follow ? 'translate-x-3' : 'translate-x-0.5'}`} />
        </span>
        Follow live
      </button>
      {view.follow && following && (
        <span className="chip animate-rise bg-signal-tint text-signal-deep" role="status">
          <i className="h-1.5 w-1.5 rounded-full bg-signal animate-breathe" />following {titleCase(following.split(' ')[0])}
        </span>
      )}
    </div>
  )
}
