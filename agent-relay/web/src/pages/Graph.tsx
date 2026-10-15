import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, Rewind } from '../components/Icons'
import { predicateLabel, when } from '../lib/format'
import { emptyGraph, type GraphState } from '../lib/graph'

// Replay of the memory graph: how it was built, fact by fact. Used by the Memory screen (/console?mode=replay)
// and the portal's own graph (components/portal/MyGraph imports at/syncTo/Edge from here).

export type Edge = GraphState['edges'] extends Map<string, infer E> ? E & { at?: number | null; until?: number | null } : never
export const at = (e: Edge) => e.at ?? e.born ?? Date.now()
const SPEEDS = [1, 2, 4] as const
const sid = (v: unknown) => (typeof v === 'string' ? v : (v as { id: string }).id)
const trueAt = (e: Edge, t: number) => (e.until ? e.until > t : e.active || (e.faded ? e.faded > t : true))

/** Copy the part of the live graph that existed at time t into `out` (mutated in place so the layout stays put). */
export function syncTo(out: GraphState, live: GraphState, t: number) {
  const want = new Map<string, Edge>()
  for (const e of live.edges.values() as Iterable<Edge>) {
    if (at(e) > t) continue
    want.set(e.id, { ...e, active: trueAt(e, t) })
  }
  const ends = new Set<string>()
  for (const e of want.values()) for (const v of [e.source, e.target]) ends.add(sid(v))
  for (const id of [...out.edges.keys()]) if (!want.has(id)) out.edges.delete(id)
  for (const [id, e] of want) {
    const cur = out.edges.get(id) as Edge | undefined
    if (cur) { cur.active = e.active; continue }
    out.edges.set(id, { ...e, source: sid(e.source), target: sid(e.target), born: Date.now() })
  }
  for (const id of [...out.nodes.keys()]) if (!ends.has(id)) out.nodes.delete(id)
  for (const id of ends) if (!out.nodes.has(id)) { const n = live.nodes.get(id); if (n) out.nodes.set(id, { ...n, born: Date.now() }) }
  out.version++
}

/** Replay state over the live store. `on` comes from the URL; `scrubFromLive` jumps straight to a moment. */
export function useReplay(store: GraphState, version: number, on: boolean, turnOn: () => void) {
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1)
  const replay = useRef(emptyGraph())
  const [rv, setRv] = useState(0)
  const pending = useRef<number | null>(null)

  const edges = useMemo(() => [...store.edges.values()] as Edge[], [store, version])
  const span = useMemo(() => {
    const ts = edges.map(at)
    return ts.length ? { from: Math.min(...ts), to: Math.max(Date.now(), ...ts) } : { from: Date.now() - 1, to: Date.now() }
  }, [edges])
  const show = useCallback((time: number) => { syncTo(replay.current, store, time); setRv((v) => v + 1) }, [store])

  // entering replay (button, slider or a ?mode=replay link): start from the beginning, or from where the slider was dropped
  const ready = edges.length > 0
  useEffect(() => {
    if (!on) { setPlaying(false); return }
    if (!ready) return
    replay.current = emptyGraph()
    const from = pending.current ?? span.from
    setT(from); show(from); setPlaying(pending.current === null)
    pending.current = null
  }, [on, ready])  // eslint-disable-line react-hooks/exhaustive-deps

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

  const scrub = (v: number) => {
    if (!on) { pending.current = v; turnOn(); return }
    setPlaying(false); setT(v); show(v)
  }
  const toggle = () => { if (t >= span.to) { replay.current = emptyGraph(); setT(span.from); show(span.from) } setPlaying((p) => !p) }

  const visible = on ? edges.filter((e) => at(e) <= t) : edges
  const current = visible.filter((e) => (on ? trueAt(e, t) : e.active))
  return { t, playing, toggle, speed, setSpeed, span, edges, visible, current, scrub, graph: replay.current, rv }
}
export type Replay = ReturnType<typeof useReplay>

/** The time scrubber under the graph: Live / Replay, play, speed, and what is true at the moment shown. */
export function TimeBar({ r, on, setOn }: { r: Replay; on: boolean; setOn: (on: boolean) => void }) {
  const things = new Set(r.visible.flatMap((e) => [sid(e.source), sid(e.target)])).size
  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div role="radiogroup" aria-label="Graph mode" className="flex rounded-full bg-sunk p-0.5 text-xs">
          {([[false, 'Live'], [true, 'Replay']] as const).map(([m, label]) => (
            <button key={label} role="radio" aria-checked={on === m} onClick={() => setOn(m)} disabled={m && !r.edges.length}
              className={`rounded-full px-3 py-1 transition duration-300 ease-spring ${on === m ? 'bg-surface font-medium text-ink shadow-soft' : 'text-ink-3 hover:text-ink'}`}>{label}</button>
          ))}
        </div>
        {on ? (
          <>
            <button className="btn h-8 w-8 !p-0 bg-ink text-paper hover:bg-ink/90" aria-label={r.playing ? 'Pause' : 'Play'} onClick={r.toggle}>
              {r.playing ? <Pause /> : <Play />}
            </button>
            <div className="flex rounded-full bg-sunk p-0.5 text-[11px]" role="radiogroup" aria-label="Replay speed">
              {SPEEDS.map((s) => <button key={s} role="radio" aria-checked={r.speed === s} onClick={() => r.setSpeed(s)}
                className={`rounded-full px-2 py-0.5 ${r.speed === s ? 'bg-surface font-medium text-ink shadow-soft' : 'text-ink-3'}`}>{s}×</button>)}
            </div>
          </>
        ) : (
          <button className="btn-ghost !py-1 text-xs" onClick={() => setOn(true)} disabled={!r.edges.length}><Rewind className="h-4 w-4" />Replay how it was built</button>
        )}
        <dl className="flex items-baseline gap-3 text-[11px] text-ink-3 num">
          <div className="flex items-baseline gap-1"><dd className="font-semibold text-ink">{r.current.length}</dd><dt>facts true</dt></div>
          <div className="flex items-baseline gap-1"><dd className="font-semibold text-ink">{r.visible.length - r.current.length}</dd><dt>no longer true</dt></div>
          <div className="flex items-baseline gap-1"><dd className="font-semibold text-ink">{things}</dd><dt>things known</dt></div>
        </dl>
        <span className="num ml-auto text-xs text-ink-2">{on ? when(new Date(r.t).toISOString()) : 'now'}</span>
      </div>
      <label htmlFor="when" className="sr-only">Replay time</label>
      <input id="when" type="range" min={r.span.from} max={r.span.to} step={Math.max(1, (r.span.to - r.span.from) / 1000)}
        value={on ? r.t : r.span.to} className="mt-2 w-full accent-[rgb(var(--signal))]" disabled={!r.edges.length}
        onChange={(e) => r.scrub(Number(e.target.value))} />
    </div>
  )
}

/** Replay's side list: the facts known at the moment shown, newest first. */
export function KnownList({ r, label, onSelect }: { r: Replay; label: (id: string) => string; onSelect: (id: string) => void }) {
  const latest = [...r.visible].sort((a, b) => at(b) - at(a)).slice(0, 30)
  return (
    <section className="flex h-full min-h-0 flex-col p-4" aria-label="Known at this moment">
      <p className="eyebrow">Known at this moment</p>
      <ul className="scroll-thin mt-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
        <AnimatePresence initial={false}>
          {latest.map((e) => (
            <motion.li key={e.id} layout initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}
              className={`rounded-xl px-3 py-2 text-sm ${trueAt(e, r.t) ? 'bg-paper/80' : 'bg-sunk/50 text-ink-3 line-through decoration-ink-3/40'}`}>
              <button className="text-left" onClick={() => onSelect(sid(e.source))}>
                <span className="font-medium">{label(sid(e.source))}</span> {predicateLabel(e.label).toLowerCase()} <span className="font-medium">{label(sid(e.target))}</span>
              </button>
              <p className="num text-[10.5px] text-ink-3">{when(new Date(at(e)).toISOString())}</p>
            </motion.li>
          ))}
        </AnimatePresence>
        {!latest.length && <li className="text-sm text-ink-3">Nothing known yet at this moment. Press play.</li>}
      </ul>
    </section>
  )
}
