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

## Development workflow

1. Sync your fork: `git fetch upstream && git rebase upstream/main`
2. Create a branch: `git checkout -b my-feature`
3. Make your changes
4. Run the quality gate:
   ```bash
   uv run pytest
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   uv run mypy src/
   ```
5. Push to your fork and open a pull request against `upstream/main`

## Code style

- **Python 3.11+** with type hints on all public APIs
- **Pydantic v2** for models and validation
- **anyio** for async (never raw `asyncio`)
- **AgentLoom** for all LLM calls — never direct HTTP to model APIs
- **AgentWarp** constants for all span attribute names
- `ruff` handles formatting and linting
- `mypy --strict` must pass

## Tests

- Use `pytest` with `pytest-asyncio` (auto mode)
- No real API calls in tests — mock via `respx` or fixture providers
- Place tests mirroring the source tree: `tests/core/`, `tests/cli/`, etc.

## Commit messages

Short, lowercase, imperative mood:

```
add policy severity filtering to evaluator
fix contract yaml round-trip for enum fields
bump version to 0.2.0
```

## Pull requests

- Keep PRs focused — one feature or fix per PR
- Link issues: `Closes #123`
- All CI checks must pass before merge
- PRs are squash-merged
