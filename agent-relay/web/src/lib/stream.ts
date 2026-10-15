import { useEffect, useRef, useState } from 'react'
import { keyFor } from './keys'
import { MOCK, WS_URL, loadKeys } from './api'
import { subscribeMock } from './mock'
import type { RelayEvent } from './types'

export type StreamStatus = 'connecting' | 'live' | 'reconnecting'

/** Live events for a tenant. Reconnects with backoff; `onReconnect` lets callers refetch snapshots. */
export function useRelayStream(tenant: string, onEvent: (e: RelayEvent) => void, onReconnect?: () => void) {
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const handler = useRef(onEvent)
  const reconnect = useRef(onReconnect)
  handler.current = onEvent
  reconnect.current = onReconnect

  useEffect(() => {
    if (MOCK) {
      setStatus('live')
      return subscribeMock((e) => handler.current(e))
    }
    let ws: WebSocket | null = null
    let closed = false
    let attempt = 0
    let timer: ReturnType<typeof setTimeout>

    const open = () => {
      ws = new WebSocket(`${WS_URL}/ws/${encodeURIComponent(tenant)}?key=${encodeURIComponent(keyFor(tenant))}`)
      ws.onopen = () => {
        if (attempt > 0) reconnect.current?.()
        attempt = 0
        setStatus('live')
      }
      ws.onmessage = (m) => {
        try { handler.current(JSON.parse(m.data) as RelayEvent) } catch { /* ignore malformed frames */ }
      }
      ws.onclose = (ev) => {
        if (closed) return
        setStatus('reconnecting')
        attempt++
        const again = () => { timer = setTimeout(open, Math.min(10_000, 500 * 2 ** attempt)) }
        if (ev.code === 4403) loadKeys().then(again)  // refused: maybe a tenant created since start; fetch its key
        else again()
      }
    }
    open()
    return () => { closed = true; clearTimeout(timer); ws?.close() }
  }, [tenant])

  return status
}
