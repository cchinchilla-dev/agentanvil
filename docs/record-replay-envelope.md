# Record/replay envelope — schema v1

The record/replay envelope is the primary reproducibility surface of
AgentAnvil. Every LLM call made through `RecordingBackend` lands in this
envelope; `MockBackend` then serves bit-for-bit identical responses on replay.

This document specifies the **v1** schema. Future schema versions bump
`recording_version` and live alongside v1 — readers must reject envelopes whose
version they do not understand.

## File format

JSON, UTF-8, indented with 2 spaces, top-level keys sorted. Atomic writes
(`<file>.tmp` then rename) so the destination is never observed in a
half-written state, even if the writer crashes.

## Top-level shape

```json
{
  "recording_version": "1",
  "agentanvil_version": "0.1.1",
  "contract_hash": "sha256:<64 hex>",
  "run_id": "run_01J...",
  "seed": 42,
  "entries": [ { ... }, { ... } ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `recording_version` | string | yes | Currently `"1"`. Bump on any breaking schema change. |
| `agentanvil_version` | string | yes | Helps debugging cross-version recordings. |
| `contract_hash` | string | yes | SHA-256 of the serialised contract. `"sha256:"` prefix + 64 hex chars. |
| `run_id` | string | yes | ULID or any unique identifier. Empty allowed for ad-hoc recordings. |
| `seed` | integer \| null | yes | Seed used for the run. `null` if none. |
| `entries` | array | yes | Ordered list of recorded calls. |

## Entry shape

```json
{
  "key": "sha256:<64 hex>",
  "step_id": "step_007",
  "request": {
    "messages": [ ... ],
    "model": "gpt-4o-2024-11-20",
    "temperature": 0.0,
    "max_tokens": 1024,
    "tools": [ ... ],
    "seed": 42
  },
  "response": {
    "content": "...",
    "tool_calls": [ ... ],
    "usage": { ... },
    "finish_reason": "stop",
    "latency_ms": 847,
    "cost_usd": "0.023",
    "model": "gpt-4o-2024-11-20",
    "provider": "openai",
    "raw": { ... }
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `key` | string | yes | SHA-256 of the normalised request (see below). `"sha256:"` prefix + 64 hex chars. |
| `step_id` | string \| null | yes | Caller-provided step identifier. Preferred lookup key on replay. |
| `request` | object | yes | Normalised request. |
| `response` | object | yes | Normalised `LLMResponse` model dump (`mode="json"`). |

## Key derivation

`key` is computed deterministically over the **normalised** request:

```python
payload = json.dumps(
    {
        "messages": [m.model_dump(mode="json") for m in messages],
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "tools": [t.model_dump(mode="json") for t in (tools or [])],
        "seed": seed,
    },
    sort_keys=True,
    separators=(",", ":"),
).encode()
key = "sha256:" + hashlib.sha256(payload).hexdigest()
```

Fields included in the key:

- `messages` — every conversational turn.
- `model` — the exact model id.
- `temperature` — different temperatures, different responses.
- `max_tokens` — caps response length, affecting outcome.
- `tools` — different tool sets, different responses.
- `seed` — even with `temperature=0`, providers often need an explicit seed for full determinism.

Fields **excluded** from the key (intentionally):

- `timeout_s` — runtime concern, does not affect content.
- `step_id` — caller annotation, not part of the request semantics.
- Any caller-side metadata.

## Lookup order on replay

`MockBackend._lookup` resolves an entry in this order:

1. **`step_id`** — if the caller passes a `step_id` and it matches a recorded entry, use it. Wins even if the request hash differs (allows refactoring callers without re-recording).
2. **`key`** — SHA-256 over the normalised request as above.
3. **Miss** → `KeyError`. Silent fallthroughs are forbidden — they would defeat the determinism guarantee.

## Concurrency

Multiple concurrent `complete` / `stream` calls inside a single
`RecordingBackend` serialise via an `anyio.Lock`. The on-disk file is rewritten
atomically (write `.tmp`, rename) on every call so a crash mid-flush leaves
either the previous valid envelope or the new one — never a partial file.

## Backwards compatibility

- Readers MUST reject envelopes with `recording_version != "1"`.
- Writers SHOULD always emit `recording_version: "1"` for new envelopes.
- A future v2 will live in a sibling document. v1 readers will continue to load
  v1 envelopes after v2 ships.

## Example

A minimal v1 envelope is shipped under `tests/fixtures/recordings/single_agent.json`
and is loaded by `tests/ci/test_determinism.py`. Use it as a reference when
authoring new fixtures.
