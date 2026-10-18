import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { titleCase } from '../../lib/format'
import { TouchLayer } from './TouchLayer'
import type { FailResult, NetNode, Network, RelayEvent } from '../../lib/types'
import INDIA from '../../data/india.json'

const W = 900, H = 820, PAD = 70
// Country outlines drawn under the hubs (lon/lat rings). India uses Natural Earth's India point-of-view boundary.
const OUTLINES: Record<string, { bounds: number[]; rings: number[][][] }> = { IN: INDIA }

/** The map: each node at its city's latitude/longitude (equirectangular, longitude squeezed by the mean latitude);
 *  area exchanges sit on a small ring around their city hub, backbones just off their city so both stay visible.
 *  With a country outline, the frame is the whole country, so the hubs land on the map where the cities are. */
function layout(nodes: NetNode[], frame?: number[]) {
  const placed = nodes.filter((n) => n.lat != null && n.lon != null)
  const pos: Record<string, { x: number; y: number }> = {}
  if (!placed.length && !frame) return { pos, W, H, project: undefined }
  const [minLon, minLat, maxLon, maxLat] = frame ?? [Math.min(...placed.map((n) => n.lon!)), Math.min(...placed.map((n) => n.lat!)),
    Math.max(...placed.map((n) => n.lon!)), Math.max(...placed.map((n) => n.lat!))]
  const k = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180)
  const spanX = (maxLon - minLon) * k || 1, spanY = maxLat - minLat || 1
  const scale = Math.min((W - 2 * PAD) / spanX, (H - 2 * PAD) / spanY)
  const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2
  const project = (lon: number, lat: number) => ({ x: ox + (lon - minLon) * k * scale, y: oy + (maxLat - lat) * scale })
  const at = (n: NetNode) => project(n.lon!, n.lat!)
  for (const n of placed) {
    if (n.kind === 'pop') pos[n.id] = at(n)
    if (n.kind === 'backbone') { const p = at(n); pos[n.id] = { x: p.x - 34, y: p.y - 34 } }
  }
  for (const pop of placed.filter((n) => n.kind === 'pop')) {
    const olts = placed.filter((n) => n.kind === 'olt' && n.city === pop.city)
    olts.forEach((o, j) => {
      const t = (j / Math.max(1, olts.length)) * Math.PI * 2, r = 20 + (olts.length > 8 ? 8 : 0)
      pos[o.id] = { x: pos[pop.id].x + Math.cos(t) * r, y: pos[pop.id].y + Math.sin(t) * r }
    })
  }
  return { pos, W, H, project }
}

/** A country's rings as one SVG path, in the map's projection. */
const outlinePath = (rings: number[][][], project: (lon: number, lat: number) => { x: number; y: number }) =>
  rings.map((ring) => ring.map(([lon, lat], i) => { const p = project(lon, lat); return `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}` }).join('') + 'Z').join('')

/** The whole region on a real map, with failure simulation. Shares the page's event stream through `subscribe`.
 *  `onHub` opens a city's customers in the lab; `hubCustomers` says how many lab customers a city has. */
export function NetworkMap({ tenant, subscribe, onHub, hubCustomers }: {
  tenant: string; subscribe: (fn: (e: RelayEvent) => void) => () => void
  onHub?: (city: string) => void; hubCustomers?: (city: string) => number
}) {
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
  useEffect(() => subscribe((e) => { if (e.type === 'outage_detected' || e.type === 'outage_resolved') load() }), [subscribe, load])

  const outline = country ? OUTLINES[country] : undefined
  const { pos, project } = useMemo(() => layout(net?.nodes ?? [], outline?.bounds), [net, outline])
  const land = useMemo(() => outline && project ? outlinePath(outline.rings, project) : null, [outline, project])
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
    <div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl font-semibold tracking-[-0.01em]">What breaks if this goes down?</h2>
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
          </div>
        </div>
        {error && <p className="mt-6 text-sm text-danger" role="alert">{error}</p>}
        {net && (
          <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
            <div className="lab-grid overflow-hidden rounded-[1.75rem] bg-ink p-3 text-white shadow-lift">
              <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto block h-auto w-full max-w-[860px]" role="img" aria-label="Network map">
                <defs>
                </defs>
                {land && <path d={land} fill="rgb(255 255 255 / 0.05)" stroke="rgb(var(--signal) / 0.45)" strokeWidth={1.2} strokeLinejoin="round" pointerEvents="none" />}
                {net.edges.map((e) => {
                  const a = pos[e.source], b = pos[e.target]
                  if (!a || !b) return null
                  const src = net.nodes.find((n) => n.id === e.source), dst = net.nodes.find((n) => n.id === e.target)
                  const core = dst?.kind === 'backbone'
                  const down = src?.status === 'down' || dst?.status === 'down'
                  const hot = onPath.has(e.source) && onPath.has(e.target)
                  const d = core ? `M${a.x} ${a.y} Q${(a.x + b.x) / 2} ${Math.min(a.y, b.y) - 40} ${b.x} ${b.y}` : `M${a.x} ${a.y} L${b.x} ${b.y}`
                  const color = down ? 'rgb(var(--danger))' : hot ? 'rgb(var(--conflict))' : core ? 'rgb(var(--signal))' : 'rgb(255 255 255 / 0.18)'
                  return (
                    <g key={e.id}>
                      <path d={d} fill="none" stroke={color} strokeOpacity={core ? 0.25 : 1} strokeWidth={core ? 5 : 1} />
                      {core && <path d={d} fill="none" stroke={color} strokeWidth={1.6} className={down ? '' : 'lab-flow'} strokeDasharray={down ? '5 5' : undefined} />}
                    </g>
                  )
                })}
                {net.nodes.map((n) => {
                  const p = pos[n.id]
                  if (!p) return null
                  const down = n.status === 'down', path = onPath.has(n.id), chosen = sel === n.id
                  const people = n.kind === 'pop' ? net.nodes.filter((o) => o.kind === 'olt' && o.city === n.city).reduce((t, o) => t + o.customers, 0) : n.customers
                  const color = down ? 'rgb(var(--danger))' : path ? 'rgb(var(--conflict))' : n.kind === 'olt' && n.customers > 0 ? 'rgb(var(--signal))' : n.kind === 'olt' ? 'rgb(255 255 255 / 0.35)' : 'rgb(var(--signal))'
                  const r = n.kind === 'olt' ? 3.2 : n.kind === 'pop' ? 9 + 6 * Math.sqrt(n.betweenness / maxB) + Math.min(6, people * 1.5) : 13
                  return (
                    <g key={n.id} role="button" tabIndex={0} aria-label={`${n.label}, ${n.status}`} className="cursor-pointer outline-none"
                      onClick={() => setSel(n.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSel(n.id) }}>
                      {down && <circle cx={p.x} cy={p.y} r={r + 6} fill="rgb(var(--danger) / 0.5)" className="lab-alarm" />}
                      {n.kind !== 'olt' && <circle cx={p.x} cy={p.y} r={r + 6} fill={color} opacity="0.12" />}
                      {n.kind === 'backbone'
                        ? <rect x={p.x - r} y={p.y - r} width={2 * r} height={2 * r} rx={5} transform={`rotate(45 ${p.x} ${p.y})`} fill="rgb(var(--ink))" stroke={color} strokeWidth={2} />
                        : <circle cx={p.x} cy={p.y} r={r} fill={n.kind === 'pop' ? 'rgb(var(--ink))' : color} stroke={n.kind === 'pop' ? color : 'none'} strokeWidth={2} />}
                      {chosen && <circle cx={p.x} cy={p.y} r={r + 5} fill="none" stroke="white" strokeWidth={1.5} />}
                      {n.kind === 'pop' && people > 0 && <text x={p.x} y={p.y + 3.5} textAnchor="middle" className="fill-white text-[10px] font-semibold num">{people}</text>}
                      {n.kind !== 'olt' && <text x={p.x} y={p.y + r + 13} textAnchor="middle" className={`text-[11px] ${n.kind === 'backbone' ? 'fill-white font-semibold' : 'fill-white/75'}`}>{n.kind === 'backbone' ? n.label : n.label.replace(' POP', '')}</text>}
                      <title>{`${n.label} · ${n.status}${people ? ` · ${people} customers` : ''}`}</title>
                    </g>
                  )
                })}
                <TouchLayer grow={10}
                  links={net.edges.filter((e) => pos[e.source] && pos[e.target]).map((e) => ({ id: e.id, a: e.source, b: e.target,
                    d: `M${pos[e.source].x} ${pos[e.source].y} L${pos[e.target].x} ${pos[e.target].y}` }))}
                  marks={net.nodes.filter((n) => pos[n.id]).map((n) => ({ id: n.id, keys: [n.id, n.label], x: pos[n.id].x, y: pos[n.id].y, r: n.kind === 'olt' ? 7 : 16 }))} />
              </svg>
              <p className="px-2 pb-1 text-[11px] text-white/55">Diamonds: backbone cores. Circles: city hubs, at their real position, sized by customers and how critical they are (number: customers). Small dots: area exchanges. Red: down. Amber: an affected customer's path. Light blue: a node or link a live Cypher query just read. Click any node, then simulate a failure.</p>
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
                      {onHub && node.city && (hubCustomers?.(node.city) ?? 0) > 0 && (
                        <button className="btn-ghost text-sm hairline" onClick={() => onHub(node.city!)}>
                          Open {node.city}'s line in the lab
                        </button>
                      )}
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
    </div>
  )
}
