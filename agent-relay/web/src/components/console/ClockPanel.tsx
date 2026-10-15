import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { predicateLabel, titleCase, when } from '../../lib/format'
import type { Customer, HistoryRow } from '../../lib/types'

const HOUR = 3_600_000
const ms = (s?: string | null) => (s ? Date.parse(s) : undefined)
const inside = (t: number, from?: number, to?: number) => from !== undefined && from <= t && (to === undefined || t < to)

type State = 'both' | 'lag' | 'stale' | 'none'
const STATE: Record<State, { label: string; tone: string; dot: string }> = {
  both: { label: 'known and true', tone: 'text-ink', dot: 'bg-current' },
  lag: { label: 'true, not on file yet', tone: 'text-conflict', dot: 'bg-conflict' },
  stale: { label: 'on file, no longer true', tone: 'text-danger', dot: 'bg-danger' },
  none: { label: 'not yet / no longer', tone: 'text-ink-3', dot: 'bg-old' },
}

/** Two clocks per fact: when it was true in the world vs when it was on file. Scrub time and see where records lag. */
export function ClockPanel({ tenant, customers, subject, onSubject, version, simTime }: {
  tenant: string; customers: Customer[]; subject: string | null; onSubject: (k: string) => void; version: number; simTime?: string
}) {
  const who = subject ?? customers[0]?.key ?? null
  const [rows, setRows] = useState<HistoryRow[]>([])
  const [at, setAt] = useState<number>()
  const tick = Math.floor(version / 3)

  useEffect(() => {
    if (!who) return
    api.history(tenant, who).then((r) => setRows(r.filter((x) => x.predicate !== 'has_ticket' && x.predicate !== 'awaiting'))).catch(() => setRows([]))
  }, [tenant, who, tick])

  // the moments worth jumping to: where the two clocks disagree (backdated facts, late corrections)
  const { lo, hi, moments } = useMemo(() => {
    const ts = rows.flatMap((r) => [r.valid_from, r.valid_to, r.recorded_at, r.expired_at].map(ms)).filter((x): x is number => x !== undefined)
    const now = ms(simTime) ?? Date.now()
    if (!ts.length) return { lo: now - 48 * HOUR, hi: now, moments: [] as { at: number; label: string }[] }
    const lo = Math.min(...ts) - 6 * HOUR, hi = Math.max(...ts, now)
    const m: { at: number; label: string }[] = [{ at: Math.min(...ts), label: 'First contact' }]
    for (const r of rows) {
      const vf = ms(r.valid_from), rec = ms(r.recorded_at)
      if (vf !== undefined && rec !== undefined && rec - vf > 6 * HOUR) m.push({ at: (vf + rec) / 2, label: `Before we knew: ${predicateLabel(r.predicate).toLowerCase()} ${titleCase(r.value)}` })
    }
    m.push({ at: hi, label: 'Now' })
    return { lo, hi, moments: m.slice(0, 5) }
  }, [rows, simTime])
  useEffect(() => { setAt(moments.length > 2 ? moments[1].at : hi) }, [who, moments, hi])

  const t = at ?? hi
  const state = (r: HistoryRow): State => {
    const world = inside(t, ms(r.valid_from), ms(r.valid_to)), file = inside(t, ms(r.recorded_at), ms(r.expired_at))
    return world && file ? 'both' : world ? 'lag' : file ? 'stale' : 'none'
  }
  const counts = rows.reduce((c, r) => { c[state(r)]++; return c }, { both: 0, lag: 0, stale: 0, none: 0 } as Record<State, number>)
  const x = (v?: number) => `${(((v ?? hi) - lo) / (hi - lo)) * 100}%`
  const span = (a?: number, b?: number) => ({ left: x(a), width: `max(3px, calc(${x(b)} - ${x(a)}))` })
  const diffs = rows.filter((r) => state(r) === 'lag' || state(r) === 'stale')

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Two clocks">
      <div className="flex flex-wrap items-center gap-3 px-4 pt-3">
        <h2 className="eyebrow">Two clocks</h2>
        <label htmlFor="clock-who" className="sr-only">Customer</label>
        <select id="clock-who" className="rounded-full bg-sunk px-2.5 py-1 text-xs text-ink-2 outline-none focus:ring-2 focus:ring-signal/40"
          value={who ?? ''} onChange={(e) => onSubject(e.target.value)}>
          {customers.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
        </select>
        <span className="ml-auto flex items-center gap-3 text-[11px] text-ink-3">
          <span className="flex items-center gap-1.5"><i className="h-1.5 w-5 rounded-full bg-current" />true in the world</span>
          <span className="flex items-center gap-1.5"><i className="h-1.5 w-5 rounded-full ring-1 ring-inset ring-ink/50" />on our file</span>
        </span>
      </div>
      {!who || !rows.length ? (
        <p className="px-4 py-6 text-sm text-ink-3">Facts appear here once the desk learns something about a customer.</p>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-4 pb-3 pt-2 xl:grid-cols-[minmax(0,1fr)_250px]">
          <div className="flex min-h-0 flex-col">
            <div className="flex flex-wrap gap-1.5 pb-2">
              {moments.map((m) => (
                <button key={m.label} onClick={() => setAt(m.at)} title={when(new Date(m.at).toISOString())}
                  className={`max-w-[220px] truncate rounded-full px-2.5 py-1 text-[11px] transition duration-300 ease-spring ${Math.abs(t - m.at) < HOUR ? 'bg-ink text-paper' : 'bg-sunk text-ink-2 hover:bg-line/10'}`}>{m.label}</button>
              ))}
            </div>
            <div className="scroll-thin relative min-h-0 flex-1 overflow-y-auto pr-1">
              {rows.map((r) => {
                const st = state(r)
                return (
                  <div key={r.fact_id} className={`grid grid-cols-[150px_minmax(0,1fr)] items-center gap-2 rounded-lg px-1 py-[3px] ${st === 'lag' ? 'bg-conflict-tint/70' : st === 'stale' ? 'bg-danger-tint/70' : ''}`}>
                    <span className={`flex min-w-0 items-center gap-1.5 text-[11.5px] ${STATE[st].tone}`} title={`${predicateLabel(r.predicate)} ${r.value} · ${STATE[st].label}`}>
                      <i className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATE[st].dot}`} />
                      <span className="truncate">{predicateLabel(r.predicate)} <span className="font-medium">{titleCase(r.value)}</span></span>
                    </span>
                    <div className="relative h-4">
                      <i className={`absolute top-0 h-1.5 rounded-full ${r.active ? 'bg-current' : 'bg-old'}`} style={span(ms(r.valid_from), ms(r.valid_to))} />
                      <i className="absolute top-[9px] h-1.5 rounded-full ring-1 ring-inset ring-ink/45" style={span(ms(r.recorded_at), ms(r.expired_at))} />
                    </div>
                  </div>
                )
              })}
              <div className="pointer-events-none absolute inset-y-0 left-[158px] right-1">
                <i className="absolute inset-y-0 w-0.5 rounded-full bg-signal" style={{ left: x(t) }} />
              </div>
            </div>
            <div className="grid grid-cols-[150px_minmax(0,1fr)] items-center gap-2 pt-1.5">
              <span className="num text-[11px] font-medium text-signal-deep">{when(new Date(t).toISOString())}</span>
              <input type="range" aria-label="Move through time" min={lo} max={hi} step={HOUR} value={t}
                onChange={(e) => setAt(Number(e.target.value))} className="w-full accent-[rgb(var(--signal))]" />
            </div>
          </div>
          <aside className="scroll-thin hidden min-h-0 overflow-y-auto rounded-xl bg-sunk/50 p-3 xl:block">
            <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-ink-3">At this moment</p>
            <dl className="mt-2 space-y-1 text-[12.5px]">
              {(['both', 'lag', 'stale'] as State[]).map((k) => (
                <div key={k} className="flex items-center justify-between gap-2">
                  <dt className="flex items-center gap-1.5 text-ink-2"><i className={`h-1.5 w-1.5 rounded-full ${STATE[k].dot}`} />{STATE[k].label}</dt>
                  <dd className="num font-semibold">{counts[k]}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-3 border-t border-line/10 pt-3">
              {diffs.length === 0
                ? <p className="text-[12.5px] text-current">Our records match reality at this moment.</p>
                : diffs.map((r) => (
                  <div key={r.fact_id} className="mt-1.5 rounded-lg bg-surface px-2.5 py-1.5 text-[12.5px] hairline">
                    <p><span className="text-ink-3">{predicateLabel(r.predicate)}</span> <span className="font-medium">{titleCase(r.value)}</span></p>
                    <p className={`text-[11px] ${STATE[state(r)].tone}`}>
                      {state(r) === 'lag' ? `true since ${when(r.valid_from)}, on file from ${when(r.recorded_at)}` : `stopped being true ${when(r.valid_to ?? null)}, still on file`}
                    </p>
                  </div>
                ))}
            </div>
          </aside>
        </div>
      )}
    </section>
  )
}
