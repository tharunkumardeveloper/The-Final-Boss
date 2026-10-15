import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Pause, Play, Rewind } from '../components/Icons'
import { Inspector } from '../components/console/Inspector'
import { KIND_COLOR, MemoryGraph } from '../components/console/MemoryGraph'
import { useConsole } from '../components/console/useConsole'
import { predicateLabel, when } from '../lib/format'
import { emptyGraph, type GraphState } from '../lib/graph'
import { useTenant } from '../lib/tenant'

export type Edge = GraphState['edges'] extends Map<string, infer E> ? E & { at?: number | null; until?: number | null } : never
export const at = (e: Edge) => e.at ?? e.born ?? Date.now()
const SPEEDS = [1, 2, 4] as const

/** Copy the part of the live graph that existed at time t into `out` (mutated in place so the layout stays put). */
export function syncTo(out: GraphState, live: GraphState, t: number) {
  const want = new Map<string, Edge>()
  for (const e of live.edges.values() as Iterable<Edge>) {
    if (at(e) > t) continue
    const active = e.until ? e.until > t : e.active || (e.faded ? e.faded > t : true)
    want.set(e.id, { ...e, active })
  }
  const ends = new Set<string>()
  for (const e of want.values()) for (const v of [e.source, e.target]) ends.add(typeof v === 'string' ? v : (v as { id: string }).id)
  for (const id of [...out.edges.keys()]) if (!want.has(id)) out.edges.delete(id)
  for (const [id, e] of want) {
    const cur = out.edges.get(id) as Edge | undefined
    if (cur) { cur.active = e.active; continue }
    out.edges.set(id, { ...e, source: typeof e.source === 'string' ? e.source : (e.source as { id: string }).id,
      target: typeof e.target === 'string' ? e.target : (e.target as { id: string }).id, born: Date.now() })
  }
  for (const id of [...out.nodes.keys()]) if (!ends.has(id)) out.nodes.delete(id)
  for (const id of ends) if (!out.nodes.has(id)) { const n = live.nodes.get(id); if (n) out.nodes.set(id, { ...n, born: Date.now() }) }
  out.version++
}

export default function GraphPage() {
  const { tenant } = useTenant()
  const c = useConsole(tenant)
  const [mode, setMode] = useState<'live' | 'replay'>('live')
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1)
  const [selected, setSelected] = useState<string | null>(null)
  const replay = useRef(emptyGraph())
  const [rv, setRv] = useState(0)

  const edges = useMemo(() => [...c.store.edges.values()] as Edge[], [c.store, c.version])
  const span = useMemo(() => {
    const ts = edges.map(at)
    return ts.length ? { from: Math.min(...ts), to: Math.max(Date.now(), ...ts) } : { from: Date.now() - 1, to: Date.now() }
  }, [edges])

  const show = useCallback((time: number) => { syncTo(replay.current, c.store, time); setRv((v) => v + 1) }, [c.store])
  const startReplay = () => { replay.current = emptyGraph(); setMode('replay'); setT(span.from); show(span.from); setPlaying(true) }
  const goLive = () => { setPlaying(false); setMode('live') }

  // play: the whole history in about 20 seconds at 1x
  useEffect(() => {
    if (!playing) return
    const step = (span.to - span.from) / 250 * speed
    const id = setInterval(() => setT((cur) => {
      const next = Math.min(span.to, cur + step)
      show(next)
      if (next >= span.to) setPlaying(false)
      return next
    }), 80)
    return () => clearInterval(id)
  }, [playing, speed, span, show])

  const now = mode === 'live' ? Date.now() : t
  const visible = mode === 'live' ? edges : edges.filter((e) => at(e) <= t)
  const current = visible.filter((e) => (mode === 'live' ? e.active : e.until ? e.until > t : e.active || (e.faded ? e.faded > t : true)))
  const nodeLabel = (id: string) => (mode === 'live' ? c.store : replay.current).nodes.get(id)?.label ?? id.replace(/^e:/, '')
  const sid = (v: unknown) => (typeof v === 'string' ? v : (v as { id: string }).id)
  const latest = [...visible].sort((a, b) => at(b) - at(a)).slice(0, 12)
  const kinds = useMemo(() => [...new Set([...c.store.nodes.values()].map((n) => n.kind))].filter((k) => KIND_COLOR[k]), [c.store, c.version])

  return (
    <div className="flex h-[100dvh] flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4">
          <Link to="/console"><Wordmark sub="Memory graph" /></Link>
          <span className={`chip ${mode === 'live' ? (c.status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict') : 'bg-signal-tint text-signal-deep'}`}>
            {mode === 'live' && <i className="h-1.5 w-1.5 rounded-full bg-current animate-breathe" />}{mode === 'live' ? 'Live' : 'Replay'} · mem:{tenant}</span>
        </div>
        <dl className="flex items-center gap-5 text-xs num">
          <div className="flex items-baseline"><dd className="font-display text-lg font-semibold">{current.length}</dd><dt className="ml-1.5 text-ink-3">facts true</dt></div>
          <div className="flex items-baseline"><dd className="font-display text-lg font-semibold">{visible.length - current.length}</dd><dt className="ml-1.5 text-ink-3">no longer true</dt></div>
          <div className="flex items-baseline"><dd className="font-display text-lg font-semibold">{new Set(visible.flatMap((e) => [sid(e.source), sid(e.target)])).size}</dd><dt className="ml-1.5 text-ink-3">things known</dt></div>
        </dl>
        <div className="flex items-center gap-2">
          <Link to="/" className="btn-ghost !py-1.5 text-xs">Customer chat</Link>
          <Link to="/console/lab" className="btn-ghost !py-1.5 text-xs">Network console</Link>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 px-4 pb-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="relative min-h-[420px] overflow-hidden rounded-[1.75rem] bg-surface shadow-lift hairline">
          <div className="absolute inset-0">
            <MemoryGraph store={mode === 'live' ? c.store : replay.current} version={mode === 'live' ? c.version : rv} selected={selected} onSelect={setSelected} />
          </div>
          <div className="pointer-events-none absolute left-4 top-4 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-3">
            {kinds.map((k) => <span key={k} className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: KIND_COLOR[k] }} />{k}</span>)}
          </div>
          {/* time bar */}
          <div className="absolute inset-x-4 bottom-4 rounded-2xl bg-surface/90 p-3 shadow-soft backdrop-blur hairline">
            <div className="flex flex-wrap items-center gap-3">
              {mode === 'live' ? (
                <button className="btn-primary !py-1.5 text-xs" onClick={startReplay} disabled={!edges.length}><Rewind className="h-4 w-4" />Replay how it was built</button>
              ) : (
                <>
                  <button className="btn h-8 w-8 !p-0 bg-ink text-paper hover:bg-ink/90" aria-label={playing ? 'Pause' : 'Play'}
                    onClick={() => { if (t >= span.to) { replay.current = emptyGraph(); setT(span.from); show(span.from) } setPlaying((p) => !p) }}>
                    {playing ? <Pause /> : <Play />}
                  </button>
                  <div className="flex rounded-full bg-sunk p-0.5 text-[11px]">
                    {SPEEDS.map((s) => <button key={s} onClick={() => setSpeed(s)} className={`rounded-full px-2 py-0.5 ${speed === s ? 'bg-surface font-medium text-ink shadow-soft' : 'text-ink-3'}`}>{s}×</button>)}
                  </div>
                  <button className="btn-ghost !py-1.5 text-xs" onClick={goLive}>Back to live</button>
                </>
              )}
              <span className="num ml-auto text-xs text-ink-2">{when(new Date(now).toISOString())}</span>
            </div>
            <label htmlFor="when" className="sr-only">Time</label>
            <input id="when" type="range" min={span.from} max={span.to} step={Math.max(1, (span.to - span.from) / 1000)}
              value={mode === 'live' ? span.to : t} className="mt-2 w-full accent-[rgb(var(--signal))]"
              onChange={(e) => {
                const v = Number(e.target.value)
                if (mode === 'live') { replay.current = emptyGraph(); setMode('replay') }
                setPlaying(false); setT(v); show(v)
              }} />
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-4">
          <section className="flex min-h-0 flex-1 flex-col rounded-[1.75rem] bg-surface p-5 hairline">
            <p className="eyebrow">{mode === 'live' ? 'Just learned' : 'Known at this moment'}</p>
            <ul className="scroll-thin mt-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
              <AnimatePresence initial={false}>
                {latest.map((e) => (
                  <motion.li key={e.id} layout initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}
                    className={`rounded-xl px-3 py-2 text-sm ${e.active ? 'bg-paper/80' : 'bg-sunk/50 text-ink-3 line-through decoration-ink-3/40'}`}>
                    <button className="text-left" onClick={() => setSelected(sid(e.source))}>
                      <span className="font-medium">{nodeLabel(sid(e.source))}</span> {predicateLabel(e.label).toLowerCase()} <span className="font-medium">{nodeLabel(sid(e.target))}</span>
                    </button>
                    <p className="num text-[10.5px] text-ink-3">{when(new Date(at(e)).toISOString())}</p>
                  </motion.li>
                ))}
              </AnimatePresence>
              {!latest.length && <li className="text-sm text-ink-3">Nothing yet. Chat as a customer and watch facts land here.</li>}
            </ul>
          </section>
          {selected && (
            <section className="max-h-[45%] min-h-0 overflow-y-auto rounded-[1.75rem] bg-surface hairline scroll-thin">
              <Inspector tenant={tenant} id={selected} version={c.version} />
            </section>
          )}
        </aside>
      </main>
    </div>
  )
}
