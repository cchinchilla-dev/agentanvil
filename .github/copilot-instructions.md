# Copilot Code Review Instructions

## Project

AgentAnvil is a testing and evaluation platform for LLM agents. Python 3.11+, async (anyio), Pydantic v2. Uses AgentLoom as LLM gateway.

## Review priorities

1. **Async safety** — all async code must use `anyio`, never raw `asyncio`. Flag any `asyncio.` import.
2. **Type annotations** — no `Any` in public signatures. Pydantic models for all data structures.
3. **LLM calls via AgentLoom** — never call LLM APIs directly. All model interactions go through `agentloom.ProviderGateway`.
4. **Contract as source of truth** — all evaluation logic must derive from the `AgentContract`. No hardcoded policies or criteria.
5. **AgentWarp constants** — never hardcode span attribute strings. Always use `SpanAttr.*` from `agentwarp`.
6. **Test quality** — `pytest-asyncio` auto mode. No real API calls in tests.

## Style

- Commit messages: short imperative phrase, no body, lowercase.
- Squash merge only.
- Ruff for lint and format (config in `pyproject.toml`).
- mypy strict mode.
