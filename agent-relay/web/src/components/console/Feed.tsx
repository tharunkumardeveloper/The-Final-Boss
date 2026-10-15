import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { predicateLabel, retiredLabel, speakerName, ticketLabel, titleCase, when } from '../../lib/format'
import type { Customer, RelayEvent } from '../../lib/types'

const AVATAR: Record<string, string> = { intake: 'bg-signal-tint text-signal-deep', resolver: 'bg-ink text-paper', customer: 'bg-sunk text-ink-2' }

function initials(name: string) {
  return name.split(' ').map((p) => p[0]).join('').slice(0, 2).toUpperCase()
}

function Item({ e }: { e: RelayEvent }) {
  const t = e.sim_time ? when(e.sim_time) : ''
  switch (e.type) {
    case 'message': {
      const who = speakerName(e.data.speaker, e.data.customer)
      const agent = e.data.speaker === 'intake' || e.data.speaker === 'resolver'
      const tool = e.data.speaker.startsWith('tool:')
      if (tool) return <System tone="tool" t={t}>{who}: {e.data.text}</System>
      return (
        <li className="flex gap-2.5 animate-rise">
          <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${AVATAR[e.data.speaker] ?? AVATAR.customer}`}>
            {initials(who)}
          </span>
          <div className="min-w-0">
            <p className="text-xs"><span className="font-semibold text-ink">{who}</span>
              {agent && <span className="text-ink-3"> to {titleCase(e.data.customer)}</span>}
              {/-web/.test(e.data.session_id) && <span className="ml-1 rounded-full bg-signal-tint px-1.5 py-px text-[10px] font-medium text-signal-deep">portal</span>}
              <span className="num text-ink-3"> · {t}</span></p>
            <p className={`mt-0.5 text-[13px] leading-relaxed ${agent ? 'text-ink-2' : 'text-ink'}`}>{e.data.text}</p>
          </div>
        </li>
      )
    }
    case 'tool_call': return <System tone="tool" t={t}>{titleCase(e.data.tool)} system: {e.data.output}</System>
    case 'ticket_opened': return <System tone="signal" t={t}>Ticket {ticketLabel(e.data.ticket)} opened for {titleCase(e.data.customer)}: {e.data.issue}</System>
    case 'handoff': return <System tone="signal" t={t}>{titleCase(e.data.from)} handed {ticketLabel(e.data.ticket)} to {e.data.to}{e.data.note ? ` · ${e.data.note}` : ''}</System>
    case 'pickup': return <System tone="signal" t={t}>{titleCase(e.data.agent)} picked up {ticketLabel(e.data.ticket)}</System>
    case 'ticket_status': return <System tone="plain" t={t}>{ticketLabel(e.data.ticket)} is now {e.data.status}</System>
    case 'fact_superseded': return <System tone="update" t={t}>Memory updated: {titleCase(e.data.subject)} {predicateLabel(e.data.predicate)} {titleCase(e.data.object)} <span className="line-through opacity-60">{titleCase(e.data.old_object)}</span></System>
    case 'fact_retired': return <System tone="plain" t={t}>Memory updated: {titleCase(e.data.subject)} {retiredLabel(e.data.predicate)} <span className="line-through opacity-70">{titleCase(e.data.object)}</span></System>
    case 'conflict': return <System tone="conflict" t={t}>Conflict on {titleCase(e.data.subject)} · {predicateLabel(e.data.predicate)}: {e.data.claims.map((c) => `${c.value} (${c.agent}${c.preferred ? ', preferred' : ''})`).join(' vs ')}</System>
    case 'answer': return <System tone="signal" t={t}>Resolver answered "{e.data.question}": {e.data.answer}</System>
    default: return null
  }
}

const TONES = {
  tool: 'bg-sunk/70 text-ink-2 font-mono text-[11.5px]',
  signal: 'bg-signal-tint/70 text-signal-deep',
  update: 'bg-current-tint/70 text-current',
  conflict: 'bg-conflict-tint text-conflict',
  plain: 'bg-sunk/60 text-ink-2',
}
function System({ tone, t, children }: { tone: keyof typeof TONES; t: string; children: ReactNode }) {
  return (
    <li className={`animate-rise rounded-xl px-3 py-2 text-xs leading-relaxed ${TONES[tone]}`}>
      {children}<span className="num ml-1.5 opacity-60">{t}</span>
    </li>
  )
}

export function Feed({ feed, customers }: { feed: RelayEvent[]; customers: Customer[] }) {
  const [who, setWho] = useState('')
  const list = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const items = useMemo(() => who ? feed.filter((e) => 'customer' in e.data && (e.data as { customer?: string }).customer === who) : feed, [feed, who])

  useEffect(() => {
    const el = list.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [items])

  return (
    <section className="flex min-h-0 flex-col" aria-label="Live conversations">
      <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-4">
        <h2 className="eyebrow">Live desk</h2>
        <label className="sr-only" htmlFor="feed-filter">Filter by customer</label>
        <select id="feed-filter" className="rounded-full bg-sunk px-2.5 py-1 text-xs text-ink-2 outline-none focus:ring-2 focus:ring-signal/40"
          value={who} onChange={(e) => setWho(e.target.value)}>
          <option value="">All customers</option>
          {customers.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
        </select>
      </div>
      <div ref={list} className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 pb-4"
        onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}>
        {items.length === 0 ? (
          <p className="mt-10 px-4 text-center text-sm text-ink-3">Nothing yet. Start the simulation or chat from the customer portal.</p>
        ) : (
          <ul className="space-y-3">{items.map((e, i) => <Item key={i} e={e} />)}</ul>
        )}
      </div>
    </section>
  )
}
