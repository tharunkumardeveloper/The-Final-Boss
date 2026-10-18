import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, MOCK } from '../../lib/api'
import { tenantLabel, when } from '../../lib/format'
import type { StreamStatus } from '../../lib/stream'
import type { SimStatus, Stats, UsagePayload } from '../../lib/types'
import { Wordmark } from '../Brand'
import { Database, Pause, Play, Pulse, Rewind } from '../Icons'
import { ConsoleNav } from './ConsoleNav'
import { quotaState } from './useConsole'

const SPEEDS = [[0.5, '½'], [1, '1'], [3, '3'], [8, '8']] as const
const PHASE: Record<string, string> = {
  starting: 'Starting the reset…', snapshot: 'Saving a snapshot first…', clearing: 'Clearing and re-seeding the graph…',
  loading: 'Loading the benchmark…', story: 'Playing the demo story through the agents (about two minutes)…',
}

export function TopBar({ tenant, setTenant, stats, sim, setSim, simTime, status, cypherCount, openCypher, onReset, usage }: {
  tenant: string; setTenant: (t: string) => void; stats?: Stats; sim: SimStatus; setSim: (s: SimStatus) => void
  simTime?: string; status: StreamStatus; cypherCount: number; openCypher: () => void; onReset: () => void; usage?: UsagePayload
}) {
  const quota = quotaState(usage)
  const [tenants, setTenants] = useState<string[]>([tenant])
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<string | null>(null)
  const done = useRef(onReset)
  done.current = onReset
  // a reset runs on the server; follow it until it's done (it reports its phase)
  useEffect(() => {
    if (!phase) return
    const id = setInterval(() => api.resetStatus(tenant).then((r) => {
      if (r.phase) setPhase(r.phase)
      else { setPhase(null); done.current() }
    }).catch(() => {}), 1500)
    return () => clearInterval(id)
  }, [phase, tenant])
  useEffect(() => { api.tenants().then((t) => setTenants(t.includes(tenant) ? t : [tenant, ...t])).catch(() => {}) }, [tenant])
  useEffect(() => { if (!confirm) return; const id = setTimeout(() => setConfirm(false), 4000); return () => clearTimeout(id) }, [confirm])

  const toggle = async () => {
    const was = sim
    setSim({ ...sim, running: !sim.running })  // answer the click at once; the server confirms
    try { setSim({ ...was, ...(was.running ? await api.simStop(tenant) : await api.simStart(tenant, was.speed ?? 1)), speed: was.speed }) }
    catch { setSim(was) }
  }
  const speed = async (v: number) => {
    setSim({ ...sim, speed: v })
    if (sim.running) api.simSpeed(tenant, v).catch(() => {})
  }
  const reset = async () => {
    if (!confirm) { setConfirm(true); return }
    setConfirm(false); setBusy(true)
    try { await api.reset(tenant, 'story'); setPhase('starting') } catch { setPhase(null) } finally { setBusy(false) }
  }

  const counters: [string, number | undefined, string?][] = [
    ['current facts', stats?.current_facts], ['superseded', stats?.superseded_facts],
    ['open tickets', stats?.open_tickets], ['conflicts', stats?.conflicts, stats?.conflicts ? 'text-conflict' : ''],
  ]

  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3">
      <Link to="/" aria-label="Customer portal"><Wordmark sub="Operations console" /></Link>

      <div className="flex items-center gap-2 text-xs">
        <label htmlFor="tenant" className="text-ink-3">Tenant</label>
        <select id="tenant" className="rounded-full bg-surface px-2.5 py-1 font-mono text-[11.5px] text-ink hairline outline-none focus:ring-2 focus:ring-signal/40"
          value={tenant} onChange={(e) => setTenant(e.target.value)}>
          {tenants.map((t) => <option key={t} value={t}>{tenantLabel(t)}</option>)}
        </select>
        <span className={`chip ${status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict'}`}>
          <i className={`h-1.5 w-1.5 rounded-full ${status === 'live' ? 'bg-current animate-breathe' : 'bg-conflict'}`} />
          {status === 'live' ? (MOCK ? 'Live · mock' : 'Live') : status === 'connecting' ? 'Connecting' : 'Reconnecting'}
        </span>
      </div>

      <dl className="flex items-center gap-4 text-xs num">
        {counters.map(([k, v, cls]) => (
          <div key={k} className="flex items-baseline gap-1.5"><dd className={`font-display text-base font-semibold ${cls ?? ''}`}>{v ?? '–'}</dd><dt className="text-ink-3">{k}</dt></div>
        ))}
      </dl>

      <div className="ml-auto flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-full bg-surface p-1 hairline" role="group" aria-label="Simulation">
          <button className={`btn h-8 !px-3 !py-0 text-xs ${sim.running ? 'bg-ink text-paper hover:bg-ink/90' : 'text-ink hover:bg-sunk'}`}
            onClick={toggle} disabled={!!phase} aria-label={sim.running ? 'Pause simulation' : 'Start simulation'}>
            {sim.running ? <Pause /> : <Play />}{sim.running ? 'Running' : 'Simulate'}
          </button>
          <div className="flex items-center rounded-full bg-sunk p-0.5" role="radiogroup" aria-label="Simulated hours per second">
            {SPEEDS.map(([v, l]) => (
              <button key={v} role="radio" aria-checked={(sim.speed ?? 1) === v} onClick={() => speed(v)}
                className={`rounded-full px-2 py-0.5 text-[11px] num transition duration-300 ease-spring ${(sim.speed ?? 1) === v ? 'bg-surface font-semibold text-ink shadow-soft' : 'text-ink-3 hover:text-ink'}`}>{l}</button>
            ))}
            <span className="px-1.5 text-[10px] text-ink-3">h/s</span>
          </div>
          <span className="num flex items-center gap-1.5 px-2 text-xs text-ink-2" title="Simulated time (IST)">
            {sim.running && <i className="h-1.5 w-1.5 rounded-full bg-current animate-breathe" />}{simTime ? when(simTime) : 'Clock idle'}
          </span>
        </div>
        {phase ? (
          <span className="chip !py-1.5 bg-signal-tint text-signal-deep" role="status">
            <i className="h-1.5 w-1.5 rounded-full bg-signal animate-breathe" />{PHASE[phase] ?? phase}
          </span>
        ) : (
          <button className={`btn !py-1.5 text-xs hairline ${confirm ? 'bg-conflict-tint text-conflict' : 'bg-surface text-ink-2 hover:bg-sunk'}`} onClick={reset} disabled={busy}>
            <Rewind className="h-4 w-4" />{confirm ? 'Click again: wipes the graph' : 'Reset story'}
          </button>
        )}
        {quota.known && (
          <Link to="/console/usage" title="LLM quota by model"
            className={`chip !py-1.5 transition duration-300 ease-spring ${quota.exhausted ? 'bg-danger-tint text-danger hover:bg-danger-tint/70'
              : quota.near ? 'bg-conflict-tint text-conflict' : 'bg-surface text-ink-2 hairline hover:bg-sunk'}`}>
            <Pulse className="h-3.5 w-3.5" />LLM quota · {quota.exhausted ? `${quota.exhausted} model${quota.exhausted > 1 ? 's' : ''} exhausted`
              : quota.near ? `${quota.near} near limit` : 'all OK'}
          </Link>
        )}
        <button className="btn-ghost !py-1.5 text-xs" onClick={openCypher}><Database className="h-4 w-4" />Cypher <span className="num text-ink-3">{cypherCount}</span></button>
        {!quota.known && <Link className="btn-ghost !py-1.5 text-xs" to="/console/usage" title="LLM quota by model"><Pulse className="h-4 w-4" />Usage</Link>}
      </div>
      <ConsoleNav className="w-full" />
    </header>
  )
}
