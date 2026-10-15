import { useEffect, useState, type ReactNode } from 'react'
import { api, loadKeys, MOCK } from '../lib/api'
import { LogoMark } from './Brand'

/** Render's free plan sleeps when idle; the first request can take ~30-60s. Say so instead of looking broken. */
export function WakeGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'waking' | 'ready' | 'down'>(MOCK ? 'ready' : 'checking')
  const [tries, setTries] = useState(0)

  useEffect(() => {
    if (MOCK) return
    let done = false
    const slow = setTimeout(() => !done && setState('waking'), 2000)
    api.health()
      .then(() => loadKeys())
      .then(() => { done = true; setState('ready') })
      .catch(() => { done = true; setState('down') })
    return () => { done = true; clearTimeout(slow) }
  }, [tries])

  if (state === 'ready') return <>{children}</>
  if (state === 'checking') return null
  return (
    <div className="flex min-h-[100dvh] items-center justify-center px-4">
      <div className="panel w-full max-w-md p-8 text-center animate-rise" role="status" aria-live="polite">
        <LogoMark className="mx-auto h-10 w-10" />
        {state === 'waking' ? (
          <>
            <h1 className="mt-5 font-display text-xl font-semibold">Waking up the support desk</h1>
            <p className="mt-2 text-sm text-ink-2">Our demo server sleeps when nobody is around. It usually takes under a minute to start.</p>
            <div className="mx-auto mt-6 h-1 w-40 overflow-hidden rounded-full bg-sunk">
              <div className="h-full w-1/3 animate-slide rounded-full bg-signal" />
            </div>
          </>
        ) : (
          <>
            <h1 className="mt-5 font-display text-xl font-semibold">Can't reach the server</h1>
            <p className="mt-2 text-sm text-ink-2">The API didn't answer. Check that it's deployed and that VITE_API_URL points at it.</p>
            <button className="btn-primary mt-6" onClick={() => { setState('waking'); setTries((n) => n + 1) }}>Try again</button>
          </>
        )}
      </div>
    </div>
  )
}
