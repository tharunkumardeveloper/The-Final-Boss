import { useState } from 'react'
import { api } from '../../lib/api'
import { ticketLabel, titleCase, when } from '../../lib/format'
import type { CypherEntry, PickupResponse, Ticket } from '../../lib/types'

const ORDER = ['open', 'in progress', 'waiting on customer', 'resolved']
const STATUS_CHIP: Record<string, string> = {
  open: 'bg-signal-tint text-signal-deep', 'in progress': 'bg-ink text-paper',
  'waiting on customer': 'bg-conflict-tint text-conflict', resolved: 'bg-current-tint text-current',
}

function TicketRow({ tenant, t, logCypher, refresh }: { tenant: string; t: Ticket; logCypher: (a: string, e?: CypherEntry[]) => void; refresh: () => void }) {
  const [open, setOpen] = useState(false)
  const [work, setWork] = useState<PickupResponse>()
  const [fix, setFix] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn() } finally { setBusy(false); refresh() } }
  const pickup = () => run(async () => { const r = await api.pickup(tenant, t.ticket); setWork(r); logCypher(`pick up ${ticketLabel(t.ticket)}`, r.cypher) })
  const record = (worked: boolean, f = fix) => run(async () => { const r = await api.fix(tenant, t.ticket, f.trim(), worked); logCypher(`fix ${ticketLabel(t.ticket)}`, r.cypher); setFix('') })

  return (
    <li className="rounded-xl bg-surface hairline">
      <button className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="font-mono text-xs font-medium text-ink">{ticketLabel(t.ticket)}</span>
        <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{titleCase(t.customer)} · {t.issues.join(', ') || 'no issue yet'}</span>
        <span className={`chip ${STATUS_CHIP[t.status] ?? 'bg-sunk text-ink-2'}`}>{t.status}</span>
      </button>
      {open && (
        <div className="space-y-3 px-3.5 pb-3.5 text-sm animate-rise">
          <p className="text-xs text-ink-3">Assigned to <span className="font-medium text-ink">{t.assigned_to ?? 'nobody'}</span>{t.opened_at ? ` · opened ${when(t.opened_at)}` : ''}</p>
          {t.trail.length > 0 && (
            <ol className="relative ml-1.5 space-y-1.5 border-l border-line/10 pl-3.5">
              {t.trail.map((s, i) => (
                <li key={i} className="text-xs text-ink-2"><span className="num text-ink-3">{when(s.at)}</span> · <span className="font-medium text-ink">{s.agent}</span> {s.action}{s.to ? ` → ${s.to}` : ''}{s.note ? <span className="text-ink-3"> · {s.note}</span> : null}</li>
              ))}
            </ol>
          )}
          {t.status !== 'resolved' && (
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary !py-1.5 text-xs" onClick={pickup} disabled={busy}>Pick up as resolver</button>
            </div>
          )}
          {work && (
            <div className="rounded-lg bg-sunk/60 p-3 text-xs">
              {work.observations.map((o) => <p key={o} className="font-mono text-ink-2">{o}</p>)}
              {work.suggestions.map((s) => (
                <p key={s.fix} className="mt-2 text-ink">
                  Worked before for {s.for_issue ?? s.issue} ({s.worked_before}×{s.for_issue && s.for_issue !== s.issue && s.distance != null ? `, similar issue, distance ${s.distance.toFixed(2)}` : ''}): <strong>{s.fix}</strong>
                  <button className="ml-2 font-medium text-signal-deep underline-offset-2 hover:underline" onClick={() => record(true, s.fix)} disabled={busy}>It worked</button>
                </p>
              ))}
            </div>
          )}
          {t.status !== 'resolved' && (
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (fix.trim()) record(true) }}>
              <label htmlFor={`fix-${t.ticket}`} className="sr-only">Fix tried</label>
              <input id={`fix-${t.ticket}`} className="field !py-1.5 text-xs" placeholder="Fix tried, e.g. replace optical cable" value={fix} onChange={(e) => setFix(e.target.value)} />
              <button className="btn-signal !py-1.5 text-xs" disabled={busy || !fix.trim()}>Worked</button>
              <button type="button" className="btn-ghost !py-1.5 text-xs" disabled={busy || !fix.trim()} onClick={() => record(false)}>Didn't</button>
            </form>
          )}
        </div>
      )}
    </li>
  )
}

export function Tickets({ tenant, tickets, logCypher, refresh }: { tenant: string; tickets: Ticket[]; logCypher: (a: string, e?: CypherEntry[]) => void; refresh: () => void }) {
  if (!tickets.length) return <p className="px-5 py-8 text-sm text-ink-3">No tickets yet. Intake opens one when a customer reports a problem.</p>
  const sorted = [...tickets].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
  return <ul className="space-y-2 px-4 py-4">{sorted.map((t) => <TicketRow key={t.ticket} tenant={tenant} t={t} logCypher={logCypher} refresh={refresh} />)}</ul>
}
