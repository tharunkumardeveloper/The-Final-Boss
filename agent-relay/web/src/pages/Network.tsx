import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { api } from '../lib/api'
import { titleCase } from '../lib/format'
import { useRelayStream } from '../lib/stream'
import { useTenant } from '../lib/tenant'
import type { FailResult, NetNode, Network } from '../lib/types'

const ROW = { backbone: 60, pop: 190, olt: 330 } as const
const OLT_GAP = 46
const PAD = 60

/** Readable layout: cores on top, one POP per city, that city's OLTs underneath; each city's column is as wide
 *  as its OLTs need, so the SVG grows with the country instead of overlapping. */
function layout(nodes: NetNode[]) {
  const pos: Record<string, { x: number; y: number }> = {}
  let x = PAD
  for (const pop of nodes.filter((n) => n.kind === 'pop')) {
    const olts = nodes.filter((n) => n.kind === 'olt' && n.city === pop.city)
    const w = Math.max(150, olts.length * OLT_GAP)
    const cx = x + w / 2
    pos[pop.id] = { x: cx, y: ROW.pop }
    olts.forEach((o, j) => { pos[o.id] = { x: cx + (j - (olts.length - 1) / 2) * OLT_GAP, y: ROW.olt } })
    x += w + 24
  }
  const W = Math.max(1080, x + PAD)
  const cores = nodes.filter((n) => n.kind === 'backbone')
  cores.forEach((b, i) => { pos[b.id] = { x: W * (i + 1) / (cores.length + 1), y: ROW.backbone } })
  return { pos, W }
}

export default function NetworkPage() {
  const { tenant } = useTenant()
  const [net, setNet] = useState<Network>()
  const [sel, setSel] = useState<string>()
  const [result, setResult] = useState<FailResult & { action: 'fail' | 'restore' }>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [country, setCountry] = useState<string>()
  useEffect(() => { setCountry(undefined); setSel(undefined); setResult(undefined) }, [tenant])
  const load = useCallback(async () => {
    try {
      const first = country ?? (await api.network(tenant)).countries?.[0]?.iso  // default: the region's first country
      if (!country && first) { setCountry(first); return }
      setNet(await api.network(tenant, first))
    } catch { setError("Couldn't load the network. Is the API running?") }
  }, [tenant, country])
  useEffect(() => { load() }, [load])
  const status = useRelayStream(tenant, (e) => { if (e.type === 'outage_detected' || e.type === 'outage_resolved') load() }, load)

  const { pos, W } = useMemo(() => layout(net?.nodes ?? []), [net])
  const maxB = Math.max(1e-9, ...(net?.nodes ?? []).map((n) => n.betweenness))
  const node = net?.nodes.find((n) => n.id === sel)
  const [cap, setCap] = useState<{ node: string; gbps: number }>()
  const [plan, setPlan] = useState<{ links: number; km: number; all_links: number; all_km: number }>()
  useEffect(() => { if (sel) api.capacity(tenant, sel).then(setCap).catch(() => setCap(undefined)) }, [tenant, sel, net])
  useEffect(() => { api.cablePlan(tenant).then(setPlan).catch(() => setPlan(undefined)) }, [tenant])
  const onPath = new Set(result?.affected.flatMap((a) => a.path) ?? [])

  const act = async (action: 'fail' | 'restore') => {
    if (!sel) return
    setBusy(true); setError(undefined)
    try {
      const r = action === 'fail' ? await api.failNode(tenant, sel) : await api.restoreNode(tenant, sel)
      setResult({ ...r, action })
      await load()
    } catch (e) {
      setError(e instanceof Error && e.message.includes('403') ? 'This workspace holds benchmark data; use a demo workspace such as pml.' : 'That did not go through.')
    } finally { setBusy(false) }
  }

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Link to="/console"><Wordmark sub="Network" /></Link>
        <Link to="/console" className="btn-ghost text-sm">Back to console</Link>
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">What breaks if this goes down?</h1>
            <p className="mt-2 max-w-2xl text-sm text-ink-2">
              Backbone, city POPs and area OLTs, stored in FalkorDB next to customer memory. Size shows how critical a node is
              (<code className="font-mono text-xs">algo.betweenness</code>). Fail a node: the NOC agent traverses the graph to every customer
              who lost their path to the backbone, records the outage, and messages them before they notice.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {net?.countries && net.countries.length > 1 && (
              <select aria-label="Country" className="field !w-auto !py-1.5 text-sm" value={country ?? ''} onChange={(e) => { setCountry(e.target.value); setSel(undefined); setResult(undefined) }}>
                {net.countries.map((c) => <option key={c.iso} value={c.iso}>{c.name}</option>)}
              </select>
            )}
            <span className={`chip ${status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict'}`}>{status === 'live' ? 'Live' : 'Reconnecting'} · mem:{tenant}</span>
          </div>
        </div>
        {error && <p className="mt-6 text-sm text-danger" role="alert">{error}</p>}
        {net && (
          <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_320px]">
            <div className="overflow-x-auto rounded-2xl bg-surface p-3 hairline">
              <svg viewBox={`0 0 ${W} 450`} style={{ minWidth: Math.max(720, W * 0.75) }} className="w-full" role="img" aria-label="Network topology">
                {net.edges.map((e) => {
                  const a = pos[e.source], b = pos[e.target]
                  if (!a || !b) return null
                  const hot = onPath.has(e.source) && onPath.has(e.target)
                  return <line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeWidth={hot ? 3 : 1.5}
                    className={hot ? 'stroke-danger' : 'stroke-ink/20'} />
                })}
                {net.nodes.map((n) => {
                  const p = pos[n.id]
                  if (!p) return null
                  const r = (n.kind === 'olt' ? 9 : 14) + 12 * Math.sqrt(n.betweenness / maxB)
                  const down = n.status === 'down'
                  return (
                    <g key={n.id} role="button" tabIndex={0} aria-label={`${n.label}, ${n.status}`} className="cursor-pointer outline-none"
                      onClick={() => setSel(n.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSel(n.id) }}>
                      <circle cx={p.x} cy={p.y} r={r} strokeWidth={sel === n.id ? 3 : 1.5}
                        className={`${down ? 'fill-danger-tint stroke-danger' : onPath.has(n.id) ? 'fill-conflict-tint stroke-conflict' : 'fill-paper stroke-ink/30'} ${sel === n.id ? '!stroke-signal-deep' : ''}`} />
                      {n.customers > 0 && <text x={p.x} y={p.y + 4} textAnchor="middle" className="fill-ink text-[11px] font-semibold num">{n.customers}</text>}
                      <text x={p.x} y={p.y + r + 14} textAnchor={n.kind === 'olt' ? 'start' : 'middle'} className="fill-ink-2 text-[11px]"
                        transform={n.kind === 'olt' ? `rotate(40 ${p.x} ${p.y + r + 14})` : undefined}>
                        {n.kind === 'olt' ? titleCase(n.area ?? n.label) : n.label}
                      </text>
                    </g>
                  )
                })}
              </svg>
              <p className="px-2 pb-1 text-[11px] text-ink-3">Numbers inside nodes: customers connected. Red: down. Amber: on an affected customer's path.</p>
              {plan && <p className="px-2 pb-1 text-[11px] text-ink-3 num">Cable plan (<code className="font-mono">algo.MSF</code> over cable km): {plan.links} of {plan.all_links} links, {Math.round(plan.km).toLocaleString()} of {Math.round(plan.all_km).toLocaleString()} km, still connect every node; the rest is redundancy.</p>}
            </div>
            <aside className="space-y-4">
              <section className="rounded-2xl bg-surface p-5 hairline">
                {node ? (
                  <>
                    <p className="eyebrow">{node.kind === 'olt' ? 'Area OLT' : node.kind === 'pop' ? 'City POP' : 'Backbone'}</p>
                    <h2 className="mt-1 font-display text-xl font-semibold">{node.label}</h2>
                    <dl className="mt-3 grid grid-cols-2 gap-2 text-sm num">
                      <div><dt className="text-[11px] text-ink-3">Status</dt><dd className={node.status === 'down' ? 'text-danger font-medium' : 'text-current font-medium'}>{node.status}</dd></div>
                      <div><dt className="text-[11px] text-ink-3">Criticality</dt><dd className="font-medium">{node.betweenness.toFixed(1)}</dd></div>
                      <div><dt className="text-[11px] text-ink-3" title="algo.HarmonicCentrality: how close it is to everything else, robust when the network splits">Reach</dt><dd className="font-medium">{(node.harmonic ?? 0).toFixed(1)}</dd></div>
                      <div><dt className="text-[11px] text-ink-3" title="algo.maxFlow to the backbone through working equipment">Capacity to backbone</dt><dd className={`font-medium ${cap?.node === node.id && cap.gbps === 0 ? 'text-danger' : ''}`}>{cap?.node === node.id ? `${cap.gbps} Gbps` : '…'}</dd></div>
                    </dl>
                    <div className="mt-4 flex gap-2">
                      {node.status === 'up'
                        ? <button className="btn-primary !bg-danger text-sm" disabled={busy} onClick={() => act('fail')}>Simulate failure</button>
                        : <button className="btn-primary text-sm" disabled={busy} onClick={() => act('restore')}>Restore</button>}
                    </div>
                  </>
                ) : <p className="text-sm text-ink-2">Pick a node to see it, or simulate a failure. Try <strong>Core West</strong>: Pune is single-homed on it.</p>}
              </section>
              {result && (
                <section className="rounded-2xl bg-surface p-5 hairline" aria-live="polite">
                  <h3 className="font-display text-base font-semibold">{result.action === 'fail' ? `${result.affected.length} customer${result.affected.length === 1 ? '' : 's'} affected` : `${result.notified.length} customer${result.notified.length === 1 ? '' : 's'} back online`}</h3>
                  <ul className="mt-3 space-y-2 text-sm">
                    {(result.action === 'fail' ? result.affected.map((a) => a.customer) : result.notified).map((c) => {
                      const a = result.affected.find((x) => x.customer === c)
                      return (
                        <li key={c}>
                          <p className="font-medium">{titleCase(c)}</p>
                          {a && <p className="text-[11px] text-ink-3 font-mono">{a.path.map((x) => x.replace(/^e:/, '')).join(' → ')}</p>}
                        </li>
                      )
                    })}
                  </ul>
                  <p className="mt-3 text-xs text-ink-3">
                    {result.action === 'fail' ? 'Each one got a message from Network ops before reporting anything.' : 'Each one was told the fault is fixed.'}
                    {result.tickets?.length ? ` Open tickets noted: ${result.tickets.join(', ')}.` : ''}
                  </p>
                </section>
              )}
            </aside>
          </div>
        )}
      </main>
    </div>
  )
}
