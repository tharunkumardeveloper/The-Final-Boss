"""The `relay` UDF library: JavaScript functions loaded into FalkorDB, so a query in FalkorDB Browser (or anywhere)
can return readable text. They show in the Browser's UDF viewer.

    MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(:Customer {name_key:'alice rao'}) RETURN relay.sentence(f)
    MATCH (p:Plan)-[r:PRICED_IN]->(:Country {iso:'IN'}) RETURN p.name, relay.money(r.amount, r.currency)
    MATCH (e:Episode) RETURN relay.ago(e.recorded_at, timestamp()), e.text

The verb and currency tables are generated from the Python ones, so Browser and app phrase facts the same way.
"""
import json
from pathlib import Path

from . import db

LIBRARY = "relay"
_loaded = [False]


def script():
    from . import cards, kb  # lazy: cards imports agents
    return f"""
const VERB = {json.dumps(cards.VERB)};
const SYMBOL = {json.dumps(kb.SYMBOL)};
const title = (s) => String(s).replace(/\\b[a-z]/g, (c) => c.toUpperCase());

// "Alice Rao lives in Pune", "Alice Rao no longer lives in Chennai (replaced)"
function sentence(f) {{
  const a = f.attributes;
  const verb = VERB[a.predicate] || String(a.predicate).replace(/^open:/, '').replace(/_/g, ' ');
  const s = title(a.subject), o = title(a.object_value);
  if (a.active) return `${{s}} ${{verb}} ${{o}}`;
  return `${{s}} no longer ${{verb}} ${{o}}` + (a.superseded_by ? ' (replaced)' : ' (ended)');
}}

// 949, 'INR' -> "₹949"; 37.99, 'GBP' -> "£37.99"
function money(amount, currency) {{
  if (amount === null || amount === 0) return 'free';
  const sym = SYMBOL[currency] || (currency + ' ');
  const n = Number(amount);
  return sym + (n % 1 ? n.toFixed(2) : String(Math.round(n))).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
}}

// epoch ms -> "3 days ago"
function ago(ms, now) {{
  if (ms === null) return null;
  const s = Math.round((now - ms) / 1000);
  const units = [[86400, 'day'], [3600, 'hour'], [60, 'minute']];
  for (const [n, u] of units) if (Math.abs(s) >= n) {{ const v = Math.round(s / n); return `${{v}} ${{u}}${{v === 1 ? '' : 's'}} ago`; }}
  return 'just now';
}}

// the state label a node carries (:Current, :Superseded, :Subscriber, :Open, :CustomerMessage, ...)
function state(n) {{
  const base = ['Entity', 'Fact', 'Episode', 'Customer', 'Ticket', 'Order'];
  return n.labels.filter((l) => !base.includes(l)).join(', ') || null;
}}

falkor.register('sentence', sentence);
falkor.register('money', money);
falkor.register('ago', ago);
falkor.register('state', state);
"""


# FalkorDB's own FLEX library (github.com/FalkorDB/flex, release flex.js, reviewed: pure functions only).
# flex.text.levenshtein ranks fuzzy name matches; flex.text.*, flex.coll.*, flex.date.* etc. are there for Browser too.
FLEX_FILE = Path(__file__).resolve().parent.parent / "data" / "flex.js"


def load(force=False):
    """Load (or replace) the libraries once per process. UDF libraries are server-wide, not per graph."""
    if _loaded[0] and not force:
        return
    conn = db.client().connection
    conn.execute_command("GRAPH.UDF", "LOAD", "REPLACE", LIBRARY, script())
    if FLEX_FILE.exists():
        try:
            conn.execute_command("GRAPH.UDF", "LOAD", "REPLACE", "flex", FLEX_FILE.read_text(encoding="utf-8"))
        except Exception as e:  # optional: fuzzy matching falls back to the full-text score
            print("FLEX not loaded:", e)
    _loaded[0] = True
