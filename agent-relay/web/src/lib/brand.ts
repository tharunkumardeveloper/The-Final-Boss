declare const __BRAND__: { company: string; tagline: string; bot: string; bot_tagline: string }

/** From ../brand.json at build time. */
export const BRAND = __BRAND__
export const { company: COMPANY, tagline: TAGLINE, bot: BOT, bot_tagline: BOT_TAGLINE } = BRAND
