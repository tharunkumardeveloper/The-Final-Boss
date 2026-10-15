import { MotionConfig } from 'framer-motion'
import { StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { WakeGate } from './components/WakeGate'
import './index.css'
import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { TenantProvider } from './lib/tenant'
import { AppRoutes } from './routes'

polyfillCountryFlagEmojis()  // Windows has no flag emoji; this adds a flag-only font there

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <TenantProvider>
        <BrowserRouter>
          <WakeGate>
            <ErrorBoundary>
            <Suspense fallback={null}>
              <AppRoutes />
            </Suspense>
            </ErrorBoundary>
          </WakeGate>
        </BrowserRouter>
      </TenantProvider>
    </MotionConfig>
  </StrictMode>,
)
