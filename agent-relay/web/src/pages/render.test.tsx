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
    expect(wrap(<Lab />, '/console/lab?talk=1')).toContain('Close chat')
  })
  it('agent team, tenants, database', () => {
    wrap(<Sharing />)
    const t = wrap(<Tenants />)
    expect(t).toContain('One graph per region')
    expect(t).toContain('Try to break into another tenant')
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
