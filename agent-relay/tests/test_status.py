"""Model status is what the provider last said, with its own recovery time, never a guess held for an hour; and a
ledger written by another process is seen. No LLM calls (a temporary ledger). Run: python -m tests.test_status"""
import json
import tempfile
from pathlib import Path

from relay import config, usage

M = "openai/gpt-oss-20b"


def main():
    usage._DIR = Path(tempfile.mkdtemp())
    usage._state.update({"date": None, "models": {}, "mtime": None})
    config.ROUTES["extract"] = [M]

    usage.record(M, 100, 10, latency_ms=900)
    s = usage.one(M)
    assert s["state"] == "available" and s["latency_ms"] == 900 and s["checked_at"], s

    # Groq's own words decide: out for ~19 minutes, not a fixed hour
    usage.record_unavailable(M, "Rate limit reached on tokens per day (TPD): Limit 200000. Please try again in 18m58.32s.")
    s = usage.one(M)
    assert s["state"] == "exhausted" and 18 * 60 < s["back_in_s"] < 20 * 60, s
    assert usage.due_for_check() == [], "not due before the provider's time"

    # the provider's time passes: due for one real check, and no longer counted as out
    day = usage._day()
    day[M]["limited_until"] = usage._now() - 1
    assert not usage.exhausted(M) and usage.due_for_check() == [M]
    assert usage.one(M)["state"] == "recovering"
    usage.record(M, 5, 1, latency_ms=300)  # the check answered
    assert usage.one(M)["state"] == "available" and usage.due_for_check() == []

    # local counters never bench a model (Groq's day rolls; ours resets at IST midnight)
    day[M]["tokens_in"] = 10_000_000
    assert not usage.exhausted(M)

    # Gemini: quota out until midnight Pacific
    usage.record_unavailable("gemini:gemini-3.5-flash-lite", "HTTP 429 You exceeded your current quota")
    assert 0 < usage.one("gemini:gemini-3.5-flash-lite")["back_in_s"] <= 24 * 3600

    # another process writes the ledger: this one sees it on its next read
    path = usage._DIR / f"{usage.today()}.json"
    other = json.loads(path.read_text(encoding="utf-8"))
    other[M]["requests"] = 999
    import os, time
    time.sleep(0.05)
    path.write_text(json.dumps(other), encoding="utf-8")
    os.utime(path, (time.time() + 1, time.time() + 1))
    assert usage.one(M)["used"]["requests"] == 999, "a write by another process is picked up"


if __name__ == "__main__":
    main()
    print("test_status: all checks passed")
