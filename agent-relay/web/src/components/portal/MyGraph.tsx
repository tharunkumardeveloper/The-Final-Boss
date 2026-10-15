import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { predicateLabel, when } from '../../lib/format'
import { emptyGraph, loadGraph } from '../../lib/graph'
import { at, syncTo, type Edge } from '../../pages/Graph'
import { MemoryGraph } from '../console/MemoryGraph'
import { Pause, Play, Rewind } from '../Icons'
import type { Subscribe } from './SupportChat'

const FACT_EVENTS = new Set(['fact_created', 'fact_corroborated', 'fact_superseded', 'fact_retired', 'ticket_opened', 'ticket_status'])

/** The customer's own memory, as a graph that grows while they chat, with a replay of how it was learned. */
export default function MyGraph({ tenant, who, subscribe }: { tenant: string; who: string | null; subscribe: Subscribe }) {
  const live = useRef(emptyGraph())
  const replay = useRef(emptyGraph())
  const [version, setVersion] = useState(0)
  const [mode, setMode] = useState<'live' | 'replay'>('live')
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()

  const load = useCallback(() => {
    if (!who) { live.current = emptyGraph(); setVersion((v) => v + 1); return }
    api.myGraph(tenant, who).then((g) => {
      live.current = loadGraph(emptyGraph(), g)
      setVersion((v) => v + 1)
    }).catch(() => {})
  }, [tenant, who])
  useEffect(() => { setMode('live'); setPlaying(false); load() }, [load])
  useEffect(() => subscribe((e) => {
    if (FACT_EVENTS.has(e.type)) { clearTimeout(timer.current); timer.current = setTimeout(load, 700) }
  }), [subscribe, load])
  useEffect(() => () => clearTimeout(timer.current), [])

  const edges = useMemo(() => [...live.current.edges.values()] as Edge[], [version])
  const span = useMemo(() => {
    const ts = edges.map(at)
    return ts.length ? { from: Math.min(...ts), to: Math.max(...ts) } : { from: Date.now() - 1, to: Date.now() }
  }, [edges])
  const show = useCallback((time: number) => { syncTo(replay.current, live.current, time); setVersion((v) => v + 1) }, [])

  useEffect(() => {
    if (!playing) return
    const step = Math.max(1, (span.to - span.from) / 160)
    const id = setInterval(() => setT((cur) => {
      const next = Math.min(span.to, cur + step)
      show(next)
      if (next >= span.to) setPlaying(false)
      return next
    }), 90)
    return () => clearInterval(id)
  }, [playing, span, show])

  const start = () => { replay.current = emptyGraph(); setMode('replay'); setT(span.from); show(span.from); setPlaying(true) }
  const sid = (v: unknown) => (typeof v === 'string' ? v : (v as { id: string }).id)
  const label = (id: string) => live.current.nodes.get(id)?.label ?? id.replace(/^e:/, '')
  const shown = mode === 'live' ? edges : edges.filter((e) => at(e) <= t)
  const latest = [...shown].filter((e) => e.active).sort((a, b) => at(b) - at(a)).slice(0, 4)

  return (
    <section className="flex h-full min-h-[560px] flex-col overflow-hidden rounded-[1.75rem] bg-surface shadow-lift hairline" aria-label="Your memory over time">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div>
          <p className="eyebrow">Your memory graph</p>
          <h2 className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">How we know you, over time</h2>
          <p className="mt-1 text-sm text-ink-3">Grows while you chat. Faded lines used to be true.</p>
        </div>
        {mode === 'live' ? (
          <button className="btn-primary !py-1.5 text-xs" onClick={start} disabled={!edges.length}><Rewind className="h-4 w-4" />Replay</button>
        ) : (
          <div className="flex items-center gap-1.5">
            <button className="btn h-8 w-8 !p-0 bg-ink text-paper hover:bg-ink/90" aria-label={playing ? 'Pause' : 'Play'}
              onClick={() => { if (t >= span.to) { replay.current = emptyGraph(); setT(span.from); show(span.from) } setPlaying((p) => !p) }}>
              {playing ? <Pause /> : <Play />}
            </button>
            <button className="btn-ghost !py-1.5 text-xs" onClick={() => { setPlaying(false); setMode('live') }}>Now</button>
          </div>
        )}
      </div>
      <div className="relative mx-4 mt-4 min-h-[300px] flex-1 overflow-hidden rounded-2xl bg-paper/70">
        {edges.length
          ? <MemoryGraph store={mode === 'live' ? live.current : replay.current} version={version} selected={selected} focusId={who ? `e:${who}` : null} onSelect={setSelected} ticker={false} />
          : <p className="px-8 pt-32 text-center text-sm text-ink-3">{who ? 'Nothing yet. Tell us about yourself and watch it fill in.' : 'Say hi in the chat. Everything you tell us lands here, as a graph that grows while you talk.'}</p>}
      </div>
      <div className="px-5 pb-4 pt-3">
        <div className="flex items-baseline justify-between text-[11px] text-ink-3">
          <span className="num">{mode === 'live' ? 'Now' : when(new Date(t).toISOString())}</span>
          <span className="num">{shown.length} things known</span>
        </div>
        <label htmlFor="my-when" className="sr-only">Time</label>
        <input id="my-when" type="range" min={span.from} max={span.to} step={Math.max(1, (span.to - span.from) / 500)}
          value={mode === 'live' ? span.to : t} className="mt-1 w-full accent-[rgb(var(--signal))]" disabled={!edges.length}
          onChange={(e) => { const v = Number(e.target.value); if (mode === 'live') { replay.current = emptyGraph(); setMode('replay') } setPlaying(false); setT(v); show(v) }} />
        {latest.length > 0 && (
          <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
            {latest.map((e) => (
              <li key={e.id} className="truncate rounded-xl bg-paper/70 px-3 py-1.5 text-[12.5px]" title={`${label(sid(e.source))} ${predicateLabel(e.label).toLowerCase()} ${label(sid(e.target))}`}>
                <span className="font-medium">{label(sid(e.source))}</span> {predicateLabel(e.label).toLowerCase()} <span className="font-medium">{label(sid(e.target))}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
