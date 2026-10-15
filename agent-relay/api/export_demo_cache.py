"""Copy exactly the cached LLM responses the demo story + full simulation use into demo_cache/ (committed).
Responses only, no keys. Run: python -m api.export_demo_cache   (re-runs are free once the cache is warm)."""
import shutil

from relay import config, db, llm, sim

used = set()
_orig = llm._cache_path


def _tracked(kind, payload):
    p = _orig(kind, payload)
    used.add(p)
    return p


if __name__ == "__main__":
    llm._cache_path = _tracked
    db.reset("demo-export")
    sim.load_story("demo-export")
    db.reset("demo-export")
    sim.Sim("demo-export").run_sync()
    db.graph("demo-export").delete()
    out = config.ROOT / "demo_cache"
    n = 0
    for p in used:
        if p.exists():
            dst = out / p.relative_to(config.CACHE_DIR)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            n += 1
    print(f"exported {n} cached responses to {out}")
