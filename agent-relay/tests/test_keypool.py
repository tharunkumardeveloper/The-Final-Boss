"""The Groq key pool: each Groq model is tried on every key slot (GROQ_API_KEY, GROQ_API_KEY_2..5) before the next
model, then Gemini; the reply cache is shared across slots. No network. Run: python -m tests.test_keypool"""
import os
import subprocess
import sys

PROBE = """
from relay import config, llm, usage
r = config.ROUTES['reply']
assert r[:3] == ['openai/gpt-oss-120b', 'groq2:openai/gpt-oss-120b', 'groq3:openai/gpt-oss-120b'], r
assert r.index('groq3:qwen/qwen3.8-27b') < r.index(config.GEMINI_LITE) == len(r) - 1, r
assert not any(m.startswith(('groq4:', 'groq5:')) for m in r), 'slots without a key stay out'
assert llm._split('groq3:openai/gpt-oss-20b') == ('groq', 'openai/gpt-oss-20b')
assert llm._split('gemini:x') == ['gemini', 'x']
assert config.same_model('groq2:allam-2-7b') == 'allam-2-7b' and config.same_model('gemini:x') == 'gemini:x'
assert usage.has_key('groq2') and not usage.has_key('groq4')
assert usage.one('groq2:openai/gpt-oss-20b')['limits']['tpd'] == 200000
print('ok')
"""


def main():
    env = {**os.environ, "GROQ_API_KEY_2": "gsk_test2", "GROQ_API_KEY_3": "gsk_test3", "PYTHONPATH": "."}
    env.update(GROQ_API_KEY_4="", GROQ_API_KEY_5="")  # set empty: the env file would fill them otherwise
    for job in ("EXTRACT", "ANSWER", "REPLY", "PERSONA", "SUMMARY"):
        env.pop(f"RELAY_ROUTE_{job}", None)
    out = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True)
    assert out.stdout.strip().endswith("ok"), out.stdout + out.stderr


if __name__ == "__main__":
    main()
    print("test_keypool: all checks passed")
