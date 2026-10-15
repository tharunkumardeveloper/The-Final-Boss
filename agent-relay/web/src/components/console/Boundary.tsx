import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useMemo, useState } from 'react'
import { API_URL } from '../../lib/api'
import { keyFor } from '../../lib/keys'

type Edge = { from: string; rel: string; to: string }
const SAMPLE = 'MATCH (c:Customer)-[r]->(x) WHERE r.fact_id IS NOT NULL RETURN c.name, type(r), coalesce(x.name, x.name_key) LIMIT 24'
const CITIES = 'MATCH (c:City) RETURN c.name LIMIT 10'

async function sample(tenant: string): Promise<{ edges: Edge[]; cities: string[] }> {
  const run = (query: string) => fetch(`${API_URL}/api/tenants/${encodeURIComponent(tenant)}/query`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Tenant-Key': keyFor(tenant) }, body: JSON.stringify({ query }),
  }).then((r) => r.json()).then((j) => (j.rows ?? []) as string[][])
  const rows = await run(SAMPLE)
  if (rows.length) return { edges: rows.map(([from, rel, to]) => ({ from, rel, to: String(to) })), cities: [] }
  return { edges: [], cities: (await run(CITIES)).map((r) => r[0]) }
}

/** A tenant's graph, drawn small from its own FalkorDB graph: customers in the middle, what we know around them. */
function Mini({ x, w, h, data, tone, glow }: { x: number; w: number; h: number; data?: { edges: Edge[]; cities: string[] }; tone: string; glow: boolean }) {
  const layout = useMemo(() => {
    if (!data) return { nodes: [] as { id: string; x: number; y: number; hub: boolean }[], links: [] as [number, number][] }
    const cx = x + w / 2, cy = h / 2
    if (!data.edges.length) {
      const nodes = data.cities.map((c, i) => ({ id: c, hub: false, x: cx + Math.cos((i / data.cities.length) * 6.283) * w * 0.32, y: cy + Math.sin((i / data.cities.length) * 6.283) * h * 0.32 }))
      return { nodes, links: [] }
    }
    const hubs = [...new Set(data.edges.map((e) => e.from))]
    const leaves = [...new Set(data.edges.map((e) => e.to))].filter((l) => !hubs.includes(l))
    const nodes = [
      ...hubs.map((id, i) => ({ id, hub: true, x: cx + Math.cos((i / hubs.length) * 6.283) * w * 0.14, y: cy + Math.sin((i / hubs.length) * 6.283) * h * 0.14 })),
      ...leaves.map((id, i) => ({ id, hub: false, x: cx + Math.cos((i / leaves.length) * 6.283 + 0.3) * w * 0.38, y: cy + Math.sin((i / leaves.length) * 6.283 + 0.3) * h * 0.38 })),
    ]
    const at = (id: string) => nodes.findIndex((n) => n.id === id)
    return { nodes, links: data.edges.map((e) => [at(e.from), at(e.to)] as [number, number]) }
  }, [data, x, w, h])
  return (
    <g>
      <rect x={x} y={8} width={w} height={h - 16} rx={22} className={glow ? 'fill-signal-tint' : 'fill-paper'} stroke="rgb(var(--line) / 0.1)" />
      {layout.links.map(([a, b], i) => <line key={i} x1={layout.nodes[a].x} y1={layout.nodes[a].y} x2={layout.nodes[b].x} y2={layout.nodes[b].y} stroke="rgb(var(--line) / 0.15)" />)}
      {layout.nodes.map((n) => (
        <g key={n.id}>
          <circle cx={n.x} cy={n.y} r={n.hub ? 7 : 4} fill={n.hub ? tone : 'rgb(var(--ink) / 0.35)'}><title>{n.id}</title></circle>
          {n.hub && <text x={n.x} y={n.y - 11} textAnchor="middle" className="fill-ink text-[10px] font-medium">{n.id.split(' ')[0]}</text>}
        </g>
      ))}
      {data && !data.edges.length && <text x={x + w / 2} y={h - 24} textAnchor="middle" className="fill-ink-3 text-[10px]">no customers yet: its graph holds the catalogue</text>}
    </g>
  )
}

export interface Shot { id: string; kind: 'cross' | 'own' | 'control'; verdict: 'blocked' | 'leaked' | 'ok' | 'running' | 'skipped'; got?: string }

/** Two tenants' graphs with the wall between them. Each attack flies from A toward B; refused ones stop at the wall. */
export function Boundary({ attacker, victim, shot }: { attacker: string; victim: string; shot?: Shot }) {
  const [a, setA] = useState<{ edges: Edge[]; cities: string[] }>()
  const [b, setB] = useState<{ edges: Edge[]; cities: string[] }>()
  useEffect(() => { sample(attacker).then(setA).catch(() => setA(undefined)) }, [attacker])
  useEffect(() => { sample(victim).then(setB).catch(() => setB(undefined)) }, [victim])
  const W = 900, H = 300, PW = 360, WALL = W / 2
  const flying = shot && shot.verdict !== 'running' && shot.verdict !== 'skipped'
  const end = !shot ? 0 : shot.kind === 'cross' ? (shot.verdict === 'leaked' ? W - PW / 2 : WALL - 14) : PW / 2
  return (
    <div className="overflow-x-auto rounded-2xl bg-surface p-3 hairline">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[640px]" role="img" aria-label={`mem:${attacker} and mem:${victim}, separated`}>
        <Mini x={0} w={PW} h={H} data={a} tone="rgb(var(--conflict))" glow={!!flying && shot!.kind !== 'cross'} />
        <Mini x={W - PW} w={PW} h={H} data={b} tone="rgb(var(--signal-deep))" glow={false} />
        <text x={PW / 2} y={30} textAnchor="middle" className="fill-ink-2 font-mono text-[12px]">mem:{attacker} · attacker's key</text>
        <text x={W - PW / 2} y={30} textAnchor="middle" className="fill-ink-2 font-mono text-[12px]">mem:{victim} · victim</text>
        <rect x={WALL - 8} y={24} width={16} height={H - 48} rx={8} fill="rgb(var(--ink))" />
        <text x={WALL} y={H - 8} textAnchor="middle" className="fill-ink-3 text-[10px]">API key check + separate graph</text>
        <AnimatePresence>
          {flying && (
            <motion.g key={shot!.id} initial={{ opacity: 1 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <motion.circle r={7} cy={H / 2} fill={shot!.verdict === 'leaked' ? 'rgb(var(--danger))' : 'rgb(var(--conflict))'}
                initial={{ cx: PW / 2 }} animate={{ cx: end }} transition={{ duration: shot!.kind === 'cross' ? 0.7 : 0.4, ease: 'easeIn' }} />
              {shot!.kind === 'cross' && shot!.verdict === 'blocked' && (
                <motion.g initial={{ opacity: 0, scale: 0.5 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.65 }} style={{ originX: `${WALL}px`, originY: `${H / 2}px` }}>
                  <circle cx={WALL} cy={H / 2} r={22} fill="rgb(var(--danger) / 0.18)" />
                  <text x={WALL} y={H / 2 - 30} textAnchor="middle" className="fill-danger text-[13px] font-semibold">{shot!.got}</text>
                </motion.g>
              )}
              {shot!.kind !== 'cross' && (
                <motion.text x={PW / 2} y={H / 2 + 32} textAnchor="middle" className="fill-ink text-[12px] font-semibold" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>
                  {shot!.got}
                </motion.text>
              )}
            </motion.g>
          )}
        </AnimatePresence>
      </svg>
    </div>
  )
}
