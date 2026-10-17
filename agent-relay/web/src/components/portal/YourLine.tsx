import type { LabHome, LabRun, LabView } from '../../lib/types'
import { Canvas, EveningChart, HOME_COLOR, HOME_WORD, useDispatch } from '../../pages/Lab'

const LEGEND: LabHome['state'][] = ['ok', 'dark', 'flapping', 'frozen', 'paused', 'slow']

/** The customer's own connection while a case is open: their box, street cabinet, exchange and hub, live, with the
 *  resolver's checks lighting up and the crew driving out if one is sent. Other homes are shown without names.
 *  It always fits its card (no scrolling); the resolver's step-by-step work is on the ticket, in Your tickets. */
export default function YourLine({ who, view, run }: { who: string | null; view?: LabView; run?: LabRun }) {
  const crew = useDispatch(run)
  if (!who || !view?.network) return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-[1.75rem] bg-surface p-6 text-center text-sm text-ink-3 hairline">
      {!who ? 'Say hi in the chat and your line shows up here.' : 'Tell us where you live in the chat, and your line shows up here.'}
    </div>
  )
  const net = view.network
  const me = net.homes.find((h) => h.customer === who)
  const last = run?.steps[run.steps.length - 1]
  const legend = [...LEGEND, ...(LEGEND.includes(me?.state ?? 'ok') ? [] : [me!.state])]
  // one line, always there (so the drawing never jumps): what's happening on this line right now
  const now = crew ? `${crew.tech ? crew.tech.replace(/\b\w/g, (x) => x.toUpperCase()) : 'A technician'} is ${crew.stage === 'enroute' ? 'on the way' : crew.stage === 'onsite' ? 'on site' : crew.stage === 'done' ? 'done, re-measuring' : 'still working on it'}`
    : run?.status === 'running' && last ? `Now: ${last.title}`
      : me?.state === 'reported' ? 'You reported a fault here, so it is marked faulty until a technician checks it'
        : me && me.state !== 'ok' ? `Your line: ${HOME_WORD[me.state]}` : ''
  return (
    <div className="lab-grid flex h-full min-h-0 flex-col overflow-hidden rounded-[1.75rem] bg-ink p-4 text-white">
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/45">Your line · Live network · {net.pop.label}</p>
          <p className="text-sm text-white/80">Core → city hub → area exchange → street cabinet → your home</p>
        </div>
        {run && <span className={`chip ${run.status === 'running' ? 'bg-conflict/20 text-conflict' : run.status === 'resolved' ? 'bg-current/25 text-white' : 'bg-white/10 text-white/80'}`}>
          {run.status === 'running' ? 'resolver on it' : run.status}</span>}
      </div>
      <p className={`mt-1 h-4 shrink-0 truncate text-xs ${me?.state === 'reported' && !crew ? 'text-[#ff9b85]' : 'text-white/70'}`} aria-live="polite">{now}</p>
      <div className="mt-1 min-h-0 flex-1">
        <Canvas view={net} focus={who} dispatch={crew} privateTo={who} fit />
      </div>
      <div className="mt-2 flex shrink-0 flex-wrap gap-x-4 gap-y-1 text-[10.5px] text-white/55">
        {legend.map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: HOME_COLOR[k] }} />{HOME_WORD[k]}</span>
        ))}
        <span className="inline-flex items-center gap-1.5"><i className="h-0.5 w-4 border-t-2 border-dotted border-white/40" />standby link</span>
      </div>
      {!!net.olts.length && (
        <details className="mt-2 shrink-0 rounded-xl bg-white/[0.04] px-3 py-2">
          <summary className="cursor-pointer list-none text-xs text-white/70">Evening load at your exchange</summary>
          {net.olts.map((o) => <div key={o.id} className="mt-2"><EveningChart o={o} /></div>)}
        </details>
      )}
      <p className="mt-2 shrink-0 text-[10.5px] text-white/45">Your home is outlined. Neighbours' homes are shown without names.</p>
    </div>
  )
}
