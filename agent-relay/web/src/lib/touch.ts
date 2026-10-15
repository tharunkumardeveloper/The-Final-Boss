import { useEffect, useState } from 'react'
import type { RelayEvent } from './types'

/** What each live Cypher query touched: the keys it started from (seek) and came back with (found).
 *  Fed by every open stream; graph views read it to light up the exact nodes and edges a query used. */
export interface Touch { name: string; write: boolean; seek: string[]; found: string[]; at: number; id: number }
export const TOUCH_MS = 2200
const recent: Touch[] = []
const byKey = new Map<string, { at: number; write: boolean; found: boolean }>()
const listeners = new Set<() => void>()
let seq = 0

// The screens' own page loads read everything at once; only the agents' work should light up.
const VIEW = /^(graph:|network:|schema:|sharing:|card:|stats|customers|tickets|community nodes|top communities|relationship types|conflict count)/

export function recordTouch(e: RelayEvent) {
  if (e.type !== 'cypher' || VIEW.test(e.data.name) || (!e.data.seek?.length && !e.data.found?.length)) return
  const t: Touch = { name: e.data.name, write: !!e.data.write, seek: e.data.seek ?? [], found: e.data.found ?? [], at: Date.now(), id: ++seq }
  recent.unshift(t); recent.length = Math.min(recent.length, 12)
  for (const k of t.seek) byKey.set(k, { at: t.at, write: t.write, found: false })
  for (const k of t.found) byKey.set(k, { at: t.at, write: t.write, found: true })
  listeners.forEach((fn) => fn())
}

/** How recently a key was touched: 1 just now, fading to 0 over TOUCH_MS. */
export function touchOf(...keys: (string | undefined | null)[]) {
  let best: { glow: number; write: boolean; found: boolean } | null = null
  for (const k of keys) {
    const t = k ? byKey.get(k.toLowerCase()) : undefined
    const glow = t ? 1 - (Date.now() - t.at) / TOUCH_MS : 0
    if (t && glow > 0 && (!best || glow > best.glow)) best = { glow, write: t.write, found: t.found }
  }
  return best
}

export const recentTouches = () => recent.filter((t) => Date.now() - t.at < TOUCH_MS * 2)

/** Re-render ~12 times a second while something is glowing (for SVG views; canvas views redraw anyway). */
export function useTouchTick() {
  const [, set] = useState(0)
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined
    const start = () => {
      clearInterval(timer)
      const until = Date.now() + TOUCH_MS * 2
      timer = setInterval(() => { set((n) => n + 1); if (Date.now() > until) clearInterval(timer) }, 80)
    }
    listeners.add(start)
    return () => { listeners.delete(start); clearInterval(timer) }
  }, [])
}
