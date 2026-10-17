import { COMPANY, TAGLINE } from '../lib/brand'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ArrowUpRight, Check, Wifi } from '../components/Icons'
import { MemoryPanel } from '../components/portal/MemoryPanel'
import { JudgeBar, useJudge } from '../components/portal/JudgeMode'
import { SupportDesk, type ChatDriver } from '../components/portal/SupportChat'
import { TicketsPanel } from '../components/portal/TicketsPanel'
import type { Chip } from '../lib/chips'

// the graph canvas is heavy; it loads once someone is chatting
const MyGraph = lazy(() => import('../components/portal/MyGraph'))
const YourLine = lazy(() => import('../components/portal/YourLine'))
import { api } from '../lib/api'
import { flag, titleCase } from '../lib/format'
import { activeOutages, applyEvent, emptyGraph, loadGraph } from '../lib/graph'
import { useLine } from '../lib/line'
import { useRelayStream } from '../lib/stream'
import { useTenant } from '../lib/tenant'
import type { Customer, Kb, Region, RelayEvent } from '../lib/types'

const PLANS = [
  { name: 'Fiber 100', price: '₹599', speed: '100 Mbps', note: 'Streaming and work calls for a small home.', perks: ['PML Hub 6 router', 'Unlimited data'] },
  { name: 'Fiber 300', price: '₹899', speed: '300 Mbps', note: 'Gaming, 4K and a full house online at once.', perks: ['PML Hub 6 router', 'Priority support'], featured: true },
  { name: 'Fiber 1000', price: '₹1,499', speed: '1 Gbps', note: 'Creators, home offices and big uploads.', perks: ['Hub 6 Pro + mesh extender', 'Static IP included'] },
]
const FALLBACK_CITIES = ['pune', 'mumbai', 'bengaluru', 'hyderabad'].map((c) => ({ city: titleCase(c), key: c, areas: [] as string[] }))
const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1)
// Plans come from the company knowledge in the graph (GET /kb?country=), in local currency; constants are a fallback.
const plansFrom = (kb?: Kb) => kb?.plans.length
  ? kb.plans.map((p) => ({ name: p.name, price: p.price_label, speed: p.speed_mbps >= 1000 ? `${p.speed_mbps / 1000} Gbps` : `${p.speed_mbps} Mbps`,
    note: p.notes, perks: [`About ${p.devices} devices`, ...p.includes.map(cap)], featured: p.key === 'fiber 300' }))
  : PLANS

type Line = ReturnType<typeof useLine>

/** Tickets and memory share one full-height panel, so each has room; it jumps to Tickets when one opens.
 *  The resolver's work shows under the ticket it's on. */
function AccountPanel({ tenant, who, customer, chips, subscribe, onAsk, line, force }: { tenant: string; who: string | null; customer?: Customer
  chips: Chip[]; subscribe: (fn: (e: RelayEvent) => void) => () => void; onAsk: (t: string) => void; line: Line
  force?: { tab: 'tickets' | 'memory'; n: number } }) {
  const [tab, setTab] = useState<'tickets' | 'memory'>('memory')
  const [fresh, setFresh] = useState<{ tickets: boolean; memory: boolean }>({ tickets: false, memory: false })
  useEffect(() => { if (force) setTab(force.tab) }, [force])  // Judge mode points at what to watch
  const settled = chips.filter((c) => c.phase === 'settled').length
  useEffect(() => subscribe((e) => {
    if (e.type === 'ticket_opened' && e.data.customer === who) setTab('tickets')
    else if ((e.type === 'pickup' || e.type === 'ticket_status' || (e.type === 'message' && e.data.speaker === 'resolver' && e.data.customer === who)))
      setFresh((f) => ({ ...f, tickets: true }))
  }), [subscribe, who])
  useEffect(() => { if (settled) setFresh((f) => ({ ...f, memory: true })) }, [settled])
  const pick = (t: 'tickets' | 'memory') => { setTab(t); setFresh((f) => ({ ...f, [t]: false })) }
  return (
    <div className="flex h-[700px] min-h-0 flex-col gap-3 xl:h-auto">
      <div className="flex rounded-full bg-surface p-1 hairline" role="tablist" aria-label="Your account">
        {([['tickets', 'Your tickets'], ['memory', 'What we remember']] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => pick(k)}
            className={`relative flex-1 rounded-full px-4 py-2 text-sm font-medium transition duration-300 ease-spring ${tab === k ? 'bg-ink text-paper shadow-soft' : 'text-ink-2 hover:bg-sunk'}`}>
            {label}
            {fresh[k] && tab !== k && <i className="absolute right-3 top-2 h-2 w-2 rounded-full bg-signal animate-breathe" aria-label="new" />}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'tickets'
          ? <TicketsPanel tenant={tenant} who={who} customer={customer} subscribe={subscribe} onAsk={onAsk} run={line.run} view={line.view} />
          : <MemoryPanel who={who} customer={customer} chips={chips} tenant={tenant} />}
      </div>
    </div>
  )
}

/** The third card. Memory while the customer is talking; once they have a line (a place) and a case (a ticket, or the
 *  resolver on it), it becomes two tabs and opens on the network lab: their line live. The resolver's step-by-step work
 *  is under the ticket in Your tickets, so the diagram keeps the whole card. */
function GraphOrLine({ tenant, who, subscribe, line, force }: { tenant: string; who: string | null; subscribe: (fn: (e: RelayEvent) => void) => () => void
  line: Line; force?: { mode: 'memory' | 'line'; n: number } }) {
  const [mode, setMode] = useState<'memory' | 'line'>('memory')
  const [hasCase, setHasCase] = useState(false)
  const auto = useRef(false)  // already opened the lab for this case: a manual switch back sticks
  useEffect(() => { if (force) { setMode(force.mode); auto.current = true } }, [force])  // Judge mode points at what to watch
  const { hasLine, reload } = line
  useEffect(() => {  // a returning customer with a case still open gets the tabs straight away
    setMode('memory'); setHasCase(false); auto.current = false
    if (!who) return
    api.tickets(tenant).then((ts) => setHasCase(ts.some((t) => t.customer === who && t.status !== 'resolved'))).catch(() => {})
  }, [tenant, who])
  useEffect(() => subscribe((e) => {
    const d = e.data as { customer?: string; subject?: string; speaker?: string; status?: string }
    if (!who || (d?.customer ?? d?.subject)?.toLowerCase() !== who) return
    // the resolver speaking in their chat is the surest sign it is on the case (its run events can arrive first or not at all)
    if (e.type === 'ticket_opened' || (e.type === 'message' && d.speaker === 'resolver') || (e.type === 'lab_run' && d.status === 'running')) {
      setHasCase(true)
      if (e.type !== 'ticket_opened' && !hasLine) reload()  // the resolver only works on a line it found
    }
  }), [subscribe, who, hasLine, reload])
  const tabs = !!who && (hasCase || !!line.run) && hasLine
  useEffect(() => { if (tabs && !auto.current) { auto.current = true; setMode('line') } }, [tabs])
  const show = tabs ? mode : 'memory'
  return (
    <div className="flex h-full min-h-[560px] flex-col gap-2 xl:min-h-0">
      {tabs && (
        <div className="flex shrink-0 gap-1 self-start rounded-full bg-surface p-1 hairline" role="tablist" aria-label="Your graphs">
          {([['line', 'Network lab'], ['memory', 'What we remember']] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={show === k} onClick={() => setMode(k)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${show === k ? 'bg-ink text-paper' : 'text-ink-2 hover:bg-paper'}`}>
              {k === 'line' && <i className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-conflict align-middle" />}{label}</button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1">
        <Suspense fallback={null}>
          {show === 'memory'
            ? <MyGraph tenant={tenant} who={who} subscribe={subscribe} />
            : <YourLine who={who} view={line.view} run={line.run} />}
        </Suspense>
      </div>
    </div>
  )
}

export default function Portal() {
  const { tenant, setTenant } = useTenant()
  const graph = useRef(emptyGraph())
  const [, bump] = useState(0)
  const [customers, setCustomers] = useState<Customer[]>([])
  const [tenants, setTenants] = useState<string[]>([tenant])
  const [kb, setKb] = useState<Kb>()
  const [country, setCountry] = useState<string>()
  const [regions, setRegions] = useState<Region[]>([])
  // First visit: start on the desk and country the visitor is browsing from (timezone, then language; no IP lookup).
  // A region or country picked by hand is remembered and wins from then on.
  useEffect(() => {
    try { if (localStorage.getItem('wifight.place.v2')) return } catch { return }
    api.locate(Intl.DateTimeFormat().resolvedOptions().timeZone, navigator.language).then((r) => {
      if (!r.country || !r.tenant) return
      if (r.tenant !== tenant) setTenant(r.tenant)
      setCountry(r.country)
      try { localStorage.setItem('wifight.place.v2', 'auto') } catch { /* private mode */ }
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.regions().then(setRegions).catch(() => {}) }, [])
  // Switching region clears the old region's data at once, and a late answer for the region we left is dropped:
  // the browser test showed India prices under "North America" while the new region was still loading.
  const current = useRef(tenant)
  current.current = tenant
  useEffect(() => { setCountry(undefined); setCustomers([]); graph.current = emptyGraph(); bump((n) => n + 1) }, [tenant])
  useEffect(() => {
    setKb(undefined)
    api.kb(tenant, country).then((k) => { if (current.current === tenant) setKb(k) }).catch(() => {})
  }, [tenant, country])
  const cities = kb?.coverage.length ? kb.coverage : tenant === 'pml' ? FALLBACK_CITIES : []
  const [who, setWho] = useState<string | null>(null)
  const [chips, setChips] = useState<Chip[]>([])
  const typeRef = useRef<((text: string) => void) | null>(null)
  const listeners = useRef(new Set<(e: RelayEvent) => void>())
  const refetch = useRef<ReturnType<typeof setTimeout>>()
  const subscribe = useCallback((fn: (e: RelayEvent) => void) => { listeners.current.add(fn); return () => { listeners.current.delete(fn) } }, [])
  const line = useLine(tenant, who, subscribe)  // their line + the resolver's run: one feed for the lab and the tickets
  // Judge mode: the story played through the real agents, nobody typing; it points the side cards at what to watch
  const driveRef = useRef<ChatDriver | null>(null)
  const [forceTab, setForceTab] = useState<{ tab: 'tickets' | 'memory'; n: number }>()
  const [forceMode, setForceMode] = useState<{ mode: 'memory' | 'line'; n: number }>()
  const onStep = useCallback((n: number) => {
    if (n === 3) { setForceTab({ tab: 'tickets', n }); setForceMode({ mode: 'line', n }) }
    if (n === 4 || n === 5) { setForceTab({ tab: 'memory', n }); setForceMode({ mode: 'memory', n }) }
  }, [])
  const judge = useJudge({ drive: driveRef, run: line.run, tenant, setTenant, customers, onStep })
  const judgeStart = useRef(judge.start)
  judgeStart.current = judge.start
  useEffect(() => {  // ?judge=1 (the README's link) starts it on arrival
    try { if (new URLSearchParams(window.location.search).get('judge') !== '1') return } catch { return }
    const id = setTimeout(() => judgeStart.current(), 1500)
    return () => clearTimeout(id)
  }, [])

  const refresh = useCallback(() => {
    api.graph(tenant).then((g) => {
      if (current.current !== tenant) return
      graph.current = loadGraph(emptyGraph(), g); bump((n) => n + 1)
    }).catch(() => {})
    api.customers(tenant).then((c) => { if (current.current === tenant) setCustomers(c) }).catch(() => {})
  }, [tenant])
  useEffect(refresh, [refresh])
  useEffect(() => { api.tenants().then((t) => setTenants(t.includes(tenant) ? t : [tenant, ...t])).catch(() => {}) }, [tenant])
  // One socket for the page: outage banner + the chat's live updates.
  const status = useRelayStream(tenant, (e) => {
    if (applyEvent(graph.current, e)) {
      bump((n) => n + 1)
      clearTimeout(refetch.current) // keep the panel's "On file" in step, one refetch per burst
      refetch.current = setTimeout(() => api.customers(tenant).then(setCustomers).catch(() => {}), 700)
    }
    listeners.current.forEach((fn) => fn(e))
  }, refresh)

  // outages only mark cities as Degraded in Coverage (and Mr.Fix-It knows them); no site-wide banner
  const down = new Set(activeOutages(graph.current).map((o) => o.city))

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-[1360px] items-center justify-between px-4 py-4 sm:px-6">
        <Wordmark />
        <nav className="flex flex-wrap items-center gap-1 text-sm" aria-label="Main">
          {regions.length > 0 && (
            <label className="flex items-center gap-1.5 rounded-full bg-surface px-3 py-1.5 text-xs text-ink-2 hairline">
              <span className="sr-only">Region</span>
              {/* a one-country region (India) has no Country menu to carry the flag, so it sits by the region name */}
              {kb && kb.countries.length <= 1 && kb.country && <span aria-hidden className="text-sm leading-none">{flag(kb.country)}</span>}
              <select aria-label="Region" className="bg-transparent outline-none" value={regions.find((r) => r.tenant === tenant)?.tenant ?? tenant}
                onChange={(e) => setTenant(e.target.value)}>
                {regions.map((r) => <option key={r.code} value={r.tenant}>{r.name}</option>)}
              </select>
              {kb && kb.countries.length > 1 && (
                <select aria-label="Country" className="bg-transparent outline-none" value={kb.country} onChange={(e) => { setCountry(e.target.value); try { localStorage.setItem('wifight.place.v2', 'picked') } catch { /* private */ } }}>
                  {kb.countries.map((c) => <option key={c.iso} value={c.iso}>{flag(c.iso)} {c.name}</option>)}
                </select>
              )}
            </label>
          )}
          <a href="#plans" className="btn-ghost hidden sm:inline-flex">Plans</a>
          <a href="#coverage" className="btn-ghost hidden sm:inline-flex">Coverage</a>
          <Link to="/console" className="btn-ghost">Staff console <ArrowUpRight className="h-4 w-4" /></Link>
        </nav>
      </header>

      <main>
        <section className="mx-auto max-w-[1360px] px-4 pb-16 sm:px-6">
          <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-2 pb-5 pt-2 animate-rise">
            <h1 className="font-display text-[32px] font-semibold leading-[1.05] tracking-[-0.02em] sm:text-[40px]">{TAGLINE}</h1>
            <div className="flex max-w-xl flex-wrap items-end gap-4 pb-1">
              <p className="max-w-md text-[15px] leading-relaxed text-ink-2">
                Fiber broadband in {kb?.stats.countries ?? 39} countries, from {kb ? (kb.coverage[0]?.city ?? 'Pune') : 'Pune'} to wherever you move next.
                Tell us once and we'll remember it, whoever you talk to next.
              </p>
              {judge.status !== 'running' && (
                <button onClick={judge.start} className="btn-signal shrink-0 !py-2 text-sm" title="Plays the whole story through the real agents, nobody typing">
                  <span aria-hidden>▶</span> Watch it work <span className="font-normal opacity-80">· ~2 min, no typing</span>
                </button>
              )}
            </div>
          </div>
          <JudgeBar judge={judge} />
          {/* chat | your tickets + what we remember | your graph */}
          <div className="grid animate-rise gap-4 [animation-delay:100ms] lg:grid-cols-[380px_minmax(0,1fr)] xl:h-[calc(100dvh-210px)] xl:min-h-[660px] xl:max-h-[940px] xl:grid-cols-[380px_minmax(340px,1fr)_minmax(0,1fr)]">
            <div className="h-[700px] min-h-0 xl:h-auto">
              <SupportDesk tenant={tenant} customers={customers} subscribe={subscribe} side="none" onWho={setWho} onChips={setChips} typeRef={typeRef}
                driveRef={driveRef} country={kb?.country} />
            </div>
            <AccountPanel tenant={tenant} who={who} customer={customers.find((c) => c.key === who)} chips={chips} subscribe={subscribe}
              onAsk={(t) => typeRef.current?.(t)} line={line} force={forceTab} />
            <div className="h-[600px] lg:col-span-2 xl:col-span-1 xl:h-auto xl:min-h-0">
              <GraphOrLine tenant={tenant} who={who} subscribe={subscribe} line={line} force={forceMode} />
            </div>
          </div>
          <dl className="mt-6 flex flex-wrap gap-x-10 gap-y-3 num">
            {[['24×7', 'AI desk, human backup'], ['0', 'times you repeat yourself'], [`${kb?.stats.countries ?? 39}`, 'countries'],
              [`${kb?.stats.cities ?? 199}`, 'cities on fiber']].map(([v, k]) => (
              <div key={k} className="flex items-baseline gap-2"><dt className="sr-only">{k}</dt><dd className="font-display text-xl font-semibold">{v}</dd><dd className="text-sm text-ink-3">{k}</dd></div>
            ))}
          </dl>
        </section>

        <section id="plans" className="bg-surface py-20 md:py-24">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <p className="eyebrow">Plans</p>
            <h2 className="mt-2 font-display text-3xl font-semibold tracking-[-0.015em]">Pick a speed. Keep the router.</h2>
            {kb && <p className="mt-2 text-sm text-ink-3">Prices in {kb.currency} for {kb.countries.find((c) => c.iso === kb.country)?.name}{kb.tax ? `, including ${kb.tax}` : ''}. Pay by {kb.payments.join(', ')}.</p>}
            <div className="mt-10 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {plansFrom(kb).map((p) => (
                <article key={p.name} className={`rounded-2xl p-6 ${p.featured ? 'bg-ink text-paper shadow-lift' : 'bg-paper hairline'}`}>
                  <div className="flex items-baseline justify-between">
                    <h3 className="font-display text-xl font-semibold">{p.name}</h3>
                    {p.featured && <span className="chip bg-signal text-white">Most picked</span>}
                  </div>
                  <p className={`mt-1 text-sm ${p.featured ? 'text-paper/70' : 'text-ink-2'}`}>{p.note}</p>
                  <p className="mt-6 num"><span className="font-display text-4xl font-semibold">{p.price}</span><span className={`text-sm ${p.featured ? 'text-paper/60' : 'text-ink-3'}`}> /month · {p.speed}</span></p>
                  <ul className="mt-5 space-y-2 text-sm">
                    {p.perks.map((perk) => <li key={perk} className="flex items-center gap-2"><Check className={p.featured ? 'text-signal' : 'text-signal-deep'} />{perk}</li>)}
                  </ul>
                </article>
              ))}
            </div>
            {kb && (
              <div className="mt-14 grid gap-10 md:grid-cols-2">
                <div>
                  <h3 className="font-display text-lg font-semibold">Services</h3>
                  <ul className="mt-4 divide-y divide-line text-sm">
                    {kb.services.map((s) => (
                      <li key={s.key} className="flex gap-4 py-3">
                        <div className="min-w-0 flex-1"><p className="font-medium">{s.name}</p><p className="mt-0.5 text-ink-2">{s.notes}</p></div>
                        <div className="shrink-0 text-right num"><p className="font-medium">{cap(s.price_label)}</p><p className="text-xs text-ink-3">{s.turnaround}</p></div>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="font-display text-lg font-semibold">Add-ons</h3>
                  <ul className="mt-4 divide-y divide-line text-sm">
                    {kb.addons.map((a) => (
                      <li key={a.key} className="flex gap-4 py-3">
                        <div className="min-w-0 flex-1"><p className="font-medium">{a.name}</p><p className="mt-0.5 text-ink-2">{a.notes}</p></div>
                        <p className="shrink-0 font-medium num">{a.price_label}<span className="text-xs text-ink-3">/mo</span></p>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-6 text-xs text-ink-3">Support: {kb.support.channels.join(', ')} · {kb.support.hours}</p>
                </div>
              </div>
            )}
          </div>
        </section>

        <section id="coverage" className="mx-auto max-w-6xl px-4 py-20 sm:px-6 md:py-24">
          <p className="eyebrow">Network status</p>
          <h2 className="mt-2 font-display text-3xl font-semibold tracking-[-0.015em]">Upfront about outages.</h2>
          <p className="mt-2 text-sm text-ink-3">
            {kb ? `${kb.coverage.length} cities in ${kb.countries.find((c) => c.iso === kb.country)?.name}; ${kb.stats.cities} cities and ${kb.stats.areas.toLocaleString()} areas across ${kb.stats.countries} countries.` : ''}
          </p>
          <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4">
            {cities.map((c) => (
              <div key={c.key} className="rounded-2xl bg-surface px-5 py-4 hairline">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2.5"><Wifi className="shrink-0 text-ink-3" /><span className="truncate">{c.city}</span></span>
                  {down.has(c.key) || c.areas.some((a) => down.has(a.toLowerCase()))
                    ? <span className="chip bg-conflict-tint text-conflict">Degraded</span>
                    : <span className="chip bg-current-tint text-current">Normal</span>}
                </div>
                {c.areas.length > 0 && <p className="mt-2 text-xs leading-relaxed text-ink-3">{c.areas.slice(0, 8).join(' · ')}</p>}
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-6xl flex-col gap-2 px-4 pb-10 text-xs text-ink-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <span className="flex flex-wrap items-center gap-2">
          © {COMPANY} · {kb?.stats.countries ?? 39} countries · place names © GeoNames (CC BY 4.0)
          <label htmlFor="portal-tenant" className="ml-2">Demo workspace</label>
          <select id="portal-tenant" className="rounded-full bg-surface px-2 py-0.5 font-mono text-[11px] text-ink hairline outline-none focus:ring-2 focus:ring-signal/40"
            value={tenant} onChange={(e) => setTenant(e.target.value)}>
            {tenants.map((t) => <option key={t} value={t}>mem:{t}</option>)}
          </select>
          <span className={`h-1.5 w-1.5 rounded-full ${status === 'live' ? 'bg-current' : 'bg-conflict'}`} title={status === 'live' ? 'Live updates on' : 'Reconnecting'} />
        </span>
        <span>{COMPANY} is a fictional company, built as a demo of shared agent memory on FalkorDB.</span>
      </footer>
    </div>
  )
}
