import { BOT } from '../lib/brand'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ConsoleNav } from '../components/console/ConsoleNav'
import { api } from '../lib/api'
import { titleCase } from '../lib/format'
import { useRelayStream } from '../lib/stream'
import { useTenant } from '../lib/tenant'
import type { Crossing, Expert, RelayEvent, Sharing } from '../lib/types'
import { HandoffReplay } from '../components/console/HandoffReplay'
import { when } from '../lib/format'
import { AnimatePresence, motion } from 'framer-motion'

const AGENTS = ['intake', 'resolver', 'noc']
const NAME: Record<string, string> = { intake: `${BOT} · intake`, resolver: 'Resolver', noc: 'Network ops' }
const X: Record<string, number> = { intake: 110, resolver: 360, noc: 610 }

/** Agent-to-agent knowledge flow: an arc from writer to reader, width by facts; pulses when a fact is used live. */
function Flows({ data, pulse, pick, picked }: { data: Sharing; pulse: { from: string; to: string; at: number } | null
  pick: (from: string, to: string) => void; picked: { reader?: string; writer?: string } }) {
  const agents = AGENTS.filter((a) => a !== 'noc' || data.agents.some((x) => x.agent === 'noc'))
  const max = Math.max(1, ...data.flows.map((f) => f.facts))
  const arc = (from: string, to: string) => {
    const a = X[from] ?? 110, b = X[to] ?? 360
    const up = a < b ? -1 : 1 // forward flows bow up, backward flows bow down, so both directions stay readable
    return `M ${a} 130 Q ${(a + b) / 2} ${130 + up * (60 + Math.abs(b - a) / 6)} ${b} 130`
  }
  return (
    <div className="overflow-x-auto">
      <svg viewBox="0 0 720 260" className="w-full min-w-[560px]" role="img" aria-label="Knowledge flowing between agents">
        <defs>
          <marker id="tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-signal-deep" />
          </marker>
        </defs>
        {data.flows.map((f) => {
          const live = pulse && pulse.from === f.from && pulse.to === f.to
          const on = picked.writer === f.from && picked.reader === f.to
          return (
            <g key={`${f.from}>${f.to}`} role="button" tabIndex={0} className="cursor-pointer outline-none" aria-label={`Facts from ${f.from} used by ${f.to}`}
              onClick={() => pick(f.from, f.to)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') pick(f.from, f.to) }}>
              <path d={arc(f.from, f.to)} fill="none" stroke="transparent" strokeWidth={24} />
              <path d={arc(f.from, f.to)} fill="none" className={on ? 'stroke-signal' : 'stroke-signal-deep/70'} strokeWidth={2 + (6 * f.facts) / max} markerEnd="url(#tip)" />
              {live && <path key={pulse!.at} d={arc(f.from, f.to)} fill="none" className="stroke-signal flow-pulse" strokeWidth={4} strokeLinecap="round" />}
              <text x={((X[f.from] ?? 0) + (X[f.to] ?? 0)) / 2} y={(X[f.from] ?? 0) < (X[f.to] ?? 0) ? 72 : 196} textAnchor="middle" className="fill-ink-2 text-[12px] num">
                {f.facts} fact{f.facts === 1 ? '' : 's'}
              </text>
            </g>
          )
        })}
        {agents.map((a) => (
          <g key={a}>
            <circle cx={X[a]} cy={130} r={30} className="fill-paper stroke-ink/20" strokeWidth={1.5} />
            <text x={X[a]} y={135} textAnchor="middle" className="fill-ink text-[13px] font-semibold">{a === 'intake' ? 'K' : a === 'resolver' ? 'R' : 'N'}</text>
            <text x={X[a]} y={186} textAnchor="middle" className="fill-ink-2 text-[12px]">{NAME[a]}</text>
          </g>
        ))}
      </svg>
      {data.flows.length === 0 && <p className="text-sm text-ink-3">No knowledge has crossed between agents yet. Press "Show me a handoff" above.</p>}
    </div>
  )
}

/** "Who on the team has worked on this before?": technicians -> tickets -> issue / router, as a traversal. */
function Experts({ tenant }: { tenant: string }) {
  const [topic, setTopic] = useState('router reboots')
  const [rows, setRows] = useState<Expert[]>()
  const [busy, setBusy] = useState(false)
  const search = async (e?: FormEvent) => {
    e?.preventDefault(); setBusy(true)
    try { setRows(await api.experts(tenant, topic)) } catch { setRows([]) } finally { setBusy(false) }
  }
  return (
    <section className="mt-10 rounded-2xl bg-surface p-5 hairline">
      <h2 className="font-display text-lg font-semibold">Who has worked on this before?</h2>
      <p className="mt-1 text-xs text-ink-3">Field technicians, ranked by resolved tickets about a matching issue, router or fix.</p>
      <form onSubmit={search} className="mt-4 flex gap-2">
        <label htmlFor="expert-topic" className="sr-only">Topic</label>
        <input id="expert-topic" className="field flex-1" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. Hub 6 Pro reboots" />
        <button className="btn-primary text-sm" disabled={busy}>Find</button>
      </form>
      {rows && (
        <ul className="mt-4 divide-y divide-line text-sm">
          {rows.map((r) => (
            <li key={r.technician} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
              <span className="min-w-0 flex-1 font-medium">{titleCase(r.technician)} <span className="font-normal text-ink-3">· {titleCase(r.city)}</span></span>
              <span className="num text-ink-2">{r.resolved} resolved of {r.tickets}</span>
              <span className="font-mono text-[11px] text-ink-3">{r.via.join(', ')}</span>
            </li>
          ))}
          {rows.length === 0 && <li className="py-3 text-ink-3">Nobody has worked on that yet.</li>}
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
      setNote(`${titleCase(r.customer)} is telling ${BOT} about a problem. Watch the arrows: the resolver will use what intake writes down.`)
    } catch { setNote("Couldn't start one. Does the Network console have customers with a line?") } finally { setBusy(false) }
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

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-6">
        <Link to="/console"><Wordmark sub="Knowledge sharing" /></Link>
        <ConsoleNav />
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">The agent team, and what they share</h1>
            <p className="mt-2 max-w-2xl text-sm text-ink-2">
              Every time an agent uses a fact, the graph records it as <code className="font-mono text-xs">(:Agent)-[:CONSULTED]-&gt;(:Fact)</code>.
              A fact written by one agent and used by another is knowledge that crossed between them, with no messages sent.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary text-sm" disabled={busy} onClick={handoff}>{busy ? 'Starting…' : 'Show me a handoff'}</button>
            <span className={`chip ${status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict'}`}>{status === 'live' ? 'Live' : 'Reconnecting'} · mem:{tenant}</span>
          </div>
        </div>
        {note && <p className="mt-4 rounded-xl bg-signal-tint px-4 py-2 text-sm text-signal-deep" role="status">{note}</p>}
        {error && <p className="mt-8 text-sm text-danger" role="alert">Couldn't load sharing data. Is the API running?</p>}
        <HandoffReplay tenant={tenant} subscribe={subscribe} />
        {data && (
          <>
            <section className="mt-10 grid gap-4 md:grid-cols-3">
              {data.agents.filter((a) => AGENTS.includes(a.agent)).map((a) => (
                <article key={a.agent} role="button" tabIndex={0} onClick={() => pickAgent(a.agent)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') pickAgent(a.agent) }} aria-pressed={picked.reader === a.agent && !picked.writer}
                  className={`cursor-pointer rounded-2xl bg-surface p-5 outline-none transition duration-300 ease-spring hover:shadow-soft ${picked.reader === a.agent && !picked.writer ? 'ring-2 ring-signal' : 'hairline'}`}>
                  <div className="flex items-baseline justify-between gap-2">
                    <h2 className="font-display text-lg font-semibold">{NAME[a.agent] ?? a.agent}</h2>
                    <span className="chip bg-sunk text-ink-2 num" title="When two agents disagree about a fact, the higher-trust claim is preferred">trust {a.trust}</span>
                  </div>
                  <p className="mt-1 text-xs text-ink-2">{a.role[0].toUpperCase() + a.role.slice(1)}.</p>
                  <dl className="mt-4 grid grid-cols-3 gap-2 num">
                    {[['Wrote', a.wrote], ['Used', a.consulted], ['From others', a.consulted_from_others]].map(([k, v]) => (
                      <div key={k as string}><dt className="text-[11px] text-ink-3">{k}</dt><dd className="font-display text-2xl font-semibold">{v}</dd></div>
                    ))}
                  </dl>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-sunk" role="meter" aria-label="Share of used facts written by other agents" aria-valuenow={a.reuse_pct} aria-valuemin={0} aria-valuemax={100}>
                    <div className="h-full rounded-full bg-signal-deep transition-[width] duration-700 ease-spring" style={{ width: `${a.reuse_pct}%` }} />
                  </div>
                  <p className="mt-1.5 text-xs text-ink-3">{a.reuse_pct}% of what it used came from another agent</p>
                </article>
              ))}
            </section>
            <section className="mt-10 rounded-2xl bg-surface p-5 hairline">
              <h2 className="font-display text-lg font-semibold">Knowledge flow</h2>
              <p className="mt-1 text-xs text-ink-3">Arrows point from the agent that wrote a fact to the agent that used it. They pulse live when it happens.</p>
              <div className="mt-4"><Flows data={data} pulse={pulse} pick={pickFlow} picked={picked} /></div>
            </section>
            <section className="mt-10 rounded-2xl bg-surface p-5 hairline">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 className="font-display text-lg font-semibold">Live hand-overs</h2>
                  <p className="mt-1 text-xs text-ink-3">
                    {picked.writer ? `Facts ${NAME[picked.writer] ?? picked.writer} wrote that ${NAME[picked.reader!] ?? picked.reader} used.`
                      : picked.reader ? `What ${NAME[picked.reader] ?? picked.reader} used from other agents.`
                        : 'Every fact one agent wrote and another used, newest first. Click an agent or an arrow to filter.'}
                  </p>
                </div>
                {(picked.reader || picked.writer) && <button className="btn-ghost !py-1 text-xs" onClick={() => setPicked({})}>Show all</button>}
              </div>
              <ul className="scroll-thin mt-4 max-h-[420px] space-y-1.5 overflow-y-auto pr-1">
                <AnimatePresence initial={false}>
                  {feed.map((r) => {
                    const k = `${r.reader}:${r.fact_id}:${r.uses}`
                    return (
                      <motion.li key={`${r.reader}:${r.fact_id}`} layout initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }}
                        className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2 text-sm transition-colors duration-700 ${fresh.has(k) ? 'bg-signal-tint' : 'bg-paper/70'}`}>
                        <span className="chip bg-surface text-[11px] text-ink-2 hairline">{NAME[r.writer] ?? r.writer} → {NAME[r.reader] ?? r.reader}</span>
                        <span className="min-w-0 flex-1">{r.sentence}</span>
                        <span className="text-[11px] text-ink-3 num">{r.uses}× · {r.last ? when(r.last) : ''}</span>
                      </motion.li>
                    )
                  })}
                </AnimatePresence>
                {feed.length === 0 && <li className="rounded-xl bg-sunk/50 px-3 py-3 text-sm text-ink-3">Nothing here yet. Press "Show me a handoff".</li>}
              </ul>
            </section>
            <Experts tenant={tenant} />
            <section className="mt-10">
              <h2 className="font-display text-lg font-semibold">Most shared facts</h2>
              <ul className="mt-4 divide-y divide-line rounded-2xl bg-surface hairline">
                {data.top_shared.map((f) => (
                  <li key={f.fact_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-sm">
                    <span className="min-w-0 flex-1">{f.sentence}</span>
                    <span className="text-xs text-ink-3">written by <strong className="font-medium text-ink-2">{NAME[f.writer] ?? f.writer}</strong> · used by {f.readers.map((r) => NAME[r] ?? r).join(', ')}</span>
                    <span className="chip bg-sunk text-ink-2 num">{f.uses}×</span>
                  </li>
                ))}
                {data.top_shared.length === 0 && <li className="px-5 py-4 text-sm text-ink-3">Nothing shared yet.</li>}
              </ul>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
