import { AnimatePresence, motion } from 'framer-motion'
import type { LabRun, LabView } from '../../lib/types'
import { FieldDispatch, Trace, useDispatch } from '../../pages/Lab'
import { SPRING } from './Kavya'

/** Under the customer's ticket: the resolver's work step by step, and the technician's trip when one is sent.
 *  Kept here rather than under the network diagram, so the diagram keeps its full height while steps stream in. */
export default function ResolverCard({ run, view }: { run: LabRun; view?: LabView }) {
  const crew = useDispatch(run)
  const reported = view?.network?.homes.some((h) => h.customer === run.customer && h.state === 'reported')
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}
      className="rounded-2xl bg-paper/80 p-4 hairline" aria-label="Resolver at work">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-ink-2">Resolver at work</p>
        {reported && <span className="chip bg-danger-tint !py-0.5 text-[10.5px] text-danger">Your line is marked faulty</span>}
      </div>
      <AnimatePresence initial={false}>
        {crew && view?.network && (
          <motion.div key={crew.at} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            transition={SPRING} className="mt-2 overflow-hidden rounded-2xl bg-ink px-1 pb-1 text-white">
            <FieldDispatch d={crew} view={view.network} />
          </motion.div>
        )}
      </AnimatePresence>
      <div className="mt-2"><Trace run={run} compact /></div>
    </motion.section>
  )
}
