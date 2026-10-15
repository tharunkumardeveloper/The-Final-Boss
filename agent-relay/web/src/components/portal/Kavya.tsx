import { BOT } from '../../lib/brand'
import { AnimatePresence, motion } from 'framer-motion'

export const SPRING = { type: 'spring', stiffness: 420, damping: 32, mass: 0.8 } as const

/** Kavya's avatar: an illustrated monogram on the brand teal, with an online dot.
 *  `thinking` = soft breathing ring while she works; `ripple` (a counter) = one ring per memory update. */
export function KavyaAvatar({ size = 44, thinking = false, ripple = 0, online = true }: { size?: number; thinking?: boolean; ripple?: number; online?: boolean }) {
  return (
    <span className="relative inline-flex shrink-0" style={{ width: size, height: size }} aria-hidden="true">
      {thinking && (
        <motion.span className="absolute inset-0 rounded-full bg-signal/25"
          initial={{ scale: 1, opacity: 0.6 }} animate={{ scale: [1, 1.22, 1], opacity: [0.55, 0.15, 0.55] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: [0.32, 0.72, 0, 1] }} />
      )}
      <AnimatePresence>
        {ripple > 0 && (
          <motion.span key={ripple} className="absolute inset-0 rounded-full border-2 border-current"
            initial={{ scale: 1, opacity: 0.7 }} animate={{ scale: 1.9, opacity: 0 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.9, ease: [0.32, 0.72, 0, 1] }} />
        )}
      </AnimatePresence>
      <svg viewBox="0 0 48 48" width={size} height={size} className="relative">
        <defs>
          <linearGradient id="kavya-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="rgb(var(--signal))" />
            <stop offset="1" stopColor="rgb(var(--signal-deep))" />
          </linearGradient>
        </defs>
        <circle cx="24" cy="24" r="24" fill="url(#kavya-bg)" />
        {/* hair arc + face: a friendly, abstract portrait rather than a stock photo */}
        <path d="M11 25c0-9 5.8-14.5 13-14.5S37 16 37 25c-2.2-4.6-6.5-7.6-13-7.6S13.2 20.4 11 25Z" fill="rgb(var(--ink))" opacity="0.92" />
        <circle cx="24" cy="26" r="10.5" fill="#F8E7D8" />
        <path d="M13.5 24.5c1.8-4.4 5.5-6.8 10.5-6.8s8.7 2.4 10.5 6.8c-3-2.4-6.3-3.4-10.5-3.4s-7.5 1-10.5 3.4Z" fill="rgb(var(--ink))" opacity="0.92" />
        <circle cx="20.2" cy="26.6" r="1.25" fill="rgb(var(--ink))" />
        <circle cx="27.8" cy="26.6" r="1.25" fill="rgb(var(--ink))" />
        <path d="M20.6 30.3c1 1.3 2.1 1.9 3.4 1.9s2.4-.6 3.4-1.9" fill="none" stroke="rgb(var(--ink))" strokeWidth="1.3" strokeLinecap="round" />
        <circle cx="24" cy="21.9" r="0.9" fill="rgb(var(--signal))" />
        <path d="M14 44c1.6-5.2 5.4-8 10-8s8.4 2.8 10 8" fill="rgb(var(--paper))" opacity="0.95" />
      </svg>
      {online && <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full bg-current ring-2 ring-surface" />}
    </span>
  )
}

/** Three-dot typing indicator in a Kavya bubble. */
/** Typing dots, plus what Kavya is actually doing right now (each label is a live lookup on the backend). */
export function Typing({ step }: { step?: string }) {
  return (
    <motion.div className="flex items-end gap-2.5" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }} transition={SPRING}
      role="status" aria-live="polite" aria-label={step ? `${BOT}: ${step}` : `${BOT} is typing`}>
      <KavyaAvatar size={32} thinking online={false} />
      <div className="flex items-center gap-3 rounded-2xl rounded-bl-md bg-sunk px-4 py-3">
        <span className="flex items-center gap-1">
          {[0, 1, 2].map((i) => (
            <motion.span key={i} className="h-2 w-2 rounded-full bg-ink-3"
              animate={{ y: [0, -4, 0], opacity: [0.45, 1, 0.45] }}
              transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.14, ease: [0.32, 0.72, 0, 1] }} />
          ))}
        </span>
        <AnimatePresence mode="wait" initial={false}>
          {step && (
            <motion.span key={step} className="text-[13px] text-ink-2"
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
              {step}…
            </motion.span>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
