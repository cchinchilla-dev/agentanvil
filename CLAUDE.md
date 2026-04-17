# AgentAnvil

## Build & test
- `uv sync --group dev` — install (core only, no AgentLoom)
- `uv sync --group dev --extra agentloom` — install with AgentLoom as LLM backend
- `uv sync --group dev --extra all` — install with all extras (AgentLoom + Docker runner)
- `uv run pytest` — tests
- `uv run ruff check src/ tests/` — lint
- `uv run ruff format src/ tests/` — format
- `uv run mypy src/` — strict type check
- `agentanvil validate examples/contract.yaml` — validate a contract

## Rules

**Async**: always `anyio`, never raw `asyncio`.

**Models**: Pydantic v2 everywhere. No `Any` in public signatures.

**LLM calls**: always go through the `LLMBackend` boundary in `src/agentanvil/backends/base.py`. Never import provider SDKs or call LLM HTTP endpoints directly from business logic. Two backends are supported: `AgentLoomBackend` (recommended, pulls resilience and observability from AgentLoom) and `DirectBackend` (httpx-only, for adopters who don't want AgentLoom).

**Contracts**: the source of truth for what to test. All modules (Generator, Evaluator, Reporter) derive their behaviour from the `AgentContract`.

**Portability**: AgentAnvil must remain operable without AgentLoom. CI runs the test matrix with both backends. A LangChain quickstart using `DirectBackend` must complete in under 10 minutes for a new user. Do not introduce hard dependencies on AgentLoom in core modules.

## Architecture (read these first)
- `core/contracts.py` — `AgentContract`, `Policy`, `Task`, `Constraints` — YAML ↔ Pydantic
- `core/models.py` — shared types: `TestScenario`, `EvalResult`, `ScoreBreakdown`
- `backends/base.py` — `LLMBackend` ABC (the portability boundary)
- `backends/direct.py` — httpx-only backend for OpenAI, Anthropic, Google
- `backends/agentloom.py` — AgentLoom-backed implementation
- `runner/` — `SubprocessRunner` (default), `DockerRunner`. K8sRunner planned for 0.4.0.
- `evaluator/` — hybrid evaluator (objective + LLM-judge + human with active sampling)
- `cli/main.py` — Typer CLI entry point

## Observability contract

Span attribute names, metric names, and trace schemas live in `agentloom.contracts` (submodule of AgentLoom). Import from there when using the AgentLoom backend:

```python
from agentloom.contracts.spans import SpanAttr
from agentloom.contracts.schemas import StepTrace
```

Never hardcode span attribute strings — always go through the constants. This guarantees that when AgentLoom renames an attribute the CI catches the mismatch at the AgentAnvil side.

When using `DirectBackend`, AgentAnvil emits and consumes OpenTelemetry GenAI semantic conventions directly, without depending on AgentLoom.

**Historical note:** a separate package named `agentwarp` was previously planned to host these contracts as an independent PyPI package. That plan was reversed after an architectural review (see `/Users/Admin/Documents/PhD/scope-justification.md` in the author's PhD repository for the rationale). The submodule `agentloom.contracts` replaces it from AgentLoom 0.5.0 onward.

## Role in the PhD thesis

AgentAnvil is the central artefact of article 2 of the doctoral compendium (target venue TSE Q1) and the experimental instrument of article 3 (target TSE/EMSE Q1). It materialises OE2 (contracts), OE3 (architecture + reproducibility envelope) and OE4 (hybrid evaluator) of the thesis proposal. See `/Users/Admin/Documents/PhD/planteamiento.md` and `/Users/Admin/Documents/PhD/agentanvil-planteamiento.md` in the PhD repository for the full framing.
