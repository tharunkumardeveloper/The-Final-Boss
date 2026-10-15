import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { api } from '../lib/api'
import { useTenant } from '../lib/tenant'
import type { Isolation, Region } from '../lib/types'

/** One FalkorDB graph per region: what each holds, and proof that a customer's memory lives only in their own. */
export default function RegionsPage() {
  const { tenant, setTenant } = useTenant()
  const [regions, setRegions] = useState<Region[]>()
  const [error, setError] = useState(false)
  const [name, setName] = useState('alice rao')
  const [iso, setIso] = useState<Isolation>()
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.regions().then(setRegions).catch(() => setError(true)) }, [])
  const check = async (e?: FormEvent) => {
    e?.preventDefault(); setBusy(true)
    try { setIso(await api.isolation(name)) } catch { setIso(undefined) } finally { setBusy(false) }
  }

  return (
    <div className="min-h-[100dvh]">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Link to="/console"><Wordmark sub="Regions" /></Link>
        <Link to="/console" className="btn-ghost text-sm">Back to console</Link>
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">One graph per region</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-2">
          Each region's customers, agents' memory, catalogue and network live in their own FalkorDB graph on one instance
          (multigraph). Nothing is filtered by a tenant column: isolation is structural, so EU memory can't leak into an India query.
        </p>
        {error && <p className="mt-6 text-sm text-danger" role="alert">Couldn't load regions. Is the API running?</p>}
        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {regions?.map((r) => (
            <article key={r.code} className={`rounded-2xl bg-surface p-5 hairline ${r.tenant === tenant ? 'ring-2 ring-signal/50' : ''}`}>
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="font-display text-lg font-semibold">{r.name}</h2>
                <code className="font-mono text-[11px] text-ink-3">{r.graph}</code>
              </div>
              <p className="mt-1 text-xs text-ink-3">{r.countries.length} countries · {r.cities} cities</p>
              <p className="mt-2 line-clamp-2 text-xs text-ink-2">{r.countries.join(', ')}</p>
              {r.stats && (
                <dl className="mt-4 grid grid-cols-3 gap-2 num">
                  {[['Customers', r.stats.customers], ['Facts', r.stats.facts], ['Nodes', r.stats.nodes]].map(([k, v]) => (
                    <div key={k as string}><dt className="text-[11px] text-ink-3">{k}</dt><dd className="font-display text-xl font-semibold">{(v as number).toLocaleString()}</dd></div>
                  ))}
                </dl>
              )}
              {r.memory_mb != null && (
                <div className="mt-3">
                  <div className="h-1.5 overflow-hidden rounded-full bg-sunk" role="meter" aria-label="Graph memory against the 100 MB free tier"
                    aria-valuenow={r.memory_mb} aria-valuemin={0} aria-valuemax={100}>
                    <div className="h-full rounded-full bg-signal-deep" style={{ width: `${Math.max(1, Math.min(100, r.memory_mb))}%` }} />
                  </div>
                  <p className="mt-1 text-[11px] text-ink-3 num">{r.memory_mb < 1 ? 'under 1' : r.memory_mb} MB of the 100 MB free tier (GRAPH.MEMORY USAGE)</p>
                </div>
              )}
              <button className="btn-ghost mt-4 !px-0 text-sm" onClick={() => setTenant(r.tenant)} disabled={r.tenant === tenant}>
                {r.tenant === tenant ? 'Current workspace' : 'Work in this region'}
              </button>
            </article>
          ))}
        </section>
        <section className="mt-10 rounded-2xl bg-surface p-5 hairline">
          <h2 className="font-display text-lg font-semibold">Isolation check</h2>
          <p className="mt-1 text-xs text-ink-3">The same lookup runs against every region graph. A customer's memory should exist only where they live.</p>
          <form onSubmit={check} className="mt-4 flex gap-2">
            <label htmlFor="iso-name" className="sr-only">Customer name</label>
            <input id="iso-name" className="field flex-1" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-primary text-sm" disabled={busy}>Check every region</button>
          </form>
          {iso && (
            <>
              <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {iso.regions.map((r) => (
                  <li key={r.region} className={`flex items-center justify-between rounded-xl px-4 py-3 text-sm ${r.found ? 'bg-current-tint' : 'bg-sunk/60'}`}>
                    <span><span className="font-medium">{r.name}</span> <code className="font-mono text-[11px] text-ink-3">{r.graph}</code></span>
                    <span className="num text-ink-2">{r.found ? `${r.facts} facts` : 'not here'}</span>
                  </li>
                ))}
              </ul>
              <pre className="mt-4 overflow-x-auto rounded-xl bg-sunk/60 p-3 font-mono text-[11px] text-ink-2">{iso.query}</pre>
            </>
          )}
        </section>
      </main>
    </div>
  )
}
