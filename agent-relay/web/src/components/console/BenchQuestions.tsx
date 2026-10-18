import { useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { grade } from '../../lib/grade'
import type { Benchmark, BenchQuestion, BenchRow, Compare } from '../../lib/types'

const TYPE_NAMES: Record<string, string> = {
  current: 'Current truth after changes', world_time: 'True on a past date', belief_time: 'On file on a past date',
  completeness: 'Complete lists', disagreement: 'Agent disagreement', handoff: 'Handoff between agents',
  multi_hop: 'Multi-hop', procedural: 'Fix that worked before', unknown: 'Should refuse to answer',
}
type Live = { state: 'running' | 'done' | 'error'; res?: Compare; note?: string }

const Mark = ({ ok }: { ok: boolean }) => (
  <span className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${ok ? 'bg-current-tint text-current' : 'bg-danger-tint text-danger'}`}
    aria-label={ok ? 'correct' : 'wrong'}>{ok ? '✓' : '✗'}</span>
)

function Answer({ who, text, ok, sub }: { who: string; text: string; ok: boolean; sub?: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-paper/70 px-3 py-2">
      <p className="text-[10.5px] uppercase tracking-[0.12em] text-ink-3">{who}</p>
      <p className="mt-0.5 flex items-start gap-2 text-sm"><Mark ok={ok} /><span className="min-w-0 break-words">{text || '—'}</span></p>
      {sub && <p className="mt-0.5 text-[11px] text-ink-3 num">{sub}</p>}
    </div>
  )
}

/** All 160 questions: what was asked, the expected answer, what each memory answered and whether it was right.
 *  Anyone can re-grade the published answers here with the benchmark's own rule, or ask a question again live. */
export function BenchQuestions({ data }: { data: Benchmark }) {
  const qs: BenchQuestion[] = data.questions ?? []
  const by = (sys: string) => new Map((data.results?.systems?.[sys]?.rows ?? []).map((r) => [r.i, r] as [number, BenchRow]))
  const full = useMemo(() => by('FULL'), [data])  // eslint-disable-line react-hooks/exhaustive-deps
  const vec = useMemo(() => by('B1'), [data])  // eslint-disable-line react-hooks/exhaustive-deps
  const [type, setType] = useState('all')
  const [find, setFind] = useState('')
  const [onlyMisses, setOnlyMisses] = useState(false)
  const [shown, setShown] = useState(12)
  const [regraded, setRegraded] = useState<{ full: number; vec: number; agree: number; n: number }>()
  const [live, setLive] = useState<Record<number, Live>>({})
  const bench = data.bench_graph

  const types = useMemo(() => [...new Set(qs.map((q) => q.type))], [qs])
  const list = useMemo(() => qs.filter((q) => (type === 'all' || q.type === type)
    && (!find || q.question.toLowerCase().includes(find.toLowerCase()))
    && (!onlyMisses || !full.get(q.i)?.correct || !vec.get(q.i)?.correct)), [qs, type, find, onlyMisses, full, vec])

  const regrade = () => {  // the published answers, graded again in this browser with the same rule as eval/run_eval.py
    let f = 0, v = 0, agree = 0, n = 0
    for (const q of qs) {
      for (const [rows, add] of [[full, (ok: boolean) => { if (ok) f++ }], [vec, (ok: boolean) => { if (ok) v++ }]] as const) {
        const r = rows.get(q.i)
        if (!r) continue
        const ok = grade(q, r)
        add(ok); n++
        if (ok === r.correct) agree++
      }
    }
    setRegraded({ full: f, vec: v, agree, n })
  }

  const ask = async (q: BenchQuestion) => {  // the same question, now, against the benchmark graph on this server
    if (!bench) return
    setLive((l) => ({ ...l, [q.i]: { state: 'running' } }))
    try {
      const res = await api.compare(bench, q.question)
      setLive((l) => ({ ...l, [q.i]: { state: 'done', res } }))
    } catch (e) {
      setLive((l) => ({ ...l, [q.i]: { state: 'error', note: e instanceof Error ? e.message.slice(0, 140) : 'failed' } }))
    }
  }
  const askSome = async () => {  // five of the questions in view, one after the other (the free model quota is shared)
    const pool = [...list].sort(() => Math.random() - 0.5).slice(0, 5)
    for (const q of pool) await ask(q)
  }

  return (
    <section className="panel mt-4 p-5 sm:p-6" aria-label="The benchmark questions">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 className="eyebrow">The {qs.length} questions</h2>
          <p className="mt-1 text-sm text-ink-3">
            Every question both memories were asked, the expected answer, and what each one said. Re-grade the published
            answers with the benchmark's own rule, or ask a question again, live, against the benchmark graph.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary !py-1.5 text-xs" onClick={regrade}>Re-grade all {qs.length} in your browser</button>
          <button className="btn-ghost !py-1.5 text-xs hairline" onClick={askSome} disabled={!bench}
            title={bench ? 'Asks five of the questions in view again, live' : 'The benchmark graph is not loaded on this server'}>
            Re-run 5 live
          </button>
        </div>
      </div>

      {regraded && (
        <p className="mt-3 rounded-xl bg-current-tint/60 px-3 py-2 text-sm text-ink" role="status">
          Re-graded here: <strong>Relay {regraded.full}/{qs.length}</strong>, <strong>vector store {regraded.vec}/{qs.length}</strong>.{' '}
          {regraded.agree === regraded.n ? `All ${regraded.n} verdicts match the published run.` : `${regraded.n - regraded.agree} of ${regraded.n} verdicts differ from the published run.`}
        </p>
      )}
      {!bench && (
        <p className="mt-3 text-xs text-ink-3">
          Live re-runs need the benchmark graph (<code className="font-mono">pml-bench</code>) on this server. To rebuild it and re-run everything
          yourself: <code className="font-mono">python -m data.load --tenant pml-bench && python -m eval.run_eval --tenant pml-bench --phases main</code>.
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Question type">
        {['all', ...types].map((t) => (
          <button key={t} role="tab" aria-selected={type === t} onClick={() => { setType(t); setShown(12) }}
            className={`rounded-full px-3 py-1 text-xs transition-colors duration-200 ${type === t ? 'bg-ink text-paper' : 'bg-sunk text-ink-2 hover:text-ink'}`}>
            {t === 'all' ? `All ${qs.length}` : `${TYPE_NAMES[t] ?? t} · ${qs.filter((q) => q.type === t).length}`}
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label htmlFor="bq-find" className="sr-only">Search questions</label>
        <input id="bq-find" className="field !w-auto min-w-0 flex-1 !py-1.5 text-sm sm:max-w-xs" placeholder="Search questions" value={find}
          onChange={(e) => { setFind(e.target.value); setShown(12) }} />
        <label className="flex items-center gap-2 text-xs text-ink-2">
          <input type="checkbox" checked={onlyMisses} onChange={(e) => { setOnlyMisses(e.target.checked); setShown(12) }} />
          Only where a memory got it wrong
        </label>
        <span className="text-xs text-ink-3 num">{list.length} shown</span>
      </div>

      <ol className="mt-4 space-y-3">
        {list.slice(0, shown).map((q) => {
          const f = full.get(q.i), v = vec.get(q.i), l = live[q.i]
          const expected = q.expect_unknown ? 'Nothing on file: it should say it doesn\'t know' : q.gold.join(' · ')
          return (
            <li key={q.i} className="rounded-2xl bg-surface p-3 hairline sm:p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium text-ink"><span className="mr-2 font-mono text-[11px] text-ink-3">q{String(q.i).padStart(3, '0')}</span>{q.question}</p>
                <span className="chip bg-sunk text-ink-2">{TYPE_NAMES[q.type] ?? q.type}</span>
              </div>
              <p className="mt-1 text-xs text-ink-3">Expected: <span className="text-ink-2">{expected}</span>
                {q.expect_conflict && ' (and say the agents disagree)'}{q.asked_by ? ` · asked as ${q.asked_by}` : ''}</p>
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {f && <Answer who="Relay · published" text={f.answer ?? f.values.join(', ')} ok={f.correct} />}
                {v && <Answer who="Vector store · published" text={v.answer ?? v.values.join(', ')} ok={v.correct} />}
              </div>
              {l?.state === 'done' && l.res && (
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2" role="status">
                  <Answer who="Relay · live now" text={l.res.graph.answer ?? ''} ok={grade(q, { values: l.res.graph.values ?? [], unknown: l.res.graph.unknown, conflict: l.res.graph.conflict })} sub={`${l.res.graph.ms} ms`} />
                  <Answer who="Vector store · live now" text={l.res.vector.answer ?? ''} ok={grade(q, { values: l.res.vector.values ?? [], unknown: l.res.vector.unknown, conflict: l.res.vector.conflict })} sub={`${l.res.vector.ms} ms`} />
                </div>
              )}
              {l?.state === 'error' && <p className="mt-2 text-xs text-danger" role="alert">Couldn't run it live: {l.note}</p>}
              <div className="mt-2 flex justify-end">
                <button className="btn-ghost !py-1 text-xs" onClick={() => ask(q)} disabled={!bench || l?.state === 'running'}
                  title={bench ? 'Ask both memories this question again, now' : 'The benchmark graph is not loaded on this server'}>
                  {l?.state === 'running' ? 'Asking both memories…' : l?.state === 'done' ? 'Ask again' : 'Ask both again, live'}
                </button>
              </div>
            </li>
          )
        })}
      </ol>
      {list.length > shown && (
        <button className="btn-ghost mt-3 w-full justify-center hairline" onClick={() => setShown((n) => n + 24)}>
          Show more ({list.length - shown} left)
        </button>
      )}
    </section>
  )
}
