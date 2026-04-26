# Changelog

## [Unreleased]

## [0.1.1] - 2026-04-26

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
