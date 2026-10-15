import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Close, Warning } from '../components/Icons'
import { mergeUsage, quotaState } from '../components/console/useConsole'
import { api } from '../lib/api'
import { useRelayStream } from '../lib/stream'
import { useTenant } from '../lib/tenant'
import type { Usage, UsagePayload } from '../lib/types'

const n = (v?: number | null) => (v == null ? '—' : v.toLocaleString('en-IN'))
const short = (m: string) => m.replace(/^gemini:/, '')

const frac = (used: number, limit: number | null) => (limit ? used / limit : null)

function Meter({ label, used, limit, hint }: { label: string; used: number; limit: number | null; hint?: string }) {
  const f = frac(used, limit)
  const tone = f === null ? 'bg-ink-3/40' : f >= 1 ? 'bg-danger' : f >= 0.85 ? 'bg-conflict' : 'bg-signal-deep'
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-ink-2">{label}</span>
        <span className="num text-ink"><strong className="font-semibold">{n(used)}</strong><span className="text-ink-3"> / {limit == null ? 'no known limit' : n(limit)}</span></span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sunk" role="meter" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit ?? undefined}>
        <div className={`h-full rounded-full transition-[width] duration-700 ease-spring ${tone}`} style={{ width: `${Math.min(100, (f ?? 0) * 100)}%` }} />
      </div>
      {hint && <p className="mt-1 text-[11px] text-ink-3">{hint}</p>}
    </div>
  )
}

function LimitsForm({ u, onSaved, onCancel }: { u: Usage; onSaved: (p: UsagePayload) => void; onCancel: () => void }) {
  const [v, setV] = useState({ rpm: u.limits.rpm, rpd: u.limits.rpd, tpm: u.limits.tpm, tpd: u.limits.tpd })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(undefined)
    try { onSaved(await api.putLimits({ model: u.model, ...v })) } catch { setErr("Couldn't save the limits.") } finally { setBusy(false) }
  }
  return (
    <form onSubmit={save} className="mt-4 rounded-xl bg-sunk/60 p-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(['rpm', 'rpd', 'tpm', 'tpd'] as const).map((k) => (
          <label key={k} className="text-[11px] text-ink-3">
            {{ rpm: 'Requests / min', rpd: 'Requests / day', tpm: 'Tokens / min', tpd: 'Tokens / day' }[k]}
            <input type="number" min={0} className="field mt-1 !py-1.5 num" value={v[k] ?? ''} placeholder="unknown"
              onChange={(e) => setV({ ...v, [k]: e.target.value === '' ? null : Number(e.target.value) })} />
          </label>
        ))}
      </div>
      {err && <p className="mt-2 text-xs text-danger" role="alert">{err}</p>}
      <div className="mt-3 flex gap-2">
        <button className="btn-primary !py-1.5 text-xs" disabled={busy}>Save limits</button>
        <button type="button" className="btn-ghost !py-1.5 text-xs" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

/** A clock that ticks every second, so "checked 12 s ago" and "back in 4:05" stay true while you watch. */
function useNow() {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id) }, [])
  return now
}

const ago = (iso: string | null | undefined, now: number) => {
  if (!iso) return null
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
}
const clock = (s: number) => `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)}:` : ''}${String(Math.floor((s % 3600) / 60)).padStart(Math.floor(s / 3600) ? 2 : 1, '0')}:${String(s % 60).padStart(2, '0')}`
const PROVIDER: Record<string, string> = { groq: 'Groq · key 1', groq2: 'Groq · key 2', groq3: 'Groq · key 3', groq4: 'Groq · key 4',
  groq5: 'Groq · key 5', gemini: 'Gemini', sarvam: 'Sarvam' }
const STATE: Record<string, string> = {
  available: 'bg-current-tint text-current', 'rate limited': 'bg-conflict-tint text-conflict', exhausted: 'bg-danger-tint text-danger',
  recovering: 'bg-conflict-tint text-conflict', 'not checked yet': 'bg-sunk text-ink-2', 'no key': 'bg-sunk text-ink-3',
}

function ModelCard({ u, onSaved, now }: { u: Usage; onSaved: (p: UsagePayload) => void; now: number }) {
  const [edit, setEdit] = useState(false)
  const [checking, setChecking] = useState(false)
  const live = u.live
  const state = u.state ?? (u.exhausted ? 'exhausted' : 'available')
  const backIn = u.back_at ? Math.max(0, Math.round((new Date(u.back_at).getTime() - now) / 1000)) : null
  const check = async () => { setChecking(true); try { onSaved(await api.checkModels(u.model)) } finally { setChecking(false) } }
  return (
    <article className={`panel p-5 ${u.exhausted ? 'ring-1 ring-danger/30' : ''}`}>
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="font-mono text-sm font-medium text-ink">{short(u.model)}</h3>
        <span className="chip bg-sunk text-ink-2">{PROVIDER[u.provider] ?? u.provider}</span>
        <span className={`chip ${STATE[state] ?? 'bg-sunk text-ink-2'}`} aria-live="polite">
          {(state === 'exhausted' || state === 'rate limited') && <Warning className="h-3.5 w-3.5" />}
          {state[0].toUpperCase() + state.slice(1)}{backIn ? ` · back in ${clock(backIn)}` : ''}
        </span>
        <span className="ml-auto flex flex-wrap gap-1">{u.jobs.map((j) => <span key={j} className="chip bg-signal-tint text-signal-deep">{j}</span>)}</span>
      </header>
      <p className="mt-2 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-3 num">
        <span>{u.checked_at ? `Last real answer or error ${ago(u.checked_at, now)}` : 'No request since the server started today'}</span>
        {u.latency_ms != null && state === 'available' && <span>· answered in {(u.latency_ms / 1000).toFixed(1)} s</span>}
        <button className="btn-ghost ml-auto !py-0.5 text-[11px]" onClick={check} disabled={checking || state === 'no key'}
          title="Sends one tiny request (a few tokens) and shows what the provider says right now">{checking ? 'Checking…' : 'Check now'}</button>
      </p>

      <div className="mt-4 space-y-3">
        <Meter label="Requests today" used={u.used.requests} limit={u.limits.rpd}
          hint={live?.remaining_requests_day != null ? `${n(live.remaining_requests_day)} left, from Groq headers${live.reset_requests ? ` · resets in ${live.reset_requests}` : ''}`
            : u.remaining.requests != null ? `${n(u.remaining.requests)} left (counted on this server)` : undefined} />
        <Meter label="Tokens today" used={u.used.tokens} limit={u.limits.tpd}
          hint={u.remaining.tokens != null ? `${n(u.remaining.tokens)} left (counted on this server)` : undefined} />
        {live?.remaining_tokens_minute != null && (
          <p className="text-[11px] text-ink-3 num">This minute: {n(live.remaining_tokens_minute)} of {n(live.limit_tokens_minute)} tokens left, from Groq headers{live.reset_tokens ? ` · resets in ${live.reset_tokens}` : ''}</p>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-xs num sm:grid-cols-4">
        {[['Tokens in', u.used.tokens_in], ['Tokens out', u.used.tokens_out], ['Cache hits', u.used.cache_hits], ['Rate-limit hits', u.used.rate_limited]].map(([k, v]) => (
          <div key={k as string}><dt className="text-ink-3">{k}</dt><dd className={`mt-0.5 font-display text-base font-semibold ${k === 'Rate-limit hits' && Number(v) > 0 ? 'text-conflict' : ''}`}>{n(v as number)}</dd></div>
        ))}
      </dl>

      {u.last_error && <p className="mt-3 break-words rounded-lg bg-danger-tint/60 px-2.5 py-1.5 font-mono text-[11px] text-danger">{u.last_error}</p>}
      {edit ? <LimitsForm u={u} onSaved={(p) => { onSaved(p); setEdit(false) }} onCancel={() => setEdit(false)} />
        : <button className="btn-ghost -ml-3 mt-3 !py-1.5 text-xs" onClick={() => setEdit(true)}>Edit limits</button>}
    </article>
  )
}

function RouteEditor({ job, models, all, onSaved }: { job: string; models: string[]; all: string[]; onSaved: (p: UsagePayload) => void }) {
  const [list, setList] = useState(models)
  const [busy, setBusy] = useState(false)
  useEffect(() => setList(models), [models])
  const dirty = list.join('|') !== models.join('|')
  const move = (i: number, d: number) => { const l = [...list]; [l[i], l[i + d]] = [l[i + d], l[i]]; setList(l) }
  const spare = all.filter((m) => !list.includes(m))
  return (
    <li className="flex flex-wrap items-center gap-2 py-3">
      <span className="w-20 shrink-0 font-medium text-ink">{job}</span>
      <ol className="flex flex-wrap items-center gap-1.5">
        {list.map((m, i) => (
          <li key={m} className="flex items-center gap-0.5 rounded-full bg-sunk py-0.5 pl-2.5 pr-1 text-xs">
            <span className="num mr-1 text-ink-3">{i + 1}</span><span className="font-mono text-ink">{short(m)}</span>
            <button className="ml-1 rounded-full px-1 text-ink-3 hover:text-ink disabled:opacity-30" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${m} up`}>←</button>
            <button className="rounded-full px-1 text-ink-3 hover:text-ink disabled:opacity-30" onClick={() => move(i, 1)} disabled={i === list.length - 1} aria-label={`Move ${m} down`}>→</button>
            <button className="rounded-full p-0.5 text-ink-3 hover:text-danger disabled:opacity-30" onClick={() => setList(list.filter((x) => x !== m))} disabled={list.length === 1} aria-label={`Remove ${m}`}><Close className="h-3.5 w-3.5" /></button>
          </li>
        ))}
      </ol>
      {spare.length > 0 && (
        <select aria-label={`Add a model to ${job}`} className="rounded-full bg-surface px-2 py-1 text-xs text-ink-2 hairline outline-none" value=""
          onChange={(e) => e.target.value && setList([...list, e.target.value])}>
          <option value="">+ add fallback</option>
          {spare.map((m) => <option key={m} value={m}>{short(m)}</option>)}
        </select>
      )}
      {dirty && (
        <span className="ml-auto flex gap-1.5">
          <button className="btn-primary !py-1 text-xs" disabled={busy} onClick={async () => { setBusy(true); try { onSaved(await api.putRoutes(job, list)) } finally { setBusy(false) } }}>Save</button>
          <button className="btn-ghost !py-1 text-xs" onClick={() => setList(models)}>Undo</button>
        </span>
      )}
    </li>
  )
}

export default function UsagePage() {
  const { tenant } = useTenant()
  const [data, setData] = useState<UsagePayload>()
  const [error, setError] = useState(false)
  const [checkingAll, setCheckingAll] = useState(false)
  const now = useNow()
  const load = () => api.usage().then((d) => { setData(d); setError(false) }).catch(() => setError(true))
  useEffect(() => { load() }, [])
  // live: every call any process makes is pushed here; on reconnect, refetch so nothing shown is stale
  const status = useRelayStream(tenant, (e) => { if (e.type === 'usage') setData((p) => mergeUsage(p, e.data)) }, load)
  const q = quotaState(data)
  const totals = (data?.models ?? []).reduce((a, m) => ({ req: a.req + m.used.requests, cache: a.cache + m.used.cache_hits }), { req: 0, cache: 0 })

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Link to="/console"><Wordmark sub="LLM usage" /></Link>
        <Link to="/console" className="btn-ghost text-sm">Back to console</Link>
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">Model quota today</h1>
            <p className="mt-2 max-w-2xl text-ink-2">Each job runs on its own model so free daily limits stack. When a model is rate-limited or out for the day, the router falls through to the next one in that job's chain.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs num">
            {data && <span className="chip bg-surface text-ink-2 hairline">{data.date} IST</span>}
            <span className={`chip ${status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict'}`}>{status === 'live' ? 'Live' : 'Reconnecting'}</span>
            {q.exhausted > 0 && <span className="chip bg-danger-tint text-danger">{q.exhausted} exhausted</span>}
            {q.near > 0 && <span className="chip bg-conflict-tint text-conflict">{q.near} near a limit</span>}
            <span className="chip bg-sunk text-ink-2">{n(totals.req)} calls · {n(totals.cache)} served from cache</span>
            <button className="btn-ghost !py-1 text-xs" disabled={checkingAll}
              onClick={async () => { setCheckingAll(true); try { setData(await api.checkModels()) } finally { setCheckingAll(false) } }}
              title="One tiny real request to every model in the routes">{checkingAll ? 'Checking all…' : 'Check all now'}</button>
          </div>
        </div>

        {error && <p className="mt-8 text-sm text-danger" role="alert">Couldn't load usage. Is the API running?</p>}
        {!data && !error && <div className="mt-10 h-48 animate-breathe rounded-2xl bg-sunk" aria-busy="true" />}

        {data && (
          <>
            <section className="mt-8 grid gap-4 lg:grid-cols-2">
              {data.models.map((u) => <ModelCard key={u.model} u={u} onSaved={setData} now={now} />)}
            </section>
            <section className="panel mt-6 p-6">
              <h2 className="eyebrow">Routing</h2>
              <p className="mt-1 text-sm text-ink-3">Order is the fallback chain: the first available model serves the job. The benchmark pins its answer model, so changes here don't affect fairness.</p>
              <ul className="mt-3 divide-y divide-line/[0.06]">
                {Object.entries(data.routes).map(([job, models]) => (
                  <RouteEditor key={job} job={job} models={models} all={data.models.map((m) => m.model)} onSaved={setData} />
                ))}
              </ul>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
