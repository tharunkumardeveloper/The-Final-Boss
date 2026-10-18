import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

// Portal and console each remember their own tenant, so a customer's region choice never changes what staff see on
// their next reload (found in the browser pass). Within one tab, moving between pages keeps the current one.
export const DEFAULT_TENANT = 'pml'
const key = () => (typeof location !== 'undefined' && location.pathname.startsWith('/console') ? 'pml.tenant.console' : 'pml.tenant.portal')
const read = () => { try { return localStorage.getItem(key()) || DEFAULT_TENANT } catch { return DEFAULT_TENANT } }

const Ctx = createContext<{ tenant: string; setTenant: (t: string) => void }>({ tenant: DEFAULT_TENANT, setTenant: () => {} })

export function TenantProvider({ children }: { children: ReactNode }) {
  const [tenant, set] = useState(read)
  const setTenant = (t: string) => { set(t); try { localStorage.setItem(key(), t) } catch { /* private mode */ } }
  // First visit, whichever page it starts on: the desk for where the visitor is (browser timezone, then language; no
  // IP lookup), unless this page already remembers a choice. Addresses given in the chat move it from there on.
  useEffect(() => {
    try { if (localStorage.getItem(key())) return } catch { return }
    api.locate(Intl.DateTimeFormat().resolvedOptions().timeZone, navigator.language)
      .then((r) => { if (r.tenant) setTenant(r.tenant) }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return <Ctx.Provider value={{ tenant, setTenant }}>{children}</Ctx.Provider>
}

export const useTenant = () => useContext(Ctx)
