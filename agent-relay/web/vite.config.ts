import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The brand lives in ../brand.json (shared with the backend): rename the company or the bot there.
const brand = readFileSync(new URL('../brand.json', import.meta.url), 'utf-8')

export default defineConfig({
  plugins: [react(), {
    name: 'brand-html',  // %COMPANY% and %TAGLINE% in index.html
    transformIndexHtml: (html) => html.replace(/%COMPANY%/g, JSON.parse(brand).company).replace(/%TAGLINE%/g, JSON.parse(brand).tagline),
  }],
  define: { __BRAND__: brand },
  server: { port: 5173 },
})
