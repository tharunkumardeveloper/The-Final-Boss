import { NavLink } from 'react-router-dom'

// The operator console's screens. Usage stays reachable at /console/usage (quota chip in the top bar) but out of the nav.
const SCREENS: [string, string][] = [
  ['/', 'Customer'], ['/console', 'Memory'], ['/console/lab', 'Network'], ['/console/sharing', 'Agent team'],
  ['/console/tenants', 'Tenants'], ['/console/db', 'Database'], ['/console/benchmark', 'Benchmark'],
]

/** One nav for every console screen. Scrolls sideways on a phone rather than wrapping into a wall of buttons. */
export function ConsoleNav({ className = '' }: { className?: string }) {
  return (
    <nav aria-label="Console" className={`scroll-thin -mx-1 max-w-full overflow-x-auto ${className}`}>
      <ul className="flex w-max items-center gap-0.5 rounded-full bg-surface p-1 hairline">
        {SCREENS.map(([to, label], i) => (
          <li key={to} className="flex items-center">
            {i === 5 && <i aria-hidden className="mx-1 h-4 w-px bg-line/15" />}
            <NavLink to={to} end
              className={({ isActive }) => `block whitespace-nowrap rounded-full px-3 py-1 text-xs transition duration-300 ease-spring ${isActive ? 'bg-ink font-medium text-paper' : 'text-ink-2 hover:bg-sunk hover:text-ink'}`}>
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
