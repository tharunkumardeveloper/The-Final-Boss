import { memo } from 'react'
import { touchOf, useTouchTick } from '../../lib/touch'

export interface Mark { id: string; keys: (string | null | undefined)[]; x: number; y: number; r: number }
export interface Link { id: string; a: string; b: string; d: string }

/** The live-query glow over a network drawing, in its own layer: only this re-renders while queries run, so the
 *  drawing under it (and its flow and alarm animations) is never redrawn by a burst of query events. */
export const TouchLayer = memo(function TouchLayer({ marks, links = [], grow = 12 }: { marks: Mark[]; links?: Link[]; grow?: number }) {
  useTouchTick()
  return (
    <g pointerEvents="none">
      {links.map((l) => {
        const ta = touchOf(l.a), tb = touchOf(l.b)
        const w = ta && tb ? Math.min(ta.glow, tb.glow) : 0  // both ends read by the query: it walked this link
        return w > 0 && <path key={l.id} d={l.d} fill="none" stroke="rgb(125 211 252)" strokeOpacity={w} strokeWidth={3} />
      })}
      {marks.map((m) => {
        const t = touchOf(...m.keys)
        return t && <circle key={m.id} cx={m.x} cy={m.y} r={m.r + (1 - t.glow) * grow} fill={t.write ? 'rgb(134 239 172 / 0.12)' : 'rgb(125 211 252 / 0.12)'}
          fillOpacity={t.glow} stroke={t.write ? 'rgb(134 239 172)' : 'rgb(125 211 252)'} strokeOpacity={t.glow} strokeWidth={2.5} />
      })}
    </g>
  )
})
