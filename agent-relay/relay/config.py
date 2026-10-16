import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The brand lives in one file: rename the company or the bot in brand.json (backend and web both read it).
BRAND_FILE = ROOT / "brand.json"
BRAND = __import__("json").loads(BRAND_FILE.read_text(encoding="utf-8"))

for env_file in (ROOT / ".env", ROOT.parent / "falkor.env"):
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split(" #", 1)[0].strip())  # "KEY=value  # note" -> value
        break

FALKOR_HOST = os.environ.get("FALKOR_HOST", "localhost")
FALKOR_PORT = int(os.environ.get("FALKOR_PORT", 6379))
FALKOR_USER = os.environ.get("FALKOR_USER") or None
FALKOR_PASS = os.environ.get("FALKOR_PASS") or None
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
# Groq key pool: GROQ_API_KEY is slot 1 (provider "groq"), GROQ_API_KEY_2..GROQ_API_KEY_12 are slots 2-12 ("groq2:"...).
# Each slot is its own quota and its own row on the Usage page. Only slots with a key are used.
GROQ_SLOTS = {i: k for i, k in ((1, GROQ_API_KEY), *((i, os.environ.get(f"GROQ_API_KEY_{i}")) for i in range(2, 13))) if k}


def groq_slot(model):
    """'groq3:openai/gpt-oss-20b' -> (3, 'openai/gpt-oss-20b'); a bare model name is slot 1."""
    head, _, rest = model.partition(":")
    if not rest:
        return 1, model
    return (int(head[4:] or 1), rest) if head.startswith("groq") else (None, model)


def same_model(model):
    """The model without its key slot: the reply cache and the limits table are per model, not per key."""
    slot, name = groq_slot(model)
    return name if slot else model


def pooled(models):
    """Every Groq model tried on each key slot in turn before the next model; other providers stay where they are."""
    out, given = [], set(models)
    for m in models:
        slot, name = groq_slot(m)
        variants = [name] + [f"groq{i}:{name}" for i in sorted(GROQ_SLOTS) if i > 1] if slot else [m]
        # a key already placed in the list keeps its place (a route reordered on the Usage page stays as set)
        out += [v for v in variants if v not in out and (v == m or v not in given)]
    return out
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
# Every read query gets a server-side timeout (verified: the server aborts with "Query timed out"). The free tier has
# 100 MB for data and query scratch space together, so no query may build big intermediate lists either.
READ_TIMEOUT_MS = int(os.environ.get("RELAY_READ_TIMEOUT_MS", "15000"))
FREE_TIER_MB = 100
SARVAM_URL = "https://api.sarvam.ai/v1/chat/completions"

EXTRACT_MODEL = os.environ.get("RELAY_EXTRACT_MODEL", "openai/gpt-oss-20b")
ANSWER_MODEL = os.environ.get("RELAY_ANSWER_MODEL", "openai/gpt-oss-120b")
GEMINI_LITE = "gemini:gemini-3.5-flash-lite"
# Paid credits, so after the free models. The "-conversations" variant: no hidden reasoning, ~1 s for an extraction
# (plain sarvam-105b spent 3-5K reasoning tokens per extraction and returned nothing 3 times out of 4).
SARVAM = "sarvam:sarvam-105b-conversations"

# Each job has its own model (Groq quotas are per model), then fallbacks tried on 429 / 5xx.
# "provider:model"; a bare model name means Groq. Override with RELAY_ROUTE_<JOB>="a,b,c".
# Order: the Groq models on every key slot (see pooled), then Gemini. Sarvam is supported but only if added to a route.
ROUTES = {
    "extract": [ANSWER_MODEL, EXTRACT_MODEL, "qwen/qwen3.8-27b", GEMINI_LITE],  # 120b first: 20b skipped facts
    "answer":  [ANSWER_MODEL, "qwen/qwen3.8-27b", GEMINI_LITE],
    "reply":   [ANSWER_MODEL, "qwen/qwen3.8-27b", GEMINI_LITE],  # allam out: it ignores style rules
    "persona": ["allam-2-7b", GEMINI_LITE],
    "summary": ["allam-2-7b", GEMINI_LITE],
}
for _job in ROUTES:
    if os.environ.get(f"RELAY_ROUTE_{_job.upper()}"):
        ROUTES[_job] = [m.strip() for m in os.environ[f"RELAY_ROUTE_{_job.upper()}"].split(",") if m.strip()]
    ROUTES[_job] = pooled(ROUTES[_job])
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384

CACHE_DIR = Path(os.environ["RELAY_CACHE_DIR"]) if os.environ.get("RELAY_CACHE_DIR") else ROOT / ".cache"
# Misspelt place names at write time (difflib ratio vs places already on file): tahne/thane 0.8, puan/pune 0.75,
# nasik/nashik 0.91; real neighbours sit lower (secunderabad/hyderabad 0.67). Calibration knob.
TYPO_MIN_RATIO = 0.75
ALIAS_MAX_DIST = 0.2  # cosine distance; measured paraphrase ~0.06, unrelated ~0.64
# Fix suggestions from similar issues. Short issue names separate poorly: "connection drops" vs
# "evening wifi issues" 0.26, vs "laggy games" 0.27. Calibration knob; a wrong suggestion is tried and recorded.
SIMILAR_ISSUE_MAX_DIST = 0.28

# Benchmark tenants: the API refuses to reset them or run the simulator on them (reloading costs LLM quota).
PROTECTED_TENANTS = {t.strip() for t in os.environ.get("RELAY_PROTECTED_TENANTS", "pml-bench,nimbus,life-locomo").split(",")
                     if t.strip()}

AGENTS = {
    "intake": {"role": "talks to customers and opens tickets", "trust": 0.9},
    "resolver": {"role": "works tickets with diagnostic, billing and outage tools", "trust": 0.6},
    "noc": {"role": "watches the network, finds affected customers and warns them first", "trust": 0.8},
    "simulator": {"role": "plays synthetic customers on a simulated clock (never writes facts itself)", "trust": 0.5},
}
