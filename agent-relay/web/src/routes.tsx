import { lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Portal from './pages/Portal'

// Staff pages (graph canvas, tables) load on demand so the customer portal stays light.
const Console = lazy(() => import('./pages/Console'))
const Benchmark = lazy(() => import('./pages/Benchmark'))
const Usage = lazy(() => import('./pages/Usage'))
const Sharing = lazy(() => import('./pages/Sharing'))
const DatabasePage = lazy(() => import('./pages/Database'))
const LabPage = lazy(() => import('./pages/Lab'))
const TenantsPage = lazy(() => import('./pages/Tenants'))

/** Where an old URL lands: its own query string kept, plus the params that pick the merged view (unless already set). */
export function movedTo(to: string, search: string, add: Record<string, string> = {}) {
  const q = new URLSearchParams(search)
  for (const [k, v] of Object.entries(add)) if (!q.has(k)) q.set(k, v)
  const s = q.toString()
  return s ? `${to}?${s}` : to
}

function Moved({ to, add }: { to: string; add?: Record<string, string> }) {
  return <Navigate replace to={movedTo(to, useLocation().search, add)} />
}

// Old screen -> merged screen. Every one keeps working.
export const MOVED: [string, string, Record<string, string>?][] = [
  ['/console/graph', '/console', { mode: 'replay' }],
  ['/console/network', '/console/lab', { view: 'map' }],
  ['/console/regions', '/console/tenants'],
  ['/console/isolation', '/console/tenants'],
  ['/talk', '/'],
  ['/console/talk', '/'],
]

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Portal />} />
      <Route path="/console" element={<Console />} />
      <Route path="/console/lab" element={<LabPage />} />
      <Route path="/console/sharing" element={<Sharing />} />
      <Route path="/console/tenants" element={<TenantsPage />} />
      <Route path="/console/db" element={<DatabasePage />} />
      <Route path="/console/benchmark" element={<Benchmark />} />
      <Route path="/console/usage" element={<Usage />} />
      {MOVED.map(([from, to, add]) => <Route key={from} path={from} element={<Moved to={to} add={add} />} />)}
      <Route path="*" element={<Portal />} />
    </Routes>
  )
}
