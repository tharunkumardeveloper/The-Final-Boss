import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BOT } from '../../lib/brand'
import type { Customer, LabRun } from '../../lib/types'
import { Close } from '../Icons'
import { SPRING } from './Kavya'
import type { ChatDriver } from './SupportChat'

/** Judge mode: the whole story, played through the real agents with nobody typing. Every message goes through the same
 *  chat endpoint a person uses; the script only answers what the agents ask, the way a customer would. */
export const JUDGE_STEPS: [string, string][] = [
  ['A new customer says hi', `No sign-up, no form: ${BOT}, the intake agent, picks the name up from the chat.`],
  ['They report a fault in plain words', `Each detail becomes a fact in the shared graph. ${BOT} opens a ticket and hands it over.`],
  ['A second agent fixes it', 'The resolver never messages the intake agent. It reads what intake wrote, measures the line with Cypher, acts, and re-measures. Watch Your tickets and the Network lab.'],
  ['A fact stops being true', '"I no longer live in Chennai, I\'ve moved to Pune": the new fact supersedes the old one, which is closed on both clocks (world and system), not deleted. The graph updates live.'],
  ['A brand-new session', 'The next visit starts a new session, yet nothing is asked again: "Pune, and your ticket is resolved" comes from memory, with the fact it rests on under the reply.'],
  ['That\'s Relay', 'Two agents that never message each other, yet never contradict each other: one FalkorDB graph per tenant is the shared state.'],
]

const FIRST = ['Asha', 'Ravi', 'Meera', 'Karthik', 'Divya', 'Arjun', 'Nila', 'Vikram', 'Priya', 'Sanjay', 'Kavin', 'Lakshmi']
const LAST = ['Menon', 'Iyer', 'Pillai', 'Nair', 'Reddy', 'Varma', 'Bose', 'Kapoor', 'Raman', 'Subramani', 'Mathew', 'Joseph']
const STOP = Symbol('stop')
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export type JudgeStatus = 'idle' | 'running' | 'done' | 'stopped' | 'error'
export interface Judge { status: JudgeStatus; step: number; note?: string; name?: string; start: () => void; stop: () => void; close: () => void }

/** Answers to what intake asks, matched on its question (the wording comes from a model, the order from the spec). */
function answerFor(q: string, phone: string): string | null {
  if (/number|mobile|phone|e-?mail|account/i.test(q)) return `It's ${phone}.`
  if (/wi-?fi only|plug|cable/i.test(q)) return 'Both, on WiFi and on the cable.'
  if (/whole home|one device|which devices?/i.test(q)) return 'The whole home, every device.'
  if (/when|start|since|how long/i.test(q)) return 'Since this morning.'
  if (/city|area|where|locat/i.test(q)) return 'T. Nagar, Chennai.'
  if (/tried|restart/i.test(q)) return "I restarted the router already, it didn't help."
  return null
}

export function useJudge({ drive, run, tenant, setTenant, customers, onStep }: {
  drive: { current: ChatDriver | null }; run?: LabRun; tenant: string; setTenant: (t: string) => void; customers: Customer[]
  onStep?: (step: number) => void
}): Judge {
  const [status, setStatus] = useState<JudgeStatus>('idle')
  const [step, setStep] = useState(0)
  const [note, setNote] = useState<string>()
  const [name, setName] = useState<string>()
  const stopped = useRef(false)
  const runRef = useRef(run)
  runRef.current = run
  const live = useRef({ tenant, customers, onStep })
  live.current = { tenant, customers, onStep }

  const start = useCallback(() => {
    if (status === 'running') return
    stopped.current = false
    setStatus('running'); setNote(undefined); setStep(0)
    const check = () => { if (stopped.current) throw STOP }
    const until = async (ok: () => boolean, ms: number) => {
      const end = Date.now() + ms
      while (!ok()) { check(); if (Date.now() > end) return false; await sleep(300) }
      return true
    }
    const go = (n: number) => { check(); setStep(n); live.current.onStep?.(n) }
    const say = async (text: string, needWho = true) => {
      check()
      if (!await until(() => !!drive.current && (needWho ? drive.current.ready() : drive.current.idle()), 45_000)) throw new Error('The chat stopped responding.')
      check()
      const reply = await drive.current!.say(text)
      check()
      return reply
    }
    ;(async () => {
      if (live.current.tenant !== 'pml') { setTenant('pml'); await sleep(1800) }  // the story's line is in Chennai, on the India desk
      const taken = new Set(live.current.customers.map((c) => c.key))
      const pick = () => `${FIRST[Math.floor(Math.random() * FIRST.length)]} ${LAST[Math.floor(Math.random() * LAST.length)]}`
      let who = pick()
      for (let i = 0; i < 20 && taken.has(who.toLowerCase()); i++) who = pick()
      setName(who)
      const phone = `9${Math.floor(100000000 + Math.random() * 899999999)}`

      // 1. a new customer, a fresh chat
      drive.current?.restart()
      await sleep(500)
      go(1)
      await say(`Hi, I'm ${who}`, false)
      await until(() => !!drive.current?.ready(), 20_000)
      await sleep(900)

      // 2. the complaint, the way a person says it; intake asks for whatever is still missing
      go(2)
      let reply = await say(`My internet keeps dropping since this morning, on every device, WiFi and cable both. `
        + `My number is ${phone} and I'm in T. Nagar, Chennai.`)
      for (let i = 0; i < 6 && reply && !/hand(ed)?|resolver/i.test(reply); i++) {
        const a = answerFor(reply, phone)
        if (!a) break
        reply = await say(a)
      }

      // 3. the resolver works the ticket; the customer answers only when it asks something
      go(3)
      const answered = new Set<string>()
      let confirmedAt = 0
      const end = Date.now() + 5 * 60_000
      while (Date.now() < end) {
        check()
        const r = runRef.current
        if (r?.confirmed || (confirmedAt && Date.now() - confirmedAt > 5000)) break
        if (r && !r.awaiting && ['handed over', 'unresolved', 'error'].includes(r.status)) break
        const key = r ? `${r.id}:${String(r.awaiting)}:${r.steps.filter((s) => s.kind === 'wait').length}` : ''
        if (r?.awaiting && !answered.has(key) && drive.current?.ready()) {
          answered.add(key)
          if (r.awaiting === 'guided') await say("I checked: the cable at the back is clicked in properly, but it's still dropping.")
          else if (r.awaiting === 'details') await say(`My address is 14 Usman Road, T. Nagar, Chennai. Mobile ${phone}, and tomorrow morning works.`)
          else { await say("Yes, it's working now. Thanks!"); confirmedAt = Date.now() }
        }
        await sleep(800)
      }
      await sleep(1500)

      // 4. something stops being true
      go(4)
      await say("One more thing: I no longer live in Chennai. I've moved to Pune, my new address is 22 FC Road, Shivajinagar, Pune.")
      await sleep(4500)

      // 5. the next visit, as a new session
      go(5)
      drive.current?.newSession()
      await until(() => !!drive.current?.ready(), 20_000)
      await sleep(2200)
      // no city named in the question: the answer has to come from memory
      await say('Hi again! Which city do you have me in now, and is my internet ticket sorted?')
      await sleep(2500)
      go(6)
      setStatus('done')
    })().catch((e) => {
      if (e === STOP) { setStatus('stopped'); return }
      setStatus('error')
      setNote(`${e instanceof Error ? e.message : 'Something went wrong.'} The free model quota may be busy: try again in a minute.`)
    })
  }, [status, drive, setTenant])

  const stop = useCallback(() => { stopped.current = true }, [])
  const close = useCallback(() => { stopped.current = true; setStatus('idle'); setStep(0) }, [])
  return { status, step, note, name, start, stop, close }
}

/** The caption bar above the three cards while Judge mode plays: which step, what to look at, stop or replay. */
export function JudgeBar({ judge }: { judge: Judge }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { if (judge.status === 'running' && judge.step <= 1) box.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [judge.status, judge.step])
  const [title, detail] = JUDGE_STEPS[Math.max(0, judge.step - 1)]
  return (
    <AnimatePresence>
      {judge.status !== 'idle' && (
        <motion.div ref={box} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={SPRING}
          className="mb-4 scroll-mt-4 rounded-2xl bg-ink p-4 text-paper shadow-lift" role="status" aria-live="polite">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="chip bg-signal text-white">Judge mode{judge.name ? ` · ${judge.name}` : ''}</span>
            <ol className="flex items-center gap-1.5" aria-label="Steps">
              {JUDGE_STEPS.map(([t], i) => (
                <li key={t} title={t} className={`h-1.5 w-7 rounded-full transition-colors duration-500 ${i + 1 < judge.step ? 'bg-signal' : i + 1 === judge.step ? 'bg-paper' : 'bg-paper/20'}`} />
              ))}
            </ol>
            <span className="text-xs text-paper/60 num">{judge.step ? `Step ${judge.step} of ${JUDGE_STEPS.length}` : 'Starting…'}</span>
            <span className="ml-auto flex items-center gap-2">
              {judge.status === 'running'
                ? <button onClick={judge.stop} className="rounded-full bg-paper/10 px-3 py-1 text-xs hover:bg-paper/20">Stop</button>
                : <button onClick={judge.start} className="rounded-full bg-paper/10 px-3 py-1 text-xs hover:bg-paper/20">Play again</button>}
              <button onClick={judge.close} className="rounded-full p-1 text-paper/60 hover:text-paper" aria-label="Close judge mode"><Close className="h-4 w-4" /></button>
            </span>
          </div>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={`${judge.step}-${judge.status}`} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.25 }}>
              <p className="mt-2 font-display text-lg font-semibold">{judge.status === 'stopped' ? 'Stopped' : judge.status === 'error' ? 'The live run stalled' : title}</p>
              <p className="mt-0.5 max-w-3xl text-sm text-paper/75">{judge.status === 'error' ? judge.note : judge.status === 'stopped' ? 'Everything it did so far is real and stays in the graph.' : detail}</p>
              {judge.status === 'done' && (
                <p className="mt-2 flex flex-wrap gap-3 text-sm">
                  <Link to="/console/benchmark" className="font-medium text-signal underline-offset-2 hover:underline">The benchmark: 99.4% vs 61% →</Link>
                  <Link to="/console" className="font-medium text-signal underline-offset-2 hover:underline">The graph behind it, in the console →</Link>
                </p>
              )}
            </motion.div>
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
