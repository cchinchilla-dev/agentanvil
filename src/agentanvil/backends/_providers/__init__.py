"""Per-provider thin httpx wrappers used by `DirectBackend`.

Each provider module exposes a Client class with `complete`, `stream` and
`normalise`; their stream normalisers live in `stream`.
Internal — the public surface is `agentanvil.backends.DirectBackend`.
"""
