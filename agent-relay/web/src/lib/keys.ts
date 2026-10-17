/** Tenant keys. The demo server hands its own web app every tenant's key at start (GET /api/demo/keys); a real
 *  deployment turns that off and gives each tenant only its own key. The API refuses a tenant's data without it. */
let tenants: Record<string, string> = {}
let operator = ''

export function setKeys(k: { tenants: Record<string, string>; operator: string }) {
  tenants = k.tenants
  operator = k.operator
}

export const keyFor = (tenant: string) => tenants[tenant] ?? ''
export const operatorKey = () => operator
export const knownTenants = () => Object.keys(tenants)

// On the public demo, resets need a reset key (RELAY_RESET_KEY). Asked for once, kept for this browser tab only.
const RESET = 'relay.resetKey'
const resetKey = () => { try { return sessionStorage.getItem(RESET) ?? '' } catch { return '' } }
export const setResetKey = (k: string) => { try { sessionStorage.setItem(RESET, k) } catch { /* private mode */ } }

/** The key headers a request needs, from its path. */
export function keyHeaders(path: string): Record<string, string> {
  const out: Record<string, string> = resetKey() ? { 'X-Reset-Key': resetKey() } : {}
  const m = path.match(/^\/api\/tenants\/([^/?]+)/)
  if (m && keyFor(decodeURIComponent(m[1]))) out['X-Tenant-Key'] = keyFor(decodeURIComponent(m[1]))
  if (!m && path.startsWith('/api/isolation') && operator) out['X-Admin-Key'] = operator
  return out
}
