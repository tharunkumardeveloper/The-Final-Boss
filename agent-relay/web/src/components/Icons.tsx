import type { SVGProps } from 'react'

// Thin 1.5px line icons, drawn on a 24px grid.
const Base = ({ children, ...p }: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>{children}</svg>
)
type P = SVGProps<SVGSVGElement>

export const ArrowUpRight = (p: P) => <Base {...p}><path d="M7 17 17 7M8 7h9v9" /></Base>
export const Send = (p: P) => <Base {...p}><path d="M4 12 20 4l-6 16-3-7-7-1Z" /></Base>
export const Play = (p: P) => <Base {...p}><path d="M7 5v14l12-7L7 5Z" /></Base>
export const Pause = (p: P) => <Base {...p}><path d="M8 5v14M16 5v14" /></Base>
export const Rewind = (p: P) => <Base {...p}><path d="M4 12a8 8 0 1 0 2.3-5.7M4 4v4h4" /></Base>
export const Database = (p: P) => <Base {...p}><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></Base>
export const Close = (p: P) => <Base {...p}><path d="M6 6l12 12M18 6 6 18" /></Base>
export const Pulse = (p: P) => <Base {...p}><path d="M3 12h4l2-6 4 12 2-6h6" /></Base>
export const Sparkle = (p: P) => <Base {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5" /></Base>
export const Ticket = (p: P) => <Base {...p}><path d="M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4V7Z" /><path d="M14 7v10" strokeDasharray="2 2" /></Base>
export const Chart = (p: P) => <Base {...p}><path d="M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3" /></Base>
export const Warning = (p: P) => <Base {...p}><path d="M12 4 2.8 19h18.4L12 4Z" /><path d="M12 10v4M12 16.5v.5" /></Base>
export const Check = (p: P) => <Base {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></Base>
export const Wifi = (p: P) => <Base {...p}><path d="M3 9a13 13 0 0 1 18 0M6 12.5a8.5 8.5 0 0 1 12 0M9 16a4 4 0 0 1 6 0" /><circle cx="12" cy="19" r="0.8" /></Base>
