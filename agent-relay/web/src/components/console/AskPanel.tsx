import { useState, type FormEvent } from 'react'
import { api } from '../../lib/api'
import { titleCase } from '../../lib/format'
import type { AskResponse, CypherEntry, Graph } from '../../lib/types'
import { Send, Sparkle } from '../Icons'

const SUGGEST = ['Which plan is Alice Rao on?', 'Where does Alice Rao live?', 'Which outage might affect Alice Rao?', 'What fix should we try for evening wifi drops?']

/** Fact → episode → session → agent, read off the answer's path graph. */
function chains(path: Graph) {
  const byId = new Map(path.nodes.map((n) => [n.id, n]))
  const into = (target: string, label: string) => path.edges.filter((e) => e.target === target && e.label === label).map((e) => byId.get(e.source))
  const outOf = (source: string, label: string) => path.edges.filter((e) => e.source === source && e.label === label).map((e) => byId.get(e.target))
  return path.nodes.filter((n) => n.kind === 'fact').map((f) => {
    const eps = into(f.id, 'DERIVED').filter(Boolean)
    return {
      fact: f,
      sources: eps.map((ep) => ({ episode: ep!, session: outOf(ep!.id, 'IN')[0], agent: into(ep!.id, 'WROTE')[0] })),
      replaced: outOf(f.id, 'SUPERSEDES').filter(Boolean),
    }
  })
}

export function AskPanel({ tenant, onAnswer, logCypher }: {
  tenant: string; onAnswer: (ids: Set<string>) => void; logCypher: (a: string, e?: CypherEntry[]) => void
}) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<AskResponse & { question: string }>()
  const [error, setError] = useState<string>()

  async function ask(e?: FormEvent, preset?: string) {
    e?.preventDefault()
    const question = (preset ?? q).trim()
    if (!question || busy) return
    setBusy(true); setError(undefined); setQ(question)
    try {
      const r = await api.ask(tenant, question)
      setRes({ ...r, question })
      logCypher(`ask: ${question}`, r.cypher)
      onAnswer(new Set([...r.path.nodes.map((n) => n.id), ...r.cited_ids.map((c) => (c.startsWith('f:') ? c : `f:${c}`))]))
    } catch {
      setError('The resolver could not answer right now. Try again in a moment.')
    } finally { setBusy(false) }
  }

  return (
    <div className="px-5 py-5">
      <form onSubmit={ask} className="flex items-center gap-2">
        <label htmlFor="ask" className="sr-only">Ask the resolver</label>
        <input id="ask" className="field rounded-full" placeholder="Ask the resolver about any customer" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-primary h-10 w-10 shrink-0 !p-0" aria-label="Ask" disabled={busy || !q.trim()}><Send /></button>
      </form>
      {!res && !busy && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {SUGGEST.map((s) => <button key={s} onClick={() => ask(undefined, s)} className="rounded-full bg-sunk px-3 py-1 text-xs text-ink-2 transition duration-300 ease-spring hover:bg-signal-tint hover:text-signal-deep">{s}</button>)}
        </div>
      )}
      {busy && <p className="mt-4 text-sm text-ink-3 animate-breathe">Following the graph…</p>}
      {error && <p className="mt-4 text-sm text-danger" role="alert">{error}</p>}
      {res && !busy && (
        <div className="mt-5 animate-rise">
          <p className="eyebrow">{res.question}</p>
          <p className="mt-2 text-[15px] leading-relaxed text-ink">{res.answer}</p>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {res.values.map((v) => <span key={v} className="chip bg-ink text-paper">{titleCase(v)}</span>)}
            {res.conflict && <span className="chip-updated">Agents disagree</span>}
            {res.unknown && <span className="chip bg-sunk text-ink-2">Not in memory, so no guess</span>}
            {!res.unknown && !res.conflict && <span className="chip-new">Grounded in {res.cited_ids.length} fact{res.cited_ids.length === 1 ? '' : 's'}</span>}
          </div>
          {chains(res.path).length > 0 && (
            <section className="mt-5">
              <h4 className="eyebrow flex items-center gap-1.5"><Sparkle className="h-3.5 w-3.5" /> Why it thinks so</h4>
              <ol className="mt-2 space-y-2.5">
                {chains(res.path).map(({ fact, sources, replaced }) => (
                  <li key={fact.id} className="rounded-xl bg-sunk/60 px-3 py-2.5 text-sm">
                    <p className="font-medium text-ink">{fact.label}</p>
                    {sources.map((s, i) => (
                      <p key={i} className="mt-1 text-xs text-ink-2">
                        from <span className="text-ink">{s.episode.label}</span>
                        {s.session && <> · session <span className="font-mono">{s.session.label}</span></>}
                        {s.agent && <> · learned by <span className="font-medium text-ink">{s.agent.label}</span></>}
                      </p>
                    ))}
                    {replaced.map((r) => <p key={r!.id} className="mt-1 text-xs text-ink-3 line-through">{r!.label}</p>)}
                  </li>
                ))}
              </ol>
            </section>
          )}
          <button className="btn-ghost mt-4 -ml-3" onClick={() => { setRes(undefined); onAnswer(new Set()) }}>Clear highlight</button>
        </div>
      )}
    </div>
  )
}
