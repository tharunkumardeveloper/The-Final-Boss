import { COMPANY } from '../lib/brand'

/** The brand mark (the W with Wi-Fi waves), from public/brand/. */
export function LogoMark({ className = 'h-7 w-7' }: { className?: string }) {
  return <img src="/brand/mark.png" alt="" aria-hidden="true" className={`${className} object-contain`} />
}

export function Wordmark({ sub }: { sub?: string }) {
  return (
    <span className="flex items-center gap-3">
      <img src="/brand/wordmark.png" alt={COMPANY} className="h-7 w-auto sm:h-8" />
      {sub && <span className="hidden border-l border-line/15 pl-3 text-[11px] sm:inline font-medium uppercase tracking-[0.14em] text-ink-3">{sub}</span>}
    </span>
  )
}
