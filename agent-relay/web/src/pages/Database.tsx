import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ConsoleNav } from '../components/console/ConsoleNav'
import { Database, Play } from '../components/Icons'
import { api } from '../lib/api'
import { useTenant } from '../lib/tenant'
import type { DbHealth, QueryResult, Schema, SlowQuery, Snapshot } from '../lib/types'

const PRESETS: [string, string][] = [
  ['Where customers live', "MATCH (c:Customer)-[:LIVES_IN]->(city)\nRETURN c.name AS customer, city.name_key AS city\nORDER BY customer"],
  ['Knowledge that crossed agents', "MATCH (a:Agent)-[c:CONSULTED]->(f:Fact)\nWHERE f.asserted_by <> a.agent_id\nRETURN f.asserted_by AS wrote, a.agent_id AS used_by,\n       f.subject + ' ' + f.predicate + ' ' + f.object_value AS fact, c.count AS times\nORDER BY times DESC LIMIT 25"],
  ['A customer’s path to the internet', "MATCH p = (c:Customer)-[:HAS_ONT]->(:Ont)-[:DROP]->(:Splitter)-[:PON]->(:Olt)\n          -[:UPLINK]->(:Pop)-[:UPLINK {active:true}]->(:Backbone)\nRETURN c.name AS customer, [n IN nodes(p) | coalesce(n.label, n.home, n.name)] AS path\nLIMIT 10"],
  ['Capacity to the core (algo.maxFlow)', "MATCH (s:Olt:Up {node_id:'olt-pune-baner'})\nMATCH (b:Backbone:Up)\nWITH s, collect(b) AS cores\nCALL algo.maxFlow({sourceNodes:[s], targetNodes:cores, capacityProperty:'flow_gbps',\n                   nodeLabels:['Up'], relationshipTypes:['UPLINK']}) YIELD maxFlow\nRETURN s.label AS exchange, maxFlow AS gbps"],
  ['Procedural memory (fixes that worked)', "MATCH (f:Fact {predicate:'resolves', active:true})\nRETURN f.subject AS fix, f.object_value AS issue, f.learned_dt AS learned\nORDER BY f.recorded_at DESC LIMIT 20"],
  ['Facts that changed (supersede)', "MATCH (new:Fact)-[:SUPERSEDES]->(old:Fact)\nRETURN new.subject AS about, new.predicate AS what, old.object_value AS was, new.object_value AS now\nLIMIT 20"],
  ['Two clocks: true before we knew', "MATCH (f:Fact)\nWHERE f.valid_from < f.recorded_at - 3600000\nRETURN f.subject AS about, f.predicate AS what, f.object_value AS value,\n       f.valid_from_dt AS true_from, f.learned_dt AS on_file_from\nLIMIT 20"],
]

function Cell({ v }: { v: unknown }) {
  const [open, setOpen] = useState(false)
  if (v === null || v === undefined) return <span className="text-ink-3">—</span>
  if (typeof v === 'object' && !Array.isArray(v)) {
    const o = v as Record<string, unknown>
    const tag = o._node ? (o._node as string[]).filter((l) => !['Entity', 'NetNode', 'LastMile'].includes(l))[0] ?? (o._node as string[])[0] : o._edge ? `:${o._edge}` : 'map'
    const name = (o.name ?? o.name_key ?? o.label ?? o.node_id ?? o.fact_id ?? o.episode_id ?? '') as string
    return (
      <span className="inline-block max-w-[340px] align-top">
        <button className="chip bg-signal-tint text-signal-deep" onClick={() => setOpen((x) => !x)}>{tag}{name ? ` · ${String(name).slice(0, 40)}` : ''}</button>
        {open && <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-ink p-2 font-mono text-[10.5px] text-white/85">{JSON.stringify(o, null, 1)}</pre>}
      </span>
    )
  }
  if (Array.isArray(v)) return <span className="font-mono text-[11.5px]">{v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : String(x))).join(' → ')}</span>
  return <span className="num">{String(v)}</span>
}

/** FalkorDB itself, live and explorable: health, memory, schema, a read-only Cypher console, snapshots, slow queries. */
export default function DatabasePage() {
  const { tenant } = useTenant()
  const [graph, setGraph] = useState(tenant)
  const [health, setHealth] = useState<DbHealth>()
  const [pings, setPings] = useState<number[]>([])
  const [schema, setSchema] = useState<Schema>()
  const [slow, setSlow] = useState<SlowQuery[]>()
  const [snaps, setSnaps] = useState<Snapshot[]>()
  const [busy, setBusy] = useState<string>()
  const [msg, setMsg] = useState<string>()
  const [query, setQuery] = useState(PRESETS[0][1])
  const [result, setResult] = useState<QueryResult>()
  const [plan, setPlan] = useState<string[]>()
  const [qerr, setQerr] = useState<string>()
  useEffect(() => setGraph(tenant), [tenant])

  const ping = useCallback(() => api.dbHealth().then((h) => { setHealth(h); if (h.ping_ms != null) setPings((p) => [...p.slice(-39), h.ping_ms!]) })
    .catch(() => setHealth({ ok: false, error: 'API not reachable' } as DbHealth)), [])
  const load = useCallback(() => {
    api.schema(graph).then(setSchema).catch(() => setSchema(undefined))
    api.slowlog(graph).then((r) => setSlow(r.queries)).catch(() => setSlow([]))
    api.snapshots(graph).then((r) => setSnaps(r.snapshots)).catch(() => setSnaps([]))
  }, [graph])
  useEffect(() => { ping(); const id = setInterval(ping, 5000); return () => clearInterval(id) }, [ping])
  useEffect(() => { load(); setResult(undefined); setPlan(undefined) }, [load])

  const run = async (q = query, mode: 'run' | 'explain' | 'profile' = 'run') => {
    setBusy(mode); setQerr(undefined); setPlan(undefined)
    try {
      if (mode === 'run') setResult(await api.query(graph, q))
      else setPlan((await api.plan(graph, q, {}, mode === 'profile')).plan)
    } catch (e) { setQerr(e instanceof Error ? e.message.replace(/^.*"detail":"?|"?}$/g, '') : 'That did not run.') } finally { setBusy(undefined) }
  }
  const pick = (q: string) => { setQuery(q); run(q) }
  const save = async () => {
    setBusy('save'); setMsg(undefined)
    try { const r = await api.takeSnapshot(graph, 'manual'); setSnaps(r.snapshots); setMsg('Snapshot saved.') }
    catch { setMsg("Couldn't save a snapshot.") } finally { setBusy(undefined) }
  }
  const restore = async (name: string) => {
    if (!window.confirm(`Replace mem:${graph} with this snapshot? The current graph is overwritten.`)) return
    setBusy(name); setMsg(undefined)
    try { await api.restoreSnapshot(graph, name); setMsg('Restored. Reload the console to see it.'); load() }
    catch (e) { setMsg(e instanceof Error && e.message.includes('403') ? 'Benchmark workspaces are protected.' : "Couldn't restore.") }
    finally { setBusy(undefined) }
  }
  const maxPing = Math.max(50, ...pings)

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-[1300px] flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-6">
        <Link to="/console"><Wordmark sub="Database" /></Link>
        <ConsoleNav />
      </header>
      <main className="mx-auto max-w-[1300px] px-4 pb-20 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">FalkorDB, live</h1>
            <p className="mt-2 max-w-2xl text-sm text-ink-2">Pick a graph, see what's in it, and query it. Read-only, straight against FalkorDB Cloud.</p>
          </div>
          <div className="rounded-2xl bg-surface px-4 py-3 hairline">
            <p className="flex items-center justify-between gap-6 text-[11px] text-ink-3">Round trip
              <span className={`num font-semibold ${health && !health.ok ? 'text-danger' : 'text-ink'}`}>{health ? (health.ok ? `${health.ping_ms} ms` : 'down') : '…'}</span></p>
            <svg viewBox="0 0 160 32" className="mt-1 h-8 w-40" aria-label="Round trip over the last few minutes">
              <polyline fill="none" className="stroke-signal" strokeWidth="1.5" points={pings.map((p, i) => `${(i / 39) * 160},${30 - (p / maxPing) * 28}`).join(' ')} />
            </svg>
            <p className="text-[10.5px] text-ink-3 num">running {health?.running ?? 0} · waiting {health?.waiting ?? 0}</p>
          </div>
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <section className="rounded-2xl bg-surface p-4 hairline">
              <h2 className="font-display text-base font-semibold">Graphs · {health ? `${health.memory_mb ?? 0} of ${health.limit_mb ?? 100} MB` : '…'}</h2>
              <ul className="mt-2 space-y-1">
                {(health?.graphs ?? []).map((g) => (
                  <li key={g.tenant}>
                    <button onClick={() => setGraph(g.tenant)} className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition duration-300 ease-spring ${g.tenant === graph ? 'bg-ink text-paper' : 'hover:bg-sunk'}`}>
                      <span className="w-24 shrink-0 truncate font-mono text-[11.5px]">{g.tenant}</span>
                      <span className={`h-1.5 flex-1 overflow-hidden rounded-full ${g.tenant === graph ? 'bg-paper/20' : 'bg-sunk'}`}><span className="block h-full rounded-full bg-signal" style={{ width: `${Math.max(2, Math.min(100, (g.mb ?? 0) * 10))}%` }} /></span>
                      <span className="w-10 text-right text-[11px] num opacity-70">{g.mb != null ? (g.mb < 1 ? '<1' : g.mb) : '?'} MB</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-2xl bg-surface p-4 hairline">
              <h2 className="font-display text-base font-semibold">What's in mem:{graph}</h2>
              <p className="mt-1 text-[11px] text-ink-3">Click a label or relationship to look at it.</p>
              <p className="mt-3 eyebrow">Nodes</p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {(schema?.labels ?? []).map((l) => (
                  <button key={l.label} onClick={() => pick(`MATCH (n:${l.label})\nRETURN n LIMIT 25`)} className="chip bg-sunk text-ink-2 transition duration-300 ease-spring hover:bg-signal-tint hover:text-signal-deep">
                    {l.label} <span className="num text-ink-3">{l.count}</span></button>
                ))}
              </div>
              <p className="mt-3 eyebrow">Relationships</p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {(schema?.relationships ?? []).map((r) => (
                  <button key={r.type} onClick={() => pick(`MATCH (a)-[r:${r.type}]->(b)\nRETURN a, r, b LIMIT 25`)} className="chip bg-sunk font-mono text-[10.5px] text-ink-2 transition duration-300 ease-spring hover:bg-signal-tint hover:text-signal-deep">
                    {r.type} <span className="num text-ink-3">{r.count}</span></button>
                ))}
              </div>
              {schema && schema.indexes.length > 0 && (
                <>
                  <p className="mt-3 eyebrow">Indexes</p>
                  <ul className="mt-1.5 space-y-1 text-[11.5px]">
                    {schema.indexes.map((x, i) => (
                      <li key={i} className="flex justify-between gap-2"><span className="font-mono">:{x.label}({x.properties.join(', ')})</span>
                        <span className="text-ink-3">{Object.values(x.types).flat().join(', ').toLowerCase()}</span></li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          </aside>

          <div className="min-w-0 space-y-6">
            <section className="rounded-2xl bg-surface p-5 hairline">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="flex items-center gap-2 font-display text-lg font-semibold"><Database className="h-5 w-5" />Query mem:{graph}</h2>
                <span className="text-[11px] text-ink-3">read-only · first 200 rows</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {PRESETS.map(([label, q]) => (
                  <button key={label} onClick={() => pick(q)} className={`rounded-full px-3 py-1 text-xs transition duration-300 ease-spring ${query === q ? 'bg-ink text-paper' : 'bg-sunk text-ink-2 hover:bg-line/10'}`}>{label}</button>
                ))}
              </div>
              <label htmlFor="cypher" className="sr-only">Cypher</label>
              <textarea id="cypher" value={query} onChange={(e) => setQuery(e.target.value)} spellCheck={false} rows={6}
                onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') run() }}
                className="mt-3 w-full rounded-xl bg-ink p-3 font-mono text-[12.5px] leading-relaxed text-white/90 outline-none focus:ring-2 focus:ring-signal/50" />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button className="btn-primary !py-1.5 text-sm" disabled={!!busy} onClick={() => run()}><Play />{busy === 'run' ? 'Running…' : 'Run'}</button>
                <button className="btn-ghost !py-1.5 text-sm hairline" disabled={!!busy} onClick={() => run(query, 'explain')}>Explain</button>
                <button className="btn-ghost !py-1.5 text-sm hairline" disabled={!!busy} onClick={() => run(query, 'profile')}>Profile</button>
                <span className="text-[11px] text-ink-3">Ctrl+Enter runs</span>
                {result && !plan && <span className="ml-auto text-xs text-ink-2 num">{result.count} row{result.count === 1 ? '' : 's'} · {result.ms} ms</span>}
              </div>
              {qerr && <p className="mt-3 rounded-xl bg-danger-tint px-3 py-2 text-sm text-danger" role="alert">{qerr}</p>}
              {plan && <pre className="scroll-thin mt-3 max-h-80 overflow-auto rounded-xl bg-sunk/70 p-3 font-mono text-[11.5px] text-ink">{plan.join('\n')}</pre>}
              {result && !plan && (
                <div className="scroll-thin mt-3 max-h-[480px] overflow-auto rounded-xl ring-1 ring-line/10">
                  <table className="w-full text-left text-[12.5px]">
                    <thead className="sticky top-0 bg-paper"><tr>{result.columns.map((c) => <th key={c} className="px-3 py-2 font-mono text-[11px] font-medium text-ink-3">{c}</th>)}</tr></thead>
                    <tbody>
                      {result.rows.map((r, i) => (
                        <tr key={i} className="border-t border-line/[0.06] align-top">{r.map((v, j) => <td key={j} className="px-3 py-1.5"><Cell v={v} /></td>)}</tr>
                      ))}
                      {result.rows.length === 0 && <tr><td className="px-3 py-3 text-ink-3" colSpan={result.columns.length || 1}>No rows.</td></tr>}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <div className="grid gap-6 xl:grid-cols-2">
              <section className="rounded-2xl bg-surface p-5 hairline">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="font-display text-lg font-semibold">Snapshots</h2>
                  <button className="btn-primary !py-1.5 text-sm" onClick={save} disabled={!!busy}>{busy === 'save' ? 'Saving…' : 'Save snapshot'}</button>
                </div>
                <p className="mt-1 text-xs text-ink-3"><code className="font-mono">GRAPH.COPY</code> of mem:{graph}. One is taken before every story reset; the newest 3 are kept.</p>
                {msg && <p className="mt-2 text-sm text-ink-2" role="status">{msg}</p>}
                <ul className="mt-3 divide-y divide-ink/5 text-sm">
                  {(snaps ?? []).length === 0 && <li className="py-2 text-ink-3">No snapshots yet.</li>}
                  {(snaps ?? []).map((s) => (
                    <li key={s.name} className="flex items-center gap-3 py-2">
                      <span className="font-mono text-xs">{s.at.replace(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$/, '$1-$2-$3 $4:$5')}</span>
                      <span className="chip bg-sunk text-ink-2">{s.label}</span>
                      <button className="btn-ghost ml-auto !py-1 text-xs" disabled={!!busy} onClick={() => restore(s.name)}>{busy === s.name ? 'Restoring…' : 'Restore'}</button>
                    </li>
                  ))}
                </ul>
              </section>
              <section className="rounded-2xl bg-surface p-5 hairline">
                <h2 className="font-display text-lg font-semibold">Slowest queries</h2>
                <p className="mt-1 text-xs text-ink-3"><code className="font-mono">GRAPH.SLOWLOG</code>. Click one to load it into the console and profile it.</p>
                <ul className="scroll-thin mt-3 max-h-72 space-y-2 overflow-y-auto">
                  {(slow ?? []).length === 0 && <li className="text-sm text-ink-3">Nothing slow yet.</li>}
                  {(slow ?? []).map((q, i) => (
                    <li key={i}>
                      <button className="w-full rounded-xl bg-sunk/50 p-3 text-left transition duration-300 ease-spring hover:bg-sunk" onClick={() => { setQuery(q.query); run(q.query, 'profile') }}>
                        <p className="text-xs num"><span className="font-semibold">{q.ms.toFixed(1)} ms</span> <span className="text-ink-3">· {new Date(q.at * 1000).toLocaleString()}</span></p>
                        <pre className="mt-1 truncate font-mono text-[11px] text-ink">{q.query.replace(/\s+/g, ' ').slice(0, 160)}</pre>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            </div>

            <section className="rounded-2xl bg-surface p-5 hairline">
              <h2 className="font-display text-lg font-semibold">Server limits</h2>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm num sm:grid-cols-5">
                {Object.entries(health?.config ?? {}).map(([k, v]) => (
                  <div key={k}><dt className="font-mono text-[10.5px] text-ink-3">{k}</dt><dd className="font-medium">{typeof v === 'number' && k.includes('MEM') ? `${Math.round(v / 1048576)} MB` : typeof v === 'number' && k.startsWith('TIMEOUT') ? (v ? `${v / 1000} s` : 'none') : String(v)}</dd></div>
                ))}
              </dl>
            </section>
          </div>
        </div>
      </main>
    </div>
  )
}
