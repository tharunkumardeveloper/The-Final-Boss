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
type Stage = 'idle' | 'plant' | 'listen' | 'verify' | 'hunt' | 'clean' | 'done'
interface Canary { token: string; customer: string; value: string; graph: string; facts?: string[]; read_back?: string[] }

const CHECKS = [
  { id: 'stream', label: 'Its live stream carried the write', own: 'heard it', other: 'heard nothing' },
  { id: 'tool', label: 'Its agent tool knows the customer', own: 'knows it', other: 'unknown name' },
  { id: 'cypher', label: 'Cypher on its graph finds the token', own: 'found', other: '0 rows' },
  { id: 'wall', label: "Its key opens the victim's graph", own: 'own key: 200', other: 'refused' },
] as const
type Check = (typeof CHECKS)[number]['id']

export interface Receipt { n: number; at: string; what: string; method: string; url: string; key: string; status: number | string; ms: number; body: string; curl: string }
let sink: ((r: Receipt) => void) | null = null
let seq = 0
const quote = (x: string) => `'${x.replace(/'/g, `'\\''`)}'`

async function call(path: string, key?: string, body?: unknown, method?: string, what = '') {
  const m = method ?? (body === undefined ? 'GET' : 'POST'), t0 = performance.now()
  const r = await fetch(API_URL + path, {
    method: m, body: body === undefined ? undefined : JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', ...(key ? { 'X-Tenant-Key': key } : {}) },
  })
  const text = await r.text()
  let json: unknown = null
  try { json = JSON.parse(text) } catch { /* empty */ }
  sink?.({ n: ++seq, at: new Date().toISOString().slice(11, 23), what, method: m, url: API_URL + path, key: key ? `${key.slice(0, 6)}…` : 'none',
    status: r.status, ms: Math.round(performance.now() - t0), body: text.slice(0, 400),
    curl: `curl -s -X ${m} ${quote(API_URL + path)}${key ? ` -H ${quote(`X-Tenant-Key: ${key}`)}` : ''}${body === undefined ? '' : ` -H 'Content-Type: application/json' -d ${quote(JSON.stringify(body))}`}` })
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
  const [word, setWord] = useState('')
  const [pause, setPause] = useState(true)
  const resume = useRef<() => void>()
  const [log, setLog] = useState<Receipt[]>([])
  const [side, setSide] = useState<'verify' | 'receipts'>('verify')
  useEffect(() => { sink = (r) => setLog((l) => [...l, r]); return () => { sink = null } }, [])
  const wordOk = !word || /^[a-z0-9]{4,16}$/.test(word)

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
    setCells({}); setExtra([]); setLeft(null); setCanary(null); setError(undefined); setLog([]); seq = 0
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
    const p = await call(`/api/tenants/${encodeURIComponent(victim)}/canary`, keyFor(victim), word ? { token: word } : {}, undefined, `plant the canary in ${victim}`)
    if (p.status !== 200) { setError(`Couldn't plant the canary (${p.status}).`); setStage('idle'); return }
    const c = p.json as Canary
    const token = c.token
    setCanary(c)
    await wait(2500)  // let the write's events reach every listening stream
    sockets.current.forEach((s) => s.close())
    for (const t of all) {  // the stream's own receipt: how many frames it got, and the first one naming the canary
      const hit = got[t].find((m) => m.includes(token))
      sink?.({ n: ++seq, at: new Date().toISOString().slice(11, 23), what: `${t}'s live stream during the write`, method: 'WS', url: `${WS_URL}/ws/${t}`,
        key: `${keyFor(t).slice(0, 6)}…`, status: `${got[t].length} frames`, ms: 0, body: hit ? hit.slice(0, 400) : `no frame mentions ${token}`, curl: `websocat '${WS_URL}/ws/${t}?key=${keyFor(t)}'` })
    }
    if (pause) {  // stop here, so the tester can look in FalkorDB Browser before anything else runs
      setStage('verify'); setSide('verify')
      await new Promise<void>((done) => { resume.current = done })
    }
    for (const t of all) {
      const own = t === victim, n = got[t].filter((m) => m.includes(token)).length
      set(t, 'stream', { state: own ? (n > 0 ? 'found' : 'miss') : n > 0 ? 'leak' : 'clean', got: `${n} event${n === 1 ? '' : 's'} mentioning ${token}` })
    }

    // 3. every region hunts for it
    setStage('hunt')
    for (const t of all) {
      const own = t === victim, key = keyFor(t), T = encodeURIComponent(t)
      set(t, 'tool', { state: 'run' })
      const tool = await call(`/api/tenants/${T}/tools/recall_customer`, key, { name: c.customer }, undefined, `${t}'s agent tool looks up ${c.customer}`)
      const outcome = (tool.json as { outcome?: string; rows?: number })?.outcome, rows = (tool.json as { rows?: number })?.rows ?? 0
      set(t, 'tool', { state: own ? (outcome === 'memory' && rows > 0 ? 'found' : 'miss') : outcome === 'unknown_entity' || rows === 0 ? 'clean' : 'leak',
        got: `${tool.status} · ${outcome ?? '?'} · ${rows} rows` })

      set(t, 'cypher', { state: 'run' })
      const q = await call(`/api/tenants/${T}/query`, key, { query: `MATCH (n:Entity) WHERE n.name_key CONTAINS '${token}' RETURN n.name_key` }, undefined, `Cypher on ${t}'s own graph`)
      const count = (q.json as { count?: number })?.count ?? -1
      set(t, 'cypher', { state: own ? (count > 0 ? 'found' : 'miss') : count === 0 ? 'clean' : 'leak', got: `${q.status} · ${count} row${count === 1 ? '' : 's'} in ${regions.find((r) => r.tenant === t)?.graph}` })

      set(t, 'wall', { state: 'run' })
      const w = await call(`/api/tenants/${encodeURIComponent(victim)}/query`, key, { query: `MATCH (n:Entity) WHERE n.name_key CONTAINS '${token}' RETURN n.name_key` }, undefined, `${t}'s key on ${victim}'s graph`)
      if (!own) { setFlying({ from: t, to: victim, ok: w.status === 403, id: Date.now() }); await wait(900) }
      set(t, 'wall', { state: own ? (w.status === 200 ? 'found' : 'miss') : w.status === 403 ? 'clean' : 'leak', got: `${w.status}${w.status === 200 ? ` · ${(w.json as { count?: number })?.count ?? 0} rows` : ''}` })
    }
    setFlying(null)

    // the doors a stranger would try: no key, a forged key
    const V = encodeURIComponent(victim), attacker = all.find((t) => t !== victim) ?? victim
    const nokey = await call(`/api/tenants/${V}/customers`, undefined, undefined, undefined, `no key on ${victim}`)
    const forged = await call(`/api/tenants/${V}/customers`, forge(keyFor(attacker)), undefined, undefined, `forged key on ${victim}`)
    setExtra([
      { id: 'nokey', label: `No key at all on ${victim}`, expect: '401', got: String(nokey.status), ok: nokey.status === 401 },
      { id: 'forged', label: `A forged key (one character of ${attacker}'s changed)`, expect: '403', got: String(forged.status), ok: forged.status === 403 },
    ])

    // 4. remove it, and prove it's gone
    setStage('clean')
    const d = await call(`/api/tenants/${V}/canary/${token}`, keyFor(victim), undefined, 'DELETE', `remove the canary from ${victim}`)
    setLeft((d.json as { left?: number })?.left ?? -1)
    setCanary(null)
    setStage('done')
  }

  const values = Object.values(cells)
  const leaks = values.filter((x) => x.state === 'leak').length + extra.filter((x) => x.ok === false).length
  const misses = values.filter((x) => x.state === 'miss').length
  const checked = values.filter((x) => ['found', 'clean', 'leak', 'miss'].includes(x.state)).length + extra.filter((x) => x.got).length
  const vName = regions?.find((r) => r.tenant === victim)?.name ?? victim
  const STEPS: [Stage, string][] = [['listen', 'Every region listens'], ['plant', `Plant in ${vName}`], ['verify', 'You check it'], ['hunt', 'Every region hunts'], ['clean', 'Remove it'], ['done', 'Verdict']]
  const order: Stage[] = ['idle', 'listen', 'plant', 'verify', 'hunt', 'clean', 'done']
  const browserQuery = (tok: string) => `MATCH (n:Entity) WHERE n.name_key CONTAINS '${tok}' RETURN n.name_key, labels(n)`
  const copy = (x: string) => { try { navigator.clipboard.writeText(x) } catch { /* no clipboard */ } }

  return (
    <div className="flex min-h-[100dvh] flex-col xl:h-[100dvh]">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link to="/console"><Wordmark sub="Tenants & isolation" /></Link>
        <ConsoleNav />
      </header>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-2 sm:px-6">
        <h1 className="font-display text-xl font-semibold tracking-[-0.01em]" title="A European customer's memory must never show up at another desk. A unique marker goes into one region's graph; every region hunts for it through every path it has. The victim's own column must find it, or the test proves nothing.">
          Plant a secret in one region. Try to find it from every other.</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-ink-3">Your secret word
            <input className={`field !w-36 !py-1.5 font-mono text-xs ${wordOk ? '' : 'ring-2 ring-danger'}`} value={word} disabled={busy} placeholder="random if empty"
              onChange={(e) => setWord(e.target.value.toLowerCase())} aria-invalid={!wordOk} title="4 to 16 letters or digits. A recording could never know it." />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-ink-2">
            <input type="checkbox" checked={pause} disabled={busy} onChange={(e) => setPause(e.target.checked)} className="accent-[rgb(var(--signal))]" />Pause so I can check</label>
          <select className="field !w-auto !py-1.5 text-xs" value={victim} disabled={busy} onChange={(e) => setVictim(e.target.value)} aria-label="Victim region">
            {regions?.map((r) => <option key={r.tenant} value={r.tenant}>Victim: {r.name}</option>)}
          </select>
          <button className="btn-primary !py-1.5 text-sm" disabled={busy || !regions?.length || !wordOk} onClick={run}>{busy ? 'Running…' : stage === 'done' ? 'Run it again' : 'Run the canary test'}</button>
        </div>
      </div>
      <ol className="grid gap-1.5 px-4 pb-3 sm:grid-cols-6 sm:px-6" aria-label="Test stages">
        {STEPS.map(([k, label], i) => {
          const now = order.indexOf(stage), me = order.indexOf(k), skipped = k === 'verify' && !pause && stage !== 'idle'
          return (
            <li key={k} className={`rounded-lg px-2.5 py-1.5 text-[11px] ${skipped ? 'bg-surface text-ink-3/60 line-through hairline' : me === now && busy ? 'bg-ink text-paper' : me < now || stage === 'done' ? 'bg-current-tint text-ink' : 'bg-surface text-ink-3 hairline'}`}>
              <span className="font-semibold">{i + 1}. {label}</span>
            </li>
          )
        })}
      </ol>
      {error && <p className="mx-4 mb-2 rounded-xl bg-danger-tint px-4 py-2 text-sm text-danger sm:mx-6" role="alert">{error}</p>}

      <main className="grid min-h-0 flex-1 gap-4 px-4 pb-4 sm:px-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="flex min-h-0 flex-col gap-3" aria-label="The instance and the verdict">
          <div className="min-h-0 shrink">
            {regions ? <Instance regions={regions} victim={victim} setVictim={setVictim} canary={canary} flying={flying} locked={busy} />
              : <p className="rounded-2xl bg-sunk/50 p-10 text-center text-sm text-ink-3">Loading the region graphs…</p>}
          </div>
          <div className="rounded-2xl bg-surface p-3 hairline">
            <div className={`flex flex-wrap items-center gap-2 rounded-xl px-3 py-2 ${stage !== 'done' ? 'bg-sunk/60' : leaks || misses ? 'bg-danger-tint' : 'bg-current-tint'}`}>
              <p className="font-display text-base font-semibold">
                {stage === 'idle' ? 'Not run yet' : stage === 'verify' ? 'Paused: check it yourself →' : stage !== 'done' ? `${checked} checks so far…`
                  : leaks ? `${leaks} leak${leaks > 1 ? 's' : ''} found` : misses ? `${misses} control${misses > 1 ? 's' : ''} failed: the test couldn't see the canary`
                    : `${checked} checks · 0 leaks · found only in ${vName}`}
              </p>
              {left !== null && <span className="chip bg-surface text-ink-2 hairline">removed · {left} left</span>}
              {extra.map((x) => <span key={x.id} className={`chip ${x.ok ? 'bg-surface text-ink-2 hairline' : 'bg-danger text-white'}`} title={x.label}>{x.id === 'nokey' ? 'no key' : 'forged key'} → {x.got}</span>)}
            </div>
            {regions && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full border-separate border-spacing-1 text-xs">
                  <thead><tr>
                    <th className="text-left font-medium text-ink-3">Check</th>
                    {regions.map((r) => <th key={r.tenant} className={`px-1 text-center text-[11px] font-semibold ${r.tenant === victim ? 'text-[#B88A12]' : 'text-ink-2'}`}>{r.name}{r.tenant === victim && <span className="block text-[9px] font-normal">victim · control</span>}</th>)}
                  </tr></thead>
                  <tbody>
                    {CHECKS.map((c) => (
                      <tr key={c.id}>
                        <td className="pr-2 text-[11px] text-ink-2">{c.label}</td>
                        {regions.map((r) => {
                          const cell = cells[`${r.tenant}:${c.id}`] ?? { state: 'idle' }, own = r.tenant === victim
                          const tone = { idle: 'bg-sunk/50 text-ink-3', run: 'bg-sunk text-ink-2 animate-breathe', found: 'bg-[#E5B53A] text-ink', clean: 'bg-current text-white', leak: 'bg-danger text-white', miss: 'bg-danger-tint text-danger' }[cell.state]
                          const say = { idle: '·', run: '…', found: c.own, clean: c.other, leak: 'LEAK', miss: 'control failed' }[cell.state]
                          return <td key={r.tenant} title={cell.got ? `${own ? 'control' : 'probe'}: ${cell.got}` : undefined}
                            className={`h-8 min-w-[70px] rounded-md px-1 text-center text-[10px] font-semibold transition-colors duration-500 ${tone}`}>{say}</td>
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-[10px] text-ink-3">Gold: the victim's own access finds it (each probe can see). Green: found nothing or refused. Hover a cell for the response.</p>
              </div>
            )}
          </div>
        </section>

        <aside className="flex min-h-[520px] flex-col rounded-[1.75rem] bg-surface p-4 hairline xl:min-h-0" aria-label="Proof">
          <div className="flex shrink-0 items-center justify-between gap-2">
            <div role="tablist" aria-label="Proof" className="inline-flex rounded-full bg-sunk/70 p-0.5">
              {([['verify', 'Check it yourself'], ['receipts', `Receipts${log.length ? ` · ${log.length}` : ''}`]] as const).map(([k, label]) => (
                <button key={k} role="tab" aria-selected={side === k} onClick={() => setSide(k)}
                  className={`rounded-full px-3 py-1 text-[11.5px] ${side === k ? 'bg-ink font-medium text-paper' : 'text-ink-2'}`}>{label}</button>
              ))}
            </div>
            {stage === 'verify' && <button className="btn-primary !py-1.5 text-xs" onClick={() => resume.current?.()}>I've checked · continue the hunt</button>}
          </div>
          <div className="scroll-thin mt-3 min-h-0 flex-1 overflow-y-auto pr-1" role="tabpanel">
            {side === 'verify' ? (
              <div className="space-y-3 text-[12.5px] text-ink-2">
                <p><strong className="text-ink">Don't trust this page: check it where the data lives.</strong> These are the ways to prove it's real without relying on our UI.</p>
                <ol className="space-y-2.5">
                  <li className="rounded-xl bg-paper/70 p-3 hairline"><p className="font-semibold text-ink">1 · Use a word only you know</p>
                    <p className="mt-0.5">Type your own secret word above. A pre-recorded animation can't know a word you made up a second ago.</p></li>
                  <li className={`rounded-xl p-3 hairline ${stage === 'verify' ? 'bg-[#E5B53A]/15 ring-2 ring-[#E5B53A]' : 'bg-paper/70'}`}>
                    <p className="font-semibold text-ink">2 · Look in FalkorDB Browser while it's paused</p>
                    <p className="mt-0.5">Open FalkorDB Browser (the database's own tool: FalkorDB Cloud console → Browser, or localhost:3000), connect to the same instance, pick each graph and run:</p>
                    <div className="mt-1.5 flex items-start gap-2">
                      <code className="min-w-0 flex-1 break-all rounded-lg bg-ink px-2 py-1.5 font-mono text-[11px] text-paper">{browserQuery(canary?.token ?? word ?? '<word>')}</code>
                      <button className="btn-ghost !px-2 !py-1 text-[11px] hairline" onClick={() => copy(browserQuery(canary?.token ?? word))}>Copy</button>
                    </div>
                    <p className="mt-1.5">It should return rows in <code className="font-mono text-[11px]">{regions?.find((r) => r.tenant === victim)?.graph ?? 'the victim'}</code> and nothing in {regions?.filter((r) => r.tenant !== victim).map((r) => r.graph).join(', ')}.</p>
                    {canary && <p className="mt-1.5 text-[11.5px]">Server receipt for the write: fact <code className="font-mono">{canary.facts?.join(', ')}</code>, read back from <code className="font-mono">{canary.graph}</code> as {canary.read_back?.map((x) => <code key={x} className="mr-1 font-mono">{x}</code>)}</p>}
                  </li>
                  <li className="rounded-xl bg-paper/70 p-3 hairline"><p className="font-semibold text-ink">3 · Re-run any request yourself</p>
                    <p className="mt-0.5">Every request this page made is in <button className="font-semibold text-signal-deep underline" onClick={() => setSide('receipts')}>Receipts</button>, with the server's answer and a <em>Copy as curl</em> button. Paste it in a terminal and you get the same 403, 401 or 0 rows. They also show in your browser's DevTools → Network tab.</p></li>
                  <li className="rounded-xl bg-paper/70 p-3 hairline"><p className="font-semibold text-ink">4 · Make it fail on purpose</p>
                    <p className="mt-0.5">The victim's column is the control: if the probes were fake or blind it couldn't turn gold, and the verdict says "control failed" instead of passing.</p></li>
                </ol>
                <details className="text-[11px] text-ink-3"><summary className="cursor-pointer">How the isolation works, and its limits</summary>
                  <p className="mt-1">Each region is a separate FalkorDB graph; a query names exactly one, and Cypher has no syntax to reach another. Every tenant request and live stream needs that tenant's key (an HMAC of its name, checked in constant time, never stored). Limit: this cloud plan has no per-tenant database users, so the API holds one database login, and the demo server hands its own web app every key so you can switch regions (<code className="font-mono">RELAY_DEMO_KEYS=0</code> turns that off).</p></details>
              </div>
            ) : (
              <ol className="space-y-1.5">
                {log.map((r) => (
                  <li key={r.n} className="rounded-xl bg-paper/70 p-2.5 hairline">
                    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                      <span className="font-mono text-ink-3">#{r.n} {r.at}</span>
                      <span className={`chip !py-0 font-mono ${String(r.status).startsWith('2') ? 'bg-current-tint text-current' : String(r.status).startsWith('4') ? 'bg-danger-tint text-danger' : 'bg-sunk text-ink-2'}`}>{r.method} {r.status}</span>
                      <span className="min-w-0 flex-1 truncate font-medium text-ink">{r.what}</span>
                      {r.ms > 0 && <span className="text-ink-3 num">{r.ms} ms</span>}
                      <button className="btn-ghost !px-2 !py-0.5 text-[10.5px] hairline" onClick={() => copy(r.curl)}>Copy as curl</button>
                    </div>
                    <p className="mt-1 truncate font-mono text-[10.5px] text-ink-3" title={r.url}>{r.url} · key {r.key}</p>
                    <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sunk/60 px-2 py-1 font-mono text-[10.5px] text-ink-2">{r.body || '(empty body)'}</pre>
                  </li>
                ))}
                {!log.length && <li className="rounded-xl bg-sunk/50 p-4 text-sm text-ink-3">Run the test: every request it makes lands here with the server's real answer.</li>}
              </ol>
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}
