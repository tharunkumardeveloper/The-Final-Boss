import { BOT } from '../lib/brand'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ConsoleNav } from '../components/console/ConsoleNav'
import { api } from '../lib/api'
import { titleCase, when } from '../lib/format'
import { useRelayStream } from '../lib/stream'
import { useTenant } from '../lib/tenant'
import type { Crossing, Expert, RelayEvent, Sharing } from '../lib/types'
import { HandoffReplay } from '../components/console/HandoffReplay'
import { AnimatePresence, motion } from 'framer-motion'

const AGENTS = ['intake', 'resolver', 'noc']
const NAME: Record<string, string> = { intake: BOT, resolver: 'Resolver', noc: 'Network ops' }
const TONE: Record<string, string> = { intake: '#14A39A', resolver: '#3D6FB6', noc: '#C47F0E' }
const INITIAL: Record<string, string> = { intake: 'F', resolver: 'R', noc: 'N' }
const name = (a: string) => NAME[a] ?? titleCase(a)
const tone = (a: string) => TONE[a] ?? '#7A8799'

// constellation geometry: shared memory in the middle, the agents around it
const W = 760, H = 440, MID = { x: 380, y: 222 }
const AT: Record<string, { x: number; y: number }> = { intake: { x: 128, y: 104 }, resolver: { x: 632, y: 104 }, noc: { x: 380, y: 392 } }

function Avatar({ agent, size = 28 }: { agent: string; size?: number }) {
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white" title={name(agent)}
      style={{ background: tone(agent), width: size, height: size, fontSize: size * 0.42 }}>{INITIAL[agent] ?? agent[0]?.toUpperCase()}</span>
  )
}

/** The team as it really works: nobody messages anybody. Each agent writes into the shared graph and reads from it;
 *  a live CONSULTED edge sends a dot from the writer, through memory, to the reader. */
export function Constellation({ data, pulse, picked, pick }: { data: Sharing; pulse: { from: string; to: string; at: number } | null
  picked?: string; pick: (a: string) => void }) {
  const agents = AGENTS.filter((a) => a !== 'noc' || data.agents.some((x) => x.agent === 'noc'))
  const stats = Object.fromEntries(data.agents.map((a) => [a.agent, a]))
  const out = (a: string) => data.flows.filter((f) => f.from === a).reduce((t, f) => t + f.facts, 0)
  const inn = (a: string) => data.flows.filter((f) => f.to === a).reduce((t, f) => t + f.facts, 0)
  const max = Math.max(1, ...agents.flatMap((a) => [out(a), inn(a)]))
  // two bows between each agent and memory: writes on one side, reads on the other, so both directions stay readable
  const bow = (a: { x: number; y: number }, b: { x: number; y: number }, side: number) => {
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1
    return `M${a.x} ${a.y} Q${mx - (dy / len) * 34 * side} ${my + (dx / len) * 34 * side} ${b.x} ${b.y}`
  }
  const write = (a: string) => bow(AT[a], MID, 1), read = (a: string) => bow(MID, AT[a], 1)
  const ring = (pct: number, r: number) => { const c = 2 * Math.PI * r; return { strokeDasharray: `${(c * pct) / 100} ${c}` } }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Agents sharing knowledge through one graph">
      <defs>
        <radialGradient id="mem-glow"><stop offset="0%" stopColor="rgb(var(--signal))" stopOpacity="0.28" /><stop offset="100%" stopColor="rgb(var(--signal))" stopOpacity="0" /></radialGradient>
        <marker id="tip-w" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#3E8E5E" /></marker>
        <marker id="tip-r" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#2F8FC9" /></marker>
      </defs>
      {agents.map((a) => {
        const dim = picked && picked !== a
        return (
          <g key={`e-${a}`} opacity={dim ? 0.25 : 1} className="transition-opacity duration-500">
            <path d={write(a)} fill="none" stroke="#3E8E5E" strokeOpacity="0.75" strokeWidth={1.5 + (7 * out(a)) / max} strokeLinecap="round" markerEnd="url(#tip-w)" />
            <path d={read(a)} fill="none" stroke="#2F8FC9" strokeOpacity="0.75" strokeWidth={1.5 + (7 * inn(a)) / max} strokeLinecap="round" strokeDasharray="1 7" className="lab-flow-slow" markerEnd="url(#tip-r)" />
          </g>
        )
      })}
      {/* shared memory */}
      <circle cx={MID.x} cy={MID.y} r="96" fill="url(#mem-glow)" />
      <g>
        <ellipse cx={MID.x} cy={MID.y - 30} rx="58" ry="14" fill="rgb(var(--ink))" />
        <path d={`M${MID.x - 58} ${MID.y - 30}v60a58 14 0 0 0 116 0v-60`} fill="rgb(var(--ink))" />
        <ellipse cx={MID.x} cy={MID.y - 30} rx="58" ry="14" fill="none" stroke="rgb(var(--signal))" strokeOpacity="0.6" />
        <path d={`M${MID.x - 58} ${MID.y}a58 14 0 0 0 116 0`} fill="none" stroke="rgb(255 255 255 / 0.15)" />
        <text x={MID.x} y={MID.y + 4} textAnchor="middle" className="fill-white text-[13px] font-semibold">Shared memory</text>
        <text x={MID.x} y={MID.y + 21} textAnchor="middle" className="fill-white/60 font-mono text-[10px]">FalkorDB · one graph</text>
      </g>
      {/* live: a fact written by one agent, read by another */}
      {pulse && AT[pulse.from] && AT[pulse.to] && (
        <g key={pulse.at} pointerEvents="none">
          <circle r="6" fill="#3E8E5E"><animateMotion dur="0.8s" path={write(pulse.from)} fill="freeze" /><animate attributeName="opacity" values="1;1;0" dur="0.85s" fill="freeze" /></circle>
          <circle r="6" fill="#2F8FC9" opacity="0"><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.05;0.9;1" begin="0.8s" dur="0.9s" fill="freeze" />
            <animateMotion dur="0.9s" begin="0.8s" path={read(pulse.to)} fill="freeze" /></circle>
          <circle cx={AT[pulse.to].x} cy={AT[pulse.to].y} r="44" fill="none" stroke="#2F8FC9" strokeWidth="3" opacity="0">
            <animate attributeName="opacity" values="0;0.9;0" begin="1.65s" dur="0.8s" fill="freeze" />
            <animate attributeName="r" values="44;64" begin="1.65s" dur="0.8s" fill="freeze" /></circle>
        </g>
      )}
      {agents.map((a) => {
        const s = stats[a], p = AT[a], on = picked === a
        return (
          <g key={a} role="button" tabIndex={0} aria-pressed={on} aria-label={`${name(a)}: wrote ${s?.wrote ?? 0}, used ${s?.consulted ?? 0}`}
            className="cursor-pointer outline-none" onClick={() => pick(a)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') pick(a) }}
            opacity={picked && !on ? 0.45 : 1}>
            <circle cx={p.x} cy={p.y} r="50" fill="rgb(var(--surface))" stroke={on ? tone(a) : 'rgb(var(--line) / 0.12)'} strokeWidth={on ? 3 : 1.5} />
            <circle cx={p.x} cy={p.y} r="42" fill="none" stroke="rgb(var(--line) / 0.08)" strokeWidth="6" />
            <circle cx={p.x} cy={p.y} r="42" fill="none" stroke={tone(a)} strokeWidth="6" strokeLinecap="round" transform={`rotate(-90 ${p.x} ${p.y})`}
              style={{ ...ring(s?.reuse_pct ?? 0, 42), transition: 'stroke-dasharray 0.8s cubic-bezier(0.22,1,0.36,1)' }}>
              <title>{`${s?.reuse_pct ?? 0}% of what ${name(a)} used was written by another agent`}</title>
            </circle>
            <circle cx={p.x} cy={p.y} r="26" fill={tone(a)} />
            <text x={p.x} y={p.y + 6} textAnchor="middle" className="fill-white text-[17px] font-semibold">{INITIAL[a]}</text>
            <text x={p.x} y={p.y + (a === 'noc' ? -62 : 70)} textAnchor="middle" className="fill-ink text-[13px] font-semibold">{name(a)}</text>
            <text x={p.x} y={p.y + (a === 'noc' ? -47 : 85)} textAnchor="middle" className="fill-ink-3 text-[10.5px] num">
              wrote {s?.wrote ?? 0} · used {s?.consulted ?? 0} · {s?.reuse_pct ?? 0}% from others · trust {s?.trust ?? '–'}</text>
          </g>
        )
      })}
    </svg>
  )
}

/** One crossing, drawn: writer -> the fact -> reader. A fresh one runs a dot along it. */
export function CrossingCard({ r, fresh }: { r: Crossing; fresh: boolean }) {
  return (
    <motion.li layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      className={`rounded-2xl p-3 transition-colors duration-700 ${fresh ? 'bg-signal-tint ring-1 ring-signal/40' : 'bg-surface hairline'}`}>
      <div className="flex items-center gap-2">
        <Avatar agent={r.writer} size={26} />
        <svg viewBox="0 0 100 10" className="h-3 min-w-0 flex-1" preserveAspectRatio="none" aria-hidden="true">
          <line x1="2" y1="5" x2="96" y2="5" stroke="rgb(var(--line) / 0.25)" strokeWidth="1.5" strokeDasharray="3 3" />
          <path d="M92 1.5 98 5 92 8.5" fill="none" stroke="rgb(var(--line) / 0.4)" strokeWidth="1.5" />
          {fresh && <circle r="3" cy="5" fill="#2F8FC9"><animate attributeName="cx" values="2;96" dur="1.2s" repeatCount="2" /></circle>}
        </svg>
        <Avatar agent={r.reader} size={26} />
        <span className="chip bg-sunk text-[10.5px] text-ink-2 num" title="times the reader used this fact">{r.uses}×</span>
      </div>
      <p className="mt-2 text-[13px] leading-snug text-ink">{r.sentence}</p>
      <p className="mt-1 text-[10.5px] text-ink-3">{name(r.writer)} wrote it · {name(r.reader)} used it{r.last ? ` · ${when(r.last)}` : ''}</p>
    </motion.li>
  )
}

/** "Who on the team has worked on this before?": a traversal technician -> tickets -> issue / router / fix. */
function Experts({ tenant }: { tenant: string }) {
  const [topic, setTopic] = useState('router reboots')
  const [rows, setRows] = useState<Expert[]>()
  const [busy, setBusy] = useState(false)
  const search = async (e?: FormEvent) => {
    e?.preventDefault(); setBusy(true)
    try { setRows(await api.experts(tenant, topic)) } catch { setRows([]) } finally { setBusy(false) }
  }
  useEffect(() => { search() }, [tenant])  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section>
      <h2 className="sr-only">Who has worked on this before?</h2>
      <p className="mt-1 text-xs text-ink-3">A walk through the graph: technician → tickets they worked → the issue, router or fix those tickets were about.</p>
      <form onSubmit={search} className="mt-4 flex gap-2">
        <label htmlFor="expert-topic" className="sr-only">Topic</label>
        <input id="expert-topic" className="field flex-1" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. Hub 6 Pro reboots" />
        <button className="btn-primary text-sm" disabled={busy}>{busy ? 'Walking…' : 'Find'}</button>
      </form>
      {rows && (
        <ul className="mt-3 grid gap-2">
          {rows.map((r, i) => {
            const pct = r.tickets ? (100 * r.resolved) / r.tickets : 0, c = 2 * Math.PI * 20
            return (
              <motion.li key={r.technician} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                className="flex gap-3 rounded-2xl bg-paper/70 p-3 hairline">
                <svg viewBox="0 0 52 52" className="h-14 w-14 shrink-0" role="img" aria-label={`${r.resolved} of ${r.tickets} resolved`}>
                  <circle cx="26" cy="26" r="20" fill="none" stroke="rgb(var(--line) / 0.1)" strokeWidth="5" />
                  <circle cx="26" cy="26" r="20" fill="none" stroke="rgb(var(--current))" strokeWidth="5" strokeLinecap="round" transform="rotate(-90 26 26)"
                    strokeDasharray={`${(c * pct) / 100} ${c}`} />
                  <text x="26" y="30" textAnchor="middle" className="fill-ink text-[12px] font-semibold num">{r.resolved}/{r.tickets}</text>
                </svg>
                <div className="min-w-0">
                  <p className="font-semibold">{titleCase(r.technician)} <span className="font-normal text-ink-3">· {titleCase(r.city)}</span></p>
                  <p className="mt-1 flex flex-wrap items-center gap-1 text-[10.5px]">
                    <span className="chip bg-ink text-paper">technician</span>
                    <span className="text-ink-3">→</span><span className="chip bg-sunk text-ink-2 num">{r.tickets} ticket{r.tickets === 1 ? '' : 's'}</span>
                    {r.via.map((v) => <span key={v} className="contents"><span className="text-ink-3">→</span><span className="chip bg-signal-tint text-signal-deep">{v}</span></span>)}
                  </p>
                  {r.last_at && <p className="mt-1 text-[10.5px] text-ink-3">last on it {when(r.last_at)}</p>}
                </div>
              </motion.li>
            )
          })}
          {rows.length === 0 && <li className="rounded-2xl bg-sunk/50 p-4 text-sm text-ink-3">Nobody has worked on that yet.</li>}
        </ul>
      )}
    </section>
  )
}

export default function SharingPage() {
  const { tenant } = useTenant()
  const [data, setData] = useState<Sharing>()
  const [error, setError] = useState(false)
  const [pulse, setPulse] = useState<{ from: string; to: string; at: number } | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const [picked, setPicked] = useState<{ reader?: string; writer?: string }>({})
  const [feed, setFeed] = useState<Crossing[]>([])
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string>()
  const seen = useRef<Set<string>>(new Set())
  const loadFeed = useCallback(() => api.crossings(tenant, picked.reader, picked.writer).then((rows) => {
    const key = (r: Crossing) => `${r.reader}:${r.fact_id}:${r.uses}`
    const newOnes = new Set(rows.map(key).filter((k) => seen.current.size && !seen.current.has(k)))
    rows.forEach((r) => seen.current.add(key(r)))
    setFeed(rows); setFresh(newOnes)
  }).catch(() => {}), [tenant, picked])
  const load = useCallback(() => {
    loadFeed()
    return api.sharing(tenant).then((d) => { setData(d); setError(false) }).catch(() => setError(true))
  }, [tenant, loadFeed])
  useEffect(() => { load() }, [load])
  const pickAgent = (a: string) => setPicked((p) => (p.reader === a && !p.writer ? {} : { reader: a }))
  const pickFlow = (from: string, to: string) => setPicked((p) => (p.writer === from && p.reader === to ? {} : { writer: from, reader: to }))
  const handoff = async () => {
    setBusy(true); setNote(undefined)
    try {
      const r = await api.labInject(tenant, { preset: 'random', complain: true })
      setNote(`${titleCase(r.customer)} is telling ${BOT} about a problem. Watch the dots: the resolver will use what ${BOT} writes down.`)
    } catch { setNote("Couldn't start one. Does the Network screen have customers with a line?") } finally { setBusy(false) }
  }
  const listeners = useRef(new Set<(e: RelayEvent) => void>())
  const subscribe = useCallback((fn: (e: RelayEvent) => void) => { listeners.current.add(fn); return () => { listeners.current.delete(fn) } }, [])
  const status = useRelayStream(tenant, (e) => {
    listeners.current.forEach((fn) => fn(e))
    if (e.type !== 'consulted') return
    const from = Object.keys(e.data.writers).find((w) => w !== e.data.agent)
    if (from) setPulse({ from, to: e.data.agent, at: Date.now() })
    clearTimeout(timer.current)
    timer.current = setTimeout(load, 500)
  }, load)

  const total = data?.flows.reduce((t, f) => t + f.facts, 0) ?? 0
  const filterLabel = picked.writer ? `${name(picked.writer)} → ${name(picked.reader!)}` : picked.reader ? `used by ${name(picked.reader)}` : null
  const [tab, setTab] = useState<'crossings' | 'experts'>('crossings')

  // One screen on a desktop: the team and the replay on the left, the record on the right; each part scrolls inside.
  return (
    <div className="flex min-h-[100dvh] flex-col xl:h-[100dvh]">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link to="/console"><Wordmark sub="Agent team" /></Link>
        <ConsoleNav />
      </header>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pb-3 sm:px-6">
        <h1 className="font-display text-xl font-semibold tracking-[-0.01em]" title="Each agent writes what it learns into the graph and reads what the others wrote; every use is a CONSULTED edge.">
          Three agents. No messages. One memory.</h1>
        <span className="chip bg-ink text-paper num">{total} facts crossed between agents</span>
        <span className={`chip ${status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict'}`}>
          <i className={`h-1.5 w-1.5 rounded-full ${status === 'live' ? 'bg-current animate-breathe' : 'bg-conflict'}`} />{status === 'live' ? 'Live' : 'Reconnecting'} · mem:{tenant}</span>
        <button className="btn-primary ml-auto !py-1.5 text-sm" disabled={busy} onClick={handoff}>{busy ? 'Starting…' : 'Show me a handoff'}</button>
      </div>
      {(note || error) && (
        <p className={`mx-4 mb-3 rounded-xl px-4 py-2 text-sm sm:mx-6 ${error ? 'bg-danger-tint text-danger' : 'bg-signal-tint text-signal-deep'}`} role="status">
          {error ? "Couldn't load sharing data. Is the API running?" : note}</p>
      )}

      <main className="grid min-h-0 flex-1 gap-4 px-4 pb-4 sm:px-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-h-0 flex-col gap-4">
          {data && (
            <section className="flex shrink-0 flex-col gap-2 rounded-[1.75rem] bg-surface p-3 hairline md:flex-row md:items-center" aria-label="The agent team">
              <div className="min-w-0 md:w-[58%] xl:max-h-[38vh] [&>svg]:max-h-[38vh]">
                <Constellation data={data} pulse={pulse} picked={picked.writer ? undefined : picked.reader} pick={pickAgent} />
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <p className="eyebrow">Who used whose facts · click to filter</p>
                <ul className="space-y-1">
                  {data.flows.map((f) => {
                    const on = picked.writer === f.from && picked.reader === f.to
                    return (
                      <li key={`${f.from}>${f.to}`}>
                        <button onClick={() => pickFlow(f.from, f.to)} aria-pressed={on}
                          className={`flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition ${on ? 'bg-ink text-paper' : 'hover:bg-sunk'}`}>
                          <Avatar agent={f.from} size={20} /><span className="text-ink-3">→</span><Avatar agent={f.to} size={20} />
                          <span className="min-w-0 flex-1 truncate">{name(f.from)} → {name(f.to)}</span>
                          <span className="font-semibold num">{f.facts}</span>
                        </button>
                      </li>
                    )
                  })}
                  {data.flows.length === 0 && <li className="text-xs text-ink-3">Nothing has crossed yet. Press “Show me a handoff”.</li>}
                </ul>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[10.5px] text-ink-3">
                  <span className="flex items-center gap-1.5"><i className="h-1 w-4 rounded bg-[#3E8E5E]" />writes a fact</span>
                  <span className="flex items-center gap-1.5"><i className="h-1 w-4 border-t-2 border-dotted border-[#2F8FC9]" />reads another agent's fact</span>
                  <span>ring: share it used from others</span>
                </div>
              </div>
            </section>
          )}
          <div className="flex min-h-[460px] flex-1 flex-col xl:min-h-0"><HandoffReplay tenant={tenant} subscribe={subscribe} /></div>
        </div>

        <aside className="flex min-h-[520px] flex-col rounded-[1.75rem] bg-surface p-4 hairline xl:min-h-0">
          <div className="flex shrink-0 items-center justify-between gap-2">
            <div role="tablist" aria-label="Record" className="inline-flex rounded-full bg-sunk/70 p-0.5">
              {([['crossings', 'Knowledge crossings'], ['experts', 'Who has worked on this?']] as const).map(([k, label]) => (
                <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                  className={`rounded-full px-3 py-1 text-[11.5px] ${tab === k ? 'bg-ink font-medium text-paper' : 'text-ink-2'}`}>{label}</button>
              ))}
            </div>
            {tab === 'crossings' && filterLabel && <button className="chip bg-ink text-paper" onClick={() => setPicked({})}>{filterLabel} ✕</button>}
          </div>
          <div className="scroll-thin mt-3 min-h-0 flex-1 overflow-y-auto pr-1" role="tabpanel">
            {tab === 'crossings' ? (
              <>
                <p className="mb-2 text-[11px] text-ink-3">Every fact one agent wrote and another used, newest first. New ones light up live.</p>
                <ul className="grid gap-2">
                  <AnimatePresence initial={false}>
                    {feed.map((r) => <CrossingCard key={`${r.reader}:${r.fact_id}`} r={r} fresh={fresh.has(`${r.reader}:${r.fact_id}:${r.uses}`)} />)}
                  </AnimatePresence>
                  {feed.length === 0 && <li className="rounded-2xl bg-sunk/50 p-4 text-sm text-ink-3">Nothing here yet. Press “Show me a handoff”.</li>}
                </ul>
              </>
            ) : <Experts tenant={tenant} />}
          </div>
        </aside>
      </main>
    </div>
  )
}
