import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { BOT } from '../../lib/brand'
import { predicateLabel, ticketLabel, titleCase, when } from '../../lib/format'
import { splitGuides } from '../Guides'
import type { CaseEvent, CaseStory, RelayEvent, Ticket } from '../../lib/types'

// four stations, left to right: the case travels between them
const ST = ['customer', 'intake', 'graph', 'resolver'] as const
type Station = (typeof ST)[number]
const SX: Record<Station, number> = { customer: 70, intake: 250, graph: 430, resolver: 610 }
const LABEL: Record<Station, string> = { customer: 'Customer', intake: BOT, graph: 'Shared memory', resolver: 'Resolver' }
const TONE: Record<Station, string> = { customer: '#0F1B2D', intake: '#14A39A', graph: '#0F1B2D', resolver: '#3D6FB6' }
const WRITE = '#3E8E5E', READ = '#2F8FC9'
const AGENT: Record<string, string> = { intake: BOT, resolver: 'Resolver', noc: 'Network ops' }
const at = (who: string): Station => (who === 'customer' ? 'customer' : who === 'intake' ? 'intake' : 'resolver')

/** Where a step moves: from which station to which, and in what colour. */
function move(e: CaseEvent): { from: Station; to: Station; color: string; label: string } {
  const n = e.facts?.length ?? 0
  if (e.kind === 'write') return { from: at(e.who), to: 'graph', color: WRITE, label: `writes ${n} fact${n === 1 ? '' : 's'}` }
  if (e.kind === 'read') return { from: 'graph', to: at(e.who), color: READ, label: `reads ${n} fact${n === 1 ? '' : 's'}` }
  if (e.kind === 'handoff') return { from: 'intake', to: 'resolver', color: '#C47F0E', label: 'hands over the ticket' }
  const from = at(e.who)
  return { from, to: from === 'customer' ? 'intake' : 'customer', color: TONE[from], label: from === 'customer' ? 'says' : 'replies' }
}

const Y = 70
const lift = (a: Station, b: Station) => (Math.abs(SX[a] - SX[b]) > 200 ? 62 : 30) * (SX[a] < SX[b] ? 1 : -1)
const arc = (a: Station, b: Station) => `M${SX[a]} ${Y} Q${(SX[a] + SX[b]) / 2} ${Y - lift(a, b)} ${SX[b]} ${Y}`

/** The diagram: four stations; the current step travels as a token, and every step so far stays drawn as a trail. */
function Stage({ events, cur }: { events: CaseEvent[]; cur: number }) {
  const e = events[cur]
  const m = e ? move(e) : null
  const trail = new Map(events.slice(0, cur).map((x) => { const k = move(x); return [`${k.from}>${k.to}>${k.color}`, k] as const }))
  return (
    <svg viewBox="0 0 680 150" className="h-auto w-full" role="img" aria-label="The case moving between the customer, the agents and shared memory">
      {[...trail.entries()].map(([k, t]) => <path key={k} d={arc(t.from, t.to)} fill="none" stroke={t.color} strokeOpacity="0.2" strokeWidth="3" />)}
      {ST.map((s) => {
        const on = !!m && (m.from === s || m.to === s)
        return (
          <g key={s}>
            {s === 'graph'
              ? <g><ellipse cx={SX[s]} cy={Y - 14} rx="34" ry="9" fill={TONE[s]} /><path d={`M${SX[s] - 34} ${Y - 14}v30a34 9 0 0 0 68 0v-30`} fill={TONE[s]} />
                <ellipse cx={SX[s]} cy={Y - 14} rx="34" ry="9" fill="none" stroke="rgb(var(--signal))" strokeOpacity={on ? 1 : 0.4} strokeWidth={on ? 2 : 1} /></g>
              : <circle cx={SX[s]} cy={Y} r="24" fill={TONE[s]} stroke={on ? 'rgb(var(--signal))' : 'transparent'} strokeWidth="3" />}
            <text x={SX[s]} y={Y + 5} textAnchor="middle" className="fill-white text-[12px] font-semibold">{s === 'graph' ? 'DB' : LABEL[s][0]}</text>
            <text x={SX[s]} y={Y + 46} textAnchor="middle" className={`text-[11.5px] ${on ? 'fill-ink font-semibold' : 'fill-ink-3'}`}>{LABEL[s]}</text>
          </g>
        )
      })}
      {m && (
        <g key={e!.id}>
          <motion.path d={arc(m.from, m.to)} fill="none" stroke={m.color} strokeWidth="3" strokeLinecap="round"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }} />
          <circle r="7" fill={m.color}><animateMotion dur="0.6s" path={arc(m.from, m.to)} fill="freeze" /></circle>
          <text x={(SX[m.from] + SX[m.to]) / 2} y={lift(m.from, m.to) > 0 ? Y - lift(m.from, m.to) / 2 - 10 : Y - lift(m.from, m.to) / 2 + 18}
            textAnchor="middle" className="text-[11px] font-semibold" fill={m.color}>{m.label}</text>
        </g>
      )}
    </svg>
  )
}

/** The proof for one step: the words said, or the facts with their ids, writer and time, as stored in the graph. */
function Proof({ e, active, onClick }: { e: CaseEvent; active: boolean; onClick: () => void }) {
  const m = move(e)
  const who = e.kind === 'say' ? (e.who === 'customer' ? 'Customer' : AGENT[e.who] ?? e.who)
    : e.kind === 'handoff' ? `${AGENT[e.who] ?? e.who} → ${AGENT[e.to ?? ''] ?? e.to}` : `${AGENT[e.who] ?? e.who} ${m.label}`
  return (
    <li>
      <button onClick={onClick} aria-current={active ? 'step' : undefined}
        className={`w-full rounded-xl px-3 py-2 text-left transition duration-300 ${active ? 'bg-ink text-paper shadow-lift' : 'hover:bg-sunk/70'}`}>
        <p className="flex items-center gap-2 text-[11px]">
          <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: m.color }} />
          <span className="font-semibold">{who}</span>
          <span className={`ml-auto shrink-0 num ${active ? 'text-paper/60' : 'text-ink-3'}`}>{e.at ? when(e.at) : ''}</span>
        </p>
        {e.kind === 'say' && <p className={`mt-1 line-clamp-2 text-[12.5px] ${active ? '' : 'text-ink-2'}`}>“{splitGuides(e.text ?? '').text}”</p>}
        {e.kind === 'handoff' && <p className={`mt-1 text-[12px] ${active ? 'text-paper/80' : 'text-ink-2'}`}>No message passed between them: the ticket is a node in the graph{e.note ? ` (${e.note})` : ''}.</p>}
        {(e.kind === 'write' || e.kind === 'read') && (
          <ul className="mt-1 space-y-0.5">
            {e.facts!.map((f) => (
              <li key={f.id} className="flex flex-wrap items-baseline gap-x-1.5 text-[12px]">
                <span className={active ? 'text-paper/70' : 'text-ink-3'}>{predicateLabel(f.predicate).toLowerCase()}</span>
                <span className="font-semibold">{titleCase(String(f.value))}</span>
                <span className={`font-mono text-[10px] ${active ? 'text-paper/50' : 'text-ink-3'}`}>{f.id}{e.kind === 'read' && f.writer ? ` · written by ${AGENT[f.writer] ?? f.writer}` : ''}</span>
              </li>
            ))}
          </ul>
        )}
      </button>
    </li>
  )
}

/** One real case replayed from the graph: a diagram of where it went, and the record behind every step. */
export function HandoffReplay({ tenant, subscribe }: { tenant: string; subscribe: (fn: (e: RelayEvent) => void) => () => void }) {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [ticket, setTicket] = useState<string>()
  const [story, setStory] = useState<CaseStory>()
  const [cur, setCur] = useState(0)
  const [playing, setPlaying] = useState(false)
  const list = useRef<HTMLOListElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()

  const loadTickets = useCallback(() => api.tickets(tenant).then((ts) => {
    const sorted = [...ts].sort((a, b) => (b.opened_at ?? '').localeCompare(a.opened_at ?? ''))
    setTickets(sorted)
    setTicket((t) => t ?? sorted[0]?.ticket)
  }).catch(() => {}), [tenant])
  const loadStory = useCallback((play: boolean) => {
    if (!ticket) return
    api.story(tenant, ticket).then((s) => {
      setStory(s)
      if (play) { setCur(0); setPlaying(true) } else setCur(s.events.length - 1)
    }).catch(() => setStory(undefined))
  }, [tenant, ticket])
  useEffect(() => { loadTickets() }, [loadTickets])
  useEffect(() => { loadStory(true) }, [loadStory])
  useEffect(() => subscribe((e) => {
    if (e.type === 'ticket_opened') { setTicket(e.data.ticket); loadTickets() }
    else if (['consulted', 'message', 'handoff', 'pickup'].includes(e.type)) {
      clearTimeout(timer.current); timer.current = setTimeout(() => loadStory(false), 800)
    }
  }), [subscribe, loadTickets, loadStory])

  const n = story?.events.length ?? 0
  useEffect(() => {
    if (!playing) return
    if (cur >= n - 1) { setPlaying(false); return }
    const id = setTimeout(() => setCur((c) => c + 1), 1400)
    return () => clearTimeout(id)
  }, [playing, cur, n])
  useEffect(() => { list.current?.querySelector('[aria-current="step"]')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [cur])

  const events = story?.events ?? []
  const writes = events.filter((e) => e.kind === 'write').reduce((t, e) => t + (e.facts?.length ?? 0), 0)
  const reads = events.filter((e) => e.kind === 'read').reduce((t, e) => t + (e.facts?.length ?? 0), 0)

  return (
    <section className="flex min-h-0 flex-col rounded-[1.75rem] bg-surface p-4 hairline" aria-label="Watch a handoff">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-lg font-semibold">Watch a handoff</h2>
          {story && <p className="text-[11px] text-ink-3 num">{ticketLabel(story.ticket)} · {titleCase(story.issues[0] ?? 'issue')} · {story.status} · {writes} facts written, {reads} read by another agent</p>}
        </div>
        <div className="flex items-center gap-1.5">
          <label htmlFor="case" className="sr-only">Case</label>
          <select id="case" className="field !w-auto !py-1.5 text-xs" value={ticket ?? ''} onChange={(e) => setTicket(e.target.value)}>
            {tickets.map((t) => <option key={t.ticket} value={t.ticket}>{ticketLabel(t.ticket)} · {titleCase(t.customer)} · {t.status}</option>)}
            {!tickets.length && <option value="">No cases yet</option>}
          </select>
          <button className="btn-ghost !px-2.5 !py-1.5 text-xs hairline" disabled={!n || cur === 0} onClick={() => { setPlaying(false); setCur((c) => Math.max(0, c - 1)) }} aria-label="Previous step">‹</button>
          <button className="btn-primary !px-3 !py-1.5 text-xs" disabled={!n} onClick={() => { if (cur >= n - 1) setCur(0); setPlaying((p) => !p) }}>{playing ? 'Pause' : cur >= n - 1 ? 'Replay' : 'Play'}</button>
          <button className="btn-ghost !px-2.5 !py-1.5 text-xs hairline" disabled={!n || cur >= n - 1} onClick={() => { setPlaying(false); setCur((c) => Math.min(n - 1, c + 1)) }} aria-label="Next step">›</button>
        </div>
      </div>
      {!story ? (
        <p className="mt-6 rounded-2xl bg-sunk/50 p-6 text-center text-sm text-ink-3">No case yet. Press “Show me a handoff”, or report a problem in the customer chat.</p>
      ) : (
        <div className="mt-2 grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <div className="flex flex-col justify-center">
            <Stage events={events} cur={cur} />
            <input type="range" min={0} max={Math.max(0, n - 1)} value={cur} aria-label="Step"
              onChange={(e) => { setPlaying(false); setCur(Number(e.target.value)) }} className="mt-1 w-full accent-[rgb(var(--signal))]" />
            <p className="mt-1 text-center text-[11px] text-ink-3 num">step {Math.min(cur + 1, n)} of {n} · each step is a node or edge in FalkorDB, listed on the right</p>
          </div>
          <ol ref={list} className="scroll-thin max-h-[320px] min-h-0 space-y-1 overflow-y-auto pr-1 md:max-h-none" aria-label="The record behind each step">
            <AnimatePresence initial={false}>
              {events.slice(0, cur + 1).map((e, i) => (
                <motion.div key={e.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
                  <Proof e={e} active={i === cur} onClick={() => { setPlaying(false); setCur(i) }} />
                </motion.div>
              ))}
            </AnimatePresence>
          </ol>
        </div>
      )}
    </section>
  )
}
