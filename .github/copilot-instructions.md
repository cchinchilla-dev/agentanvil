# Copilot Code Review Instructions

## Project

AgentAnvil is a contract-based testing framework for LLM agents. Python 3.11+, async (`anyio`), Pydantic v2. Portable: works without AgentLoom via `DirectBackend`; uses AgentLoom as the recommended optional backend.

## Review priorities

1. **Async safety** — all async code must use `anyio`, never raw `asyncio`. Flag any `asyncio.` import.
2. **Type annotations** — no `Any` in public signatures. Pydantic v2 models for all data structures.
3. **LLM calls via the `LLMBackend` ABC** — never import provider SDKs or call LLM HTTP endpoints from business logic. Two backends ship: `DirectBackend` (httpx-only, no AgentLoom) and `AgentLoomBackend` (recommended, optional).
4. **Contract as source of truth** — all evaluation logic must derive from the `AgentContract`. No hardcoded policies or criteria.
5. **Observability constants from `agentloom.contracts`** — never hardcode span attribute names or metric names. Import enums (`SpanAttr`, `MetricName`) from `agentloom.contracts.stable` when integrating with the AgentLoom backend.
6. **Custom exceptions** — domain errors should subclass `AgentAnvilError` (`BackendError`, `RunnerError`, `RecordingError`, `ContractValidationError`). Avoid bare `ValueError` / `KeyError` for framework-level failures.
7. **Test quality** — `pytest-asyncio` auto mode. No real API calls in tests; mock via `httpx.MockTransport`.

## Style

- Commit messages: Conventional-Commits with scope (`feat(backends): …`, `fix(runner): …`, `chore(release): …`). Imperative, lowercase, no body unless explicitly required.
- Squash merge only.
- Ruff for lint and format (config in `pyproject.toml`).
- mypy `--strict` must pass.
- `from __future__ import annotations` at the top of every Python module that uses type hints.
