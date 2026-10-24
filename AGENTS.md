# AgentAnvil

Project rules for contributors and AI coding assistants. Any assistant that reads `AGENTS.md` (Claude Code, Codex, Copilot, Cursor, …) picks these up; Claude Code reads them through `CLAUDE.md`.

## Build & test
- `uv sync --group dev` — install (core only, no AgentLoom)
- `uv sync --group dev --extra agentloom` — install with AgentLoom (its backend lands in 0.2.0, #9)
- `uv sync --group dev --extra all` — install with every optional extra
- `make check` — every CI gate in one go, check-only (no auto-fix)
- `uv run pytest` — tests
- `uv run ruff check src/ tests/` — lint
- `uv run ruff format src/ tests/` — format
- `uv run mypy src/` — strict type check
- `uv run agentanvil validate path/to/contract.yaml` — validate a contract (`run` is a placeholder until 0.2.0)
- `uv run agentanvil proxy --log-dir recordings` — run the transport proxy ([docs/transport-proxy.md](docs/transport-proxy.md))

## Rules

**Async**: always `anyio`, never raw `asyncio`.

**Models**: Pydantic v2 everywhere. No `Any` in public signatures. `from __future__ import annotations` at the top of every module that uses type hints.

**LLM calls**: always go through the `LLMBackend` boundary in `src/agentanvil/backends/base.py`. Never import provider SDKs or call LLM HTTP endpoints directly from business logic. The one exception is the transport proxy (`record_replay/proxy.py`), which forwards OpenAI-compatible JSON with `httpx` because the payload on the wire is what it records. `DirectBackend` (httpx-only, no AgentLoom) is implemented; `AgentLoomBackend` (recommended once available, pulls resilience and observability from AgentLoom) is planned in #9.

**Contracts**: the source of truth for what to test. Every module, current and planned (Generator, Evaluator, Reporter), derives its behaviour from the `AgentContract`.

**Portability**: AgentAnvil must remain operable without AgentLoom. CI will run the test matrix with both backends once `AgentLoomBackend` exists (#15). A LangChain quickstart using `DirectBackend` must complete in under 10 minutes for a new user. Do not introduce hard dependencies on AgentLoom in core modules.

**Errors**: domain errors subclass `AgentAnvilError` (`BackendError`, `RunnerError`, `RecordingError`, `ContractValidationError`). No bare `ValueError` / `KeyError` for framework-level failures.

**Commits**: Conventional-Commits with scope (`feat(backends): …`, `fix(runner): …`, `test(core): …`). Imperative, lowercase after the colon, single-line subject. The PR title becomes the squash-merge commit on `main`, so the same rule applies to PR titles. Release commits are the one exception: exactly `bump version to X.Y.Z`, with no type or scope, because `auto-tag.yml` only tags commits that start with that prefix. Squash merge only.

**Versions**: when bumping the version, update `pyproject.toml`, `CHANGELOG.md` and `__version__` in `src/agentanvil/__init__.py` in the same commit. The `version-linearity` CI job fails when they disagree.

## Architecture (read these first)

Implemented (0.1.x):
- `core/contracts.py` — `AgentContract`, `Policy`, `Task`, `Constraints` — YAML ↔ Pydantic
- `core/models.py` — shared types: `Scenario`, `EvalResult`, `ScoreBreakdown`
- `core/traces.py` — `Trace` and typed `Step` records of an agent run
- `core/run_record.py`, `core/report.py` — run metadata and report models
- `backends/base.py` — `LLMBackend` ABC (the portability boundary)
- `backends/direct.py` — httpx-only backend for OpenAI, Anthropic, Google
- `record_replay/` — `RecordingBackend` and `MockBackend` for deterministic replay; transport proxy (`proxy.py`, `proxy_session.py`, `proxy_layers.py`, `proxy_log.py`, `normalize.py`; faults in `proxy_faults.py` and `perturb*.py`) for any runtime at the HTTP boundary
- `runner/` — `Runner` ABC and `SubprocessRunner`
- `exceptions.py` — `AgentAnvilError` hierarchy
- `cli/main.py` — Typer CLI (`version`, `validate`, `proxy`; `run` is a placeholder)

Planned (0.2.0, roadmap #18): `backends/agentloom.py` (#9), analyzer (#5), generator (#6), `DockerRunner` (#7), evaluator (#10, #11), reporter (#12). K8sRunner comes later.

## Observability contract

Shared types and observability names come from `agentloom.contracts`, a submodule of AgentLoom that ships with AgentLoom 0.5.0 (design in [agentloom#159](https://github.com/cchinchilla-dev/agentloom/issues/159); span and metric names stay experimental while the OpenTelemetry GenAI conventions are unstable). Import them when using the AgentLoom backend and never hardcode span attribute strings, so a rename on the AgentLoom side fails CI here instead of drifting silently. The temporary `agentloom>=0.4.0` pin in `pyproject.toml` does not provide it yet.

With `DirectBackend`, AgentAnvil does not depend on AgentLoom; OpenTelemetry GenAI support for that path is planned.

## Review guidelines

Reviews (local assistant passes during development, and automated PR review) check, in order:

1. **Async safety** — any `asyncio.` import or raw asyncio primitive.
2. **Types** — `Any` in public signatures; data structures that are not Pydantic models.
3. **Backend boundary** — provider SDK imports or LLM HTTP calls outside `LLMBackend` implementations and the transport proxy.
4. **Portability** — any import of `agentloom` outside the optional AgentLoom backend; it must stay guarded so `pip install agentanvil` works without extras.
5. **Contract as source of truth** — hardcoded policies or criteria that should come from the `AgentContract`.
6. **Observability names** — span attribute or metric strings hardcoded instead of imported from `agentloom.contracts` (once AgentLoom 0.5.0 ships it).
7. **Errors** — framework-level failures raised as bare `ValueError` / `KeyError` instead of an `AgentAnvilError` subclass.
8. **Tests** — real API calls (mock with `httpx.MockTransport`), sleeps used for synchronisation, record/replay tests that are not byte-for-byte deterministic.
9. **Versions** — public API changes without a `CHANGELOG.md` entry; version bumps that skip one of `pyproject.toml` / `CHANGELOG.md` / `__version__`.

Do not flag style or lint issues: ruff and `mypy --strict` run in CI.

## Skills

Reusable task prompts (check, review, commit, pr, release, …) live in `.agents/skills/`. Claude Code loads them through the `.claude/skills` symlink; other assistants can read the `SKILL.md` files directly.
