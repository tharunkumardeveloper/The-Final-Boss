import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { BOT } from '../../lib/brand'
import { predicateLabel, ticketLabel, titleCase, when } from '../../lib/format'
import { splitGuides } from '../Guides'
import type { CaseEvent, CaseStory, RelayEvent, Ticket } from '../../lib/types'

const LANES = ['customer', 'intake', 'graph', 'resolver'] as const
const LANE_NAME: Record<string, string> = { customer: 'Customer', intake: `${BOT} (intake)`, graph: 'Shared memory · FalkorDB', resolver: 'Resolver' }
const AGENT: Record<string, string> = { intake: BOT, resolver: 'Resolver', noc: 'Network ops' }
const lane = (e: CaseEvent) => (e.kind === 'write' || e.kind === 'read' ? 'graph' : e.who === 'noc' ? 'resolver' : e.who)
const SPRING = { type: 'spring', stiffness: 360, damping: 30 } as const

function FactChip({ f, tone }: { f: { predicate: string; value: string; writer?: string }; tone: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11.5px] ${tone}`}>
      <span className="opacity-70">{predicateLabel(f.predicate).toLowerCase()}</span><span className="font-semibold">{titleCase(String(f.value))}</span>
    </span>
  )
}

const LANE_TONE: Record<string, string> = { customer: 'rgb(var(--ink))', intake: '#14A39A', graph: 'rgb(var(--ink))', resolver: '#3D6FB6' }

/** A drawn arrow across a lane: into memory (a write, green) or out of it (a read, blue). */
function Arrow({ dir, color, label }: { dir: 'left' | 'right'; color: string; label: string }) {
  return (
    <motion.div initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      style={{ originX: dir === 'right' ? 0 : 1 }} className="flex h-full items-center gap-1.5">
      {dir === 'left' && <svg viewBox="0 0 8 10" className="h-2.5 w-2 shrink-0" aria-hidden="true"><path d="M8 0 0 5 8 10z" fill={color} /></svg>}
      <span className="h-[3px] flex-1 rounded-full" style={{ background: color }} />
      <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white" style={{ background: color }}>{label}</span>
      <span className="h-[3px] flex-1 rounded-full" style={{ background: color }} />
      {dir === 'right' && <svg viewBox="0 0 8 10" className="h-2.5 w-2 shrink-0" aria-hidden="true"><path d="M0 0 8 5 0 10z" fill={color} /></svg>}
    </motion.div>
  )
}

export function Row({ e }: { e: CaseEvent }) {
  if (e.kind === 'handoff') {
    return (
      <div className="col-span-4 my-1 flex items-center gap-3 rounded-2xl bg-ink px-4 py-2.5 text-sm text-paper">
        <span className="font-semibold">{AGENT[e.who] ?? e.who}</span>
        <svg viewBox="0 0 60 12" className="h-3 w-14 shrink-0" aria-hidden="true"><path d="M0 6h54m-6-5 6 5-6 5" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
        <span className="font-semibold">{AGENT[e.to ?? ''] ?? e.to}</span>
        <span className="text-paper/60">handed over the ticket{e.note ? `: ${e.note}` : ''}. No message passed between them; the ticket lives in the graph.</span>
      </div>
    )
  }
  const col = LANES.indexOf(lane(e) as (typeof LANES)[number])
  return (
    <>
      {LANES.map((l, i) => (
        <div key={l} className={`min-h-[2rem] border-l border-line/[0.07] px-2 py-1.5 ${i === 0 ? 'border-l-0' : ''}`}>
          {i === col && e.kind === 'say' && (
            <p className={`rounded-2xl px-3 py-2 text-[13px] leading-snug ${e.who === 'customer' ? 'bg-ink text-paper' : e.who === 'resolver' ? 'bg-signal-tint text-ink' : 'bg-sunk text-ink'}`}>
              {splitGuides(e.text ?? '').text}
            </p>
          )}
          {i === col && e.kind === 'write' && (
            <div className="rounded-2xl bg-current-tint/60 p-2">
              <p className="mb-1 text-[10.5px] font-medium uppercase tracking-[0.12em] text-current">← written by {AGENT[e.who] ?? e.who}</p>
              <div className="flex flex-wrap gap-1">{e.facts!.map((f) => <FactChip key={f.id} f={f} tone="bg-surface text-ink hairline" />)}</div>
            </div>
          )}
          {i === col && e.kind === 'read' && (
            <div className="rounded-2xl bg-signal-tint p-2 ring-1 ring-signal/40">
              <p className="mb-1 text-[10.5px] font-medium uppercase tracking-[0.12em] text-signal-deep">read by {AGENT[e.who] ?? e.who} →</p>
              <div className="flex flex-wrap gap-1">
                {e.facts!.map((f) => <FactChip key={f.id} f={f} tone="bg-surface text-ink ring-1 ring-signal/40" />)}
              </div>
              <p className="mt-1 text-[10.5px] text-ink-3">written by {[...new Set(e.facts!.map((f) => AGENT[f.writer ?? ''] ?? f.writer))].join(', ')}, never asked again</p>
            </div>
          )}
          {e.kind === 'write' && LANES[i] === lane({ ...e, kind: 'say' }) && (
            <Arrow dir={i < 2 ? 'right' : 'left'} color="#3E8E5E" label={`writes ${e.facts!.length}`} />
          )}
          {i === 3 && e.kind === 'read' && (
            <div className="space-y-1">
              <Arrow dir="right" color="#2F8FC9" label={`reads ${e.facts!.length}`} />
              <p className="text-[11px] text-ink-3">used to work the case, never asked again</p>
            </div>
          )}
        </div>
      ))}
    </>
  )
}

/** A case replayed step by step from the graph: messages, facts written, the handoff, facts another agent read. */
export function HandoffReplay({ tenant, subscribe }: { tenant: string; subscribe: (fn: (e: RelayEvent) => void) => () => void }) {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [ticket, setTicket] = useState<string>()
  const [story, setStory] = useState<CaseStory>()
  const [shown, setShown] = useState(0)
  const [playing, setPlaying] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()

  const loadTickets = useCallback(() => api.tickets(tenant).then((ts) => {
    const list = [...ts].sort((a, b) => (b.opened_at ?? '').localeCompare(a.opened_at ?? ''))
    setTickets(list)
    setTicket((t) => t ?? list[0]?.ticket)
  }).catch(() => {}), [tenant])
  const loadStory = useCallback((play: boolean) => {
    if (!ticket) return
    api.story(tenant, ticket).then((s) => {
      setStory(s)
      if (play) { setShown(0); setPlaying(true) } else setShown(s.events.length)
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

  useEffect(() => {
    if (!playing || !story) return
    if (shown >= story.events.length) { setPlaying(false); return }
    const id = setTimeout(() => setShown((n) => n + 1), story.events[shown]?.kind === 'say' ? 900 : 650)
    return () => clearTimeout(id)
  }, [playing, shown, story])
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' }) }, [shown])

  const events = story?.events.slice(0, shown) ?? []
  const crossings = story?.events.filter((e) => e.kind === 'read').reduce((n, e) => n + (e.facts?.length ?? 0), 0) ?? 0

  return (
    <section className="mt-10 rounded-[1.75rem] bg-surface p-5 hairline">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Watch a handoff</h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-3">One real case, replayed from the graph. Green: a fact an agent wrote. Teal: a fact another agent read. That crossing is the shared memory at work.</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="case" className="sr-only">Case</label>
          <select id="case" className="field !w-auto !py-2 text-sm" value={ticket ?? ''} onChange={(e) => setTicket(e.target.value)}>
            {tickets.map((t) => <option key={t.ticket} value={t.ticket}>{ticketLabel(t.ticket)} · {titleCase(t.customer)} · {t.status}</option>)}
            {!tickets.length && <option value="">No cases yet</option>}
          </select>
          <button className="btn-primary !py-2 text-sm" disabled={!story} onClick={() => loadStory(true)}>{playing ? 'Playing…' : 'Replay'}</button>
        </div>
      </div>
      {story && (
        <p className="mt-3 text-xs text-ink-3 num">
          {ticketLabel(story.ticket)} · {titleCase(story.issues[0] ?? 'issue')} · {story.status} · {story.events.length} steps · {crossings} fact{crossings === 1 ? '' : 's'} crossed between agents
        </p>
      )}
      <div className="mt-4 grid grid-cols-4 gap-x-0 rounded-t-2xl bg-sunk/60 text-[11px] font-medium uppercase tracking-[0.12em] text-ink-3">
        {LANES.map((l) => (
          <p key={l} className={`flex items-center gap-1.5 px-2 py-2 ${l === 'graph' ? 'text-current' : ''}`}>
            <i className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: LANE_TONE[l] }} />{LANE_NAME[l]}
          </p>
        ))}
      </div>
      <div ref={box} className="scroll-thin max-h-[560px] overflow-y-auto rounded-b-2xl ring-1 ring-line/[0.06]">
        <div className="grid grid-cols-4 gap-y-1 py-2">
          <AnimatePresence initial={false}>
            {events.map((e) => (
              <motion.div key={e.id} className="contents" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={SPRING}>
                <Row e={e} />
              </motion.div>
            ))}
          </AnimatePresence>
          {!story && <p className="col-span-4 px-4 py-8 text-center text-sm text-ink-3">No case yet. Report a problem in the customer chat and it shows up here, live.</p>}
          {story && events.length > 0 && events.length === story.events.length && (
            <p className="col-span-4 px-4 pt-2 text-center text-[11px] text-ink-3">last step {when(events[events.length - 1].at)}</p>
          )}
        </div>
      </div>
    </section>
  )
}
