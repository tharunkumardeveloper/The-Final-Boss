import { MotionConfig } from 'framer-motion'
import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { WakeGate } from './components/WakeGate'
import './index.css'
import { TenantProvider } from './lib/tenant'
import Portal from './pages/Portal'

// Staff pages (graph canvas, tables) load on demand so the customer portal stays light.
const Console = lazy(() => import('./pages/Console'))
const Benchmark = lazy(() => import('./pages/Benchmark'))
const Usage = lazy(() => import('./pages/Usage'))
const Sharing = lazy(() => import('./pages/Sharing'))
const NetworkPage = lazy(() => import('./pages/Network'))
const RegionsPage = lazy(() => import('./pages/Regions'))
const DatabasePage = lazy(() => import('./pages/Database'))
const LabPage = lazy(() => import('./pages/Lab'))
const GraphPage = lazy(() => import('./pages/Graph'))
const IsolationPage = lazy(() => import('./pages/Isolation'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <TenantProvider>
        <BrowserRouter>
          <WakeGate>
            <ErrorBoundary>
            <Suspense fallback={null}>
              <Routes>
                <Route path="/" element={<Portal />} />
                <Route path="/console" element={<Console />} />
                <Route path="/console/benchmark" element={<Benchmark />} />
                <Route path="/console/usage" element={<Usage />} />
                <Route path="/console/sharing" element={<Sharing />} />
                <Route path="/console/network" element={<NetworkPage />} />
                <Route path="/console/regions" element={<RegionsPage />} />
                <Route path="/console/db" element={<DatabasePage />} />
                <Route path="/console/lab" element={<LabPage />} />
                <Route path="/console/graph" element={<GraphPage />} />
                <Route path="/console/isolation" element={<IsolationPage />} />
                <Route path="*" element={<Portal />} />
              </Routes>
            </Suspense>
            </ErrorBoundary>
          </WakeGate>
        </BrowserRouter>
      </TenantProvider>
    </MotionConfig>
  </StrictMode>,
)
