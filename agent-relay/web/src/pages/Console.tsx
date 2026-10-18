import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { KnownList, TimeBar, useReplay } from './Graph'
import { AskPanel } from '../components/console/AskPanel'
import { ClockPanel } from '../components/console/ClockPanel'
import { CypherDrawer } from '../components/console/CypherDrawer'
import { Feed } from '../components/console/Feed'
import { GraphControls } from '../components/console/GraphControls'
import { entityId } from '../lib/graph'
import { Inspector } from '../components/console/Inspector'
import { KIND_COLOR, MemoryGraph } from '../components/console/MemoryGraph'
import { Tickets } from '../components/console/Tickets'
import { TopBar } from '../components/console/TopBar'
import { useConsole } from '../components/console/useConsole'
import { api } from '../lib/api'
import { titleCase } from '../lib/format'
import { useTenant } from '../lib/tenant'
import type { Community } from '../lib/types'

type Tab = 'inspect' | 'ask' | 'tickets' | 'clocks'
const LEGEND_KINDS = ['customer', 'city', 'plan', 'device', 'issue', 'fix', 'outage', 'ticket']

export default function Console() {
  const { tenant, setTenant } = useTenant()
  const c = useConsole(tenant)
  const [tab, setTab] = useState<Tab>('ask')
  const [selected, setSelected] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<Set<string>>(new Set())
  const [clockWho, setClockWho] = useState<string | null>(null)
  const [cypherOpen, setCypherOpen] = useState(false)
  const [communities, setCommunities] = useState<Community[]>()
  const [consolidating, setConsolidating] = useState(false)
  // Live or Replay, in the URL so /console?mode=replay (and the old /console/graph) opens straight into the replay
  const [params, setParams] = useSearchParams()
  const replaying = params.get('mode') === 'replay'
  const setReplaying = (on: boolean) => setParams((p) => { const n = new URLSearchParams(p); if (on) n.set('mode', 'replay'); else n.delete('mode'); return n })
  const r = useReplay(c.store, c.version, replaying, () => setReplaying(true))
  const graph = replaying ? r.graph : c.store

  const select = (id: string | null) => {
    setSelected(id)
    if (id) setTab('inspect')
    const node = id ? c.store.nodes.get(id) : undefined
    if (node?.kind === 'customer') setClockWho(node.label)
  }
  const GRAPH_H = 'h-[min(78vh,860px)] min-h-[520px]'  // the graph is the screen: tall, and the side panels match it

  const consolidate = async () => {
    setConsolidating(true)
    try { const r = await api.consolidate(tenant); setCommunities(r.communities); c.refreshAll() } finally { setConsolidating(false) }
  }

  const tabs: [Tab, string][] = [['ask', 'Ask'], ['inspect', 'Inspect'], ['tickets', `Tickets${c.tickets.length ? ` · ${c.tickets.filter((t) => t.status !== 'resolved').length} open` : ''}`], ['clocks', 'Two clocks']]

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <TopBar tenant={tenant} setTenant={setTenant} stats={c.stats} sim={c.sim} setSim={c.setSim} simTime={c.simTime} status={c.status}
        cypherCount={c.cypher.length} openCypher={() => setCypherOpen(true)} usage={c.usage}
        onReset={() => { setSelected(null); setHighlight(new Set()); setCommunities(undefined); c.clearFeed(); c.refreshAll(true) }} />

      <div className="grid grid-cols-1 items-start gap-3 px-3 pb-3 lg:grid-cols-[280px_minmax(0,1fr)_380px] xl:grid-cols-[320px_minmax(0,1fr)_420px]">
        <aside className={`panel order-3 flex h-[340px] flex-col overflow-hidden sm:h-[420px] lg:order-none lg:h-[min(78vh,860px)] lg:min-h-[520px]`}>
          {replaying
            ? <KnownList r={r} label={(id) => r.graph.nodes.get(id)?.label ?? c.store.nodes.get(id)?.label ?? id.replace(/^e:/, '')} onSelect={select} />
            : <Feed feed={c.feed} customers={c.customers} />}
        </aside>

        <main className="order-1 flex min-w-0 flex-col gap-3 lg:order-none">
          <section className={`panel relative overflow-hidden ${GRAPH_H}`} aria-label={replaying ? 'Memory graph, replay' : 'Memory graph'}>
            <MemoryGraph store={graph} version={replaying ? r.rv : c.version} highlight={replaying ? undefined : highlight} selected={selected} onSelect={select}
              focusId={!replaying && c.view.focus ? entityId(c.view.focus) : null} />
            <div className="absolute left-4 right-28 top-3">
              <GraphControls customers={c.customers} view={c.view} setView={c.setView} following={c.following} />
              <p className="pointer-events-none mt-1.5 text-xs text-ink-3 num">
                <span className="eyebrow mr-1.5">mem:{tenant}</span>
                {c.view.focus ? `${c.view.depth}-hop neighbourhood · ` : ''}{c.store.nodes.size} entities · {c.store.edges.size} facts
              </p>
            </div>
            <button className="btn-ghost absolute right-3 top-2 !py-1.5 text-xs" onClick={consolidate} disabled={consolidating}>
              {consolidating ? 'Clustering…' : 'Consolidate'}
            </button>
            {communities && (
              <div className="absolute right-3 top-12 w-72 rounded-2xl bg-surface/95 p-3 shadow-lift hairline animate-rise">
                <div className="flex items-center justify-between"><p className="eyebrow">Communities · label propagation</p>
                  <button className="text-xs text-ink-3 hover:text-ink" onClick={() => setCommunities(undefined)}>Hide</button></div>
                <ul className="mt-2 space-y-2">
                  {communities.slice(0, 5).map((m) => (
                    <li key={m.id} className="text-xs">
                      <p className="font-medium text-ink">{m.top.map((t) => titleCase(t)).join(' · ')} <span className="num font-normal text-ink-3">({m.size})</span></p>
                      {m.summary && <p className="mt-0.5 text-ink-2">{m.summary}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {c.store.nodes.size === 0 && (
              <div className="absolute inset-0 flex items-center justify-center p-6 text-center">
                <div><p className="font-display text-lg font-semibold">Memory is empty</p>
                  <p className="mt-1 text-sm text-ink-3">{c.error ? `Couldn't load the graph: ${c.error}` : 'Press play to start the simulated customers, or chat from the portal.'}</p></div>
              </div>
            )}
            <div className="pointer-events-none absolute bottom-3 left-4 right-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3">
              {LEGEND_KINDS.map((k) => <span key={k} className="flex items-center gap-1"><i className="h-2 w-2 rounded-full" style={{ background: KIND_COLOR[k] }} />{k}</span>)}
              <span className="flex items-center gap-1"><i className="h-px w-4 bg-ink-3" />current</span>
              <span className="flex items-center gap-1"><i className="w-4 border-t border-dashed border-old" />superseded</span>
              <span className="flex items-center gap-1"><i className="h-0.5 w-4 bg-conflict" />conflict</span>
              <span className="flex items-center gap-1"><i className="h-0.5 w-4 bg-signal" />answer path</span>
            </div>
          </section>
          <section className="panel shrink-0" aria-label="Time">
            <TimeBar r={r} on={replaying} setOn={setReplaying} />
          </section>
        </main>

        <aside className={`panel order-2 flex h-[640px] flex-col overflow-hidden lg:order-none lg:h-[min(78vh,860px)] lg:min-h-[520px]`}>
          <div role="tablist" aria-label="Inspector" className="flex gap-1 p-2 shadow-[0_1px_0_rgb(var(--line)/0.07)]">
            {tabs.map(([id, name]) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                className={`btn !px-3 !py-1.5 text-xs ${tab === id ? 'bg-ink text-paper' : 'text-ink-2 hover:bg-sunk'}`}>{name}</button>
            ))}
          </div>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto" role="tabpanel">
            <div hidden={tab !== 'ask'}><AskPanel tenant={tenant} onAnswer={setHighlight} logCypher={c.logCypher} /></div>
            {tab === 'inspect' && <Inspector tenant={tenant} id={selected} version={c.version} />}
            {tab === 'tickets' && <Tickets tenant={tenant} tickets={c.tickets} logCypher={c.logCypher} refresh={c.refreshLists} />}
            {tab === 'clocks' && <ClockPanel tenant={tenant} customers={c.customers} subject={clockWho} onSubject={setClockWho} version={c.version} simTime={c.simTime} />}
          </div>
        </aside>
      </div>

      <CypherDrawer open={cypherOpen} onClose={() => setCypherOpen(false)} entries={c.cypher} tenant={tenant} calls={c.calls} />
    </div>
  )
}
