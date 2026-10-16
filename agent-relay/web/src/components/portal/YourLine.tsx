import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import type { LabHome, LabView, RelayEvent } from '../../lib/types'
import { Canvas, EveningChart, FieldDispatch, HOME_COLOR, HOME_WORD, useDispatch } from '../../pages/Lab'

type Subscribe = (fn: (e: RelayEvent) => void) => () => void

/** The customer's own connection while a case is open: their box, street cabinet, exchange and hub, live, with the
 *  resolver's checks lighting up and the crew driving out if one is sent. Other homes are shown without names. */
export default function YourLine({ tenant, who, subscribe, onMemory }: { tenant: string; who: string | null; subscribe: Subscribe
  onMemory?: () => void }) {
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

  const back = onMemory && <button onClick={onMemory} className="rounded-full bg-white/10 px-3 py-1 text-xs text-white/85 hover:bg-white/15">← What we remember</button>
  if (!who || !view?.network) return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-[1.75rem] bg-surface p-6 text-center text-sm text-ink-3 hairline">
      {!who ? 'Say hi in the chat and your line shows up here.' : 'Tell us where you live in the chat, and your line shows up here.'}
      {onMemory && <button onClick={onMemory} className="btn-ghost !py-1 text-xs hairline">← What we remember</button>}
    </div>
  )
  return (
    <div className="lab-grid flex h-full flex-col overflow-hidden rounded-[1.75rem] bg-ink p-4 text-white">
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/45">Your line · Live network · {view.network.pop.label}</p>
          <p className="text-sm text-white/80">Core → city hub → area exchange → street cabinet → your home</p>
        </div>
        <div className="flex items-center gap-2">
          {run && <span className={`chip ${run.status === 'running' ? 'bg-conflict/20 text-conflict' : run.status === 'resolved' ? 'bg-current/25 text-white' : 'bg-white/10 text-white/80'}`}>
            {run.status === 'running' ? 'resolver on it' : run.status}</span>}
          {back}
        </div>
      </div>
      {last && run?.status === 'running' && <p className="mt-2 shrink-0 text-xs text-white/70">Now: {last.title}</p>}
      <div className="scroll-thin mt-2 flex min-h-0 flex-1 items-center justify-center overflow-auto">
        <Canvas view={view.network} focus={who} dispatch={crew} privateTo={who} />
      </div>
      {crew && <FieldDispatch d={crew} view={view.network} />}
      {/* the same legend and evening load as the Lab's live network */}
      <div className="mt-2 flex shrink-0 flex-wrap gap-x-4 gap-y-1 text-[10.5px] text-white/55">
        {(['ok', 'dark', 'flapping', 'frozen', 'paused', 'slow'] as LabHome['state'][]).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: HOME_COLOR[k] }} />{HOME_WORD[k]}</span>
        ))}
        <span className="inline-flex items-center gap-1.5"><i className="h-0.5 w-4 border-t-2 border-dotted border-white/40" />standby link</span>
      </div>
      {!!view.network.olts.length && (
        <details className="mt-2 shrink-0 rounded-xl bg-white/[0.04] px-3 py-2">
          <summary className="cursor-pointer list-none text-xs text-white/70">Evening load at your exchange</summary>
          {view.network.olts.map((o) => <div key={o.id} className="mt-2"><EveningChart o={o} /></div>)}
        </details>
      )}
      <p className="mt-2 shrink-0 text-[10.5px] text-white/45">Your home is outlined. Neighbours' homes are shown without names.</p>
    </div>
  )
}
