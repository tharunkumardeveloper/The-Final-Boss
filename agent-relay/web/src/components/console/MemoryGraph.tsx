import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import { label as display, predicateLabel } from '../../lib/format'
import type { GraphState } from '../../lib/graph'

// Canvas colours (mirrors the CSS tokens; canvas can't read CSS variables cheaply per frame).
export const KIND_COLOR: Record<string, string> = {
  customer: '#0F1B2D', city: '#14A39A', plan: '#3D6FB6', router: '#5B7083', channel: '#2F8FC9', device: '#8B97A8',
  issue: '#C2553F', fix: '#3E8E5E', outage: '#A8322D', ticket: '#9A6B2F', status: '#A5AFBD', agent: '#44536A',
}
const INK = '#0F1B2D', SIGNAL = '#14A39A', AMBER = '#C47F0E', OLD = '#9AA5B4', EDGE = '#C3CBD6'
const FRESH_MS = 2600

type N = { id: string; kind: string; label: string; salience?: number; born?: number; appear?: number; x?: number; y?: number }
const FADE_MS = 700
type L = { id: string; source: string | N; target: string | N; label: string; active: boolean; conflict?: boolean; born?: number; faded?: number }
const idOf = (v: string | N) => (typeof v === 'string' ? v : v.id)

interface Props {
  store: GraphState
  version: number
  highlight?: Set<string>
  selected?: string | null
  focusId?: string | null
  onSelect: (id: string | null) => void
}

export function MemoryGraph({ store, version, highlight, selected, focusId, onSelect }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const fg = useRef<ForceGraphMethods<N, L>>()
  const [size, setSize] = useState({ w: 600, h: 400 })
  const fitted = useRef(false)
  const shown = useRef(store)
  if (shown.current !== store) { shown.current = store; fitted.current = false } // new snapshot: fit again
  const reduced = useMemo(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false, [])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const data = useMemo(() => {
    const nodes = [...store.nodes.values()] as N[]
    const links = ([...store.edges.values()] as L[]).filter((l) => store.nodes.has(idOf(l.source)) && store.nodes.has(idOf(l.target)))
    return { nodes, links }
  }, [store, version]) // store is mutated in place; version marks each change

  const degree = useMemo(() => {
    const d = new Map<string, number>()
    for (const l of data.links) if (l.active) for (const id of [idOf(l.source), idOf(l.target)]) d.set(id, (d.get(id) ?? 0) + 1)
    return d
  }, [data])

  useEffect(() => {
    fg.current?.d3Force('charge')?.strength(-140)
    fg.current?.d3Force('link')?.distance((l: L) => (l.active ? 46 : 64))
  }, [])

  const lit = highlight && highlight.size > 0
  const radius = (n: N) => (n.kind === 'customer' ? 7 : 4.5) + Math.min(degree.get(n.id) ?? 0, 10) * 0.35 + (n.salience ?? 0) * 14

  return (
    <div ref={box} className="absolute inset-0" aria-label="Live memory graph" role="img">
      <ForceGraph2D<N, L>
        ref={fg}
        width={size.w}
        height={size.h}
        graphData={data}
        backgroundColor="rgba(0,0,0,0)"
        autoPauseRedraw={false}
        cooldownTicks={reduced ? 0 : 120}
        d3VelocityDecay={0.32}
        linkHoverPrecision={6}
        onEngineStop={() => {
          if (fitted.current || !data.nodes.length) return
          fitted.current = true
          fg.current?.zoomToFit(reduced ? 0 : 450, 70)
          const f = focusId ? (store.nodes.get(focusId) as N | undefined) : undefined
          if (f?.x !== undefined) setTimeout(() => fg.current?.centerAt(f.x, f.y, reduced ? 0 : 600), reduced ? 0 : 480)
        }}
        onNodeClick={(n) => onSelect(n.id)}
        onLinkClick={(l) => onSelect(l.id)}
        onBackgroundClick={() => onSelect(null)}
        nodeLabel={(n) => `${n.kind}: ${display(n.label, n.kind)}`}
        linkLabel={(l) => `${predicateLabel(l.label)}${l.active ? '' : ' (superseded)'}${l.conflict ? ' · conflict' : ''}`}
        nodeCanvasObject={(n, ctx, scale) => {
          const r = radius(n), x = n.x ?? 0, y = n.y ?? 0
          const dim = lit && !highlight!.has(n.id)
          const age = n.born ? Date.now() - n.born : FRESH_MS
          const fade = !reduced && n.appear ? Math.min(1, (Date.now() - n.appear) / FADE_MS) : 1
          ctx.globalAlpha = (dim ? 0.22 : 1) * fade
          if (n.id === focusId) {
            ctx.beginPath(); ctx.arc(x, y, r + 5, 0, 2 * Math.PI)
            ctx.fillStyle = 'rgba(20,163,154,0.14)'; ctx.fill()
            ctx.strokeStyle = SIGNAL; ctx.lineWidth = 2 / scale; ctx.stroke()
          }
          if (!reduced && age < FRESH_MS) {
            const t = age / FRESH_MS
            ctx.beginPath(); ctx.arc(x, y, r + 3 + t * 10, 0, 2 * Math.PI)
            ctx.strokeStyle = `rgba(20,163,154,${0.55 * (1 - t)})`; ctx.lineWidth = 2 / scale; ctx.stroke()
          }
          ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI)
          ctx.fillStyle = KIND_COLOR[n.kind] ?? '#7A8799'; ctx.fill()
          if (n.kind === 'customer') { ctx.beginPath(); ctx.arc(x, y, r * 0.38, 0, 2 * Math.PI); ctx.fillStyle = SIGNAL; ctx.fill() }
          if (n.id === selected || (lit && highlight!.has(n.id))) {
            ctx.beginPath(); ctx.arc(x, y, r + 2.5, 0, 2 * Math.PI)
            ctx.strokeStyle = n.id === selected ? INK : SIGNAL; ctx.lineWidth = 1.6 / scale; ctx.stroke()
          }
          if (scale > 0.9 || n.kind === 'customer' || n.id === selected || n.id === focusId || (lit && highlight!.has(n.id))) {
            const fs = Math.max(10.5 / scale, 2.4)
            ctx.font = `${n.kind === 'customer' ? 600 : 500} ${fs}px "Instrument Sans", sans-serif`
            ctx.textAlign = 'center'; ctx.textBaseline = 'top'
            const text = display(n.label, n.kind)
            const w = ctx.measureText(text).width
            ctx.fillStyle = 'rgba(244,246,248,0.85)'; ctx.fillRect(x - w / 2 - 2 / scale, y + r + 2 / scale, w + 4 / scale, fs + 2 / scale)
            ctx.fillStyle = n.kind === 'customer' ? INK : '#44536A'; ctx.fillText(text, x, y + r + 3 / scale)
          }
          ctx.globalAlpha = 1
        }}
        nodePointerAreaPaint={(n, color, ctx) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x ?? 0, n.y ?? 0, radius(n) + 3, 0, 2 * Math.PI); ctx.fill() }}
        linkCanvasObjectMode={() => 'replace'}
        linkCanvasObject={(l, ctx, scale) => {
          const s = l.source as N, t = l.target as N
          if (s.x === undefined || t.x === undefined) return
          const on = lit && highlight!.has(l.id)
          const age = l.born ? Date.now() - l.born : FRESH_MS
          ctx.save()
          const fade = reduced ? 1 : Math.min(...[s.appear, t.appear].map((a) => (a ? Math.min(1, (Date.now() - a) / FADE_MS) : 1)))
          ctx.globalAlpha = (lit && !on ? 0.15 : l.active ? 1 : 0.55) * fade
          if (l.conflict && l.active) { ctx.shadowColor = 'rgba(196,127,14,0.55)'; ctx.shadowBlur = 8 }
          ctx.strokeStyle = on ? SIGNAL : l.conflict && l.active ? AMBER : !l.active ? OLD : age < FRESH_MS && !reduced ? SIGNAL : EDGE
          ctx.lineWidth = (on ? 2.4 : l.conflict ? 1.8 : 1.1) / scale
          ctx.setLineDash(l.active ? [] : [4 / scale, 3 / scale])
          ctx.beginPath(); ctx.moveTo(s.x!, s.y!); ctx.lineTo(t.x!, t.y!); ctx.stroke()
          if (l.id === selected) { ctx.strokeStyle = INK; ctx.lineWidth = 2 / scale; ctx.stroke() }
          if (scale > 1.5 || on || l.id === selected) {
            const fs = Math.max(9 / scale, 2)
            ctx.shadowBlur = 0; ctx.setLineDash([])
            ctx.font = `500 ${fs}px "IBM Plex Mono", monospace`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
            ctx.fillStyle = l.active ? '#44536A' : OLD
            ctx.fillText(l.label, (s.x! + t.x!) / 2, (s.y! + t.y!) / 2 - 4 / scale)
          }
          ctx.restore()
        }}
      />
    </div>
  )
}
