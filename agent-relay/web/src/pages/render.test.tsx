import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TenantProvider } from '../lib/tenant'
import { AppRoutes, MOVED, movedTo } from '../routes'
import Benchmark from './Benchmark'
import Console from './Console'
import Database from './Database'
import Lab, { ProcedureCard } from './Lab'
import Portal from './Portal'
import Sharing from './Sharing'
import Tenants from './Tenants'
import Usage from './Usage'

// the graph canvas needs a browser
vi.mock('react-force-graph-2d', () => ({ default: () => null }))
vi.mock('../components/console/MemoryGraph', async (real) => ({ ...(await real<object>()), MemoryGraph: () => null }))

// Smoke test: the first render of every screen must not throw, and every old URL must land on its merged screen.
describe('pages render', () => {
  const wrap = (el: JSX.Element, url = '/') => renderToString(<TenantProvider><MemoryRouter initialEntries={[url]}>{el}</MemoryRouter></TenantProvider>)
  it('portal', () => {
    const html = wrap(<Portal />)
    expect(html).toContain('Binge harder')
    expect(html).toContain('Fiber 300')
    expect(html).toContain('fictional company')
  })
  it('memory, live and replay', () => {
    expect(wrap(<Console />, '/console')).toContain('Replay how it was built')
    expect(wrap(<Console />, '/console?mode=replay')).toContain('Known at this moment')
  })
  it('network: lab, map and talk mode', () => {
    expect(wrap(<Lab />, '/console/lab')).toContain('Break the network')
    expect(wrap(<Lab />, '/console/lab?view=map')).toContain('Whole region')
    expect(wrap(<Lab />, '/console/lab?talk=1')).not.toContain('Close chat')  // talking as a customer is on the home page now
  })
  it('agent team, tenants, database', () => {
    wrap(<Sharing />)
    const t = wrap(<Tenants />)
    expect(t).toContain('Plant a secret in one region')
    expect(t).toContain('Run the canary test')
    wrap(<Database />)
  })
  it('benchmark', () => {
    expect(wrap(<Benchmark />)).toContain('Does the graph earn its place?')
  })
  it('usage', () => {
    expect(wrap(<Usage />)).toContain('Model quota today')
  })
  it('old URLs redirect, keeping the query string', () => {
    expect(movedTo('/console', '', { mode: 'replay' })).toBe('/console?mode=replay')
    expect(movedTo('/console/lab', '?tenant=pml', { view: 'map' })).toBe('/console/lab?tenant=pml&view=map')
    expect(movedTo('/console/tenants', '?x=1')).toBe('/console/tenants?x=1')
    expect(movedTo('/console', '?mode=live', { mode: 'replay' })).toBe('/console?mode=live')
    for (const [from] of MOVED) wrap(<AppRoutes />, from)  // the redirect element itself renders
  })
  it('procedure card', () => {
    const html = renderToString(<ProcedureCard p={{ id: 'p1', successes: 3, failures: 1, rate: 0.75, steps: ['remote_reboot', 'dispatch_technician_home'], nearest_hops: 2, places: [{ at: 'e:spl-1', hops: 2, times: 2 }] }} />)
    expect(html).toContain('Restart the box remotely')
    expect(html).toContain('75%')
    expect(html).toContain('same exchange')
    expect(html).toContain('spl-1 ×2')
  })
})

describe('answer contract and tools', async () => {
  const { Hops, OutcomeChip, OUTCOME } = await import('../components/Hops')
  const { ToolCalls } = await import('../components/console/CypherDrawer')
  const { HowIKnow } = await import('../components/portal/SupportChat')
  const { ShowMe } = await import('../components/console/ShowMe')
  const text = (el: JSX.Element) => renderToString(el).replace(/<!-- -->/g, '')
  it('every outcome has a chip', () => {
    for (const o of ['path', 'memory', 'not_in_graph', 'unknown_entity'] as const) {
      expect(renderToString(<OutcomeChip outcome={o} />)).toContain(OUTCOME[o].label)
    }
    expect(OUTCOME.unknown_entity.label).toContain('no query ran')
  })
  it('hops show the path with dates and writers', () => {
    const html = text(<Hops hops={[{ from: 'alice rao', rel: 'LIVES_IN', to: 'mumbai', since: '2026-09-03', by: ['intake'] },
      { from: 'fibre cut', rel: 'AFFECTS', to: 'mumbai' }]} />)
    expect(html).toContain('Alice Rao')
    expect(html).toContain('LIVES_IN')
    expect(html).toContain('since 3 Sept')
    expect(html).toContain('by intake')
    expect(html).toContain('AFFECTS')
  })
  it('tool calls table and the customer how-I-know line', () => {
    const t = text(<ToolCalls calls={[{ tool: 'affected_by', args: { node: 'pop-mumbai', depth: 3 }, ms: 12.5, rows: 33, outcome: 'path', queries: [], at: 0 }]} />)
    expect(t).toContain('affected_by')
    expect(t).toContain('depth=3')
    expect(t).toContain('Answered with a path')
    const h = text(<HowIKnow hops={[{ from: 'alice rao', rel: 'LIVES_IN', to: 'mumbai', learned: '2026-09-01', by: ['intake'] }]} />)
    expect(h).toContain('you live in')
    expect(h).not.toContain('LIVES_IN')
    expect(h).not.toContain('MATCH')
  })
  it('show me card renders before picks load', () => {
    const wrap = (el: JSX.Element) => renderToString(<TenantProvider><MemoryRouter>{el}</MemoryRouter></TenantProvider>)
    expect(wrap(<ShowMe tenant="pml" />)).toContain('Show me')
    expect(wrap(<ShowMe tenant="pml" kind="network" />)).toContain('Looking for real examples')
  })
})

describe('field dispatch', async () => {
  const { FieldDispatch, Canvas } = await import('./Lab')
  const net = {
    pop: { id: 'pop-1', label: 'Mumbai POP', city: 'mumbai' },
    links: [{ id: 'core-a', label: 'Core West', status: 'up', role: 'primary' as const, active: true, link: 'up' as const, gbps: 10, flow: 4 }],
    olts: [{ id: 'olt-1', label: 'Andheri OLT', status: 'up', peak_gbps: 6, uplink_gbps: 10, flow_gbps: 4, free_peak_mbps: 900, curve: [1, 2] }],
    splitters: [{ id: 'spl-1', label: 'Cabinet 4', feeder: 'cut' as const, olt: 'olt-1' }],
    homes: [{ id: 'ont-1', splitter: 'spl-1', port: 3, customer: 'kevin', name: 'Kevin', rx: -30, box: 'b', account: 'active', wifi: 1, state: 'dark' as const }],
  }
  const d = { action: 'dispatch_cable_crew', customer: 'kevin', name: 'Kevin', tech: 'ravi kumar', at: 0, ms: 8000, arrive: 3600, stage: 'onsite' as const }
  const text = (el: JSX.Element) => renderToString(el).replace(/<!-- -->/g, '')
  it('says who went where and how far along the job is', () => {
    const t = text(<FieldDispatch d={d} view={net} />)
    expect(t).toContain('Cable crew · Ravi Kumar sent to the feeder cable of Cabinet 4')
    expect(t).toContain('On site · repairing')
    expect(t).toContain('fast-forwarded to 8 s')
  })
  it("a customer's own screen never shows a neighbour's name", () => {
    const two = { ...net, homes: [...net.homes, { ...net.homes[0], id: 'ont-2', port: 4, customer: 'priya', name: 'Priya Naik' }] }
    expect(renderToString(<Canvas view={two} focus="kevin" />)).toContain('Priya')
    const mine = renderToString(<Canvas view={two} focus="kevin" privateTo="kevin" />)
    expect(mine).not.toContain('Priya')
    expect(mine).toContain('Kevin')
  })
  it('draws the van on the diagram only while a crew is out', () => {
    expect(renderToString(<Canvas view={net} focus="kevin" dispatch={d} />)).toContain('stroke-dasharray="3 5"')
    expect(renderToString(<Canvas view={net} focus="kevin" />)).not.toContain('stroke-dasharray="3 5"')
  })
})

describe('query glow layer', async () => {
  const { TouchLayer } = await import('../components/console/TouchLayer')
  const { recordTouch } = await import('../lib/touch')
  const marks = [{ id: 'olt-1', keys: ['olt-1'], x: 10, y: 10, r: 14 }]
  it('rings only what a query just touched', () => {
    expect(renderToString(<svg><TouchLayer marks={marks} /></svg>)).not.toContain('<circle')
    recordTouch({ id: 'x', type: 'cypher', sim_time: null, wall: 0, data: { name: 'lab: line test', ms: 3, rows: 1, seek: ['olt-1'], found: [] } } as never)
    expect(renderToString(<svg><TouchLayer marks={marks} /></svg>)).toContain('<circle')
  })
})

describe('agent team visuals', async () => {
  const { Constellation, CrossingCard } = await import('./Sharing')
  const data = {  // the shape /sharing returns for mem:pml
    agents: [
      { agent: 'intake', role: 'r', trust: 0.9, wrote: 114, consulted: 118, consulted_from_others: 9, uses: 120, reuse_pct: 8 },
      { agent: 'resolver', role: 'r', trust: 0.6, wrote: 33, consulted: 39, consulted_from_others: 37, uses: 40, reuse_pct: 95 },
      { agent: 'noc', role: 'r', trust: 0.8, wrote: 3, consulted: 1, consulted_from_others: 1, uses: 1, reuse_pct: 100 }],
    flows: [{ from: 'intake', to: 'resolver', facts: 37 }, { from: 'resolver', to: 'intake', facts: 8 }],
    top_shared: [{ fact_id: 'f1', sentence: 'Alice lives in Mumbai', writer: 'intake', readers: ['resolver'], uses: 4 }],
  }
  const text = (el: JSX.Element) => renderToString(el).replace(/<!-- -->/g, '')
  it('draws the team around shared memory, with a live dot', () => {
    const t = text(<Constellation data={data} pulse={{ from: 'intake', to: 'resolver', at: 1 }} pick={() => {}} />)
    expect(t).toContain('Shared memory')
    expect(t).toContain('95% from others')
    expect(t).toContain('animateMotion')
  })
  it('crossings are drawn, not tabled', () => {
    expect(text(<ul><CrossingCard r={{ reader: 'resolver', writer: 'intake', fact_id: 'f1', subject: 'alice rao', sentence: 'Alice lives in Mumbai', uses: 2, last: null }} fresh /></ul>))
      .toContain('<animate')
  })
})

describe('handoff replay', async () => {
  const { HandoffReplay } = await import('../components/console/HandoffReplay')
  it('renders with no case yet', () => {
    const html = renderToString(<HandoffReplay tenant="pml" subscribe={() => () => {}} />)
    expect(html).toContain('Watch a handoff')
    expect(html).toContain('No case yet')
  })
})
