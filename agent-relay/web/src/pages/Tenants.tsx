import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ConsoleNav } from '../components/console/ConsoleNav'
import { api, API_URL, WS_URL } from '../lib/api'
import { keyFor } from '../lib/keys'
import { useTenant } from '../lib/tenant'
import type { Region } from '../lib/types'

/* The canary test. A unique marker is written into ONE region's graph; then every region hunts for it through every path
   an agent or an attacker has (its live stream, its agent tool, raw Cypher on its graph, its key against the victim).
   The victim's own column must find it (proof the probes can see), every other column must come back empty. */

type Cell = { state: 'idle' | 'run' | 'found' | 'clean' | 'leak' | 'miss'; got?: string }
type Stage = 'idle' | 'plant' | 'listen' | 'hunt' | 'clean' | 'done'
interface Canary { token: string; customer: string; value: string; graph: string }

const CHECKS = [
  { id: 'stream', label: 'Its live stream carried the write', own: 'heard it', other: 'heard nothing' },
  { id: 'tool', label: 'Its agent tool knows the customer', own: 'knows it', other: 'unknown name' },
  { id: 'cypher', label: 'Cypher on its graph finds the token', own: 'found', other: '0 rows' },
  { id: 'wall', label: "Its key opens the victim's graph", own: 'own key: 200', other: 'refused' },
] as const
type Check = (typeof CHECKS)[number]['id']

async function call(path: string, key?: string, body?: unknown, method?: string) {
  const r = await fetch(API_URL + path, {
    method: method ?? (body === undefined ? 'GET' : 'POST'), body: body === undefined ? undefined : JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', ...(key ? { 'X-Tenant-Key': key } : {}) },
  })
  let json: unknown = null
  try { json = await r.json() } catch { /* empty */ }
  return { status: r.status, json }
}
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const forge = (k: string) => k.slice(0, -1) + (k.endsWith('0') ? '1' : '0')

// ---------------------------------------------------------------- the instance, drawn

const W = 900, H = 330
function layout(n: number) {
  const cols = n <= 3 ? n : Math.ceil(n / 2), rows = n <= 3 ? 1 : 2
  return (i: number) => ({ x: 90 + ((W - 180) * ((i % cols) + 0.5)) / cols, y: rows === 1 ? 175 : 110 + Math.floor(i / cols) * 150 })
}

function Instance({ regions, victim, setVictim, canary, flying, locked }: { regions: Region[]; victim: string; setVictim: (t: string) => void
  canary: Canary | null; flying: { from: string; to: string; ok: boolean; id: number } | null; locked: boolean }) {
  const at = layout(regions.length)
  const pos = Object.fromEntries(regions.map((r, i) => [r.tenant, at(i)]))
  const maxN = Math.max(1, ...regions.map((r) => r.stats?.nodes ?? 0))
  const rad = (r: Region) => 34 + 22 * Math.sqrt((r.stats?.nodes ?? 0) / maxN)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="One FalkorDB instance holding one graph per region">
      <rect x="8" y="8" width={W - 16} height={H - 16} rx="26" fill="rgb(var(--ink))" />
      <text x="34" y="40" className="fill-white/50 text-[11px] uppercase tracking-[0.14em]">One FalkorDB instance · one graph per region · each behind its own key</text>
      {regions.map((r) => {
        const p = pos[r.tenant], R = rad(r), on = r.tenant === victim
        return (
          <g key={r.tenant} role="button" tabIndex={0} aria-pressed={on} aria-label={`${r.name}: ${r.graph}`}
            className={locked ? '' : 'cursor-pointer'} onClick={() => !locked && setVictim(r.tenant)}
            onKeyDown={(e) => { if (!locked && (e.key === 'Enter' || e.key === ' ')) setVictim(r.tenant) }}>
            {/* the wall: every graph is its own island; a request names exactly one */}
            <circle cx={p.x} cy={p.y} r={R + 10} fill="none" stroke={on ? '#E5B53A' : 'rgb(255 255 255 / 0.22)'} strokeWidth={on ? 3 : 2} strokeDasharray={on ? undefined : '4 5'} />
            <circle cx={p.x} cy={p.y} r={R} fill={on ? 'rgb(229 181 58 / 0.12)' : 'rgb(255 255 255 / 0.05)'} />
            {Array.from({ length: 9 }, (_, k) => {  // a hint of the graph inside
              const a = (k / 9) * Math.PI * 2 + r.tenant.length, d = R * (0.35 + 0.4 * ((k * 7) % 5) / 5)
              return <circle key={k} cx={p.x + Math.cos(a) * d} cy={p.y + Math.sin(a) * d} r="2.4" fill="rgb(255 255 255 / 0.35)" />
            })}
            <text x={p.x} y={p.y - 3} textAnchor="middle" className="fill-white text-[13px] font-semibold">{r.name}</text>
            <text x={p.x} y={p.y + 13} textAnchor="middle" className="fill-white/55 font-mono text-[10px]">{r.graph}</text>
            <text x={p.x} y={p.y + R + 28} textAnchor="middle" className="fill-white/55 text-[10.5px] num">
              {r.stats ? `${r.stats.customers} customers · ${r.stats.facts.toLocaleString()} facts` : 'not loaded'}{r.memory_mb != null ? ` · ${r.memory_mb < 1 ? '<1' : r.memory_mb} MB` : ''}</text>
            {on && canary && (
              <motion.g initial={{ y: -60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ type: 'spring', stiffness: 220, damping: 16 }}>
                <circle cx={p.x + R * 0.45} cy={p.y + R * 0.45} r="9" fill="#E5B53A" />
                <circle cx={p.x + R * 0.45} cy={p.y + R * 0.45} r="9" fill="none" stroke="#E5B53A" className="lab-alarm" />
                <text x={p.x + R * 0.45} y={p.y + R * 0.45 + 24} textAnchor="middle" className="fill-[#E5B53A] font-mono text-[10px]">{canary.token}</text>
              </motion.g>
            )}
          </g>
        )
      })}
      <AnimatePresence>
        {flying && pos[flying.from] && pos[flying.to] && (() => {
          const a = pos[flying.from], b = pos[flying.to]
          const vr = rad(regions.find((r) => r.tenant === flying.to)!) + 10
          const len = Math.hypot(b.x - a.x, b.y - a.y) || 1
          const stop = { x: b.x - ((b.x - a.x) / len) * vr, y: b.y - ((b.y - a.y) / len) * vr }  // the wall
          const end = flying.ok ? stop : b
          return (
            <motion.g key={flying.id} exit={{ opacity: 0 }}>
              <line x1={a.x} y1={a.y} x2={stop.x} y2={stop.y} stroke="rgb(255 255 255 / 0.18)" strokeDasharray="3 5" />
              <motion.circle r="7" fill={flying.ok ? '#7dd3fc' : '#ff9b8f'} initial={{ cx: a.x, cy: a.y }} animate={{ cx: end.x, cy: end.y }} transition={{ duration: 0.55, ease: 'easeIn' }} />
              {flying.ok && (
                <motion.g initial={{ opacity: 0, scale: 0.4 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.5 }} style={{ originX: `${stop.x}px`, originY: `${stop.y}px` }}>
                  <circle cx={stop.x} cy={stop.y} r="15" fill="rgb(var(--danger) / 0.3)" />
                  <path d={`M${stop.x - 6} ${stop.y - 6}l12 12M${stop.x + 6} ${stop.y - 6}l-12 12`} stroke="#ff9b8f" strokeWidth="2.5" strokeLinecap="round" />
                  <text x={stop.x} y={stop.y - 22} textAnchor="middle" className="fill-[#ff9b8f] text-[11px] font-semibold">403</text>
                </motion.g>
              )}
            </motion.g>
          )
        })()}
      </AnimatePresence>
    </svg>
  )
}

// ---------------------------------------------------------------- the page

export default function TenantsPage() {
  const { tenant } = useTenant()
  const [regions, setRegions] = useState<Region[]>()
  const [error, setError] = useState<string>()
  const [victim, setVictim] = useState('')
  const [stage, setStage] = useState<Stage>('idle')
  const [canary, setCanary] = useState<Canary | null>(null)
  const [cells, setCells] = useState<Record<string, Cell>>({})
  const [extra, setExtra] = useState<{ id: string; label: string; expect: string; got?: string; ok?: boolean }[]>([])
  const [flying, setFlying] = useState<{ from: string; to: string; ok: boolean; id: number } | null>(null)
  const [left, setLeft] = useState<number | null>(null)
  const sockets = useRef<WebSocket[]>([])

  useEffect(() => {
    api.regions().then((rs) => {
      const usable = rs.filter((r) => r.loaded && keyFor(r.tenant))
      setRegions(usable)
      setVictim((v) => v || (usable.find((r) => r.tenant !== tenant) ?? usable[0])?.tenant || '')
    }).catch(() => setError("Couldn't load the region graphs. Is the API running?"))
    return () => sockets.current.forEach((s) => s.close())
  }, [tenant])

  const set = (t: string, c: Check, v: Cell) => setCells((m) => ({ ...m, [`${t}:${c}`]: v }))
  const busy = stage !== 'idle' && stage !== 'done'

  const run = async () => {
    if (!regions?.length || !victim) return
    setCells({}); setExtra([]); setLeft(null); setCanary(null); setError(undefined)
    const all = regions.map((r) => r.tenant)
    all.forEach((t) => CHECKS.forEach((c) => set(t, c.id, { state: 'idle' })))

    // 1. every region listens on its own live stream, with its own key, before anything is written
    setStage('listen')
    // everything each stream receives is kept: the write's events can arrive before the plant request returns the token
    const got: Record<string, string[]> = Object.fromEntries(all.map((t) => [t, []]))
    sockets.current.forEach((s) => s.close())
    sockets.current = all.map((t) => {
      const ws = new WebSocket(`${WS_URL}/ws/${encodeURIComponent(t)}?key=${encodeURIComponent(keyFor(t))}`)
      ws.onmessage = (m) => { got[t].push(String(m.data)) }
      return ws
    })
    await wait(1200)

    // 2. plant the canary in the victim's graph only
    setStage('plant')
    const p = await call(`/api/tenants/${encodeURIComponent(victim)}/canary`, keyFor(victim), {})
    if (p.status !== 200) { setError(`Couldn't plant the canary (${p.status}).`); setStage('idle'); return }
    const c = p.json as Canary
    const token = c.token
    setCanary(c)
    await wait(2500)  // let the write's events reach every listening stream
    sockets.current.forEach((s) => s.close())
    for (const t of all) {
      const own = t === victim, n = got[t].filter((m) => m.includes(token)).length
      set(t, 'stream', { state: own ? (n > 0 ? 'found' : 'miss') : n > 0 ? 'leak' : 'clean', got: `${n} event${n === 1 ? '' : 's'} mentioning ${token}` })
    }

    // 3. every region hunts for it
    setStage('hunt')
    for (const t of all) {
      const own = t === victim, key = keyFor(t), T = encodeURIComponent(t)
      set(t, 'tool', { state: 'run' })
      const tool = await call(`/api/tenants/${T}/tools/recall_customer`, key, { name: c.customer })
      const outcome = (tool.json as { outcome?: string; rows?: number })?.outcome, rows = (tool.json as { rows?: number })?.rows ?? 0
      set(t, 'tool', { state: own ? (outcome === 'memory' && rows > 0 ? 'found' : 'miss') : outcome === 'unknown_entity' || rows === 0 ? 'clean' : 'leak',
        got: `${tool.status} · ${outcome ?? '?'} · ${rows} rows` })

      set(t, 'cypher', { state: 'run' })
      const q = await call(`/api/tenants/${T}/query`, key, { query: `MATCH (n:Entity) WHERE n.name_key CONTAINS '${token}' RETURN n.name_key` })
      const count = (q.json as { count?: number })?.count ?? -1
      set(t, 'cypher', { state: own ? (count > 0 ? 'found' : 'miss') : count === 0 ? 'clean' : 'leak', got: `${q.status} · ${count} row${count === 1 ? '' : 's'} in ${regions.find((r) => r.tenant === t)?.graph}` })

      set(t, 'wall', { state: 'run' })
      const w = await call(`/api/tenants/${encodeURIComponent(victim)}/query`, key, { query: `MATCH (n:Entity) WHERE n.name_key CONTAINS '${token}' RETURN n.name_key` })
      if (!own) { setFlying({ from: t, to: victim, ok: w.status === 403, id: Date.now() }); await wait(900) }
      set(t, 'wall', { state: own ? (w.status === 200 ? 'found' : 'miss') : w.status === 403 ? 'clean' : 'leak', got: `${w.status}${w.status === 200 ? ` · ${(w.json as { count?: number })?.count ?? 0} rows` : ''}` })
    }
    setFlying(null)

    // the doors a stranger would try: no key, a forged key
    const V = encodeURIComponent(victim), attacker = all.find((t) => t !== victim) ?? victim
    const nokey = await call(`/api/tenants/${V}/customers`)
    const forged = await call(`/api/tenants/${V}/customers`, forge(keyFor(attacker)))
    setExtra([
      { id: 'nokey', label: `No key at all on ${victim}`, expect: '401', got: String(nokey.status), ok: nokey.status === 401 },
      { id: 'forged', label: `A forged key (one character of ${attacker}'s changed)`, expect: '403', got: String(forged.status), ok: forged.status === 403 },
    ])

    // 4. remove it, and prove it's gone
    setStage('clean')
    const d = await call(`/api/tenants/${V}/canary/${token}`, keyFor(victim), undefined, 'DELETE')
    setLeft((d.json as { left?: number })?.left ?? -1)
    setCanary(null)
    setStage('done')
  }

  const values = Object.values(cells)
  const leaks = values.filter((x) => x.state === 'leak').length + extra.filter((x) => x.ok === false).length
  const misses = values.filter((x) => x.state === 'miss').length
  const checked = values.filter((x) => ['found', 'clean', 'leak', 'miss'].includes(x.state)).length + extra.filter((x) => x.got).length
  const vName = regions?.find((r) => r.tenant === victim)?.name ?? victim
  const STEPS: [Stage, string][] = [['listen', 'Every region listens'], ['plant', `Plant in ${vName}`], ['hunt', 'Every region hunts'], ['clean', 'Remove it'], ['done', 'Verdict']]
  const order: Stage[] = ['idle', 'listen', 'plant', 'hunt', 'clean', 'done']

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link to="/console"><Wordmark sub="Tenants & isolation" /></Link>
        <ConsoleNav />
      </header>
      <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 pb-10 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="max-w-3xl">
            <p className="eyebrow">Data residency · one graph per regional desk</p>
            <h1 className="mt-1 font-display text-2xl font-semibold tracking-[-0.01em] sm:text-3xl">Plant a secret in one region. Try to find it from every other.</h1>
            <p className="mt-1 text-sm text-ink-2">
              A European customer's memory must never show up at another desk. The canary test proves it with real requests from your
              browser: a unique marker goes into one region's graph, then every region hunts for it through every path it has.
              The victim's own column has to find it, or the test proves nothing.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-3">Victim: click a region, or</span>
            <select className="field !w-auto !py-1.5 text-sm" value={victim} disabled={busy} onChange={(e) => setVictim(e.target.value)} aria-label="Victim region">
              {regions?.map((r) => <option key={r.tenant} value={r.tenant}>{r.name} · {r.graph}</option>)}
            </select>
            <button className="btn-primary !py-2" disabled={busy || !regions?.length} onClick={run}>{busy ? 'Running…' : stage === 'done' ? 'Run it again' : 'Run the canary test'}</button>
          </div>
        </div>
        {error && <p className="mt-3 rounded-xl bg-danger-tint px-4 py-2 text-sm text-danger" role="alert">{error}</p>}

        <ol className="mt-4 grid gap-1.5 sm:grid-cols-5" aria-label="Test stages">
          {STEPS.map(([k, label], i) => {
            const now = order.indexOf(stage), me = order.indexOf(k)
            return (
              <li key={k} className={`rounded-xl px-3 py-2 text-xs ${me === now && busy ? 'bg-ink text-paper' : me < now || stage === 'done' ? 'bg-current-tint text-ink' : 'bg-surface text-ink-3 hairline'}`}>
                <span className="font-semibold">{i + 1}. {label}</span>
              </li>
            )
          })}
        </ol>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <section aria-label="The instance">
            {regions ? <Instance regions={regions} victim={victim} setVictim={setVictim} canary={canary} flying={flying} locked={busy} />
              : <p className="rounded-2xl bg-sunk/50 p-10 text-center text-sm text-ink-3">Loading the region graphs…</p>}
            {canary && (
              <p className="mt-2 rounded-xl bg-[#E5B53A]/15 px-3 py-2 text-xs text-ink">
                Planted in <code className="font-mono">{canary.graph}</code> only: customer <strong>{canary.customer}</strong>, address <strong>{canary.value}</strong>.
              </p>
            )}
          </section>

          <section className="rounded-[1.75rem] bg-surface p-4 hairline" aria-label="Verdict">
            <div className={`flex flex-wrap items-center gap-2 rounded-2xl px-4 py-3 ${stage !== 'done' ? 'bg-sunk/60' : leaks || misses ? 'bg-danger-tint' : 'bg-current-tint'}`}>
              <p className="font-display text-lg font-semibold">
                {stage === 'idle' ? 'Not run yet'
                  : stage !== 'done' ? `${checked} checks so far…`
                    : leaks ? `${leaks} leak${leaks > 1 ? 's' : ''} found`
                      : misses ? `${misses} control${misses > 1 ? 's' : ''} failed: the test couldn't see the canary`
                        : `${checked} checks · 0 leaks · the canary was found only in ${vName}`}
              </p>
              {left !== null && <span className="chip bg-surface text-ink-2 hairline">canary removed · {left} left</span>}
            </div>
            {regions && (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full border-separate border-spacing-1 text-xs">
                  <thead>
                    <tr>
                      <th className="text-left font-medium text-ink-3">Check</th>
                      {regions.map((r) => (
                        <th key={r.tenant} className={`px-1 text-center font-semibold ${r.tenant === victim ? 'text-[#B88A12]' : 'text-ink-2'}`}>
                          {r.name}{r.tenant === victim && <span className="block text-[9.5px] font-normal">victim · control</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {CHECKS.map((c) => (
                      <tr key={c.id}>
                        <td className="pr-2 text-ink-2">{c.label}</td>
                        {regions.map((r) => {
                          const cell = cells[`${r.tenant}:${c.id}`] ?? { state: 'idle' }, own = r.tenant === victim
                          const tone = { idle: 'bg-sunk/50 text-ink-3', run: 'bg-sunk text-ink-2 animate-breathe', found: 'bg-[#E5B53A] text-ink', clean: 'bg-current text-white', leak: 'bg-danger text-white', miss: 'bg-danger-tint text-danger' }[cell.state]
                          const word = { idle: '·', run: '…', found: c.own, clean: c.other, leak: 'LEAK', miss: 'control failed' }[cell.state]
                          return (
                            <td key={r.tenant} title={cell.got ? `${own ? 'control' : 'probe'}: ${cell.got}` : undefined}
                              className={`h-9 min-w-[76px] rounded-lg px-1 text-center text-[10.5px] font-semibold transition-colors duration-500 ${tone}`}>{word}</td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-[10.5px] text-ink-3">Gold: the victim's own access finds the canary (proves each probe can see it). Green: another region found nothing or was refused. Hover any cell for the real response.</p>
              </div>
            )}
            {extra.length > 0 && (
              <ul className="mt-3 space-y-1">
                {extra.map((x) => (
                  <li key={x.id} className="flex items-center gap-2 rounded-xl bg-paper/70 px-3 py-1.5 text-xs">
                    <span className={`h-2 w-2 rounded-full ${x.ok ? 'bg-current' : 'bg-danger'}`} />
                    <span className="min-w-0 flex-1">{x.label}</span>
                    <span className="font-mono text-ink-3">expected {x.expect} · got {x.got}</span>
                  </li>
                ))}
              </ul>
            )}
            <details className="mt-3 text-[11px] text-ink-3">
              <summary className="cursor-pointer">How the isolation works, and its limits</summary>
              <p className="mt-1">Each region is a separate FalkorDB graph; a query names exactly one, and Cypher has no syntax to reach another.
                Every tenant request and live stream needs that tenant's key (an HMAC of its name, checked in constant time, never stored).
                Limit: this cloud plan has no per-tenant database users, so the API holds one database login, and the demo server hands its own
                web app every key so you can switch regions (<code className="font-mono">RELAY_DEMO_KEYS=0</code> turns that off).</p>
            </details>
          </section>
        </div>
      </main>
    </div>
  )
}
