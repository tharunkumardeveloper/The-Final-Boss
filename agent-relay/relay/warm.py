"""Build-time warm-up (Render build command): seed the LLM cache from demo_cache/ and download the embedding model,
so the first request after a deploy is fast and the demo replays without spending LLM quota."""
import shutil

from . import config, embed

if __name__ == "__main__":
    demo = config.ROOT / "demo_cache"
    if demo.exists():
        shutil.copytree(demo, config.CACHE_DIR, dirs_exist_ok=True)
        print(f"seeded {sum(1 for _ in demo.rglob('*.json'))} cached LLM responses into {config.CACHE_DIR}")
    print(f"embedding model ready: {len(embed.embed_one('warm up'))}-d")
