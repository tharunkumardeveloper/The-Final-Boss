import { COMPANY } from '../lib/brand'
/** Brand mark: a signal dot between two returning arcs ("we ping you back"). */
export function LogoMark({ className = 'h-7 w-7' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="rgb(var(--ink))" />
      <circle cx="16" cy="16" r="3" fill="rgb(var(--signal))" />
      <path d="M9.5 16a6.5 6.5 0 0 1 6.5-6.5M22.5 16a6.5 6.5 0 0 1-6.5 6.5" fill="none"
        stroke="rgb(var(--paper))" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function Wordmark({ sub }: { sub?: string }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      <span className="flex flex-col leading-none">
        <span className="font-display text-[17px] font-semibold tracking-[-0.01em] text-ink">{COMPANY}</span>
        {sub && <span className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-3">{sub}</span>}
      </span>
    </span>
  )
}
