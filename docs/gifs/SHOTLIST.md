# GIF shot list for the README

Save each GIF in this folder under the exact file name below; the README already points at these paths.

**Format for every GIF:** 8–20 seconds, about 1200–1400 px wide (the README shows them at 900 px), 10–15 fps, under
8 MB each (GitHub stops animating very large GIFs). Record at 100% browser zoom with the API already awake (open the
site once first). Hide bookmarks and extensions; a clean browser window reads best.

| # | File | Where | What to record | Length |
|---|---|---|---|---|
| 01 | `01-judge-mode.gif` | wifight.vercel.app → **▶ Watch it work** | The hero shot. The caption bar at the top, then the chat typing by itself, the ticket appearing in Your tickets, the resolver's steps, the move to Pune, and step 5's "Pune, and your ticket is resolved". Speed it up 2–3× in editing so it fits | 15–20 s |
| 02 | `02-wifight-home.gif` | Home page, scrolled | Switch the region (India → Europe), the plans re-price in euros, scroll to Plans and Coverage (Normal / Degraded) | 8–12 s |
| 03 | `03-ticket-lifecycle.gif` | Home page, **Your tickets** | A ticket going Reported → Checking your line → Fixing → Fixed, the "Resolver at work" steps filling in, and the technician strip (Dispatched → En route → On site → Verified) | 10–15 s |
| 04 | `04-network-lab.gif` | Home page, third card → **Network lab** | Your home glowing (faulty or "reported faulty"), the van driving from the hub to the home, the line turning green | 8–12 s |
| 05 | `05-console-memory.gif` | /console → **Memory** | The live graph as a fact lands; switch to **Replay** and drag the time bar; **Show me** → "Where does Alice Rao live?" (two clocks), then "What plan is Alice Rao on?" and click **This one is right** | 15–20 s |
| 06 | `06-network-break-it.gif` | /console → **Network** | Pick a fault (Damaged home fibre is the most visual), the 4-step strip advancing, the resolver's trace, the van, and "Graded against the hidden truth: correct, fixed" | 15–20 s |
| 07 | `07-agent-team.gif` | /console → **Agent team** | Dots flying from writer to reader through Shared memory; open **Watch a handoff** for a few seconds | 8–12 s |
| 08 | `08-tenants-canary.gif` | /console → **Tenants** | Type a word, write it into one region, the other regions' cells turning "clean", the verdict | 10–15 s |
| 09 | `09-mcp-claude.gif` | Claude Code + the site | Claude Code calling `remember_fact` (agent mcp, Alice Rao's router), then the site: chat as Alice, "Which router do I have?", the answer with "How I know"; then Agent team showing the purple **MCP client** | 15–20 s |

**Before recording 05:** "This one is right" settles the only disagreement in the demo graph. After recording, reset to
**story** (console → reset, with the reset key) so judges still have one to click.

**Tools:** ScreenToGif (Windows, free) records and trims and exports GIFs directly. Or record an MP4 with the Xbox Game
Bar (Win+G) or OBS and convert it at ezgif.com (*Video to GIF*, then *Optimize* to get under 8 MB).
