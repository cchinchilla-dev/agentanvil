# Contributing to AgentAnvil

Thanks for considering a contribution. Here's how to get started.

## Setup

```bash
git clone https://github.com/<your-user>/agentanvil.git
cd agentanvil
git remote add upstream https://github.com/cchinchilla-dev/agentanvil.git

uv sync --group dev
uv run pytest
```

To install with optional backends or extras:

```bash
uv sync --group dev --extra agentloom    # AgentLoom backend
uv sync --group dev --all-extras         # everything (all extras bundle)
```

## Development workflow

1. Sync your fork: `git fetch upstream && git rebase upstream/main`
2. Create a branch: `git checkout -b feat/my-feature` (use `feat/`, `fix/`, `chore/`, `ci/`, `docs/`, `refactor/` prefixes).
3. Make your changes.
4. Run the quality gate:
   ```bash
   uv run pytest
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   uv run mypy src/
   ```
5. Push to your fork and open a pull request against `upstream/main`.

## Code style

- **Python 3.11+** with type hints on all public APIs.
- **Pydantic v2** for models and validation.
- **anyio** for async (never raw `asyncio`).
- **LLMBackend abstraction** for all LLM calls — never import provider SDKs or
  call LLM HTTP endpoints from business logic. Two backends ship today:
  `DirectBackend` (httpx-only, portability target) and `AgentLoomBackend`
  (recommended, optional via `agentanvil[agentloom]`).
- `ruff` handles formatting and linting.
- `mypy --strict` must pass.

## Tests

- Use `pytest` with `pytest-asyncio` (auto mode).
- No real API calls in tests — mock via `httpx.MockTransport` (preferred) or `respx`.
- Place tests mirroring the source tree: `tests/core/`, `tests/backends/`,
  `tests/runner/`, `tests/record_replay/`, `tests/ci/`.

## Versioning

When bumping the version, update **both** `pyproject.toml` and `CHANGELOG.md`
in the same commit. The `version-linearity` CI job fails when they disagree.

## Commit messages

Conventional-Commits style with scope:

```
feat(backends): add LLMBackend ABC with Pydantic message and response types
fix(runner): honour timeout when child process spawns subprocesses
chore(release): bump version to 0.2.0
ci(version): add version-linearity gate
docs(record-replay): document recording envelope schema v1
refactor(backends): extract provider client base class to reduce duplication
test(backends): add ABC contract suite with MockBackend fixture
```

- Imperative mood, lowercase after the colon.
- No body unless explicitly justified — single-line description.
- Common scopes: `backends`, `core`, `runner`, `record-replay`, `cli`,
  `release`, `deps`, `version`, `a2a`, `evaluator`, `analyzer`, `reporter`.
- PR-merge commits append `(#NN)` and may include `(#issue)` references.

## Pull requests

- Keep PRs focused — one feature or fix per PR.
- Link issues: `Closes #123`.
- All CI checks must pass before merge.
- PRs are squash-merged.
