import type { ReactNode } from 'react'

/** Premade instruction pictures. A message carries `[guide:key]`; the chat shows the card instead of the marker.
 *  To use a photo instead of a drawing, put it in web/public/guides/<key>.jpg and set `photo` below. */
const INK = 'rgb(var(--ink))', SIG = 'rgb(var(--signal))', RED = 'rgb(var(--danger))', MUTE = 'rgb(var(--ink) / 0.35)', OK = 'rgb(var(--current))'

const BoxFront = ({ x, y, los = 'off' }: { x: number; y: number; los?: 'off' | 'red' }) => (
  <g transform={`translate(${x} ${y})`}>
    <rect width="150" height="64" rx="12" fill={INK} />
    <text x="75" y="17" textAnchor="middle" fontSize="7" fill="white" opacity="0.4" letterSpacing="2">FIBRE BOX</text>
    {['POWER', 'PON', 'LOS', 'NET', 'WI-FI'].map((n, i) => {
      const c = n === 'LOS' ? (los === 'red' ? RED : 'rgb(255 255 255 / 0.15)') : OK
      return <g key={n}><circle cx={21 + i * 27} cy="34" r="4" fill={c} /><text x={21 + i * 27} y="52" textAnchor="middle" fontSize="6.5" fill="white" opacity="0.55">{n}</text></g>
    })}
  </g>
)

interface Guide { title: string; steps: string[]; art: ReactNode; photo?: string }

export const GUIDES: Record<string, Guide> = {
  model_sticker: {
    title: 'Find your router model',
    steps: ['Turn the router over gently.', 'Look for the white sticker underneath.', 'The model is next to "MODEL", e.g. PML Hub 6.'],
    art: (
      <svg viewBox="0 0 320 170" className="w-full">
        <g transform="rotate(-8 120 95)">
          <rect x="40" y="55" width="170" height="80" rx="14" fill="rgb(var(--sunk))" stroke={INK} strokeWidth="2" />
          <rect x="72" y="72" width="104" height="46" rx="5" fill="white" stroke={MUTE} />
          <text x="80" y="87" fontSize="8" fontWeight="700" fill={INK}>MODEL: PML Hub 6</text>
          <text x="80" y="99" fontSize="7" fill={MUTE}>S/N 4F21 0098 7713</text>
          <text x="80" y="110" fontSize="7" fill={MUTE}>Acct PML-AC-…</text>
          <rect x="72" y="72" width="104" height="46" rx="5" fill="none" stroke={RED} strokeWidth="2.5" />
        </g>
        <path d="M228 60 C 255 60, 262 80, 214 92" fill="none" stroke={RED} strokeWidth="2" markerEnd="url(#ga)" />
        <text x="232" y="50" fontSize="10" fontWeight="600" fill={INK}>the sticker</text>
        <text x="232" y="62" fontSize="9" fill={MUTE}>is underneath</text>
        <defs><marker id="ga" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8z" fill={RED} /></marker></defs>
      </svg>
    ),
  },
  los_light: {
    title: 'Check the LOS light',
    steps: ['Find the light marked LOS on the front of the box.', 'Off is good: the fibre signal is reaching you.', 'Red or blinking red means no signal on the fibre. Tell us; you can\'t fix that yourself.'],
    art: (
      <svg viewBox="0 0 320 150" className="w-full">
        <BoxFront x={20} y={30} los="red" />
        <circle cx={95} cy={64} r="11" fill="none" stroke={RED} strokeWidth="2.5" />
        <g fontSize="10" fill={INK}>
          <circle cx="200" cy="48" r="5" fill="rgb(255 255 255 / 0.15)" stroke={MUTE} /><text x="212" y="52">off = all good</text>
          <circle cx="200" cy="74" r="5" fill={RED} /><text x="212" y="78">red = no signal</text>
          <circle cx="200" cy="100" r="5" fill={RED} opacity="0.5" /><text x="212" y="104">blinking = weak</text>
        </g>
      </svg>
    ),
  },
  restart_box: {
    title: 'Restart the box',
    steps: ['Unplug the power cable from the box.', 'Wait 10 seconds.', 'Plug it back in. The lights blink for about a minute; that\'s normal.'],
    art: (
      <svg viewBox="0 0 320 150" className="w-full">
        <BoxFront x={20} y={40} />
        <path d="M170 72 h40" stroke={INK} strokeWidth="4" strokeLinecap="round" />
        <rect x="210" y="64" width="22" height="16" rx="3" fill={INK} />
        <path d="M232 68 h8 M232 76 h8" stroke={INK} strokeWidth="2.5" />
        <path d="M252 72 h24" stroke={MUTE} strokeWidth="4" strokeLinecap="round" strokeDasharray="2 6" />
        <circle cx="270" cy="38" r="18" fill="none" stroke={SIG} strokeWidth="3" />
        <text x="270" y="42" textAnchor="middle" fontSize="11" fontWeight="700" fill={SIG}>10 s</text>
        <text x="200" y="118" fontSize="10" fill={INK}>unplug · wait · plug back</text>
      </svg>
    ),
  },
  router_placement: {
    title: 'Give your Wi-Fi a clear path',
    steps: ['Put the box out in the open, around chest height.', 'Keep it away from the TV, the microwave and metal cupboards.', 'Not inside a cabinet or behind the TV.'],
    art: (
      <svg viewBox="0 0 320 160" className="w-full">
        <rect x="14" y="20" width="140" height="125" rx="10" fill="rgb(var(--current-tint))" />
        <rect x="40" y="78" width="88" height="6" rx="2" fill={INK} opacity="0.5" />
        <rect x="62" y="58" width="44" height="20" rx="5" fill={INK} />
        {[22, 36, 50].map((r) => <path key={r} d={`M${84 - r} ${58 - r * 0.35} A ${r} ${r} 0 0 1 ${84 + r} ${58 - r * 0.35}`} fill="none" stroke={OK} strokeWidth="2.5" />)}
        <text x="84" y="128" textAnchor="middle" fontSize="10" fontWeight="600" fill={OK}>open shelf, chest height</text>
        <rect x="166" y="20" width="140" height="125" rx="10" fill="rgb(var(--danger-tint))" />
        <rect x="186" y="42" width="56" height="36" rx="3" fill={INK} opacity="0.8" />
        <text x="214" y="64" textAnchor="middle" fontSize="8" fill="white">TV</text>
        <rect x="250" y="60" width="40" height="20" rx="3" fill="none" stroke={INK} strokeWidth="2" />
        <text x="270" y="73" textAnchor="middle" fontSize="7" fill={INK}>micro</text>
        <rect x="196" y="90" width="40" height="14" rx="4" fill={INK} />
        <path d="M188 84 L 296 116 M296 84 L188 116" stroke={RED} strokeWidth="2.5" opacity="0.8" />
        <text x="236" y="128" textAnchor="middle" fontSize="10" fontWeight="600" fill={RED}>behind the TV, near metal</text>
      </svg>
    ),
  },
  fibre_cable: {
    title: 'Check the fibre cable',
    steps: ['Look at the back of the box for the thin cable with a green plug.', 'Push the plug in gently until it clicks.', 'Make sure the cable isn\'t bent sharply or squashed behind furniture.'],
    art: (
      <svg viewBox="0 0 320 160" className="w-full">
        <rect x="20" y="40" width="120" height="70" rx="12" fill={INK} />
        <text x="80" y="58" textAnchor="middle" fontSize="7" fill="white" opacity="0.4" letterSpacing="2">BACK</text>
        <rect x="56" y="76" width="18" height="14" rx="2" fill="rgb(var(--current))" />
        <circle cx="65" cy="83" r="15" fill="none" stroke={SIG} strokeWidth="2.5" />
        <path d="M65 90 C 65 130, 120 140, 150 132" fill="none" stroke="#d9c79a" strokeWidth="3" />
        <text x="16" y="138" fontSize="10" fontWeight="600" fill={OK}>clicked in, gentle curve</text>
        <path d="M200 60 L 236 100 L 272 60" fill="none" stroke="#d9c79a" strokeWidth="3" />
        <path d="M222 72 L 250 100 M250 72 L 222 100" stroke={RED} strokeWidth="3" />
        <text x="236" y="128" textAnchor="middle" fontSize="10" fontWeight="600" fill={RED}>no sharp bends</text>
      </svg>
    ),
  },
}

const MARK = /\s*\[guide:([a-z_]+)\]/g

/** Text without its guide markers, and the guides it asked for (known ones only). */
export function splitGuides(text: string) {
  const guides = [...text.matchAll(MARK)].map((m) => m[1]).filter((k) => k in GUIDES)
  return { text: text.replace(MARK, '').trim(), guides: [...new Set(guides)] }
}

export function GuideCard({ id, compact = false }: { id: string; compact?: boolean }) {
  const g = GUIDES[id]
  if (!g) return null
  return (
    <figure className="w-full max-w-sm overflow-hidden rounded-2xl bg-surface ring-1 ring-line/10">
      <div className="bg-paper px-3 pt-3">{g.photo ? <img src={g.photo} alt={g.title} className="w-full rounded-lg" /> : g.art}</div>
      <figcaption className="px-4 pb-3 pt-2">
        <p className="text-sm font-semibold text-ink">{g.title}</p>
        {!compact && <ol className="mt-1.5 space-y-1 text-[13px] leading-snug text-ink-2">
          {g.steps.map((s, i) => <li key={i} className="flex gap-2"><span className="num font-semibold text-signal-deep">{i + 1}</span>{s}</li>)}
        </ol>}
      </figcaption>
    </figure>
  )
}
