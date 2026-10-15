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

/** The key header a request needs, from its path. */
export function keyHeaders(path: string): Record<string, string> {
  const m = path.match(/^\/api\/tenants\/([^/?]+)/)
  if (m) return keyFor(decodeURIComponent(m[1])) ? { 'X-Tenant-Key': keyFor(decodeURIComponent(m[1])) } : {}
  if (path.startsWith('/api/isolation') && operator) return { 'X-Admin-Key': operator }
  return {}
}
