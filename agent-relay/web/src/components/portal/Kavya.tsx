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
      <img src="/brand/mr-fix-it.gif" alt="" width={size} height={size} className="relative rounded-full object-cover ring-1 ring-line/10" />
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
