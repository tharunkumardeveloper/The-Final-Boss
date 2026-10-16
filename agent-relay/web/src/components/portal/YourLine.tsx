import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import type { LabView, RelayEvent } from '../../lib/types'
import { Canvas, FieldDispatch, useDispatch } from '../../pages/Lab'

type Subscribe = (fn: (e: RelayEvent) => void) => () => void

/** The customer's own connection while a case is open: their box, street cabinet, exchange and hub, live, with the
 *  resolver's checks lighting up and the crew driving out if one is sent. Other homes are shown without names. */
export default function YourLine({ tenant, who, subscribe }: { tenant: string; who: string | null; subscribe: Subscribe }) {
  const [view, setView] = useState<LabView>()
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const load = useCallback(() => {
    if (!who) return
    api.lab(tenant, who).then((v) => setView(v.focus === who ? v : undefined)).catch(() => setView(undefined))
  }, [tenant, who])
  useEffect(() => { load() }, [load])
  useEffect(() => subscribe((e) => {
    if (['lab_step', 'lab_state', 'lab_run'].includes(e.type) || (e.type === 'fact_created' && e.data.predicate === 'lives_in')) {
      clearTimeout(timer.current); timer.current = setTimeout(load, 400)
    }
  }), [subscribe, load])
  const run = view?.runs.filter((r) => r.customer === who).sort((a, b) => b.started_at - a.started_at)[0]
  const crew = useDispatch(run)
  const last = run?.steps[run.steps.length - 1]

  if (!who) return <p className="p-6 text-center text-sm text-ink-3">Say hi in the chat and your line shows up here.</p>
  if (!view?.network) return <p className="p-6 text-center text-sm text-ink-3">Tell us where you live in the chat, and your line shows up here.</p>
  return (
    <div className="lab-grid flex h-full flex-col overflow-hidden rounded-[1.75rem] bg-ink p-4 text-white">
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/45">Your line · {view.network.pop.label.replace(' POP', '')}</p>
          <p className="text-sm text-white/80">Your box → street cabinet → exchange → hub → core</p>
        </div>
        {run && <span className={`chip ${run.status === 'running' ? 'bg-conflict/20 text-conflict' : run.status === 'resolved' ? 'bg-current/25 text-white' : 'bg-white/10 text-white/80'}`}>
          {run.status === 'running' ? 'resolver checking' : run.status}</span>}
      </div>
      {last && run?.status === 'running' && <p className="mt-2 shrink-0 text-xs text-white/70">Now: {last.title}</p>}
      <div className="scroll-thin mt-2 flex min-h-0 flex-1 items-center justify-center overflow-auto">
        <Canvas view={view.network} focus={who} dispatch={crew} privateTo={who} />
      </div>
      {crew && <FieldDispatch d={crew} view={view.network} />}
      <p className="mt-2 shrink-0 text-[10.5px] text-white/45">Your home is outlined. Neighbours' homes are shown without names.</p>
    </div>
  )
}
