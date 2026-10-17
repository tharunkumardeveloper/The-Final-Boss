import { AnimatePresence, motion } from 'framer-motion'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { ConsoleNav } from '../components/console/ConsoleNav'
import { NetworkMap } from '../components/console/NetworkMap'
import { ShowMe } from '../components/console/ShowMe'
import { GuideCard, splitGuides } from '../components/Guides'
import { Check, Database, Pulse, Sparkle, Warning } from '../components/Icons'
import { api } from '../lib/api'
import { titleCase } from '../lib/format'
import { BOT } from '../lib/brand'
import { useRelayStream } from '../lib/stream'
import { useTenant } from '../lib/tenant'
import { TouchLayer } from '../components/console/TouchLayer'
import type { LabHome, LabManual, LabMessage, LabOlt, LabPreset, LabProcedure, LabRun, LabStep, LabView, RelayEvent } from '../lib/types'

const SPRING = { type: 'spring', stiffness: 380, damping: 32 } as const
const C = { ok: 'rgb(var(--signal))', bad: 'rgb(var(--danger))', warn: 'rgb(var(--conflict))', idle: 'rgb(255 255 255 / 0.22)', frozen: '#8fa2ff' }
export const HOME_COLOR: Record<LabHome['state'], string> = {
  ok: C.ok, dark: C.bad, flapping: C.warn, frozen: C.frozen, paused: '#c49bff', offline: C.bad, slow: C.warn, wifi: C.warn, reported: '#ff7a59',
}
export const HOME_WORD: Record<LabHome['state'], string> = {
  ok: 'online', dark: 'no light', flapping: 'weak light', frozen: 'box frozen', paused: 'account paused', offline: 'no route', slow: 'slow at night', wifi: 'Wi-Fi interference',
  reported: 'reported faulty',
}
const ACTIONS: [string, string][] = [
  ['remote_reboot', 'Restart the box remotely'], ['change_wifi_channel', 'Move Wi-Fi to a quieter channel'],
  ['dispatch_technician_home', 'Send a technician to the home'], ['dispatch_cable_crew', 'Send the cable crew to the cabinet'],
  ['reroute_standby', 'Switch the hub to its standby link'], ['dispatch_backbone_crew', 'Send the backbone team'],
  ['upgrade_uplink', 'Add capacity to the area uplink'], ['send_payment_link', 'Send a payment link'],
]
const WHAT: Record<string, string> = { light: 'light at the box', box: 'the box', account: 'the account', route: 'route to the internet', evening: 'evening speed', wifi: 'Wi-Fi' }

function PresetIcon({ name, className = 'h-5 w-5' }: { name: string; className?: string }) {
  const p = {
    box: <><rect x="4" y="7" width="16" height="10" rx="2" /><path d="M8 12h.01M12 12h.01M16 12h.01" /></>,
    wifi: <><path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0" /><path d="M12 19.5h.01" /></>,
    cable: <><path d="M4 18c4 0 4-12 8-12s4 12 8 12" /><circle cx="4" cy="18" r="1.5" /><circle cx="20" cy="18" r="1.5" /></>,
    scissors: <><circle cx="6" cy="7" r="2.5" /><circle cx="6" cy="17" r="2.5" /><path d="M8 8.5 20 17M8 15.5 20 7" /></>,
    route: <><circle cx="5" cy="18" r="2" /><circle cx="19" cy="6" r="2" /><path d="M7 18h6a3 3 0 0 0 0-6h-2a3 3 0 0 1 0-6h6" /></>,
    gauge: <><path d="M4 16a8 8 0 1 1 16 0" /><path d="m12 16 4-5" /></>,
    card: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M3 10h18M7 15h3" /></>,
  }[name]
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>{p}</svg>
}


// ---------------------------------------------------------------- field dispatch (only when the resolver sends people)

const CREW: Record<string, { who: string; to: string }> = {
  dispatch_technician_home: { who: 'Technician', to: 'home' },
  dispatch_cable_crew: { who: 'Cable crew', to: 'cabinet' },
  dispatch_backbone_crew: { who: 'Backbone team', to: 'hub link' },
}
export interface Dispatch { action: string; customer: string; name: string; tech?: string | null; at: number; ms: number
  arrive: number; verified?: LabStep; stage: 'enroute' | 'onsite' | 'done' | 'failed' }

const EASE = [0.22, 1, 0.36, 1] as const
/** Where the van is right now (0 at the depot, 1 on site), and how long it still drives: the motion runs on its own. */
function drive(d: Dispatch) {
  const left = Math.max(0, d.arrive - Date.now())
  const travel = d.arrive - d.at
  const done = travel > 0 ? 1 - left / travel : 1
  return { from: 1 - (1 - done) ** 3, left: left / 1000 }  // ease out: it slows as it arrives
}

/** The run's latest field job, while it is out (and for a few seconds after the re-measurement, so the result is seen). */
export function useDispatch(run?: LabRun): Dispatch | null {
  // No ticking: the van glides by itself (framer-motion), so the page only re-renders when the van arrives and when
  // the result has been shown long enough. Re-rendering the whole page 10x a second was what made the lab stutter.
  const [, force] = useState(0)
  const act = run ? [...run.steps].reverse().find((x) => x.kind === 'act' && String(x.data?.action ?? '') in CREW) : undefined
  const verified = act && run ? run.steps.find((x) => x.i > act.i && x.kind === 'verify') : undefined
  const ms = act ? Math.max(4, Number(act.data?.delayed) || 6) * 1000 : 0
  const arrive = act ? act.at + ms * 0.45 : 0
  const until = verified ? verified.at + 12_000 : 0
  useEffect(() => {
    const ids = [arrive, until].filter((t) => t > Date.now()).map((t) => setTimeout(() => force((n) => n + 1), t - Date.now() + 30))
    return () => ids.forEach(clearTimeout)
  }, [arrive, until])
  const gone = !act || !run || (until > 0 && Date.now() > until)
  const stage = verified ? (verified.status === 'ok' ? 'done' : 'failed') : Date.now() < arrive ? 'enroute' : 'onsite'
  return useMemo(() => gone || !act || !run ? null
    : { action: String(act.data.action), customer: run.customer, name: run.name, tech: run.technician, at: act.at, ms, arrive, verified, stage },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [gone, act?.at, verified?.i, stage, run?.customer, run?.technician])
}

function Van({ x, y, color }: { x: number; y: number; color: string }) {
  return (
    <g transform={`translate(${x - 13} ${y - 9})`} pointerEvents="none">
      <rect x="0" y="2" width="18" height="11" rx="2.5" fill={color} />
      <path d="M18 5h4.5l3.5 4v4h-8z" fill={color} />
      <rect x="19.5" y="6" width="3.5" height="3" rx="0.6" fill="rgb(var(--ink))" opacity="0.6" />
      <circle cx="5" cy="14.5" r="2.4" fill="rgb(var(--ink))" stroke="white" strokeWidth="1" />
      <circle cx="20" cy="14.5" r="2.4" fill="rgb(var(--ink))" stroke="white" strokeWidth="1" />
    </g>
  )
}

/** Under the diagram, only while a crew is out: who went where, the route, and how far along the job is. */
export function FieldDispatch({ d, view }: { d: Dispatch; view: NonNullable<LabView['network']> }) {
  const crew = CREW[d.action]
  const home = view.homes.find((h) => h.customer === d.customer)
  const cab = view.splitters.find((x) => x.id === home?.splitter)
  const link = view.links.find((l) => l.link === 'cut') ?? view.links[0]
  const first = d.name.split(' ')[0]
  const where = d.action === 'dispatch_technician_home' ? `${first}'s home${home ? ` · port ${home.port}` : ''}${cab ? `, ${cab.label}` : ''}`
    : d.action === 'dispatch_cable_crew' ? `the feeder cable of ${cab?.label ?? 'the street cabinet'}`
      : `${view.pop.label.replace(' POP', '')} hub ↔ ${link?.label ?? 'core'}`
  const stages: [Dispatch['stage'] | 'sent', string][] = [['sent', 'Dispatched'], ['enroute', 'En route'], ['onsite', 'On site · repairing'], ['done', 'Verified by re-measuring']]
  const at = { sent: 0, enroute: 1, onsite: 2, done: 3, failed: 3 }[d.stage]
  const go = drive(d)
  const tone = d.stage === 'failed' ? '#ff9b8f' : d.stage === 'done' ? 'rgb(var(--current))' : 'rgb(var(--conflict))'
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={SPRING}
      className="mt-2 shrink-0 rounded-2xl bg-white/[0.06] p-3 ring-1 ring-white/10" role="status" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold">
          <span style={{ color: tone }}>●</span> {crew.who}{d.tech ? ` · ${titleCase(d.tech)}` : ''} sent to {where}
        </p>
        <p className="text-[11px] text-white/50">Only a hands-on fix clears this · about 2 hours in real life, fast-forwarded to {Math.round(d.ms / 1000)} s</p>
      </div>
      <svg viewBox="0 0 600 34" className="mt-2 h-8 w-full" aria-hidden="true">
        <line x1="20" y1="22" x2="580" y2="22" stroke="rgb(255 255 255 / 0.15)" strokeWidth="4" strokeLinecap="round" />
        <motion.line x1="20" y1="22" y2="22" stroke={tone} strokeWidth="4" strokeLinecap="round"
          initial={{ x2: 20 + 560 * go.from }} animate={{ x2: 580 }} transition={{ duration: go.left, ease: EASE }} />
        <text x="20" y="10" className="fill-white/50 text-[9px]">Depot · {view.pop.label.replace(' POP', '')}</text>
        <text x="580" y="10" textAnchor="end" className="fill-white/70 text-[9px]">{crew.to}</text>
        <motion.g initial={{ x: 560 * go.from }} animate={{ x: 560 }} transition={{ duration: go.left, ease: EASE }}><Van x={20} y={20} color={tone} /></motion.g>
      </svg>
      <ol className="mt-2 grid grid-cols-4 gap-1.5">
        {stages.map(([k, label], i) => (
          <li key={k} className={`rounded-lg px-2 py-1 text-[10.5px] ${i < at ? 'bg-white/10 text-white/80' : i === at ? 'text-ink' : 'bg-white/[0.03] text-white/35'}`}
            style={i === at ? { background: tone } : undefined}>
            {i < at ? '✓ ' : ''}{k === 'done' && d.stage === 'failed' ? 'Still failing · retrying' : label}
          </li>
        ))}
      </ol>
    </motion.div>
  )
}

// ---------------------------------------------------------------- the network canvas

type P = { x: number; y: number }
type Pos = { core: P[]; pop: P; olt: Record<string, P>; spl: Record<string, P>; home: Record<string, P>; label: Record<string, P> }

/** The network as the container allows: left to right when there's room, top to bottom when narrow. Never cut.
 *  fit: scaled to fill the container's height as well, so it never scrolls (the customer's own line). */
export const Canvas = memo(function Canvas({ view, focus, dispatch, privateTo, fit = false }: { view: NonNullable<LabView['network']>; focus: string | null
  dispatch?: Dispatch | null; privateTo?: string | null; fit?: boolean }) {
  // privateTo: drawn on a customer's own screen, so every other home is anonymous (no name, no readings)
  const mine = (h: LabHome) => !privateTo || h.customer === privateTo
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 720, h: 0 })
  useEffect(() => {
    const el = box.current
    if (!el) return
    // rounded to 8 px, so a scrollbar or a one-pixel reflow doesn't re-lay out (and visibly jump) the whole drawing
    const ro = new ResizeObserver(([e]) => {
      const w = Math.max(300, Math.floor(e.contentRect.width / 8) * 8), h = Math.floor(e.contentRect.height / 8) * 8
      setSize((s) => s.w === w && s.h === h ? s : { w, h })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const W = Math.min(size.w, 860)  // wider than this, the network turns into one long thin strip
  const STEP = 30, HOME = 14
  const blocks = view.splitters.map((s) => ({ s, homes: view.homes.filter((h) => h.splitter === s.id) }))
  const cores = view.links

  // ---- positions
  const place = (wide: boolean): { pos: Pos; H: number } => {
  const pos: Pos = { core: [], pop: { x: 0, y: 0 }, olt: {}, spl: {}, home: {}, label: {} }
  let H: number
  if (wide) {
    const X = { core: W * 0.08, pop: W * 0.27, olt: W * 0.46, spl: W * 0.62, home: W * 0.68 }
    const cols = Math.max(3, Math.floor((W - X.home - 24) / STEP))
    let y = 26
    for (const b of blocks) {
      const rows = Math.ceil(b.homes.length / cols)
      const h = rows * STEP + 30
      pos.label[b.s.id] = { x: X.home, y: y + 10 }
      b.homes.forEach((hm, i) => { pos.home[hm.id] = { x: X.home + 10 + (i % cols) * STEP, y: y + 32 + Math.floor(i / cols) * STEP } })
      pos.spl[b.s.id] = { x: X.spl, y: y + h / 2 + 6 }
      y += h + 26
    }
    H = Math.max(240, y)
    pos.pop = { x: X.pop, y: H / 2 }
    cores.forEach((_, i) => { pos.core[i] = { x: X.core, y: H / 2 + (i - (cores.length - 1) / 2) * 110 } })
    for (const o of view.olts) {
      const ys = view.splitters.filter((s) => s.olt === o.id).map((s) => pos.spl[s.id].y)
      pos.olt[o.id] = { x: X.olt, y: ys.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : H / 2 }
    }
  } else {
    const cols = Math.max(4, Math.floor((W - 30) / STEP))
    cores.forEach((_, i) => { pos.core[i] = { x: W * (i + 1) / (cores.length + 1), y: 34 } })
    pos.pop = { x: W / 2, y: 132 }
    view.olts.forEach((o, i) => { pos.olt[o.id] = { x: W * (i + 1) / (view.olts.length + 1), y: 236 } })
    let y = 318
    for (const b of blocks) {
      pos.spl[b.s.id] = { x: pos.olt[b.s.olt]?.x ?? W / 2, y }
      pos.label[b.s.id] = { x: 16, y: y + 34 }
      const rows = Math.ceil(b.homes.length / cols)
      const left = (W - (Math.min(cols, b.homes.length) - 1) * STEP) / 2
      b.homes.forEach((hm, i) => { pos.home[hm.id] = { x: left + (i % cols) * STEP, y: y + 58 + Math.floor(i / cols) * STEP } })
      y += 58 + rows * STEP + 30
    }
    H = y
  }
  return { pos, H }
  }
  // fitted: whichever orientation ends up larger in the box; otherwise left to right once there's room
  let wide = W >= 620, laid = place(wide)
  if (fit && size.h > 0 && W >= 520) {
    const other = place(!wide), scale = (H: number) => Math.min(size.w / W, size.h / H)
    if (scale(other.H) > scale(laid.H) * 1.05) { wide = !wide; laid = other }
  }
  const { pos, H } = laid
  const curve = (a: P, b: P) => wide
    ? `M${a.x} ${a.y} C${(a.x + b.x) / 2} ${a.y}, ${(a.x + b.x) / 2} ${b.y}, ${b.x} ${b.y}`
    : `M${a.x} ${a.y} C${a.x} ${(a.y + b.y) / 2}, ${b.x} ${(a.y + b.y) / 2}, ${b.x} ${b.y}`
  const mid = (a: P, b: P) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })

  // Plain functions, not components defined in here: a component created inside render is a new type every render,
  // so React would rebuild these elements ~10x a second (query glow, dispatch) and restart their CSS animations
  const cut = (p: P) => (
    <g><circle cx={p.x} cy={p.y} r="11" fill="rgb(var(--danger) / 0.18)" className="lab-alarm" /><circle cx={p.x} cy={p.y} r="9" fill="rgb(var(--ink))" stroke={C.bad} strokeWidth="1.5" />
      <path d={`M${p.x - 3.5} ${p.y - 3.5}l7 7M${p.x + 3.5} ${p.y - 3.5}l-7 7`} stroke={C.bad} strokeWidth="2" strokeLinecap="round" /></g>
  )
  const wire = (a: P, b: P, state: 'up' | 'cut' | 'standby' | 'hot', w = 2) => {
    const d = curve(a, b)
    const color = state === 'cut' ? C.bad : state === 'standby' ? C.idle : state === 'hot' ? C.warn : C.ok
    return (
      <g>
        <path d={d} fill="none" stroke={color} strokeOpacity={state === 'standby' ? 1 : 0.25} strokeWidth={w + 3} strokeDasharray={state === 'standby' ? '2 6' : undefined} />
        {state !== 'standby' && state !== 'cut' && <path d={d} fill="none" stroke={color} strokeWidth={w} className={state === 'hot' ? 'lab-flow-slow' : 'lab-flow'} />}
        {state === 'cut' && <path d={d} fill="none" stroke={color} strokeWidth={w} strokeDasharray="5 5" />}
      </g>
    )
  }

  return (
    <div ref={box} className={fit ? 'h-full w-full' : 'w-full'}>
      <svg viewBox={`0 0 ${W} ${H}`} width={fit ? '100%' : W} height={fit ? '100%' : H} preserveAspectRatio="xMidYMid meet"
        className={fit ? 'block' : 'mx-auto block max-w-full'} role="img" aria-label={`Network for ${view.pop.label}`}>
        <defs>
        </defs>
        {cores.map((l, i) => (
          <g key={l.id}>{wire(pos.pop, pos.core[i], l.link === 'cut' ? 'cut' : !l.active ? 'standby' : 'up', 3)}
            {l.link === 'cut' && cut(mid(pos.pop, pos.core[i]))}</g>
        ))}
        {view.olts.map((o) => {
          const hot = o.flow_gbps > 0 && o.free_peak_mbps < 300
          return <g key={o.id}>{wire(pos.olt[o.id], pos.pop, o.flow_gbps <= 0 ? 'cut' : hot ? 'hot' : 'up', hot ? 4 : 2.5)}</g>
        })}
        {view.splitters.map((s) => pos.olt[s.olt] && (
          <g key={s.id}>{wire(pos.spl[s.id], pos.olt[s.olt], s.feeder === 'cut' ? 'cut' : 'up')}
            {s.feeder === 'cut' && cut(mid(pos.spl[s.id], pos.olt[s.olt]))}</g>
        ))}
        {blocks.map(({ s, homes }) => (
          <g key={`h-${s.id}`}>
            <text x={pos.label[s.id].x} y={pos.label[s.id].y} className="fill-white/50 text-[10px] uppercase tracking-[0.14em]">{s.label}</text>
            {homes.map((h) => {
              const p = pos.home[h.id], color = HOME_COLOR[h.state], me = !!h.customer && h.customer === focus, bad = h.state !== 'ok'
              const sz = me ? 18 : HOME
              return (
                <g key={h.id}>
                  <path d={curve(pos.spl[s.id], p)} fill="none" stroke={h.state === 'dark' || h.state === 'flapping' || h.state === 'reported' ? C.bad : 'rgb(255 255 255 / 0.08)'} strokeWidth="1" />
                  {bad && <circle cx={p.x} cy={p.y} r="8" fill={color} opacity="0.5" className="lab-alarm" />}
                  <rect x={p.x - sz / 2} y={p.y - sz / 2} width={sz} height={sz} rx="4" fill={color} fillOpacity={bad ? 0.95 : 0.85}
                    stroke={me ? 'white' : 'none'} strokeWidth="2">
                    <title>{mine(h) ? `${h.name} · port ${h.port} · ${HOME_WORD[h.state]}${h.rx != null ? ` · ${h.rx} dBm` : ''}` : `a neighbour's home · ${HOME_WORD[h.state]}`}</title>
                  </rect>
                  {h.customer && mine(h) && <text x={p.x} y={p.y + (me ? 22 : 19)} textAnchor="middle" className={`text-[9.5px] font-semibold ${me ? 'fill-white' : 'fill-white/70'}`}>{h.name.split(' ')[0]}</text>}
                </g>
              )
            })}
          </g>
        ))}
        {cores.map((l, i) => (
          <g key={`c-${l.id}`}>
            <circle cx={pos.core[i].x} cy={pos.core[i].y} r="26" fill={l.status === 'up' ? C.ok : C.bad} opacity="0.12" />
            <circle cx={pos.core[i].x} cy={pos.core[i].y} r="20" fill="rgb(var(--ink))" stroke={l.status === 'up' ? C.ok : C.bad} strokeWidth="2" />
            <text x={pos.core[i].x} y={pos.core[i].y + 4} textAnchor="middle" className="fill-white text-[9.5px] font-semibold">CORE</text>
            <text x={pos.core[i].x} y={pos.core[i].y + 34} textAnchor="middle" className="fill-white/70 text-[10.5px]">
              {l.label.replace('Core ', '')} · {l.link === 'cut' ? 'cut' : l.active ? l.role : 'standby'}</text>
          </g>
        ))}
        <g>
          <circle cx={pos.pop.x} cy={pos.pop.y} r="32" fill={C.ok} opacity="0.12" />
          <circle cx={pos.pop.x} cy={pos.pop.y} r="25" fill="rgb(var(--ink))" stroke={C.ok} strokeWidth="2.5" />
          <text x={pos.pop.x} y={pos.pop.y + 4} textAnchor="middle" className="fill-white text-[11px] font-semibold">HUB</text>
          <text x={pos.pop.x} y={pos.pop.y + 40} textAnchor="middle" className="fill-white/80 text-[11px]">{view.pop.label.replace(' POP', '')} hub</text>
        </g>
        {view.olts.map((o) => {
          const p = pos.olt[o.id]
          return (
            <g key={`o-${o.id}`}>
              <rect x={p.x - 28} y={p.y - 15} width="56" height="30" rx="9" fill="rgb(var(--ink))" stroke={o.status !== 'up' ? C.bad : o.free_peak_mbps < 300 && o.flow_gbps > 0 ? C.warn : C.ok} strokeWidth="2" />
              <text x={p.x} y={p.y + 4} textAnchor="middle" className="fill-white text-[9.5px] font-semibold">EXCH</text>
              <text x={p.x} y={p.y + 29} textAnchor="middle" className="fill-white/70 text-[10.5px]">{o.label.replace(' OLT', '')}</text>
              <text x={p.x} y={p.y + 42} textAnchor="middle" className="fill-white/40 text-[9.5px] num">{o.uplink_gbps} Gbps uplink</text>
            </g>
          )
        })}
        {view.splitters.map((s) => {
          const p = pos.spl[s.id]
          return <path key={`s-${s.id}`} d={`M${p.x} ${p.y - 11} l11 11 l-11 11 l-11 -11z`} fill="rgb(var(--ink))" stroke={s.feeder === 'cut' ? C.bad : C.ok} strokeWidth="2">
            <title>{s.label}</title></path>
        })}
        {dispatch && (() => {  // the crew: from the hub out to the place only hands can fix
          const home = view.homes.find((h) => h.customer === dispatch.customer)
          const ci = Math.max(0, cores.findIndex((l) => l.link === 'cut'))
          const goal = dispatch.action === 'dispatch_technician_home' && home ? pos.home[home.id]
            : dispatch.action === 'dispatch_cable_crew' && home && pos.olt[view.splitters.find((x) => x.id === home.splitter)?.olt ?? '']
              ? mid(pos.spl[home.splitter], pos.olt[view.splitters.find((x) => x.id === home.splitter)!.olt])
              : pos.core[ci] ? mid(pos.pop, pos.core[ci]) : pos.pop
          if (!goal) return null
          const from = { x: pos.pop.x, y: pos.pop.y + 34 }
          const go = drive(dispatch)
          const at = { x: from.x + (goal.x - from.x) * go.from, y: from.y + (goal.y - from.y) * go.from }
          const tone = dispatch.stage === 'failed' ? C.bad : dispatch.stage === 'done' ? C.ok : C.warn
          return (
            <g pointerEvents="none">
              <line x1={from.x} y1={from.y} x2={goal.x} y2={goal.y} stroke={tone} strokeOpacity="0.35" strokeWidth="1.5" strokeDasharray="3 5" />
              {dispatch.stage === 'onsite' && <circle cx={goal.x} cy={goal.y} r="16" fill="none" stroke={tone} strokeWidth="2" className="lab-alarm" />}
              {dispatch.stage === 'done' && <g><circle cx={goal.x} cy={goal.y} r="13" fill={C.ok} /><path d={`M${goal.x - 5} ${goal.y}l3.5 3.5 6.5-7`} stroke="white" strokeWidth="2.2" fill="none" strokeLinecap="round" /></g>}
              <motion.g initial={{ x: at.x, y: at.y }} animate={{ x: goal.x, y: goal.y }} transition={{ duration: go.left, ease: EASE }}>
                <Van x={0} y={-16} color={tone} /></motion.g>
            </g>
          )
        })()}
        {/* what live Cypher just read: the resolver measuring this line, node by node (its own layer, see TouchLayer) */}
        <TouchLayer grow={14} marks={[
          ...cores.map((l, i) => ({ id: l.id, keys: [l.id], x: pos.core[i].x, y: pos.core[i].y, r: 14 })),
          { id: view.pop.id, keys: [view.pop.id], x: pos.pop.x, y: pos.pop.y, r: 14 },
          ...view.olts.filter((o) => pos.olt[o.id]).map((o) => ({ id: o.id, keys: [o.id], x: pos.olt[o.id].x, y: pos.olt[o.id].y, r: 14 })),
          ...view.splitters.filter((x) => pos.spl[x.id]).map((x) => ({ id: x.id, keys: [x.id], x: pos.spl[x.id].x, y: pos.spl[x.id].y, r: 14 })),
          ...view.homes.filter((h) => pos.home[h.id]).map((h) => ({ id: h.id, keys: [h.id, h.customer, h.box, h.account], x: pos.home[h.id].x, y: pos.home[h.id].y, r: 14 })),
        ]} />
      </svg>
    </div>
  )
})

export function EveningChart({ o }: { o: LabOlt }) {
  const hot = o.free_peak_mbps < 300
  return (
    <div className="rounded-xl bg-white/[0.04] p-3">
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="font-medium text-white/80">{o.label.replace(' OLT', '')} exchange · load through the day</span>
        <span className={`num ${o.flow_gbps <= 0 ? 'text-danger' : hot ? 'text-conflict' : 'text-signal'}`}>
          {o.flow_gbps <= 0 ? 'no route' : `${o.free_peak_mbps.toLocaleString()} Mbps free at 9 pm`}
        </span>
      </div>
      <div className="relative mt-2 flex h-14 items-end gap-[3px]">
        <div className="pointer-events-none absolute inset-x-0 top-0 border-t border-dashed border-white/25" />
        <span className="pointer-events-none absolute right-0 -top-3.5 text-[9px] text-white/35">full</span>
        {o.curve.map((u, h) => (
          <motion.div key={h} title={`${h}:00 · ${Math.round(u * 100)}% used`} initial={false} animate={{ height: `${Math.max(4, u * 100)}%` }} transition={SPRING}
            className="flex-1 rounded-t-sm" style={{ background: u >= 0.95 ? C.bad : u >= 0.8 ? C.warn : C.ok, opacity: h === 21 ? 1 : 0.65 }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[9px] text-white/35 num"><span>00</span><span>06</span><span>12</span><span>18</span><span>21</span><span>23</span></div>
    </div>
  )
}

// ---------------------------------------------------------------- the resolver trace

const KIND: Record<LabStep['kind'], { label: string; icon: JSX.Element }> = {
  memory: { label: 'Shared memory', icon: <Database className="h-3.5 w-3.5" /> },
  check: { label: 'Measure', icon: <Pulse className="h-3.5 w-3.5" /> },
  think: { label: 'Reason', icon: <Sparkle className="h-3.5 w-3.5" /> },
  act: { label: 'Act', icon: <PresetIcon name="route" className="h-3.5 w-3.5" /> },
  wait: { label: 'Field job', icon: <Pulse className="h-3.5 w-3.5" /> },
  verify: { label: 'Verify', icon: <Check className="h-3.5 w-3.5" /> },
}
const TONE: Record<LabStep['status'], string> = {
  ok: 'bg-current-tint text-current', bad: 'bg-danger-tint text-danger', info: 'bg-signal-tint text-signal-deep', pending: 'bg-conflict-tint text-conflict',
}

const ACTION_LABEL = Object.fromEntries(ACTIONS)
const HOPS: Record<number, string> = { 0: 'same cabinet', 2: 'same exchange', 4: 'same hub' }
export const ProcBadge = () => <span className="chip bg-signal-tint !py-0.5 text-[10px] text-signal-deep"><Database className="h-3 w-3" />procedural memory</span>

/** A past procedure from the graph: the path it took, how often it worked, and how close the cases were. */
export function ProcedureCard({ p }: { p: LabProcedure }) {
  const total = p.successes + p.failures
  const rate = p.rate ?? (total ? p.successes / total : 0)
  return (
    <div className="mt-2 rounded-xl bg-sunk/60 p-2.5 text-xs">
      {p.steps && p.steps.length > 0 && (
        <p className="flex flex-wrap items-center gap-1" aria-label="Past path">
          {p.steps.map((x, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span aria-hidden className="text-ink-3">→</span>}
              <span className={`rounded-full px-2 py-0.5 text-[10.5px] ${i === p.steps!.length - 1 ? 'bg-ink font-medium text-paper' : 'bg-surface text-ink-2 hairline'}`}>{ACTION_LABEL[x] ?? x.replace(/_/g, ' ')}</span>
            </span>
          ))}
        </p>
      )}
      <div className="mt-2 flex items-center gap-2">
        <div className="flex h-1.5 flex-1 overflow-hidden rounded-full bg-danger/25" role="meter" aria-label="Success rate" aria-valuenow={Math.round(rate * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-current" style={{ width: `${rate * 100}%` }} />
        </div>
        <span className="num shrink-0 text-[10.5px] text-ink-2">{Math.round(rate * 100)}% · {p.successes} worked, {p.failures} failed</span>
      </div>
      {(p.nearest_hops != null || (p.places?.length ?? 0) > 0) && (
        <p className="mt-1.5 text-[10.5px] text-ink-3">
          {p.nearest_hops != null && <>Nearest case: <span className="font-medium text-ink-2">{HOPS[p.nearest_hops] ?? `${p.nearest_hops} hops away`}</span></>}
          {p.places?.length ? <>{p.nearest_hops != null ? ' · ' : ''}seen at {p.places.slice(0, 4).map((x) => `${x.at.replace(/^e:/, '')}${x.times > 1 ? ` ×${x.times}` : ''}`).join(', ')}</> : null}
        </p>
      )}
    </div>
  )
}

function Step({ s, live }: { s: LabStep; live: boolean }) {
  const [open, setOpen] = useState(false)
  const pending = s.status === 'pending' && live
  const more = s.cypher.length > 0 || s.data.facts || s.data.hypotheses || s.data.curve
  return (
    <motion.li layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={SPRING} className="relative pl-9">
      <span className={`absolute left-0 top-0.5 flex h-6 w-6 items-center justify-center rounded-full ${TONE[s.status]} ${pending ? 'animate-breathe' : ''}`}>{KIND[s.kind].icon}</span>
      <button type="button" disabled={!more} onClick={() => setOpen((o) => !o)} className="block w-full text-left disabled:cursor-default">
        <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-ink-3">{KIND[s.kind].label}{s.kind === 'think' && s.data.by ? ` · ${s.data.by === 'rules' ? 'rule engine' : s.data.by.split('/').pop()}` : ''}</p>
        <p className="text-sm font-medium leading-snug text-ink">{s.title}</p>
        {s.detail && <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{s.detail}</p>}
        {s.data.by === 'procedural memory' && <p className="mt-1"><ProcBadge /></p>}
        {s.kind === 'think' && s.data.by && s.data.by !== 'rules' && (
          <p className={`mt-1 text-[11px] ${s.data.agrees ? 'text-current' : 'text-conflict'}`}>{s.data.agrees ? 'Rule engine agrees' : `Rule engine would say: ${String(s.data.rules?.cause).replace(/_/g, ' ')}`}</p>
        )}
        {more && <p className="mt-1 text-[11px] font-medium text-signal-deep">{open ? 'Hide details' : s.cypher.length ? `Show the ${s.cypher.length > 1 ? 'queries' : 'query'}` : 'Show details'}</p>}
      </button>
      {s.data.procedure && <ProcedureCard p={s.data.procedure as LabProcedure} />}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-2 space-y-2">
              {s.data.facts && <ul className="space-y-1">{(s.data.facts as { id: string; text: string; by: string }[]).map((f) => (
                <li key={f.id} className="flex items-baseline justify-between gap-2 rounded-lg bg-sunk/70 px-2.5 py-1.5 text-xs"><span className="text-ink">{f.text}</span><span className="shrink-0 text-[10px] text-ink-3">by {f.by}</span></li>))}</ul>}
              {s.data.hypotheses && <ul className="space-y-1">{(s.data.hypotheses as { label: string; likely: boolean; evidence: string }[]).map((h) => (
                <li key={h.label} className={`flex items-baseline justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs ${h.likely ? 'bg-danger-tint text-ink' : 'bg-sunk/60 text-ink-3'}`}>
                  <span className={h.likely ? 'font-medium' : 'line-through decoration-ink-3/40'}>{h.label}</span><span className="text-[10.5px]">{h.evidence}</span></li>))}</ul>}
              {s.cypher.map((q, i) => (
                <div key={i} className="rounded-lg bg-ink p-2.5"><p className="flex justify-between text-[10px] text-white/50"><span>{q.name}</span><span className="num">{q.ms} ms · {q.rows} rows</span></p>
                  <pre className="scroll-thin mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10.5px] leading-relaxed text-white/85">{q.query}</pre></div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

export function Trace({ run, fill = false, compact = false }: { run?: LabRun; fill?: boolean; compact?: boolean }) {
  // compact: inside the customer's ticket card, which already names them and the ticket
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { const el = box.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }) }, [run?.steps.length])
  if (!run) return <p className="rounded-2xl bg-sunk/60 p-4 text-sm text-ink-2">Break something on the left. The customer will complain the way a real person would, intake hands the ticket over, and the resolver's work shows up here, step by step.</p>
  const live = run.status === 'running'
  return (
    <div className={fill ? 'flex h-full min-h-0 flex-col' : ''}>
      <div className="flex flex-wrap items-center gap-2">
        {!compact && <h3 className="font-display text-lg font-semibold">{run.name}</h3>}
        {run.ticket && !compact && <span className="chip bg-sunk font-mono text-ink-2">{run.ticket}</span>}
        <span className={`chip ${live ? 'bg-conflict-tint text-conflict' : run.status === 'resolved' ? 'bg-current-tint text-current' : 'bg-danger-tint text-danger'}`}>
          {live && <i className="h-1.5 w-1.5 rounded-full bg-conflict animate-breathe" />}{live ? 'working' : run.status}</span>
        {run.diagnosis?.by === 'procedural memory' && <ProcBadge />}
      </div>
      {run.said && <p className="mt-1 text-xs text-ink-3">Said: <span className="italic text-ink-2">“{run.said}”</span>{run.symptoms.length > 0 && <> · heard: {run.symptoms.join(', ')}</>}</p>}
      <div ref={box} className={`scroll-thin overflow-y-auto pr-1 ${compact ? 'mt-3' : 'mt-4'} ${fill ? 'min-h-0 flex-1' : compact ? 'max-h-[320px]' : 'max-h-[540px]'}`}>
        <ol className="relative space-y-4 before:absolute before:left-3 before:top-2 before:h-[calc(100%-1rem)] before:w-px before:bg-line/10">
          {run.steps.map((s) => <Step key={s.i} s={s} live={live && s.i === run.steps.length - 1} />)}
          {live && <li className="pl-9 text-xs text-ink-3 animate-breathe">Working…</li>}
        </ol>
        {run.verdict && !compact && (
          <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={SPRING}
            className={`mt-5 rounded-2xl p-4 ${run.verdict.correct && run.verdict.fixed ? 'bg-current-tint' : 'bg-danger-tint'}`}>
            <p className="eyebrow">Graded against the hidden truth</p>
            <div className="mt-2 grid grid-cols-2 gap-3 text-sm">
              <div><p className="text-[11px] text-ink-3">What was really broken</p><p className="font-medium">{run.verdict.truth_label}</p></div>
              <div><p className="text-[11px] text-ink-3">What the resolver concluded</p><p className="font-medium capitalize">{(run.verdict.said ?? '—').replace(/_/g, ' ')}</p></div>
            </div>
            <p className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className={`chip ${run.verdict.correct ? 'bg-current text-white' : 'bg-danger text-white'}`}>{run.verdict.correct ? 'Right diagnosis' : 'Wrong diagnosis'}</span>
              <span className={`chip ${run.verdict.fixed ? 'bg-current text-white' : 'bg-danger text-white'}`}>{run.verdict.fixed ? 'Fixed, proven by re-measuring' : 'Not fixed'}</span>
              <span className="chip bg-surface text-ink-2">{run.actions.length} action{run.actions.length === 1 ? '' : 's'}</span>
            </p>
          </motion.div>
        )}
      </div>
    </div>
  )
}

export function Phone({ run }: { run?: LabRun }) {
  const msgs: (LabMessage & { me?: boolean })[] = run ? [...(run.said ? [{ text: run.said, at: run.started_at - 1, me: true }] : []), ...run.messages] : []
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { const el = box.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }) }, [msgs.length])
  return (
    <div className="mx-auto w-full max-w-[340px] rounded-[2.2rem] bg-ink p-2.5 shadow-lift">
      <div className="rounded-[1.8rem] bg-paper">
        <div className="flex items-center gap-2 border-b border-line/[0.06] px-4 py-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ink text-[10px] font-semibold text-paper">RS</span>
          <div><p className="text-xs font-semibold">Support · resolver</p><p className="text-[10px] text-ink-3">{run ? `chatting with ${run.name.split(' ')[0]}` : 'what the customer sees'}</p></div>
        </div>
        <div ref={box} className="scroll-thin h-[300px] space-y-2 overflow-y-auto px-3 py-3">
          {!msgs.length && <p className="pt-24 text-center text-xs text-ink-3">Messages to the customer appear here, in plain words.</p>}
          {msgs.map((m, i) => (
            <motion.div key={`${m.at}-${i}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={SPRING} className={`flex ${m.me ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-[12.5px] leading-snug ${m.me ? 'rounded-br-md bg-ink text-paper' : 'rounded-bl-md bg-signal-tint text-ink'}`}>
                {splitGuides(m.text).text}
                {splitGuides(m.text).guides.map((g) => <div key={g} className="mt-2"><GuideCard id={g} compact /></div>)}
                {m.image?.src && <figure className="mt-2 overflow-hidden rounded-xl bg-surface"><img src={m.image.src} alt={m.image.title} className="h-28 w-full object-cover" loading="lazy" />
                  <figcaption className="px-2 py-1 text-[10px] text-ink-3">Picture: {m.image.title} (Wikipedia)</figcaption></figure>}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- the page

/** Lab state plus live runs, kept current from the event stream. One socket; other parts of the page can subscribe. */
export function useLab(tenant: string, focus?: string | null) {
  const [view, setView] = useState<LabView>()
  const [runs, setRuns] = useState<Record<string, LabRun>>({})
  const [picked, setPicked] = useState<string>()
  const [error, setError] = useState<string>()
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const listeners = useRef(new Set<(e: RelayEvent) => void>())
  const subscribe = useCallback((fn: (e: RelayEvent) => void) => { listeners.current.add(fn); return () => { listeners.current.delete(fn) } }, [])

  const load = useCallback(async () => {
    try {
      const v = await api.lab(tenant, focus ?? undefined)
      setView(v); setError(undefined)
      setRuns((rs) => {
        const next = { ...rs }
        for (const r of v.runs) if (!next[r.id] || next[r.id].steps.length <= r.steps.length) next[r.id] = r
        return next
      })
    } catch { setError("Couldn't load the lab. Is the API running?") }
  }, [tenant, focus])
  useEffect(() => { load() }, [load])
  const soon = useCallback(() => { clearTimeout(timer.current); timer.current = setTimeout(load, 350) }, [load])
  useEffect(() => () => clearTimeout(timer.current), [])

  const status = useRelayStream(tenant, (e) => {
    listeners.current.forEach((fn) => fn(e))
    if (e.type === 'lab_step') {
      const { run, step, message } = e.data
      setRuns((rs) => {
        const r = rs[run]
        if (!r) { soon(); return rs }
        if (step && r.steps.some((x) => x.i === step.i)) return rs
        return { ...rs, [run]: { ...r, steps: step ? [...r.steps, step] : r.steps, messages: message ? [...r.messages, message] : r.messages } }
      })
      if (step && (step.kind === 'act' || step.kind === 'verify' || step.kind === 'wait')) soon()
    } else if (e.type === 'lab_run') {
      if (e.data.status === 'running') setPicked(e.data.run)
      soon()
    } else if (e.type === 'lab_state') soon()
    else if (e.type === 'fact_created' && ['lives_in', 'address'].includes(e.data.predicate)) soon()  // a new line in the network
  }, load)

  const ordered = useMemo(() => Object.values(runs).sort((a, b) => b.started_at - a.started_at), [runs])
  const run = picked && runs[picked] ? runs[picked] : ordered[0]
  return { view, runs, setRuns, ordered, run, picked, setPicked, load, status, error, setError, subscribe }
}

export default function LabPage() {
  const { tenant } = useTenant()
  const [focus, setFocus] = useState<string>()
  const { view, setRuns, ordered, run, setPicked, load, status, error, setError, subscribe } = useLab(tenant, focus)
  const [busy, setBusy] = useState<string>()
  const [waiting, setWaiting] = useState<string>()
  const [manual, setManual] = useState<{ action: string; result?: LabManual; busy?: boolean }>({ action: ACTIONS[0][0] })
  useEffect(() => { if (!focus && view?.focus) setFocus(view.focus) }, [focus, view?.focus])
  useEffect(() => subscribe((e) => { if (e.type === 'lab_run' && e.data.status === 'running') setWaiting(undefined) }), [subscribe])
  // talking as a customer moved to the home page; an old ?talk=1 link lands there
  const [params, setParams] = useSearchParams()
  const talk = params.get('talk') === '1'
  // map view: the whole region zoomed out; a hub opens its customers back here in the lab
  const map = params.get('view') === 'map'
  const setMap = (on: boolean) => setParams(on ? { view: 'map' } : {}, { replace: false })
  const inCity = (city: string) => (view?.customers ?? []).filter((c) => c.city.toLowerCase() === city.toLowerCase())
  const openHub = (city: string) => { const c = inCity(city)[0]; if (c) { setFocus(c.key); setManual((m) => ({ action: m.action })) } setMap(false) }
  const [pick, setPick] = useState<string>()
  const [side, setSide] = useState<'trace' | 'phone'>('trace')

  const custs = view?.customers ?? []
  const me = custs.find((c) => c.key === focus)
  const s = view?.score

  const inject = async (p: LabPreset | 'random') => {
    const key = p === 'random' ? 'random' : p.key
    setBusy(key); setError(undefined)
    try {
      const r = await api.labInject(tenant, { preset: key, customer: p === 'random' ? undefined : focus, blind: p === 'random' })
      setWaiting(r.customer); setFocus(r.customer)
      await load()
    } catch (e) { setError(e instanceof Error ? e.message.replace(/^.*"detail":"?|"?}$/g, '') : 'That did not go through.') } finally { setBusy(undefined) }
  }
  const heal = async () => {
    setBusy('heal')
    try { await api.labReset(tenant); setRuns({}); setPicked(undefined); setManual({ action: manual.action }); await load() }
    catch { setError("Couldn't reset the lab. Is the API running?") } finally { setBusy(undefined) }
  }
  const investigate = async () => { if (!focus) return; setBusy('investigate'); try { await api.labInvestigate(tenant, focus) } catch { setError('The resolver is already on this customer.') } finally { setBusy(undefined) } }
  const tryFix = async () => {
    if (!focus) return
    setManual((m) => ({ ...m, busy: true, result: undefined }))
    try { const r = await api.labAction(tenant, manual.action, focus); setManual((m) => ({ ...m, busy: false, result: r })); load() } catch { setManual((m) => ({ ...m, busy: false })) }
  }

  const tiles: [string, string | number, string?][] = [
    ['Faults injected', s?.injected ?? '–'], ['Right diagnosis', s ? `${s.correct}/${s.investigated}` : '–', 'text-current'],
    ['Fixed & proven', s ? `${s.fixed}/${s.investigated}` : '–', 'text-current'], ['First-try fixes', s?.first_try ?? '–'],
    ['Avg time to fix', s?.avg_seconds != null ? `${s.avg_seconds}s` : '–'],
  ]

  // the one story a judge should follow: break -> customer complains -> resolver works -> verified
  const focusRun = ordered.find((r) => r.customer === focus)
  const broken = !!view?.faults.some((f) => f.active && f.customer === focus)
  const stage = focusRun?.verdict || (focusRun && focusRun.status !== 'running') ? 3 : focusRun ? 2 : broken || waiting ? 1 : 0
  const STEPS = [
    ['Break it', 'Pick a fault below. The truth goes into a graph the resolver cannot read.'],
    ['Customer complains', `${me?.name.split(' ')[0] ?? 'The customer'} messages ${BOT}; the complaint lands in shared memory.`],
    ['Resolver works', 'It reads what intake learned, measures the line with Cypher, picks an action.'],
    ['Verified & graded', focusRun?.verdict ? `${focusRun.verdict.correct ? 'Right diagnosis' : 'Wrong diagnosis'} · ${focusRun.verdict.fixed ? 'fixed and proven' : 'not fixed'}` : 'Only "fixed" when the readings prove it, then graded against the hidden truth.'],
  ]
  const chosen = view?.presets.find((p) => p.key === pick)
  const crew = useDispatch(focusRun ?? run)

  // talking as a customer happens on the home page now; the rest of the query (?customer=...) goes with it
  if (talk) { const q = new URLSearchParams(params); q.delete('talk'); const s = q.toString(); return <Navigate to={s ? `/?${s}` : '/'} replace /> }

  // One screen on a desktop: the page never scrolls, each column scrolls inside itself. Smaller screens stack.
  return (
    <div className="flex min-h-[100dvh] flex-col xl:h-[100dvh]">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link to="/console"><Wordmark sub="Network" /></Link>
        <ConsoleNav />
        <div className="flex items-center gap-2">
          <span className={`chip ${status === 'live' ? 'bg-current-tint text-current' : 'bg-conflict-tint text-conflict'}`}>
            <i className={`h-1.5 w-1.5 rounded-full ${status === 'live' ? 'bg-current animate-breathe' : 'bg-conflict'}`} />{status === 'live' ? 'Live' : 'Reconnecting'} · mem:{tenant}</span>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pb-3 sm:px-6">
        <div role="tablist" aria-label="Network view" className="inline-flex rounded-full bg-surface p-1 hairline">
          {([[false, 'One line · lab'], [true, 'Whole region · map']] as const).map(([m, label]) => (
            <button key={label} role="tab" aria-selected={map === m} onClick={() => setMap(m)}
              className={`rounded-full px-3.5 py-1.5 text-xs transition duration-300 ease-spring ${map === m ? 'bg-ink font-medium text-paper' : 'text-ink-2 hover:bg-sunk'}`}>{label}</button>
          ))}
        </div>
        {!map && (
          <>
            <h1 className="font-display text-xl font-semibold tracking-[-0.01em]" title="The last mile lives in FalkorDB. A fault's truth goes into a separate graph the resolver can't read; it measures with Cypher and algo.maxFlow, acts, and only calls it fixed when the readings prove it.">
              Break the network. Watch it get fixed.</h1>
            <dl className="ml-auto flex flex-wrap gap-1.5">
              {tiles.map(([k, v, cls]) => (
                <div key={k} className="flex items-baseline gap-1.5 rounded-full bg-surface px-3 py-1 hairline">
                  <dd className={`font-display text-sm font-semibold num ${cls ?? ''}`}>{v}</dd><dt className="text-[10.5px] text-ink-3">{k}</dt>
                </div>
              ))}
            </dl>
          </>
        )}
      </div>

      {map ? (
        <main className="grid min-h-0 flex-1 gap-4 px-4 pb-4 sm:px-6 xl:grid-cols-[minmax(0,1fr)_400px]" role="tabpanel">
          <div className="min-h-0 xl:overflow-y-auto scroll-thin">
            {error && <p className="mb-4 rounded-xl bg-danger-tint px-4 py-2 text-sm text-danger" role="alert">{error}</p>}
            <NetworkMap tenant={tenant} subscribe={subscribe} onHub={openHub} hubCustomers={(city) => inCity(city).length} />
          </div>
          <aside className="scroll-thin min-h-0 xl:overflow-y-auto"><ShowMe tenant={tenant} kind="network" /></aside>
        </main>
      ) : (
      <main className="flex min-h-0 flex-1 flex-col gap-3 px-4 pb-4 sm:px-6" role="tabpanel">
        <ol className="grid shrink-0 gap-1.5 sm:grid-cols-4" aria-label="What happens">
          {STEPS.map(([t, d], i) => (
            <li key={t} aria-current={i === stage ? 'step' : undefined} title={d}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 transition duration-300 ease-spring ${i === stage ? 'bg-ink text-paper shadow-lift' : i < stage ? 'bg-current-tint text-ink' : 'bg-surface text-ink-3 hairline'}`}>
              <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] num ${i === stage ? 'bg-paper text-ink' : i < stage ? 'bg-current text-white' : 'bg-sunk'}`}>{i < stage ? '✓' : i + 1}</span>
              <span className="min-w-0"><span className="block text-xs font-semibold">{t}</span>
                <span className={`block truncate text-[10.5px] ${i === stage ? 'text-paper/70' : ''}`}>{d}</span></span>
            </li>
          ))}
        </ol>
        {error && <p className="shrink-0 rounded-xl bg-danger-tint px-4 py-2 text-sm text-danger" role="alert">{error}</p>}

        <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[300px_minmax(0,1fr)_380px]">
          {/* faults */}
          <section aria-label="Faults" className="scroll-thin min-h-0 space-y-3 xl:overflow-y-auto xl:pr-1">
            <div className="rounded-2xl bg-surface p-3 hairline">
              <p className="eyebrow">Customer</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {custs.map((c) => (
                  <button key={c.key} onClick={() => { setFocus(c.key); setManual((m) => ({ action: m.action })) }}
                    className={`rounded-full px-3 py-1.5 text-xs font-medium transition duration-300 ease-spring ${c.key === focus ? 'bg-ink text-paper' : 'bg-sunk/70 text-ink-2 hover:bg-sunk'}`}>
                    {c.name.split(' ')[0]} <span className="opacity-60">· {c.city}</span>
                  </button>
                ))}
              </div>
              {me && <p className="mt-2 text-[11px] text-ink-3">{me.area} · {me.pop_label} · {me.uplinks > 1 ? 'hub has a backup link' : 'hub has no backup link'}</p>}
              <div className="mt-3 flex gap-2">
                <button className="btn-primary flex-1 !py-2 text-xs" disabled={!!busy} onClick={() => inject('random')}
                  title="Breaks something random. Even the console hides what it was until the resolver is graded.">
                  <Sparkle className="h-4 w-4" />{busy === 'random' ? 'Breaking…' : 'Blind test'}
                </button>
                <button className="btn-ghost !py-2 text-xs hairline" disabled={!!busy} onClick={heal}>{busy === 'heal' ? 'Healing…' : 'Heal all'}</button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {view?.presets.map((p) => {
                const fits = !!focus && p.customers.includes(focus)
                return (
                  <button key={p.key} onClick={() => setPick(p.key)} aria-pressed={pick === p.key} disabled={!fits}
                    title={fits ? p.blurb : 'Pick a customer whose hub fits this fault'}
                    className={`flex items-center gap-2 rounded-xl p-2 text-left transition duration-300 ease-spring disabled:opacity-40 ${pick === p.key ? 'bg-ink text-paper' : 'bg-surface hairline hover:shadow-soft'}`}>
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${pick === p.key ? 'bg-paper/15' : 'bg-sunk'}`}><PresetIcon name={p.icon} className="h-4 w-4" /></span>
                    <span className="min-w-0"><span className="block text-[11.5px] font-semibold leading-tight">{p.title}</span>
                      <span className={`block text-[10px] ${pick === p.key ? 'text-paper/60' : 'text-ink-3'}`}>{p.layer}</span></span>
                  </button>
                )
              })}
            </div>
            {chosen && (
              <div className="rounded-2xl bg-surface p-3 hairline">
                <h3 className="text-sm font-semibold">{chosen.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-ink-2">{chosen.blurb}</p>
                <p className="mt-1.5 text-xs italic text-ink-3">“{chosen.says}”</p>
                <div className="mt-2.5 flex items-center justify-between gap-2">
                  <span className="text-[10.5px] text-ink-3">Right fix: {chosen.action.toLowerCase()}</span>
                  <button className="btn !bg-danger !px-3 !py-1 text-xs text-white hover:!bg-danger/90" disabled={!focus || !chosen.customers.includes(focus) || !!busy} onClick={() => inject(chosen)}>
                    {busy === chosen.key ? 'Breaking…' : `Break it for ${me?.name.split(' ')[0] ?? 'them'}`}
                  </button>
                </div>
              </div>
            )}
            <details className="rounded-2xl bg-surface p-3 hairline">
              <summary className="cursor-pointer list-none text-sm font-semibold">Operator tools <span className="font-normal text-ink-3">· try a fix yourself</span></summary>
              <p className="mt-2 text-xs text-ink-2">Same network, same check. A wrong fix stays broken, and the readings show it.</p>
              <label htmlFor="lab-action" className="sr-only">Action</label>
              <select id="lab-action" className="field mt-2 !py-2 text-sm" value={manual.action} onChange={(e) => setManual({ action: e.target.value })}>
                {ACTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              <div className="mt-2 flex gap-2">
                <button className="btn-primary flex-1 !py-2 text-xs" disabled={!focus || manual.busy} onClick={tryFix}>{manual.busy ? 'Working…' : `Apply to ${me?.name.split(' ')[0] ?? '…'}`}</button>
                <button className="btn-ghost !py-2 text-xs hairline" disabled={!focus || busy === 'investigate'} onClick={investigate}>Ask the resolver</button>
              </div>
              <AnimatePresence>
                {manual.result && (
                  <motion.p initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    className={`mt-2 rounded-xl px-3 py-2 text-xs ${manual.result.fixed ? 'bg-current-tint text-current' : manual.result.before.length ? 'bg-danger-tint text-danger' : 'bg-sunk text-ink-2'}`}>
                    {manual.result.fixed ? `${manual.result.label}: fixed. Every reading is healthy now.`
                      : manual.result.before.length ? `${manual.result.label}: didn't fix it. Still failing: ${manual.result.after.map((x) => WHAT[x] ?? x).join(', ')}.`
                        : `${manual.result.label}: nothing was broken for this customer.`}
                  </motion.p>
                )}
              </AnimatePresence>
            </details>
          </section>

          {/* network: takes whatever height is left */}
          <section aria-label="Network" className="lab-grid flex min-h-[520px] min-w-0 flex-col overflow-hidden rounded-[1.75rem] bg-ink p-4 text-white shadow-lift xl:min-h-0">
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 px-1">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/45">Live network · {view?.network?.pop.label ?? '…'}</p>
                <p className="text-sm text-white/80">Core → city hub → area exchange → street cabinet → homes</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {view?.faults.filter((f) => f.active).map((f) => (
                  <span key={f.id} className={`chip ${f.mitigated ? 'bg-conflict/20 text-conflict' : 'bg-danger/20 text-[#ff9b8f]'}`}>
                    <Warning className="h-3 w-3" />{f.title ?? 'Hidden fault'}{f.mitigated ? ' · on backup' : ''}</span>
                ))}
                {waiting && <span className="chip bg-white/10 text-white/80 animate-breathe">{waiting.split(' ')[0]} is telling intake…</span>}
              </div>
            </div>
            <div className={`scroll-thin mt-3 min-h-0 overflow-auto ${crew ? 'shrink' : 'flex flex-1 items-center justify-center'}`}>
              {view?.network ? <Canvas view={view.network} focus={focus ?? null} dispatch={crew} /> : <p className="py-24 text-center text-sm text-white/50">{view && !custs.length ? 'No customer has a line yet. Chat as a customer with a city first.' : 'Loading the network…'}</p>}
            </div>
            <AnimatePresence>{crew && view?.network && <FieldDispatch key={crew.at} d={crew} view={view.network} />}</AnimatePresence>
            <div className="mt-2 flex shrink-0 flex-wrap gap-x-4 gap-y-1 px-1 text-[10.5px] text-white/55">
              {(['ok', 'dark', 'flapping', 'frozen', 'paused', 'slow', ...(view?.network?.homes.some((h) => h.state === 'reported') ? ['reported'] : [])] as LabHome['state'][]).map((k) => (
                <span key={k} className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: HOME_COLOR[k] }} />{HOME_WORD[k]}</span>
              ))}
              <span className="inline-flex items-center gap-1.5"><i className="h-0.5 w-4 border-t-2 border-dotted border-white/40" />standby link</span>
            </div>
            {!!view?.network?.olts.length && (
              <details className="mt-2 shrink-0 rounded-xl bg-white/[0.04] px-3 py-2">
                <summary className="cursor-pointer list-none text-xs text-white/70">Evening load at the exchange{view.network.olts.length > 1 ? 's' : ''} <span className="text-white/40">· capacity from algo.maxFlow</span></summary>
                {view.network.olts.map((o) => <div key={o.id} className="mt-2"><EveningChart o={o} /></div>)}
              </details>
            )}
          </section>

          {/* resolver: the trace, or what the customer sees */}
          <section aria-label="Resolver" className="flex min-h-[560px] flex-col rounded-2xl bg-surface p-4 hairline xl:min-h-0">
            <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
              <div role="tablist" aria-label="Resolver view" className="inline-flex rounded-full bg-sunk/70 p-0.5">
                {([['trace', 'Resolver at work'], ['phone', `What ${run ? run.name.split(' ')[0] : 'the customer'} sees`]] as const).map(([k, label]) => (
                  <button key={k} role="tab" aria-selected={side === k} onClick={() => setSide(k)}
                    className={`rounded-full px-3 py-1 text-[11px] ${side === k ? 'bg-ink font-medium text-paper' : 'text-ink-2'}`}>{label}</button>
                ))}
              </div>
              {ordered.length > 1 && (
                <select aria-label="Pick a run" className="rounded-full bg-sunk px-2 py-1 text-[11px] text-ink-2 outline-none" value={run?.id ?? ''} onChange={(e) => setPicked(e.target.value)}>
                  {ordered.map((r) => <option key={r.id} value={r.id}>{r.name.split(' ')[0]} · {r.status}</option>)}
                </select>
              )}
            </div>
            <div className="min-h-0 flex-1" role="tabpanel">
              {side === 'trace' ? <Trace run={run} fill /> : <div className="scroll-thin h-full overflow-y-auto"><Phone run={run} /></div>}
            </div>
          </section>
        </div>
      </main>
      )}
    </div>
  )
}
