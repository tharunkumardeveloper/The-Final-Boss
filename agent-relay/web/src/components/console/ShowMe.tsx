import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { titleCase } from '../../lib/format'
import type { ConfirmResult, DemoPicks, Hop, ToolResult } from '../../lib/types'
import { Hops, OutcomeChip, shortDate } from '../Hops'

type Demo = 'clock' | 'conflict' | 'blast'
type Ran = { demo: Demo; a: ToolResult; b?: ToolResult; label: [string, string?] }

/** A path as one line: Dev → CONNECTED_VIA → Andheri OLT → UPLINK → Mumbai POP. */
function PathLine({ hops }: { hops: Hop[] }) {
  return (
    <p className="text-[11px] leading-relaxed text-ink-2">
      {hops.map((h, i) => (
        <span key={i}>{i === 0 && <span className="font-medium text-ink">{titleCase(h.from)}</span>}
          <span className="font-mono text-[10px] text-signal-deep"> → {h.rel} → </span>
          <span className="font-medium text-ink">{titleCase(h.to)}</span></span>
      ))}
    </p>
  )
}

function Clock({ r, predicate, label }: { r: ToolResult; predicate: string; label: string }) {
  const rows = r.paths.filter((p) => p[0] && r.result.find((f) => f.fact_id === p[0].fact_id)?.predicate === predicate)
  return (
    <div className="min-w-0 flex-1 rounded-xl bg-sunk/60 p-3">
      <p className="eyebrow">{label}</p>
      {rows.length ? rows.map((p, i) => <div key={i} className="mt-1.5"><p className="font-display text-lg font-semibold">{titleCase(p[0].to)}</p><Hops hops={p} /></div>)
        : <p className="mt-1.5 text-sm text-ink-3">Nothing true yet on the world clock.</p>}
      {r.extra.belief && r.extra.at && (
        <p className="mt-2 text-[11px] text-ink-3">On file then (system clock): {r.extra.belief.filter((b: any) => b.predicate === predicate).map((b: any) => titleCase(b.value)).join(', ') || 'nothing'}</p>
      )}
    </div>
  )
}

function Blast({ r, label }: { r: ToolResult; label: string }) {
  const kinds = new Map<string, number>()
  for (const x of r.result) kinds.set(x.kind, (kinds.get(x.kind) ?? 0) + 1)
  return (
    <div className="min-w-0 flex-1 rounded-xl bg-sunk/60 p-3">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 font-display text-lg font-semibold num">{r.extra.customers ?? 0} customer{r.extra.customers === 1 ? '' : 's'}</p>
      <p className="text-[11px] text-ink-3">{[...kinds].map(([k, n]) => `${n} ${k}`).join(' · ') || 'nothing below it'}</p>
      <div className="mt-2 max-h-48 space-y-1 overflow-y-auto scroll-thin">
        {r.paths.slice(0, 30).map((p, i) => <PathLine key={i} hops={p} />)}
      </div>
    </div>
  )
}

/** One-click 15-second contrasts over real entities of this tenant (read-only tool calls). */
export function ShowMe({ tenant, kind = 'memory' }: { tenant: string; kind?: 'memory' | 'network' }) {
  const [picks, setPicks] = useState<DemoPicks>()
  const [ran, setRan] = useState<Ran>()
  const [busy, setBusy] = useState<Demo>()
  const [error, setError] = useState<string>()
  const [settled, setSettled] = useState<ConfirmResult>()  // a person said which claim is right
  const [confirming, setConfirming] = useState<string>()
  useEffect(() => {
    setPicks(undefined); setRan(undefined); setSettled(undefined)
    api.demos(tenant).then(setPicks).catch(() => setPicks({ clock: null, conflict: null, exchange: null }))
  }, [tenant])

  /** "This one is right": the other claims retire (kept in history), the Conflict closes, trust learns from it. */
  const confirm = async (factId: string) => {
    const c = picks?.conflict
    if (!c) return
    setConfirming(factId); setError(undefined)
    try {
      const res = await api.confirmClaim(tenant, { subject: c.name, predicate: c.predicate, fact_id: factId })
      setSettled(res)
      setRan({ demo: 'conflict', a: await api.tool(tenant, 'claims', { name: c.name, predicate: c.predicate }), label: [c.question] })
    } catch (e) { setError(e instanceof Error && /isn't active/.test(e.message) ? 'That claim was already settled. Run it again to see the current state.' : 'Could not record that right now.') }
    finally { setConfirming(undefined) }
  }

  const run = async (demo: Demo) => {
    if (!picks) return
    setBusy(demo); setError(undefined); setSettled(undefined)
    try {
      if (demo === 'clock' && picks.clock) {
        const c = picks.clock
        const [a, b] = await Promise.all([api.tool(tenant, 'facts_at', { name: c.name, at: 'now' }), api.tool(tenant, 'facts_at', { name: c.name, at: c.before })])
        setRan({ demo, a, b, label: ['Now', `As of ${shortDate(c.before)}`] })
      } else if (demo === 'conflict' && picks.conflict) {
        setRan({ demo, a: await api.tool(tenant, 'claims', { name: picks.conflict.name, predicate: picks.conflict.predicate }), label: [picks.conflict.question] })
      } else if (demo === 'blast' && picks.exchange) {
        const n = picks.exchange.node
        const [a, b] = await Promise.all([api.tool(tenant, 'affected_by', { node: n, depth: 1 }), api.tool(tenant, 'affected_by', { node: n, depth: 3 })])
        setRan({ demo, a, b, label: ['Depth 1', 'Depth 3'] })
      }
    } catch { setError('That demo could not run right now.') } finally { setBusy(undefined) }
  }

  const options: [Demo, string, string][] = kind === 'network'
    ? (picks?.exchange ? [['blast', `${picks.exchange.label} is down: who is affected?`, 'The same question at depth 1 and depth 3, with the path for every row.']] : [])
    : [
        ...(picks?.clock ? [['clock', picks.clock.question, `Asked now and as of ${shortDate(picks.clock.before)}: two clocks, two answers.`] as [Demo, string, string]] : []),
        ...(picks?.conflict ? [['conflict', picks.conflict.question, 'Both agents’ claims, who wrote each, the trust ranking and the Conflict node.'] as [Demo, string, string]] : []),
      ]

  return (
    <section className="mt-5 rounded-2xl bg-surface p-3 hairline" aria-label="Show me">
      <p className="eyebrow">Show me · 15 seconds</p>
      {!picks && <p className="mt-2 text-xs text-ink-3 animate-breathe">Looking for real examples in this graph…</p>}
      {picks && options.length === 0 && (
        <p className="mt-2 text-xs text-ink-3">{kind === 'network' ? 'No exchange in this graph has customers below it yet.' : 'This graph has no changed fact or disagreement to contrast yet. Chat from the portal or press play, then come back.'}</p>
      )}
      <div className="mt-2 space-y-1.5">
        {options.map(([id, q, hint]) => (
          <button key={id} onClick={() => run(id)} disabled={!!busy}
            className={`w-full rounded-xl px-3 py-2 text-left transition duration-300 ease-spring hover:bg-signal-tint ${ran?.demo === id ? 'bg-signal-tint' : 'bg-sunk/60'}`}>
            <span className="block text-sm font-medium text-ink">{busy === id ? 'Running…' : q}</span>
            <span className="block text-[11px] text-ink-3">{hint}</span>
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-xs text-danger" role="alert">{error}</p>}
      {ran && !busy && (
        <div className="mt-3 animate-rise">
          {ran.demo === 'clock' && picks?.clock && ran.b && (
            <div className="flex flex-col gap-2 sm:flex-row">
              <Clock r={ran.a} predicate={picks.clock.predicate} label={ran.label[0]} />
              <Clock r={ran.b} predicate={picks.clock.predicate} label={ran.label[1]!} />
            </div>
          )}
          {ran.demo === 'conflict' && (
            <div className="rounded-xl bg-sunk/60 p-3">
              <div className="flex flex-wrap items-center gap-1.5"><OutcomeChip outcome={ran.a.outcome} />{ran.a.extra.disputed && <span className="chip-updated">Agents disagree</span>}</div>
              <ol className="mt-2 space-y-2">
                {ran.a.result.map((c: any, i: number) => (
                  <li key={c.fact_id} className="text-sm">
                    <p><span className="num text-ink-3">#{c.rank}</span> <span className="font-semibold">{titleCase(c.value)}</span>
                      <span className="text-xs text-ink-3"> · written by {c.agents.join(', ')} · trust {c.trust}
                        {c.record ? ` (fixed ${c.base_trust}, ${c.record > 0 ? '+' : ''}${c.record} from people's confirmations)` : ''}</span>
                      {c.preferred && <span className="chip-new ml-1.5 !py-0 text-[10px]">preferred</span>}
                      {settled?.confirmed.fact_id === c.fact_id && <span className="chip ml-1.5 bg-current-tint !py-0 text-[10px] text-current">confirmed by a person</span>}</p>
                    {ran.a.paths[i] && <Hops hops={ran.a.paths[i]} />}
                    {ran.a.extra.disputed && (
                      <button onClick={() => confirm(c.fact_id)} disabled={!!confirming}
                        className="mt-1 rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-medium text-signal-deep hairline transition hover:bg-signal-tint disabled:opacity-50">
                        {confirming === c.fact_id ? 'Recording…' : 'This one is right'}</button>
                    )}
                  </li>
                ))}
              </ol>
              {settled && (
                <div className="mt-2 rounded-lg bg-current-tint px-3 py-2 text-xs text-ink" role="status">
                  <p><span className="font-semibold">Settled: {titleCase(settled.confirmed.value)}.</span>
                    {settled.rejected.length ? ` ${settled.rejected.map((r) => titleCase(r.value)).join(', ')} retired: both clocks closed, kept in history as rejected.` : ''} The Conflict is closed.</p>
                  <p className="mt-0.5 text-ink-2">Trust learned for this kind of fact: {settled.trust.map((t) => `${t.agent} ${t.from} → ${t.to}`).join(' · ')}. The next disagreement like this is ranked with it.</p>
                </div>
              )}
              {ran.a.extra.conflict && (
                <p className="mt-2 font-mono text-[10.5px] text-ink-3">(:Conflict {'{'}id: '{ran.a.extra.conflict.id}', status: '{ran.a.extra.conflict.status}', policy: '{ran.a.extra.conflict.policy}'{'}'})-[:BETWEEN]-&gt;(:Fact) ×{ran.a.result.length}</p>
              )}
            </div>
          )}
          {ran.demo === 'blast' && ran.b && (
            <div className="flex flex-col gap-2 sm:flex-row"><Blast r={ran.a} label={ran.label[0]} /><Blast r={ran.b} label={ran.label[1]!} /></div>
          )}
          <p className="mt-2 text-[11px] text-ink-3 num">
            {[ran.a, ran.b].filter(Boolean).map((r) => `${r!.tool}(${Object.values(r!.args).join(', ')}) · ${r!.rows} rows · ${r!.ms} ms`).join('  |  ')}
          </p>
        </div>
      )}
    </section>
  )
}
