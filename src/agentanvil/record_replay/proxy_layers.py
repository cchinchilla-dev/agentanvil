"""Layer rewrites of the transport proxy: derived seeds and seeded orders.

Pure functions of their inputs, stable across processes and Python versions, so
a session log is enough to reproduce every rewrite the proxy applied.
"""

from __future__ import annotations

import hashlib

from agentanvil.record_replay.normalize import JSON


def derive_seed(seed: int, *parts: str | int) -> int:
    """A 31-bit seed from a base seed and a path, stable across processes and Python versions."""
    key = ":".join(str(p) for p in (seed, *parts)).encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:4], "big") & 0x7FFFFFFF


def permutation(n: int, seed: int) -> list[int]:
    """Order of `n` items under `seed`, by hash sort (independent of `random`'s algorithm)."""
    return sorted(range(n), key=lambda i: hashlib.sha256(f"{seed}:{i}".encode()).digest())


def permute_tool_runs(messages: list[JSON], seed: int) -> list[JSON]:
    """Permute each run of two or more consecutive tool results, keyed by where the run starts."""
    out = list(messages)
    i = 0
    while i < len(out):
        j = i
        while j < len(out) and isinstance(m := out[j], dict) and m.get("role") == "tool":
            j += 1
        if j - i >= 2:
            run = out[i:j]
            out[i:j] = [run[n] for n in permutation(len(run), derive_seed(seed, i))]
        i = max(j, i + 1)
    return out
