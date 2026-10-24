# Changelog

## [Unreleased]

### Added
- Fault injection in the transport proxy (#36): a session's `perturb` list
  applies one operator to one crossing of a role, on live crossings only, so
  `replay_until` doubles as the injection point. On the request: `tool_result`,
  `tool_error`, `drop_instruction`, `user_rewrite`; on the response: `tool_call`,
  `output_rewrite`, `inflate`, `loop`, `delay`; and `upstream_error`, which
  answers 429, 500 or 504 without calling the upstream and without consuming
  the crossing. Choices inside an operator come from a seed. The crossing logs
  the `perturbation` (op, parameters, site, hashes before and after), and the
  request sent upstream or the upstream's answer when the fault changed them;
  `request_hash` and the divergence checks stay on what the client sent and
  the upstream answered. A fault with nothing to act on logs a
  `perturbation_miss` failure. Faults with `on_divergence: abort` are refused
  (422), and so is a fault on a replayed crossing (409). Logs of sessions
  without faults keep their shape.
- Transport proxy (`agentanvil proxy`, `record_replay.ProxyServer`, #21): records and
  replays any runtime at the HTTP boundary, in front of an OpenAI-compatible
  server. Sessions per episode and boundary (`/s/<session>/<role>/v1`), JSON Lines
  logs, seed rewriting per role and crossing, seeded tool-order permutation,
  replay of the first crossings with k-th crossing semantics, and divergence
  checks against a reference (log or abort), hashed under the session's
  normaliser: crossings the reference lacks are `extra`, and closing a session
  logs the ones it had left (`missing`). A reference must end with its `close`
  record, and requests from a browser (`Origin` header) get 403.
- `record_replay.normalize`: request and response hashes over a normalised copy
  (tool-call ids as ordinals, sorted argument keys, per-call fields dropped;
  timestamps, UUIDs and whitespace optional).
- Per-call fields of more servers dropped before hashing (llama.cpp `timings`,
  vLLM `metrics`, SGLang `sglext`, Groq `x_groq`, ...), as field paths such as
  `choices[].meta_info`; `normalizer.ignore_request` and `ignore_response` add
  paths for other servers, and tool-call ids become ordinals wherever a message
  carries them (#30).
- `ReplayDivergenceError`, a `RecordingError` raised when a session aborts on
  divergence.
- `MockBackend(path, strict=True)`: fails with `ReplayMissError` once the
  recorded entries for a call run out, instead of serving the last one again (#22).

### Changed
- Replay misses raise `ReplayMissError`, a `RecordingError` that is still a
  `KeyError`, so existing `except KeyError` handlers keep working (#22).
- Re-recording into an existing file replaces what earlier runs left for each
  `step_id` (or request key) the recorder records, instead of appending after
  it; repeats within one recorder still accumulate in order (#22).
- `RecordingBackend.stream` hands each chunk over one chunk late, so a caller
  that stops at the last chunk still leaves a recording (#22).

### Fixed
- `MockBackend` replays repeated calls in recorded order: a repeated `step_id`
  or request gets the next matching entry instead of always the last one (#22).
- `RecordingBackend.stream` records a streamed call as one entry with every
  chunk (`chunks`) and the whole answer as its `response`, instead of one entry
  per chunk; `MockBackend.stream` replays the chunks in order, and streams a
  non-streamed entry as a text delta plus a final chunk (#22).
- Strict `MockBackend` no longer serves another step's entry once a `step_id`
  runs out of entries (#22).
- `DirectBackend.stream` returns the streamed answer. OpenAI chunks were read as
  full messages (`message` instead of `delta`) and Anthropic events as a full
  response, so every chunk came back with `content=None`. Each provider now
  yields text deltas and one final chunk with the assembled `tool_calls`, usage,
  cost and finish reason; OpenAI streams ask for `stream_options.include_usage`.
  A vendor error event, a stream with no events and tool-call arguments cut off
  mid-JSON raise `BackendError`; the requested model prices a stream whose
  chunks omit it, and OpenAI-compatible servers that omit the tool-call `index`
  are handled (#33).
- `DirectBackend` raises `BackendError` when a tool call's arguments are not a
  JSON object (or, from OpenAI, not valid JSON), in `complete` and `stream`,
  instead of a validation error or empty `arguments` (#33).
- `DirectBackend` no longer fails a call to a self-hosted model. Each provider
  priced the response with `cost_for`, which raises `KeyError` for a model
  missing from `pricing.yaml`, after the call had succeeded, so every call to a
  server behind a custom `base_url` (vLLM, SGLang, Ollama's OpenAI endpoint)
  failed. Behind a custom `base_url`, a model without a price now costs 0 and
  the response has `priced=False` (new field, `True` by default and left out of
  dumps, so recordings of priced responses keep their shape); the last chunk of
  a stream does the same. Against the vendor's API a missing price still raises,
  and so does `cost_estimate`. With an empty `api_key`, the OpenAI client sends
  no `Authorization` header, for servers that take no key; it sent `Bearer `,
  which httpx refuses as an illegal header value (#23).

## [0.1.1] - 2026-04-29

### Added
- `AgentAnvilError` exception hierarchy (`BackendError`, `RunnerError`,
  `RecordingError`, `ContractValidationError`) mirroring AgentLoom's pattern.
  Bare `ValueError` raises in backend / record-replay paths now route through
  the typed hierarchy.
- `py.typed` marker so downstream type-checkers pick up AgentAnvil's
  annotations.
- `LLMBackend` ABC with Pydantic primitives (`Message`, `ContentBlock`, `ToolDef`, `ToolCall`, `Usage`, `LLMResponse`).
  Single abstraction for every LLM call; reasoning-token field for o1/o3/Claude extended thinking.
- `DirectBackend` covering OpenAI, Anthropic and Google Gemini via `httpx` only.
  Pinned per-provider pricing tables (`pricing_table_version="2026-04-09"`).
- ABC contract suite (`tests/backends/test_abc_contract.py`) every backend must pass.
- `Runner` ABC with `SubprocessRunner`. JSON-over-stdin/stdout protocol documented in
  `docs/runner-protocol.md`. Timeout enforcement via `anyio.fail_after`.
- Core trace models: `Trace`, `Step`, `LLMCallStep`, `ToolCallStep`, `InterAgentStep`,
  `StateStep`, `ErrorStep`. `Trace.total_duration_ms` / `total_cost_usd` aggregations.
- `RunRecord` and `RunMetadata` — canonical envelope of one evaluation. `Report` and
  `ReportFormat` for downstream rendering (JSON/HTML/Markdown/SARIF).
- Record/replay envelope (schema v1): `RecordingBackend` wraps any `LLMBackend` and
  flushes per-call atomically. `MockBackend` serves canned responses by `step_id` or
  SHA-256 of the normalised request.
- Bit-for-bit determinism CI test (`tests/ci/test_determinism.py`) protects the
  reproducibility invariant. Edge-case tests cover hash-key sensitivity, concurrent
  flush serialisation, append-existing-envelope and atomic-rename.
- `version-linearity` CI gate ensures `pyproject.toml` and `CHANGELOG.md` agree.
- `determinism` CI job runs the slow-marked replay determinism tests.
- Coverage configuration (`[tool.coverage.run]` + `[tool.coverage.report]`
  with `fail_under = 85`) mirroring AgentLoom's threshold.

### Changed
- `pyproject.toml` reorganised with optional-dependency bundles (`agentloom`,
  `docker`, `viz`, `stats`, `replication`, `security`, `cicd`, `all`).
  Description and keywords aligned with the contract-based testing framing.
- Pricing table moved from per-provider JSON files to a single
  `src/agentanvil/backends/pricing/pricing.yaml` (USD per 1K tokens) mirroring
  AgentLoom's format. Override via the new `AGENTANVIL_PRICING_FILE` env var.
- Default pytest invocation excludes the `slow` marker (`addopts = "-m 'not slow'"`);
  the CI `determinism` job opts in via `-m slow`.
- `CONTRIBUTING.md` adopts Conventional-Commits with scope (`feat(backends): …`),
  documents the bump-both rule for versioning, and reflects the `LLMBackend`
  abstraction (no more "AgentLoom for all LLM calls" wording).
- Provider clients (`OpenAIClient`, `AnthropicClient`, `GoogleClient`) refactored to
  inherit from `ProviderClientBase` for shared httpx scaffolding and SSE iteration.

### Fixed
- Version drift between `pyproject.toml` (`0.0.1`) and `CHANGELOG.md` (`0.1.0`)
  resolved by bumping to `0.1.1` and adding the linearity CI gate.
- CLI now runnable as `python -m agentanvil.cli.main <command>` (added missing
  `if __name__ == "__main__": app()` guard). The installed entry-point
  `agentanvil` was already working.

## [0.1.0] - 2026-04-16

### Added
- `AgentContract` — YAML/Python contract definition with policies, tasks, and constraints
- `Scenario`, `EvalResult`, `PromptSuggestion` — core evaluation models
- CLI: `validate`, `run`, `version` commands via Typer
