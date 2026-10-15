import { GuideCard, splitGuides } from '../Guides'
import { BOT, BOT_TAGLINE, COMPANY } from '../../lib/brand'
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api } from '../../lib/api'
import { fromEvent, fromLearned, launch, settle, type Chip } from '../../lib/chips'
import { speakerName, ticketLabel, titleCase, when } from '../../lib/format'
import type { ConversationSession, Customer, RelayEvent, ChatImages } from '../../lib/types'
import { Close, Send, Ticket as TicketIcon } from '../Icons'
import { KavyaAvatar, SPRING, Typing } from './Kavya'
import { MemoryChip, MemoryPanel } from './MemoryPanel'
import { TicketsPanel } from './TicketsPanel'

// `local` lines (our echo / the POST reply) get confirmed by the socket's copy; `ep` is the episode id.
interface Line { id: string; ep?: string; speaker: string; text: string; at?: string; pending?: boolean; local?: boolean
  mark?: string; rename?: boolean; images?: ChatImages }
export type Subscribe = (fn: (e: RelayEvent) => void) => () => void

const QUICK: [string, string][] = [
  ['My wifi drops every evening', 'My wifi drops every evening, mostly on my PS5.'],
  ['I moved house', 'I moved house last week, to '],
  ['Which plan am I on?', 'Which plan am I on?'],
  ['How much is Fiber 300?', 'How much is Fiber 300?'],
  ['Do you cover Baner?', 'Do you cover Baner?'],
  ['I no longer live in …', 'I no longer live in '],
]
const FLY_MS = 1200

const sessionKey = (tenant: string, who: string) => `pml.session.${tenant}.${who}`
// The last conversation on this device, shown straight away next visit (the graph has the full history too).
interface LastChat { who: string; session?: string; at: number; lines: Line[] }
const lastKey = (tenant: string) => `pml.lastChat.${tenant}`
const readLast = (tenant: string): LastChat | undefined => { try { return JSON.parse(localStorage.getItem(lastKey(tenant)) ?? 'null') ?? undefined } catch { return undefined } }
const writeLast = (tenant: string, v: LastChat) => { try { localStorage.setItem(lastKey(tenant), JSON.stringify(v)) } catch { /* private mode */ } }

/** The text with one name highlighted (where Kavya picked it up from your message). */
function Marked({ text, mark }: { text: string; mark?: string }) {
  if (!mark) return <>{text}</>
  const i = text.toLowerCase().indexOf(mark.toLowerCase())
  if (i < 0) return <>{text}</>
  return <>{text.slice(0, i)}<mark className="rounded-md bg-signal/30 px-1 font-semibold text-inherit">{text.slice(i, i + mark.length)}</mark>{text.slice(i + mark.length)}</>
}
const readSession = (k: string) => { try { return localStorage.getItem(k) ?? undefined } catch { return undefined } }
const writeSession = (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }
const first = (who: string) => titleCase(who.split(' ')[0])

// Greetings and lead-in words are never part of a name ("Myself Adit Raj" is Adit Raj).
const GREETING = /^(hi+|hello+|hey+|hiya|yo|namaste|vanakkam|good|morning|afternoon|evening|there|team|kavya|myself|me|i|am|im|i'm|is|it's|its|this|here|my|name|called|sir|madam|mr|mrs|ms|dr)$/i
// Words that end a name ("I'm Adit and my wifi drops" -> Adit) or show it isn't one ("I'm in Goa", "I'm a gamer").
const NOT_NAME = new Set(['and', 'but', 'from', 'in', 'at', 'on', 'my', 'i', 'a', 'an', 'the', 'with', 'living', 'live', 'calling',
  'here', 'so', 'just', 'not', 'yes', 'no', 'ok', 'okay', 'thanks', 'thank', 'please', 'help', 'wifi', 'internet', 'plan', 'plans',
  'router', 'broadband', 'fiber', 'fibre', 'what', 'which', 'how', 'why', 'when', 'where', 'who', 'do', 'does', 'can', 'is', 'are',
  'you', 'your', 'cover', 'service', 'services', 'having', 'facing', 'new', 'moving', 'looking', 'customer', 'user', 'gamer', 'student'])
const LEAD = /(?:my name is|my name's|myself|i am|i'm|im|this is|here is|call me|it's|its)\s+([a-z][a-z'.-]*(?:\s+[a-z][a-z'.-]*){0,3})/i

/** Find a name in a chat message, without a name box:
 *  "Hi, I'm Adit and my wifi drops" -> "adit"; "Adit Raj" -> "adit raj"; "do you cover goa?" -> null. */
export function nameFrom(input: string): string | null {
  const t = input.trim()
  const lead = t.match(LEAD)
  if (lead) {
    const words: string[] = []
    for (const raw of lead[1].split(/\s+/)) {
      const w = raw.replace(/[.,!?;:]+$/, '')
      if (!w || NOT_NAME.has(w.toLowerCase()) || GREETING.test(w)) break
      words.push(w)
      if (w !== raw) break  // "Asha Rao." : punctuation ends the name
    }
    if (words.length) return words.slice(0, 3).join(' ').toLowerCase()
    return null  // "I'm in Goa", "I'm a gamer": a lead-in, but no name after it
  }
  if (/[?]/.test(t)) return null  // a question, not a name
  const words = t.replace(/[.!,]+$/g, '').split(/[\s,]+/).filter((w) => w && !GREETING.test(w))
  if (!words.length || words.length > 3) return null
  if (!words.every((w) => /^[a-z][a-z'.-]*$/i.test(w) && !NOT_NAME.has(w.toLowerCase()))) return null
  return words.join(' ').toLowerCase()
}

/** Was there more in the message than the name? ("I'm Adit and my wifi drops" -> true: send it on.) */
export function saysMore(input: string, name: string): boolean {
  const rest = input.toLowerCase().replace(name, ' ').split(/[^a-z0-9]+/)
    .filter((w) => w && !GREETING.test(w) && !['and', 'my', 'name', 'call', 'me', 'this', 'is', 'here'].includes(w))
  return rest.length >= 2
}

function Bubble({ l, customer, flying, onRename }: { l: Line; customer: string; flying: Chip[]; onRename?: () => void }) {
  const mine = l.speaker === 'customer'
  const kavya = l.speaker === 'intake'
  const tool = l.speaker.startsWith('tool:')
  const name = mine ? 'You' : kavya ? BOT : speakerName(l.speaker, customer)
  const said = splitGuides(l.text)
  return (
    <motion.div layout="position" initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={SPRING}
      className={`flex items-end gap-2.5 ${mine ? 'flex-row-reverse' : ''}`}>
      {kavya ? <KavyaAvatar size={32} online={false} /> : !mine && (
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${tool ? 'bg-sunk text-ink-2' : l.speaker === 'noc' ? 'bg-current text-white' : 'bg-ink text-paper'}`}>
          {tool ? 'SYS' : l.speaker === 'noc' ? 'NOC' : 'RS'}
        </span>
      )}
      <div className={`flex min-w-0 max-w-[78%] flex-col ${mine ? 'items-end' : 'items-start'}`}>
        <p className="mb-1 px-1 text-[11.5px] text-ink-3">
          <span className="font-medium text-ink-2">{name}</span><span className="num"> · {l.pending ? 'sending…' : when(l.at)}</span>
        </p>
        <p className={`rounded-[1.25rem] px-4 py-2.5 text-[15px] leading-relaxed ${mine ? 'rounded-br-md bg-ink text-paper'
          : tool ? 'rounded-bl-md bg-sunk/70 font-mono text-[13px] text-ink-2'
          : l.speaker === 'resolver' ? 'rounded-bl-md bg-signal-tint text-ink'
          : l.speaker === 'noc' ? 'rounded-bl-md bg-current-tint text-ink ring-1 ring-current/30' : 'rounded-bl-md bg-sunk text-ink'}`}>
          <Marked text={said.text} mark={l.mark} />
          {l.rename && onRename && (
            <button type="button" onClick={onRename} className="ml-1.5 text-[13px] font-medium text-signal-deep underline-offset-2 hover:underline">Not right? Change it</button>
          )}
        </p>
        {said.guides.map((g) => <div key={g} className="mt-2 w-full"><GuideCard id={g} /></div>)}
        {l.images && (
          <div className="mt-2 grid w-full max-w-sm grid-cols-2 gap-1.5" aria-label={`Pictures: ${l.images.query}`}>
            {l.images.images.map((im, i) => (
              <a key={i} href={im.link ?? undefined} target="_blank" rel="noreferrer noopener" title={im.title}
                className="block overflow-hidden rounded-xl bg-sunk ring-1 ring-line/10 transition duration-300 ease-spring hover:ring-signal/40">
                <img src={im.src} alt={im.title} loading="lazy" className="aspect-[4/3] w-full bg-paper object-contain p-1" />
                <span className="block truncate px-2 py-1 text-[11px] text-ink-3">{im.title} · Wikipedia</span>
              </a>
            ))}
          </div>
        )}
        {flying.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5 px-1">{flying.map((c) => <MemoryChip key={c.key} c={c} />)}</div>
        )}
      </div>
    </motion.div>
  )
}

function HistoryRow({ s, customer }: { s: ConversationSession; customer: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-2xl bg-sunk/50">
      <button className="flex w-full items-baseline gap-3 px-4 py-2.5 text-left text-sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="num shrink-0 text-xs text-ink-3">{when(s.started_at ?? s.messages[0]?.at)}</span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{s.summary ?? s.messages[0]?.text ?? s.session_id}</span>
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={SPRING} className="text-ink-3">›</motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.38, ease: [0.32, 0.72, 0, 1] }} className="overflow-hidden">
            <div className="space-y-3 px-4 pb-4 pt-1">
              {s.messages.map((m) => <Bubble key={m.episode_id} l={{ id: m.episode_id, speaker: m.speaker, text: m.text, at: m.at }} customer={customer} flying={[]} />)}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function SupportDesk({ tenant, customers, subscribe, onWho, onChips, typeRef, memoryWidth = 380, side = 'memory' }: { tenant: string; customers: Customer[]; subscribe: Subscribe
  onWho?: (who: string | null) => void; onChips?: (chips: Chip[]) => void; memoryWidth?: number; side?: 'memory' | 'tickets' | 'none'
  typeRef?: { current: ((text: string) => void) | null } }) {
  const reduce = useReducedMotion()
  const [who, setWho] = useState<string | null>(null)
  const [session, setSession] = useState<string>()
  const [history, setHistory] = useState<ConversationSession[]>([])
  const [lines, setLines] = useState<Line[]>([])
  const [chips, setChips] = useState<Chip[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<string>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  const [ripple, setRipple] = useState(0)
  const [toast, setToast] = useState<{ ticket: string; issue?: string }>()
  const [intro, setIntro] = useState<Line[]>([])       // this visit's chat before Kavya knew your name
  const [pendingAsk, setPendingAsk] = useState<string>() // a question you asked before giving your name
  const [autoSend, setAutoSend] = useState<string>()
  const [loadedFor, setLoadedFor] = useState<string | null>(null) // whose history has finished loading
  const [lastChat, setLastChat] = useState<LastChat | undefined>(() => readLast(tenant))
  useEffect(() => setLastChat(readLast(tenant)), [tenant])
  const scroller = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const tickets = useRef(new Set<string>())
  const busyRef = useRef(false)
  const typer = useRef<ReturnType<typeof setInterval>>()
  const linesRef = useRef(lines)
  const chipsRef = useRef(chips)
  linesRef.current = lines
  chipsRef.current = chips

  const customer = customers.find((c) => c.key === who)
  useEffect(() => { onWho?.(who) }, [who, onWho])
  useEffect(() => { onChips?.(chips) }, [chips, onChips])
  const last = history[history.length - 1]

  const clear = () => { setLines([]); setHistory([]); setChips([]); setSession(undefined); setToast(undefined) }
  const reset = () => { setWho(null); clear(); setIntro([]); setPendingAsk(undefined) }
  // "Not right? Change it": back to asking, keeping what was said so far on screen
  const rename = () => {
    setWho(null); clear()
    setIntro((l) => [...l, { id: `ask-${Date.now()}`, speaker: 'intake', text: 'No problem. What should I call you?' }])
    input.current?.focus()
  }
  useEffect(clear, [tenant]) // a region is its own desk and graph: keep the person, load that desk's history for them
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: reduce ? 'auto' : 'smooth' }) }, [lines, history, busy, chips.length, reduce])
  useEffect(() => { if (!toast) return; const id = setTimeout(() => setToast(undefined), 6500); return () => clearTimeout(id) }, [toast])
  useEffect(() => () => clearInterval(typer.current), [])
  useEffect(() => {
    if (!who || !lines.length) return
    const v = { who, session, at: Date.now(), lines: lines.filter((l) => !l.pending).slice(-30).map(({ id, ep, speaker, text, at }) => ({ id, ep, speaker, text, at })) }
    writeLast(tenant, v)
  }, [tenant, who, session, lines])

  // Previous sessions; continue the stored one if it still exists.
  useEffect(() => {
    if (!who) return
    let live = true
    const stored = readSession(sessionKey(tenant, who))
    tickets.current = new Set(customers.filter((c) => c.key === who && c.open_ticket).map((c) => c.open_ticket!.toLowerCase()))
    setLoading(true)
    api.conversation(tenant, who).then((c) => {
      if (!live) return
      const current = c.sessions.find((s) => s.session_id === stored)
      setHistory(c.sessions.filter((s) => s !== current))
      setSession(current?.session_id)
      setLines((current?.messages ?? []).map((m) => ({ id: m.episode_id, ep: m.episode_id, speaker: m.speaker, text: m.text, at: m.at })))
    }).catch(() => live && setHistory([])).finally(() => { if (live) { setLoading(false); setLoadedFor(who); input.current?.focus() } })
    return () => { live = false }
  }, [tenant, who]) // customers is read once at chat start on purpose

  useEffect(() => {
    if (!who || loadedFor !== who || !autoSend) return  // after their history has loaded, so it can't overwrite it
    const msg = autoSend
    setAutoSend(undefined)
    send(undefined, msg)
  }, [who, loadedFor, autoSend]) // eslint-disable-line react-hooks/exhaustive-deps

  // Live: messages for this customer and memory changes about them, from the page's tenant socket.
  useEffect(() => {
    if (!who) return
    return subscribe((e) => {
      if (e.type === 'kavya_step') { if (e.data.customer === who && busyRef.current) setStep(e.data.step); return }
      if (e.type === 'message') {
        if (e.data.customer !== who || e.data.speaker === 'action') return  // internal notes stay in the console
        if (side !== 'memory' && e.data.speaker.startsWith('tool:')) return  // customers never see raw tool output
        const d = e.data
        setLines((ls) => {
          if (d.episode_id && ls.some((l) => l.ep === d.episode_id)) return ls
          const i = ls.findIndex((l) => l.local && l.speaker === d.speaker && l.text === d.text)
          if (i >= 0) return ls.map((l, j) => (j === i ? { ...l, ep: d.episode_id, local: false, pending: false, at: e.sim_time ?? l.at } : l))
          return [...ls, { id: d.episode_id ?? `ws-${e.wall}-${ls.length}`, ep: d.episode_id, speaker: d.speaker, text: d.text, at: e.sim_time ?? undefined }]
        })
        return
      }
      if (e.type === 'ticket_opened' && e.data.customer === who) setToast({ ticket: e.data.ticket, issue: e.data.issue })
      const phase = busyRef.current ? 'pending' : 'settled'
      const next = fromEvent(chipsRef.current, e, who, tickets.current, phase)
      if (next === chipsRef.current) return
      chipsRef.current = next
      setChips(next)
      if (phase === 'settled') setRipple((r) => r + 1)
    })
  }, [who, subscribe])

  if (typeRef) typeRef.current = typeInto  // lets a panel outside the chat type a message into it
  function typeInto(full: string) {
    clearInterval(typer.current)
    input.current?.focus()
    if (reduce) { setText(full); return }
    let i = 0
    setText('')
    typer.current = setInterval(() => {
      i += 1
      setText(full.slice(0, i))
      if (i >= full.length) clearInterval(typer.current)
    }, 16)
  }

  /** Before Kavya knows your name, your first messages are how she learns it: no name box. */
  function introduce(msg: string) {
    const n = nameFrom(msg)
    const id = `intro-${Date.now()}`
    if (!n) {
      const question = msg.split(/\s+/).length >= 2 && !/^\s*(hi+|hello+|hey+|hiya|namaste)\b[\s!.,]*$/i.test(msg)
      if (question) setPendingAsk(msg)
      setIntro((l) => [...l, { id, speaker: 'customer', text: msg, at: new Date().toISOString() },
        { id: `${id}-k`, speaker: 'intake', at: new Date().toISOString(),
          text: question ? "Happy to help with that. First, what should I call you?" : "I didn't quite catch your name. What should I call you?" }])
      return
    }
    setIntro((l) => [...l, { id, speaker: 'customer', text: msg, mark: n, at: new Date().toISOString() }])
    const follow = saysMore(msg, n) ? msg : pendingAsk
    setPendingAsk(undefined)
    clear(); setWho(n)
    if (follow) setAutoSend(follow)
  }

  async function send(e?: FormEvent, override?: string) {
    e?.preventDefault()
    const msg = (override ?? text).trim()
    if (!msg || busy) return
    if (!who) { setText(''); introduce(msg); return }
    clearInterval(typer.current)
    setText(''); setError(undefined); setBusy(true); busyRef.current = true
    const localId = `local-${Date.now()}`
    setLines((l) => [...l, { id: localId, speaker: 'customer', text: msg, pending: true, local: true }])
    try {
      const r = await api.chat(tenant, { customer: who, text: msg, session_id: session, greeted: true })  // we greet on screen
      setSession(r.session_id)
      writeSession(sessionKey(tenant, who), r.session_id)
      // The socket may already have delivered Kavya's reply. The reply's episode id is the shared key, so the
      // socket copy and this one collapse into one bubble whichever arrives first (no text matching, no races).
      const replyId = r.reply_episode_id
        ?? linesRef.current.find((l) => l.speaker === 'intake' && l.text === r.reply)?.id
        ?? `reply-${localId}`
      setLines((ls) => {
        const done = ls.map((l) => (l.id === localId ? { ...l, ep: r.episode_id ?? l.ep, pending: false, at: l.at ?? new Date().toISOString() } : l))
          .filter((l, i, all) => !(l.ep && all.findIndex((x) => x.ep === l.ep) !== i))
        const next = done.some((l) => l.id === replyId || l.ep === replyId) ? done
          : [...done, { id: replyId, ep: r.reply_episode_id ?? undefined, speaker: 'intake', text: r.reply,
            at: new Date().toISOString(), local: !r.reply_episode_id }]
        const pics = r.images?.images.length ? r.images : undefined
        return pics ? next.map((l) => (l.id === replyId || l.ep === replyId ? { ...l, images: pics } : l)) : next
      })
      if (r.ticket_opened) setToast((t) => t ?? { ticket: r.ticket_opened! })
      // Chips ride on Kavya's reply, then fly into the memory panel.
      setChips((cs) => launch(fromLearned(cs, r.learned, 'pending'), replyId, r.learned.map((f) => f.fact_id)))
      setTimeout(() => { setChips((cs) => settle(cs, replyId)); setRipple((x) => x + 1) }, reduce ? 0 : FLY_MS)
    } catch {
      setLines((ls) => ls.filter((l) => l.id !== localId))
      setChips((cs) => cs.map((c) => (c.phase === 'pending' ? { ...c, phase: 'settled', at: Date.now() } : c)))
      setError("That message didn't go through. Please try again.")
      setText(msg)
    } finally {
      setBusy(false); busyRef.current = false; setStep(undefined)
    }
  }

  const continueAs = (n: string) => { clear(); setIntro([]); setWho(n) }

  return (
    <LayoutGroup>
      <div className={`grid h-full min-h-0 grid-cols-1 gap-4 ${side === 'none' ? '' : memoryWidth === 380 ? 'lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]' : 'lg:grid-cols-[minmax(0,1fr)_300px]'}`}>
        <section className="relative flex min-h-[620px] flex-col overflow-hidden rounded-[1.75rem] bg-surface shadow-lift hairline lg:min-h-0" aria-label={`Chat with ${BOT}`}>
          <header className="flex items-center gap-3.5 px-6 py-4 shadow-[0_1px_0_rgb(var(--line)/0.07)]">
            <KavyaAvatar size={48} thinking={busy} ripple={ripple} />
            <div className="min-w-0 flex-1">
              <p className="font-display text-lg font-semibold leading-tight">{BOT}</p>
              <p className="text-[13px] text-ink-3">“{BOT_TAGLINE}” · <span className="text-current">online</span>, replies in seconds</p>
            </div>
            {who && (
              <button className="chip bg-sunk !py-1.5 text-ink-2 transition duration-300 ease-spring hover:bg-line/10" onClick={reset} title="Switch customer">
                {titleCase(who)} <span className="text-ink-3">· switch</span>
              </button>
            )}
          </header>

          <AnimatePresence>
            {toast && (
              <motion.div role="status" initial={{ opacity: 0, y: -12, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8 }} transition={SPRING}
                className="absolute right-5 top-[84px] z-10 flex w-[290px] items-start gap-3 rounded-2xl bg-surface p-3.5 shadow-lift hairline">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-signal-tint text-signal-deep"><TicketIcon /></span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">Ticket <span className="font-mono">{ticketLabel(toast.ticket)}</span> opened</p>
                  <p className="mt-0.5 text-xs text-ink-2">{toast.issue ? `${titleCase(toast.issue)} · ` : ''}handed to our resolver, who'll check your line next.</p>
                </div>
                <button className="text-ink-3 hover:text-ink" onClick={() => setToast(undefined)} aria-label="Dismiss"><Close className="h-4 w-4" /></button>
              </motion.div>
            )}
          </AnimatePresence>

          <div ref={scroller} className="scroll-thin flex-1 space-y-4 overflow-y-auto px-6 py-6" aria-live="polite">
            {!who && lastChat && intro.length === 0 && (
              <div className="rounded-2xl bg-sunk/50 p-4">
                <p className="eyebrow">Last time on this device · {when(new Date(lastChat.at).toISOString())}</p>
                <div className="mt-3 space-y-3 opacity-90">
                  {lastChat.lines.slice(-4).map((l) => <Bubble key={`last-${l.id}`} l={l} customer={lastChat.who} flying={[]} />)}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button className="btn-primary !py-1.5 text-sm" onClick={() => continueAs(lastChat.who)}>Continue as {titleCase(lastChat.who)}</button>
                  <span className="text-xs text-ink-3">The desk remembers the rest, whoever you talk to next.</span>
                </div>
              </div>
            )}
            <Bubble l={{ id: 'hi', speaker: 'intake', text: `Hey, I'm ${BOT} from ${COMPANY}. ${BOT_TAGLINE} Tell me once and I'll remember it, so nobody here ever asks you twice. What should I call you?` }} customer="" flying={[]} />
            {intro.map((l) => <Bubble key={l.id} l={l} customer={who ?? ''} flying={[]} />)}
            {!who && customers.length > 0 && intro.length === 0 && (
              <p className="px-1 text-xs text-ink-3">Demo customers: {customers.slice(0, 4).map((c, i) => (
                <span key={c.key}>{i ? ', ' : ''}<button className="font-medium text-signal-deep hover:underline" onClick={() => continueAs(c.key)}>{c.name}</button></span>
              ))}</p>
            )}
            {who && (
              <>
                {loading && <p className="text-xs text-ink-3 animate-breathe">Pulling up your notes…</p>}
                {history.length > 0 && (
                  <div className="space-y-2">
                    <p className="eyebrow">Earlier conversations</p>
                    {history.map((s) => <HistoryRow key={s.session_id} s={s} customer={who} />)}
                  </div>
                )}
                {!loading && (
                  <Bubble customer={who} flying={[]} onRename={rename} l={{ id: 'greet', speaker: 'intake', mark: first(who), rename: true, text: last
                    ? `Welcome back, ${first(who)}! Last time: ${(last.summary ?? last.messages[last.messages.length - 1]?.text ?? '').replace(/\.$/, '')}. What's up today?`
                    : `Lovely to meet you, ${first(who)}. What's acting up today? Wifi sulking, a move, a plan question, I'm all ears.` }} />
                )}
                {lines.filter((l) => side === 'memory' || !l.speaker.startsWith('tool:')).map((l) => <Bubble key={l.id} l={l} customer={who} flying={side !== 'tickets' ? chips.filter((c) => c.phase === 'flying' && c.line === l.id) : []} />)}
              </>
            )}
            <AnimatePresence>{busy && <Typing key="typing" step={step} />}</AnimatePresence>
            {error && <p className="text-sm text-danger" role="alert">{error}</p>}
          </div>

          <div className="space-y-3 px-5 pb-5 pt-2">
              {who && <div className="flex flex-wrap gap-2">
                {QUICK.map(([label, full]) => (
                  <button key={label} type="button" onClick={() => typeInto(full)} disabled={busy}
                    className="rounded-full bg-sunk px-3.5 py-1.5 text-[13px] text-ink-2 transition duration-300 ease-spring hover:bg-signal-tint hover:text-signal-deep active:scale-[0.97] disabled:opacity-50">
                    {label}
                  </button>
                ))}
              </div>}
              <form onSubmit={send} className="flex items-center gap-2 rounded-full bg-sunk/70 p-1.5 pl-5 ring-signal/40 transition duration-300 ease-spring focus-within:bg-surface focus-within:ring-2">
                <label htmlFor="pml-msg" className="sr-only">Message {BOT}</label>
                <input id="pml-msg" ref={input} className="h-10 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
                  placeholder={who ? `Message ${BOT}, ${first(who)}` : `Say hi and tell ${BOT} your name`} value={text}
                  onChange={(e) => { clearInterval(typer.current); setText(e.target.value) }} disabled={busy} autoFocus={!who} />
                <button className="btn-signal h-11 w-11 shrink-0 !p-0" aria-label="Send" disabled={busy || !text.trim()}><Send /></button>
              </form>
              {session && <p className="px-2 font-mono text-[10.5px] text-ink-3">session {session} · continues next time on this device</p>}
            </div>
        </section>

        {side === 'none' ? null : side === 'tickets'
          ? <TicketsPanel tenant={tenant} who={who} customer={customer} subscribe={subscribe} onAsk={typeInto} />
          : <MemoryPanel who={who} customer={customer} chips={chips} tenant={tenant} />}
      </div>
    </LayoutGroup>
  )
}
