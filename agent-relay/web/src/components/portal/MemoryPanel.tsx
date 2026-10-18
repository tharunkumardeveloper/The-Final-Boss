import { BOT } from '../../lib/brand'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import type { Chip, MemoryKind } from '../../lib/chips'
import { predicateLabel, retiredLabel, ticketLabel, titleCase, when } from '../../lib/format'
import type { Card, Customer, HistoryRow } from '../../lib/types'
import { ArrowUpRight, Sparkle } from '../Icons'
import { SPRING } from './Kavya'

export const GLOW: Record<Chip['status'], string> = {
  new: 'rgb(38 133 84 / 0.28)', updated: 'rgb(196 127 14 / 0.30)', corroborated: 'rgb(20 163 154 / 0.24)', retired: 'rgb(154 165 180 / 0.35)',
}
const TONE: Record<Chip['status'], string> = {
  new: 'bg-current-tint text-current', updated: 'bg-conflict-tint text-conflict',
  corroborated: 'bg-signal-tint text-signal-deep', retired: 'border border-dashed border-old bg-surface text-ink-3',
}
const WORD: Record<Chip['status'], string> = { new: 'New', updated: 'Updated', corroborated: 'Confirmed', retired: 'No longer true' }

/** The chip itself; the same layoutId is used in the chat bubble and in the panel, so it flies between them. */
/** The three memory types, one colour each, the same everywhere they are flagged. */
export const MEMORY_KINDS: Record<MemoryKind, { label: string; cls: string; what: string }> = {
  semantic: { label: 'Semantic', cls: 'bg-current-tint text-current', what: 'Facts: what is true about you now (plan, city, devices), and what used to be' },
  episodic: { label: 'Episodic', cls: 'bg-signal-tint text-signal-deep', what: 'Episodes: every message and reply, timestamped, which each fact can be traced back to' },
  procedural: { label: 'Procedural', cls: 'bg-conflict-tint text-conflict', what: 'Know-how: fixes that worked before, tried first next time' },
}

export function MemoryKindPill({ kind, className = '' }: { kind: MemoryKind; className?: string }) {
  const k = MEMORY_KINDS[kind]
  return <span title={`${k.label} memory: ${k.what}`} className={`inline-flex shrink-0 items-center rounded-full px-1.5 py-px text-[9.5px] font-semibold uppercase tracking-wider ${k.cls} ${className}`}>{k.label}</span>
}

/** A one-line key for a memory graph: which part of the picture is which kind of memory. */
export function MemoryKindKey({ className = '' }: { className?: string }) {
  return (
    <p className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3 ${className}`} aria-label="Memory types">
      <span className="flex items-center gap-1"><MemoryKindPill kind="semantic" />lines: facts</span>
      <span className="flex items-center gap-1"><MemoryKindPill kind="procedural" />green nodes: fixes that worked</span>
      <span className="flex items-center gap-1"><MemoryKindPill kind="episodic" />Replay and sources: the conversations behind them</span>
    </p>
  )
}

export function MemoryChip({ c, compact = false }: { c: Chip; compact?: boolean }) {
  return (
    <motion.span layoutId={`mem-${c.key}`} transition={SPRING}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${TONE[c.status]}`}>
      <Sparkle className="h-3 w-3" />{c.label}{!compact && c.note && <span className="font-normal opacity-75">· {c.note}</span>}
      {c.kind && <MemoryKindPill kind={c.kind} className="ml-0.5 bg-surface/70" />}
    </motion.span>
  )
}

function Entry({ c }: { c: Chip }) {
  const reduce = useReducedMotion()
  return (
    <motion.li layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, x: 12 }} transition={SPRING}
      className="relative rounded-xl px-3 py-2.5">
      {/* arrival glow: one soft pulse in the chip's own colour */}
      {!reduce && <motion.span key={c.at} className="pointer-events-none absolute inset-0 rounded-xl"
        initial={{ boxShadow: `0 0 0 6px ${GLOW[c.status]}`, backgroundColor: GLOW[c.status] }}
        animate={{ boxShadow: '0 0 0 0px rgba(0,0,0,0)', backgroundColor: 'rgba(0,0,0,0)' }}
        transition={{ duration: 1.4, ease: [0.32, 0.72, 0, 1] }} />}
      <div className="relative flex items-start justify-between gap-2">
        <MemoryChip c={c} compact />
        <span className="shrink-0 pt-1 text-[10.5px] uppercase tracking-[0.12em] text-ink-3">{WORD[c.status]}</span>
      </div>
      {c.note && <p className="relative mt-1 pl-1 text-xs text-ink-3">{c.note}</p>}
    </motion.li>
  )
}

// Staff bookkeeping stays out of the customer's view (it is still in memory and in the console).
const HIDDEN = new Set(['awaiting', 'doesnt_know', 'has_priority', 'visit_reason'])  // what they asked for shows
const value = (r: HistoryRow) => (r.predicate === 'has_ticket' ? ticketLabel(r.value) : titleCase(r.value))
const AGENT: Record<string, string> = { intake: `${BOT} (intake)`, resolver: 'the resolver', noc: 'network operations', simulator: 'the simulator',
  mcp: 'an outside AI agent (MCP)' }
// One current value per thing for these; a second active claim is a disagreement between sources, shown as such.
const SINGLE = new Set(['lives_in', 'on_plan', 'has_router', 'prefers_channel', 'budget', 'moving_to', 'occupation',
  'connection_type', 'preferred_language', 'household_size', 'current_provider', 'address'])
/** A source the customer may see in words: their own message, or one sent to them. Internal notes only say who/when. */
const SAID = (speaker: string) => speaker === 'customer' || speaker === 'agent' || speaker === 'intake' || speaker === 'noc'
const SPOKE: Record<string, string> = { customer: 'You said', agent: `${BOT} said`, intake: `${BOT} said`, noc: 'We told you' }

/** "How I know this": the message it came from, when, who wrote it, and both clocks. From the fact's graph card. */
function HowIKnow({ tenant, row, also = [] }: { tenant: string; row: HistoryRow; also?: HistoryRow[] }) {
  const [open, setOpen] = useState(false)
  const [card, setCard] = useState<Card | null>()
  const toggle = () => {
    setOpen((o) => !o)
    if (card === undefined) api.card(tenant, `f:${row.fact_id}`).then(setCard).catch(() => setCard(null))
  }
  const sources = card?.sections.find((x) => x.title === 'Sources')?.rows ?? []
  return (
    <li className="rounded-xl bg-paper/70 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className={row.active ? 'text-ink' : 'text-ink-3 line-through decoration-ink-3/40'}>
          {row.active ? predicateLabel(row.predicate) : retiredLabel(row.predicate)} <span className="font-medium">{value(row)}</span>
          {also.length > 0 && <span className="block text-[11px] text-conflict">Another record says {also.map(value).join(', ')}; we go with the more trusted source.</span>}
        </span>
        <button type="button" onClick={toggle} aria-expanded={open} className="shrink-0 text-[11px] font-medium text-signal-deep hover:underline">
          {open ? 'Hide' : 'How I know'}
        </button>
      </div>
      {!row.active && row.valid_to && <p className="text-[11px] text-ink-3">until {when(row.valid_to, false)}</p>}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }} className="overflow-hidden">
            <div className="mt-2 space-y-1.5 border-l-2 border-signal/30 pl-3 text-xs text-ink-2">
              {card === undefined && <p className="animate-breathe text-ink-3">Following the graph…</p>}
              {card === null && <p className="text-ink-3">Couldn't load the source.</p>}
              {card && <>
                {sources.slice(0, 3).map(([who, said], i) => {
                  const [speaker, day] = who.split(' · ')
                  return SAID(speaker)
                    ? <p key={i}><span className="text-ink-3">{SPOKE[speaker] ?? 'Said'} on {day}:</span> “{said}”</p>
                    : <p key={i} className="text-ink-3">Recorded by {speaker.startsWith('tool:') ? `our ${speaker.slice(5)} system` : 'the support team'} on {day}.</p>
                })}
                <p className="text-ink-3">Written by {row.agents.map((a) => AGENT[a] ?? a).join(', ') || 'the desk'} · true since {when(row.valid_from, false)}
                  {row.recorded_at ? ` · on file since ${when(row.recorded_at, false)}` : ''}</p>
                {card.lines.slice(1).map((ln, i) => <p key={i} className="text-ink-3">{ln}</p>)}
              </>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

type ProceduralFix = { fix: string; issue: string; times: number; last_used: string | null }

const MEMORY_TYPE_PILL = 'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider'

export function MemoryPanel({ who, customer, chips, tenant }: { who: string | null; customer?: Customer; chips: Chip[]; tenant: string }) {
  const [memory, setMemory] = useState<HistoryRow[]>([])
  const [procedural, setProcedural] = useState<ProceduralFix[]>([])
  const settledCount = chips.filter((c) => c.phase === 'settled').length
  // Semantic memory: facts about the customer from the graph (any agent, any session)
  useEffect(() => {
    if (!who) { setMemory([]); return }
    let live = true
    api.history(tenant, who).then((rows) => live && setMemory(rows.filter((r) => !HIDDEN.has(r.predicate)))).catch(() => {})
    return () => { live = false }
  }, [tenant, who, settledCount])
  // Procedural memory: fixes that resolved similar issues before (shared across all customers)
  useEffect(() => {
    if (!who) { setProcedural([]); return }
    let live = true
    api.procedural(tenant).then((r) => live && setProcedural(r.fixes)).catch(() => {})
    return () => { live = false }
  }, [tenant, who])

  const active = memory.filter((r) => r.active)
  const seen = new Map<string, HistoryRow[]>()
  const now = active.filter((r) => {
    if (!SINGLE.has(r.predicate)) return true
    const list = seen.get(r.predicate)
    if (list) { list.push(r); return false }
    seen.set(r.predicate, [])
    return true
  })
  const before = memory.filter((r) => !r.active).slice(-6).reverse()
  const settled = chips.filter((c) => c.phase === 'settled').slice().reverse()
  const onFile: [string, string | null | undefined][] = customer ? [
    ['Lives in', customer.city && titleCase(customer.city)], ['Plan', customer.plan && titleCase(customer.plan)],
    ['Router', customer.router], ['Contact by', customer.channel && titleCase(customer.channel)],
    ['Devices', customer.devices.length ? customer.devices.map(titleCase).join(', ') : null],
    ['Open ticket', customer.open_ticket && ticketLabel(customer.open_ticket)],
  ] : []
  const known = onFile.filter(([, v]) => v)

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-[1.75rem] bg-surface/70 p-5 hairline" aria-label={`What ${BOT} remembers`}>
      <p className="eyebrow">Graph Memory</p>
      <h2 className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">What the desk remembers</h2>
      <p className="mt-1 text-sm text-ink-3">Three kinds of memory in one graph — you never have to repeat yourself.</p>

      {!who ? (
        <div className="mt-6 space-y-3">
          <p className="rounded-2xl bg-sunk/60 p-4 text-sm text-ink-2">Say hello and tell {BOT} your name. Anything you share lands here, live.</p>
          <div className="rounded-2xl bg-sunk/40 p-4 space-y-2">
            <p className="text-xs font-semibold text-ink-2">Three memory types in this graph:</p>
            <div className="space-y-1.5 text-xs text-ink-3">
              <p><span className={`${MEMORY_TYPE_PILL} bg-current-tint text-current mr-2`}>Semantic</span>Facts about you — plan, city, devices</p>
              <p><span className={`${MEMORY_TYPE_PILL} bg-signal-tint text-signal-deep mr-2`}>Episodic</span>Every conversation, timestamped</p>
              <p><span className={`${MEMORY_TYPE_PILL} bg-conflict-tint text-conflict mr-2`}>Procedural</span>Fixes that resolved issues before</p>
            </div>
          </div>
        </div>
      ) : (
        <div className="scroll-thin mt-5 min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
          {/* Semantic Memory */}
          {now.length > 0 ? (
            <section>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="eyebrow">Semantic Memory</h3>
                <span className={`${MEMORY_TYPE_PILL} bg-current-tint text-current`}>Facts</span>
              </div>
              <p className="mb-2 text-xs text-ink-3">What the desk knows about you — from you, our tools, and the resolver.</p>
              <ul className="space-y-1.5">{now.map((r) => <HowIKnow key={r.fact_id} tenant={tenant} row={r} also={seen.get(r.predicate) ?? []} />)}</ul>
              {customer?.last_seen && <p className="mt-1.5 text-[11px] text-ink-3">Last updated {when(customer.last_seen)}</p>}
            </section>
          ) : known.length > 0 && (
            <section>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="eyebrow">Semantic Memory</h3>
                <span className={`${MEMORY_TYPE_PILL} bg-current-tint text-current`}>Facts</span>
              </div>
              <dl className="divide-y divide-line/[0.06] rounded-2xl bg-paper/70 px-3">
                {known.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 py-2 text-sm"><dt className="text-ink-3">{k}</dt><dd className="text-right font-medium text-ink">{v}</dd></div>
                ))}
              </dl>
            </section>
          )}

          {/* Episodic Memory — what changed over time */}
          {before.length > 0 && (
            <section>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="eyebrow">Episodic Memory</h3>
                <span className={`${MEMORY_TYPE_PILL} bg-signal-tint text-signal-deep`}>History</span>
              </div>
              <p className="mb-2 text-xs text-ink-3">Bi-temporal: memory knows what used to be true, and when it changed.</p>
              <ul className="space-y-1.5">{before.map((r) => <HowIKnow key={r.fact_id} tenant={tenant} row={r} />)}</ul>
            </section>
          )}

          {/* Procedural Memory — shared fixes */}
          {procedural.length > 0 && (
            <section>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="eyebrow">Procedural Memory</h3>
                <span className={`${MEMORY_TYPE_PILL} bg-conflict-tint text-conflict`}>Fixes</span>
              </div>
              <p className="mb-2 text-xs text-ink-3">Fixes that resolved issues before — the resolver reads this before every pickup.</p>
              <ul className="space-y-1.5">
                {procedural.slice(0, 5).map((f) => (
                  <li key={`${f.fix}:${f.issue}`} className="rounded-xl bg-paper/70 px-3 py-2 text-sm">
                    <span className="font-medium text-ink">{titleCase(f.fix)}</span>
                    <span className="text-ink-3"> resolved </span>
                    <span className="text-ink-2">{f.issue}</span>
                    <span className="ml-1.5 text-[11px] text-ink-3">× {f.times}{f.last_used ? ` · last ${when(f.last_used)}` : ''}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Live chips from this session */}
          <section>
            <div className="mb-1 flex items-center gap-2">
              <h3 className="eyebrow">Learned in this chat</h3>
              <span className={`${MEMORY_TYPE_PILL} bg-sunk text-ink-3`}>Live</span>
            </div>
            {settled.length === 0
              ? <p className="py-2 text-sm text-ink-3">Nothing new yet. Tell {BOT} something and watch it land here.</p>
              : <ul className="-mx-1 space-y-1"><AnimatePresence initial={false}>{settled.map((c) => <Entry key={c.key} c={c} />)}</AnimatePresence></ul>}
          </section>
        </div>
      )}
      <Link to="/console" className="mt-4 inline-flex items-center gap-1 self-start text-xs font-medium text-signal-deep hover:underline">
        See the graph behind this <ArrowUpRight className="h-3.5 w-3.5" />
      </Link>
    </aside>
  )
}
