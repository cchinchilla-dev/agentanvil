"""Per-provider thin httpx wrappers used by `DirectBackend`.

Each module exposes a Client class with `complete`, `stream` and `normalise`.
Internal — the public surface is `agentanvil.backends.DirectBackend`.
"""
