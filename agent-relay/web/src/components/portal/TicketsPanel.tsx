import { AnimatePresence, motion } from 'framer-motion'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { BOT } from '../../lib/brand'
import { ticketLabel, titleCase, when } from '../../lib/format'
import type { Customer, LabRun, LabView, Ticket } from '../../lib/types'
import { Check, Sparkle, Ticket as TicketIcon } from '../Icons'
import type { Subscribe } from './SupportChat'
import { SPRING } from './Kavya'

// the trace shares the lab's code, which is heavy; it loads once the resolver is on a case
const ResolverCard = lazy(() => import('./ResolverCard'))

const STAGES = ['Reported', 'Checking your line', 'Fixing', 'Fixed'] as const
const stage = (t: Ticket) => t.status === 'resolved' ? 3 : t.status === 'in progress' || t.status === 'waiting on customer'
  ? (t.trail.some((s) => s.action !== 'handed_off' && s.action !== 'picked_up') ? 2 : 1) : t.trail.some((s) => s.action === 'picked_up') ? 1 : 0
const NEXT: Record<number, string> = {
  0: 'Our resolver is picking this up. You don\'t need to do anything.',
  1: 'The resolver is testing your line from our side right now.',
  2: 'A fix is underway. You\'ll get a message here the moment it\'s done.',
  3: 'Sorted. If anything comes back, just tell us in the chat.',
}
const REFRESH = new Set(['ticket_opened', 'handoff', 'pickup', 'ticket_status', 'lab_run'])
const onTicket = (r: LabRun, t: Ticket) => !!r.ticket && r.ticket.toLowerCase() === t.ticket.toLowerCase()

/** What a customer sees next to the chat: their own tickets, how far along they are, and their plan. */
export function TicketsPanel({ tenant, who, customer, subscribe, onAsk, run, view }: {
  tenant: string; who: string | null; customer?: Customer; subscribe: Subscribe; onAsk: (text: string) => void
  run?: LabRun; view?: LabView  // the resolver's latest run on this customer's line, shown under its ticket
}) {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => {
    if (!who) { setTickets([]); return }
    let live = true
    const load = () => api.tickets(tenant).then((ts) => live && setTickets(ts.filter((t) => t.customer === who).reverse())).catch(() => {})
    load()
    const off = subscribe((e) => {
      const lab = e.type === 'lab_step' && (e.data.step?.kind === 'act' || e.data.step?.kind === 'verify')
      if (REFRESH.has(e.type) || lab || (e.type === 'message' && e.data.customer === who && e.data.speaker === 'resolver')) {
        clearTimeout(timer.current); timer.current = setTimeout(load, 400)
      }
    })
    return () => { live = false; off(); clearTimeout(timer.current) }
  }, [tenant, who, subscribe])

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-[1.75rem] bg-surface/70 p-5 hairline" aria-label="Your tickets">
      <p className="eyebrow">Your support</p>
      <h2 className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">Your tickets</h2>
      <p className="mt-1 text-sm text-ink-3">Anything you report shows up here, with where it's at.</p>
      <div className="scroll-thin mt-5 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {!who && <p className="rounded-2xl bg-sunk/60 p-4 text-sm text-ink-2">Tell {BOT} your name and you'll see your tickets here.</p>}
        {who && tickets.length === 0 && (
          <div className="rounded-2xl bg-sunk/50 p-4 text-sm text-ink-2">
            <p>No tickets. Everything's running smoothly.</p>
            <p className="mt-1 text-xs text-ink-3">If something's off, just describe it in the chat. No tech words needed.</p>
          </div>
        )}
        {run && !tickets.some((t) => onTicket(run, t)) && <Suspense fallback={null}><ResolverCard run={run} view={view} /></Suspense>}
        <AnimatePresence initial={false}>
          {tickets.map((t, i) => {
            const n = stage(t)
            return (
              // position only: a size animation would squash the text while the resolver card under it grows
              <motion.div key={t.ticket} layout="position" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}
                className="space-y-2">
              <article className={`rounded-2xl p-4 ${i === 0 && n < 3 ? 'bg-surface shadow-soft ring-1 ring-signal/25' : 'bg-paper/80 hairline'}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className={`flex h-8 w-8 items-center justify-center rounded-xl ${n === 3 ? 'bg-current-tint text-current' : 'bg-signal-tint text-signal-deep'}`}>
                      {n === 3 ? <Check className="h-4 w-4" /> : <TicketIcon />}
                    </span>
                    <div>
                      <p className="font-mono text-xs font-medium text-ink">{ticketLabel(t.ticket)}</p>
                      <p className="text-sm font-medium text-ink">{titleCase(t.issues[0] ?? 'Your request')}</p>
                    </div>
                  </div>
                  {t.opened_at && <span className="text-[11px] text-ink-3 num">{when(t.opened_at)}</span>}
                </div>
                <ol className="mt-3 grid grid-cols-4 gap-1">
                  {STAGES.map((s, j) => (
                    <li key={s} className="min-w-0">
                      <motion.span className="block h-1.5 rounded-full" initial={false}
                        animate={{ backgroundColor: j <= n ? (n === 3 ? 'rgb(38 133 84)' : 'rgb(20 163 154)') : 'rgb(15 27 45 / 0.08)' }} />
                      <span className={`mt-1 block truncate text-[10.5px] ${j === n ? 'font-medium text-ink' : 'text-ink-3'}`}>{s}</span>
                    </li>
                  ))}
                </ol>
                <p className="mt-2 text-xs text-ink-2">{NEXT[n]}</p>
              </article>
              {run && onTicket(run, t) && <Suspense fallback={null}><ResolverCard run={run} view={view} /></Suspense>}
              </motion.div>
            )
          })}
        </AnimatePresence>

        {who && customer?.plan && (
          <div className="rounded-2xl bg-ink p-4 text-paper">
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-paper/50">Your plan</p>
            <p className="mt-1 font-display text-lg font-semibold">{titleCase(customer.plan)}</p>
            <p className="mt-1 text-xs text-paper/70">Gaming late, or a full house streaming? There's more speed when you want it.</p>
            <button className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-paper/10 px-3 py-1.5 text-xs font-medium text-paper transition duration-300 ease-spring hover:bg-paper/20"
              onClick={() => onAsk('What upgrades or offers do you have for me?')}><Sparkle className="h-3.5 w-3.5" />See my offers</button>
          </div>
        )}
      </div>
    </aside>
  )
}
