import { createContext, useContext, useState, type ReactNode } from 'react'

// Portal and console each remember their own tenant, so a customer's region choice never changes what staff see on
// their next reload (found in the browser pass). Within one tab, moving between pages keeps the current one.
export const DEFAULT_TENANT = 'pml'
const key = () => (typeof location !== 'undefined' && location.pathname.startsWith('/console') ? 'pml.tenant.console' : 'pml.tenant.portal')
const read = () => { try { return localStorage.getItem(key()) || DEFAULT_TENANT } catch { return DEFAULT_TENANT } }

const Ctx = createContext<{ tenant: string; setTenant: (t: string) => void }>({ tenant: DEFAULT_TENANT, setTenant: () => {} })

export function TenantProvider({ children }: { children: ReactNode }) {
  const [tenant, set] = useState(read)
  const setTenant = (t: string) => { set(t); try { localStorage.setItem(key(), t) } catch { /* private mode */ } }
  return <Ctx.Provider value={{ tenant, setTenant }}>{children}</Ctx.Provider>
}

export const useTenant = () => useContext(Ctx)
