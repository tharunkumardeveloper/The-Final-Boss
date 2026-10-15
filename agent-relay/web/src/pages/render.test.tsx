import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { TenantProvider } from '../lib/tenant'
import Benchmark from './Benchmark'
import Portal from './Portal'
import Usage from './Usage'

// Smoke test: first render of the pages must not throw (the console needs a canvas, so it's covered by the build).
describe('pages render', () => {
  const wrap = (el: JSX.Element) => renderToString(<TenantProvider><MemoryRouter>{el}</MemoryRouter></TenantProvider>)
  it('portal', () => {
    const html = wrap(<Portal />)
    expect(html).toContain('Binge harder')
    expect(html).toContain('Fiber 300')
    expect(html).toContain('fictional company')
  })
  it('benchmark', () => {
    expect(wrap(<Benchmark />)).toContain('Does the graph earn its place?')
  })
  it('usage', () => {
    expect(wrap(<Usage />)).toContain('Model quota today')
  })
})
