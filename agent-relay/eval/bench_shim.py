"""Eval-side workaround, NOT an engine fix: at fe9abb5, retrieve.recall raises KeyError on any fact whose predicate is
an open attribute ("open:works_from_home"), because _predicate_vecs() only embeds registry predicates. On the reloaded
pml-bench graph that is 155/160 questions. This gives an unknown predicate its own embedding on first use.

python -m eval.bench_shim --tenant pml-bench --phases main      (same arguments as eval.run_eval)
"""
import numpy as np

from relay import embed, retrieve

_orig = retrieve._predicate_vecs


class _Vecs(dict):
    def __missing__(self, p):
        name = p.split(":", 1)[-1].replace("_", " ")
        v = np.array(embed.embed_one(f"{name}: customer {name}"))
        self[p] = v / np.linalg.norm(v)
        return self[p]


_cache = {}


def _patched():
    if "v" not in _cache:
        _cache["v"] = _Vecs(_orig())
    return _cache["v"]


retrieve._predicate_vecs = _patched

if __name__ == "__main__":
    from eval.run_eval import main
    main()
