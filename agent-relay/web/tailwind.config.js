/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: v('paper'),
        surface: v('surface'),
        sunk: v('sunk'),
        ink: { DEFAULT: v('ink'), 2: v('ink-2'), 3: v('ink-3') },
        line: v('line'),
        signal: { DEFAULT: v('signal'), deep: v('signal-deep'), tint: v('signal-tint') },
        current: { DEFAULT: v('current'), tint: v('current-tint') },
        conflict: { DEFAULT: v('conflict'), tint: v('conflict-tint') },
        old: v('old'),
        danger: { DEFAULT: v('danger'), tint: v('danger-tint') },
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['"Twemoji Country Flags"', '"Instrument Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        soft: '0 1px 2px rgb(15 27 45 / 0.04), 0 8px 24px -12px rgb(15 27 45 / 0.10)',
        lift: '0 2px 4px rgb(15 27 45 / 0.04), 0 20px 48px -24px rgb(15 27 45 / 0.18)',
        inner: 'inset 0 1px 0 rgb(255 255 255 / 0.9)',
      },
      transitionTimingFunction: { spring: 'cubic-bezier(0.32, 0.72, 0, 1)' },
      keyframes: {
        rise: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'none' } },
        slide: { from: { transform: 'translateX(-100%)' }, to: { transform: 'translateX(300%)' } },
        breathe: { '0%,100%': { opacity: '0.35' }, '50%': { opacity: '1' } },
      },
      animation: {
        rise: 'rise 600ms cubic-bezier(0.32, 0.72, 0, 1) both',
        slide: 'slide 1.4s cubic-bezier(0.32, 0.72, 0, 1) infinite',
        breathe: 'breathe 1.6s cubic-bezier(0.32, 0.72, 0, 1) infinite',
      },
    },
  },
  plugins: [],
}
