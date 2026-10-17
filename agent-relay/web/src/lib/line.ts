import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { LabRun, LabView, RelayEvent } from './types'

type Subscribe = (fn: (e: RelayEvent) => void) => () => void
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const latestFor = (v: LabView, who: string) => v.runs.filter((r) => r.customer === who).sort((a, b) => b.started_at - a.started_at)[0]

/** One customer's line and the resolver's latest run on it, shared by the portal's network lab and tickets panel.
 *  Steps are appended as they stream in; the view is refetched only when the network can have changed, and an
 *  unchanged network keeps its old object, so the drawing (and its animations) isn't rebuilt by every refresh. */
export function useLine(tenant: string, who: string | null, subscribe: Subscribe) {
  const [view, setView] = useState<LabView>()
  const [run, setRun] = useState<LabRun>()
  const key = useRef('')
  const runId = useRef<string>()
  const timer = useRef<ReturnType<typeof setTimeout>>()
  key.current = `${tenant}:${who}`
  runId.current = run?.id

  const load = useCallback(() => {
    if (!who) return
    const asked = `${tenant}:${who}`
    api.lab(tenant, who).then((v) => {
      if (key.current !== asked) return  // the customer or region changed while this was in flight
      if (v.focus !== who) { setView(undefined); setRun(undefined); return }
      setView((old) => old?.network && v.network && same(old.network, v.network) ? { ...v, network: old.network } : v)
      const next = latestFor(v, who)
      setRun((old) => {
        if (!next) return undefined
        if (!old || old.id !== next.id) return next
        const steps = old.steps.length > next.steps.length ? old.steps : next.steps  // streamed steps can be ahead
        const merged = { ...next, steps, messages: old.messages.length > next.messages.length ? old.messages : next.messages }
        return same(old, merged) ? old : merged
      })
    }).catch(() => {})  // keep what's on screen: a failed refresh shouldn't blank the diagram
  }, [tenant, who])

  useEffect(() => {
    setView(undefined); setRun(undefined)
    load()
    return () => clearTimeout(timer.current)
  }, [load])

  useEffect(() => subscribe((e) => {
    if (!who) return
    const soon = (ms = 450) => { clearTimeout(timer.current); timer.current = setTimeout(load, ms) }
    const d = e.data as { run?: string; step?: LabRun['steps'][number]; message?: LabRun['messages'][number]; customer?: string
      status?: string; subject?: string; predicate?: string }
    if (e.type === 'lab_step') {
      if (d.run !== runId.current) { if (!runId.current) soon(); return }
      setRun((r) => {
        if (!r || r.id !== d.run) return r
        if (d.step && r.steps.some((x) => x.i === d.step!.i)) return r
        return { ...r, steps: d.step ? [...r.steps, d.step] : r.steps, messages: d.message ? [...r.messages, d.message] : r.messages }
      })
      if (d.step && ['act', 'verify', 'wait'].includes(d.step.kind)) soon()  // the network or the run's status moves
    } else if (e.type === 'lab_run') {
      if (!d.customer || d.customer === who || d.run === runId.current) soon(150)
    } else if (e.type === 'lab_state') soon()
    else if ((e.type === 'fact_created' || e.type === 'fact_superseded') && (d.predicate === 'lives_in' || d.predicate === 'address')
      && (d.subject ?? d.customer)?.toLowerCase() === who) soon(600)
  }), [subscribe, who, load])

  const hasLine = !!who && view?.focus === who && !!view.network
  return { view: hasLine ? view : undefined, run, hasLine, reload: load }
}
