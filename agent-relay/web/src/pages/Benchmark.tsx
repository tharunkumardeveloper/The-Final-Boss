import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ConsoleNav } from '../components/console/ConsoleNav'
import { api, ApiError } from '../lib/api'
import { pct, wilson } from '../lib/format'
import { useTenant } from '../lib/tenant'
import type { Benchmark as B, BenchRow, Compare } from '../lib/types'

const SYSTEMS: [string, string][] = [
  ['FULL', 'Relay (graph memory)'], ['B1', 'Vector store + dates, newest first'], ['B0', 'Vector store'],
  ['A1', 'Relay without the two clocks'], ['A2', 'Relay without multi-hop'],
]
const TYPE_NAMES: Record<string, string> = {
  current: 'Current truth after changes', world_time: 'True on a past date', belief_time: 'On file on a past date',
  completeness: 'Complete lists', disagreement: 'Agent disagreement', handoff: 'Handoff between agents',
  multi_hop: 'Multi-hop', procedural: 'Fix that worked before', unknown: 'Should refuse to answer',
}
const COLORS: Record<string, string> = { FULL: 'bg-signal-deep', B1: 'bg-ink-3', B0: 'bg-old', A1: 'bg-signal/60', A2: 'bg-signal/40' }

function score(rows: BenchRow[]) {
  const ok = rows.filter((r) => !r.error)
  const k = ok.filter((r) => r.correct).length
  return { k, n: ok.length, p: ok.length ? k / ok.length : 0, ci: wilson(k, ok.length) }
}

function Bar({ sys, rows }: { sys: string; rows: BenchRow[] }) {
  const s = score(rows)
  if (!s.n) return <span className="text-xs text-ink-3">not run</span>
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-2.5 flex-1 rounded-full bg-sunk" aria-hidden="true">
        <i className={`absolute inset-y-0 left-0 rounded-full ${COLORS[sys] ?? 'bg-ink-3'}`} style={{ width: pct(s.p) }} />
        <i className="absolute top-1/2 h-4 -translate-y-1/2 border-x border-ink/50" style={{ left: pct(s.ci[0]), width: `calc(${pct(s.ci[1])} - ${pct(s.ci[0])})` }} />
      </div>
      <span className="num w-[132px] shrink-0 text-right text-xs"><strong className="text-sm text-ink">{pct(s.p)}</strong> <span className="text-ink-3">{s.k}/{s.n} · {pct(s.ci[0])}–{pct(s.ci[1])}</span></span>
    </div>
  )
}

const EXAMPLES = ['Where does Alice Rao live now?', 'Which plan is Bob Menon on?', "Which fix worked for Bob Menon's wifi drops?",
  'Where did Alice Rao live on 5 September?', 'Does Esha Kulkarni own a PS5?']

/** One question, both memories, same answer model: the benchmark made tangible. */
function AskBoth() {
  const { tenant } = useTenant()
  const [q, setQ] = useState(EXAMPLES[0])
  const [res, setRes] = useState<Compare>()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  const ask = async (question = q, e?: FormEvent) => {
    e?.preventDefault(); setQ(question); setBusy(true); setErr(undefined)
    try { setRes(await api.compare(tenant, question)) } catch (e) {
      // the API says why when it can (a graph with no conversations yet); otherwise the likely causes
      const detail = e instanceof ApiError ? (() => { try { return JSON.parse(e.message).detail } catch { return null } })() : null
      setErr(typeof detail === 'string' ? detail : "Couldn't ask. Is the API running, and is the model quota OK?")
    } finally { setBusy(false) }
  }
  const Side = ({ title, sub, s, tone }: { title: string; sub: string; s?: Compare['graph']; tone: string }) => (
    <div className={`rounded-2xl p-4 ${tone}`}>
      <p className="text-sm font-semibold">{title} <span className="font-normal text-ink-3">· {sub}</span></p>
      {busy && <p className="mt-3 h-6 w-2/3 animate-breathe rounded bg-sunk" />}
      {!busy && s && (
        <>
          <p className="mt-2 font-display text-xl font-semibold">{s.unknown ? "Doesn't know" : s.answer || '—'}</p>
          <p className="text-[11px] text-ink-3 num">{s.ms} ms to recall and answer{s.conflict ? ' · flags a disagreement' : ''}</p>
          <p className="mt-3 text-[11px] font-medium uppercase tracking-[0.12em] text-ink-3">What it read</p>
          <ul className="mt-1 space-y-1">
            {s.evidence.slice(0, 5).map((e, i) => <li key={i} className="truncate rounded-lg bg-surface/80 px-2 py-1 font-mono text-[10.5px] text-ink-2" title={e}>{e}</li>)}
          </ul>
        </>
      )}
    </div>
  )
  return (
    <section className="panel mt-10 p-6">
      <h2 className="eyebrow">Ask both memories</h2>
      <p className="mt-1 text-sm text-ink-3">The benchmark, live: one question to Relay's graph and to the vector-store baseline, same answer model. The first question takes a few seconds while the vector store embeds every message.</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {EXAMPLES.map((x) => <button key={x} onClick={() => ask(x)} disabled={busy} className={`rounded-full px-3 py-1 text-xs transition duration-300 ease-spring ${q === x ? 'bg-ink text-paper' : 'bg-sunk text-ink-2 hover:bg-line/10'}`}>{x}</button>)}
      </div>
      <form onSubmit={(e) => ask(q, e)} className="mt-3 flex gap-2">
        <label htmlFor="ask-both" className="sr-only">Question</label>
        <input id="ask-both" className="field flex-1" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-primary text-sm" disabled={busy || !q.trim()}>{busy ? 'Asking…' : 'Ask both'}</button>
      </form>
      {err && <p className="mt-3 text-sm text-danger" role="alert">{err}</p>}
      {(res || busy) && (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <Side title="Relay" sub="graph memory" s={res?.graph} tone="bg-signal-tint/60" />
          <Side title="Vector store" sub="top-10 messages, dated" s={res?.vector} tone="bg-sunk/70" />
        </div>
      )}
    </section>
  )
}

export default function Benchmark() {
  const [data, setData] = useState<B>()
  const [error, setError] = useState(false)
  useEffect(() => { api.benchmark().then(setData).catch(() => setError(true)) }, [])

  const systems = useMemo(() => SYSTEMS.filter(([s]) => data?.results?.systems?.[s]?.rows.length), [data])
  const types = useMemo(() => [...new Set(Object.values(data?.results?.systems ?? {}).flatMap((s) => s.rows.map((r) => r.type)))], [data])
  const rowsOf = (sys: string, type?: string) => (data?.results?.systems?.[sys]?.rows ?? []).filter((r) => !type || r.type === type)

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-6">
        <Link to="/console"><Wordmark sub="Benchmark" /></Link>
        <ConsoleNav />
      </header>
      <main className="mx-auto max-w-5xl px-4 pb-20 sm:px-6">
        <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">Does the graph earn its place?</h1>
        <p className="mt-3 max-w-2xl text-ink-2">
          Same questions, same answer model ({data?.results?.answer_model ?? '…'}), same prompt. Only the memory differs.
          Bars show accuracy; whiskers are 95% Wilson intervals. Small per-type cells are directional, so read the aggregate first.
        </p>
        {error && <p className="mt-8 text-sm text-danger" role="alert">Couldn't load benchmark results. Run <code className="font-mono">python -m eval.run_eval</code> on the API host.</p>}
        {!data && !error && <div className="mt-10 h-40 animate-breathe rounded-2xl bg-sunk" aria-busy="true" />}

        <AskBoth />

        {data?.results && (
          <>
            <section className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded-2xl bg-surface p-5 hairline">
                <p className="eyebrow">This run</p>
                <p className="mt-2 text-sm text-ink-2">
                  {rowsOf('FULL').length} of {data.results.dataset?.match(/(\d+) questions/)?.[1] ?? '160'} questions scored for Relay
                  {rowsOf('B1').length ? `, ${rowsOf('B1').length} for the vector baseline.` : '. The vector baseline hasn\'t been scored in this run yet.'}
                </p>
                <p className="mt-2 text-xs text-ink-3">Continue it on the API host: <code className="font-mono">python -m eval.run_eval --tenant pml</code> (it resumes, and waits out the free model quota).</p>
              </div>
              <div className="rounded-2xl bg-surface p-5 hairline">
                <p className="eyebrow">First run (in the README)</p>
                <p className="mt-2 font-display text-2xl font-semibold num">93% <span className="text-base font-normal text-ink-3">vs</span> 43%</p>
                <p className="text-xs text-ink-3">Relay vs vector store with dates, 74 questions over 8 customers (91% vs 43% on the 46 both answered).</p>
              </div>
            </section>
            <section className="panel mt-4 p-6">
              <h2 className="eyebrow">Overall</h2>
              <div className="mt-4 space-y-3">
                {systems.map(([s, name]) => (
                  <div key={s} className="grid grid-cols-1 items-center gap-1 sm:grid-cols-[260px_minmax(0,1fr)] sm:gap-4">
                    <span className="text-sm"><span className="font-mono text-xs text-ink-3">{s}</span> {name}</span>
                    <Bar sys={s} rows={rowsOf(s)} />
                  </div>
                ))}
              </div>
              {Array.isArray(data.results.pending) && data.results.pending.length > 0 && (
                <p className="mt-4 text-xs text-ink-3">{data.results.pending.length} (system, question) pairs still queued behind the free daily LLM quota.</p>
              )}
            </section>

            <section className="panel mt-4 p-6">
              <h2 className="eyebrow">Where the gap comes from</h2>
              <p className="mt-1 text-sm text-ink-3">The vector baseline holds up on simple recall and falls behind where structure matters: updates, time, disagreement.</p>
              <div className="mt-5 space-y-5">
                {types.map((t) => (
                  <div key={t}>
                    <p className="text-sm font-medium">{TYPE_NAMES[t] ?? t} <span className="num font-normal text-ink-3">· n={rowsOf('FULL', t).length}</span></p>
                    <div className="mt-2 space-y-1.5">
                      {SYSTEMS.filter(([s]) => s === 'FULL' || s === 'B1').map(([s]) => (
                        <div key={s} className="grid grid-cols-[48px_minmax(0,1fr)] items-center gap-3">
                          <span className="font-mono text-xs text-ink-3">{s}</span><Bar sys={s} rows={rowsOf(s, t)} />
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {data?.bench && (
          <section className="panel mt-4 overflow-x-auto p-6">
            <h2 className="eyebrow">Concurrency and scale</h2>
            <p className="mt-1 text-sm text-ink-3">{data.bench.note}</p>
            <table className="mt-4 w-full min-w-[560px] text-sm num">
              <thead><tr className="text-left text-xs text-ink-3"><th className="py-2 font-medium">Graphs</th><th className="font-medium">Writers</th><th className="font-medium">Writes/s</th><th className="font-medium">Write p50 / p95</th><th className="font-medium">Read p50 / p95</th><th className="font-medium">Duplicates</th></tr></thead>
              <tbody className="divide-y divide-line/[0.06]">
                {data.bench.concurrency?.map((r) => (
                  <tr key={r.graphs}><td className="py-2">{r.graphs}</td><td>{r.writer_threads}</td>
                    <td><span className="flex items-center gap-2"><span className="h-1.5 w-20 overflow-hidden rounded-full bg-sunk"><i className="block h-full rounded-full bg-signal-deep" style={{ width: `${Math.min(100, r.writes_per_s * 3)}%` }} /></span><strong>{r.writes_per_s}</strong></span></td>
                    <td>{Math.round(r.write_p50_ms)} / {Math.round(r.write_p95_ms)} ms</td><td>{Math.round(r.read_p50_ms)} / {Math.round(r.read_p95_ms)} ms</td>
                    <td className="text-current">{r.duplicate_entities + r.duplicate_active_facts}</td></tr>
                ))}
              </tbody>
            </table>
            <table className="mt-6 w-full min-w-[420px] text-sm num">
              <thead><tr className="text-left text-xs text-ink-3"><th className="py-2 font-medium">Customers</th><th className="font-medium">Facts</th><th className="font-medium">Recall p50 / p95 (no LLM)</th></tr></thead>
              <tbody className="divide-y divide-line/[0.06]">
                {data.bench.scale?.map((r) => (
                  <tr key={r.customers}><td className="py-2">{r.customers.toLocaleString('en-IN')}</td><td>{r.facts?.toLocaleString('en-IN') ?? '—'}</td>
                    <td>{r.error ? <span className="text-ink-3">{/maxmemory/.test(r.error) ? 'Not run: the free tier caps memory at 100 MB' : r.error}</span> : `${Math.round(r.recall_p50_ms!)} / ${Math.round(r.recall_p95_ms!)} ms`}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </main>
    </div>
  )
}
