import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { Close, Database } from '../Icons'
import type { LoggedCypher } from './useConsole'

const WRITES = /\b(CREATE|MERGE|SET|DELETE|REMOVE|DETACH|DROP)\b/i

/** FalkorDB's own view of a query: GRAPH.EXPLAIN (plan only) or GRAPH.PROFILE (runs it; read-only queries only). */
function Plan({ tenant, e }: { tenant: string; e: LoggedCypher }) {
  const [out, setOut] = useState<{ kind: string; lines: string[] } | { kind: 'error'; text: string }>()
  const [busy, setBusy] = useState(false)
  const run = (profile: boolean) => {
    setBusy(true)
    api.plan(tenant, e.query, e.params, profile)
      .then((r) => setOut({ kind: profile ? 'Profile' : 'Explain', lines: r.plan }))
      .catch((err) => setOut({ kind: 'error', text: String(err?.message ?? err) }))
      .finally(() => setBusy(false))
  }
  const writes = WRITES.test(e.query)
  return (
    <div className="mt-2">
      <div className="flex gap-2">
        <button className="btn-ghost !py-1 text-[11px]" disabled={busy} onClick={() => run(false)}>Explain</button>
        <button className="btn-ghost !py-1 text-[11px]" disabled={busy || writes} onClick={() => run(true)}
          title={writes ? 'Profile runs the query: only for read-only queries' : 'Run it and show rows and time per operation'}>Profile</button>
      </div>
      {out && 'lines' in out && (
        <pre className="scroll-thin mt-2 overflow-x-auto whitespace-pre rounded-lg bg-surface p-2.5 font-mono text-[11px] leading-relaxed text-ink hairline"
          aria-label={`${out.kind} plan`}>{`GRAPH.${out.kind.toUpperCase()}\n` + out.lines.join('\n')}</pre>
      )}
      {out && 'text' in out && <p className="mt-2 text-[11px] text-danger" role="alert">{out.text}</p>}
    </div>
  )
}

export function CypherDrawer({ open, onClose, entries, tenant }: { open: boolean; onClose: () => void; entries: LoggedCypher[]; tenant: string }) {
  const close = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    if (!open) return
    close.current?.focus()
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onCloseRef.current()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open])

  return (
    <div className={`fixed inset-0 z-30 transition duration-500 ease-spring ${open ? '' : 'pointer-events-none'}`} aria-hidden={!open}
      {...({ inert: open ? undefined : '' } as Record<string, string | undefined>)}>
      <div className={`absolute inset-0 bg-ink/10 transition-opacity duration-500 ease-spring ${open ? 'opacity-100' : 'opacity-0'}`} onClick={onClose} />
      <aside role="dialog" aria-label="Cypher used" aria-modal="true"
        className={`absolute inset-y-0 right-0 flex w-full max-w-xl flex-col bg-surface shadow-lift transition-transform duration-500 ease-spring ${open ? 'translate-x-0' : 'translate-x-full'}`}>
        <header className="flex items-center gap-3 px-5 py-4 shadow-[0_1px_0_rgb(var(--line)/0.07)]">
          <Database className="text-signal-deep" />
          <div className="flex-1">
            <h2 className="font-display text-lg font-semibold">Cypher used</h2>
            <p className="text-xs text-ink-3">Every query behind every action. Paste any of them into FalkorDB Browser to check.</p>
          </div>
          <button ref={close} className="btn-ghost h-9 w-9 !p-0" onClick={onClose} aria-label="Close"><Close /></button>
        </header>
        <div className="scroll-thin flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {entries.length === 0 && <p className="text-sm text-ink-3">Run an action (ask, chat, pick up a ticket) and its queries appear here.</p>}
          {entries.map((e, i) => (
            <article key={i} className="rounded-xl bg-sunk/50 p-3">
              <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
                <span className="font-semibold text-ink">{e.name}</span>
                <span className="num text-ink-3">{e.rows} rows · {e.ms} ms</span>
                <span className="ml-auto truncate text-ink-3">{e.action}</span>
              </p>
              {e.query && <pre className="scroll-thin mt-2 overflow-x-auto whitespace-pre rounded-lg bg-surface p-2.5 font-mono text-[11px] leading-relaxed text-ink hairline">{e.query}</pre>}
              {Object.keys(e.params).length > 0 && <p className="mt-1.5 break-all font-mono text-[10.5px] text-ink-3">{JSON.stringify(e.params).slice(0, 400)}</p>}
              {e.query && <Plan tenant={tenant} e={e} />}
            </article>
          ))}
        </div>
      </aside>
    </div>
  )
}
