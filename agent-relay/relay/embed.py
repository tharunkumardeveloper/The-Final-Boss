import os
import threading
from functools import lru_cache

from . import config

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


_load = threading.Lock()  # lru_cache doesn't stop two threads loading the model at once on the first call


@lru_cache
def _model():
    with _load:
        from fastembed import TextEmbedding
        # one thread: the free host has 0.1 CPU, and every extra ONNX thread keeps its own memory arena
        return TextEmbedding(config.EMBED_MODEL, cache_dir=str(config.CACHE_DIR / "fastembed"), threads=1)


def embed(texts):
    # small batches: seeding a region's catalogue in one batch peaked at 618 MB, over the free host's 512 MB
    return [v.tolist() for v in _model().embed(list(texts), batch_size=16)]


def embed_one(text):
    return embed([text])[0]


@lru_cache(maxsize=4096)
def embed_name(name):
    """Entity names repeat constantly; cache their vectors."""
    return embed_one(name)
