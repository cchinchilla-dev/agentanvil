# Contributing to AgentAnvil

Thanks for considering a contribution. Here's how to get started.

## Setup

```bash
git clone https://github.com/<your-user>/agentanvil.git
cd agentanvil
git remote add upstream https://github.com/cchinchilla-dev/agentanvil.git

uv sync --group dev
uv run pre-commit install   # ruff and version-linearity on every commit
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
  call LLM HTTP endpoints from business logic. `DirectBackend` (httpx-only,
  the portability target) ships today; `AgentLoomBackend` (optional via
  `agentanvil[agentloom]`) is planned in #9.
- `ruff` handles formatting and linting.
- `mypy --strict` must pass.

## Tests

- Use `pytest` with `pytest-asyncio` (auto mode).
- No real API calls in tests — mock via `httpx.MockTransport`.
- Place tests mirroring the source tree: `tests/core/`, `tests/backends/`,
  `tests/runner/`, `tests/record_replay/`, `tests/cli/`; CI helpers under
  `tests/ci/` and `tests/scripts/`.

## Versioning

When bumping the version, update `pyproject.toml`, `CHANGELOG.md` and
`__version__` in `src/agentanvil/__init__.py` in the same commit. The `version-linearity` CI job fails when they disagree.

## Commit messages

Conventional-Commits style with scope:

```
feat(backends): add LLMBackend ABC with Pydantic message and response types
fix(runner): honour timeout when child process spawns subprocesses
chore(deps): bump httpx to 0.28.1
ci(version): add version-linearity gate
docs(record-replay): document recording envelope schema v1
refactor(backends): extract provider client base class to reduce duplication
test(backends): add ABC contract suite with MockBackend fixture
```

- Imperative mood, lowercase after the colon.
- No body unless explicitly justified — single-line description.
- Common scopes: `backends`, `core`, `runner`, `record-replay`, `cli`,
  `release`, `deps`, `version`, `meta`, `evaluator`, `analyzer`, `reporter`.
- Several scopes go comma-separated, without spaces: `feat(core,steps): …`.
- PR-merge commits append `(#NN)` and may include `(#issue)` references.
- Release commits are the one exception: exactly `bump version to X.Y.Z`,
  with no type or scope. `auto-tag.yml` only tags commits that start with
  that prefix.

The PR title becomes the squash-merge commit on `main`, so the same
convention applies to PR titles.

## Pull requests

- Keep PRs focused — one feature or fix per PR.
- Link issues: `Closes #123`.
- All CI checks must pass before merge.
- PRs are squash-merged.

## AI-assisted contributions

AI coding assistants are welcome. The project rules they need live in
[`AGENTS.md`](AGENTS.md), which most assistants read automatically.

The repository ships a small set of shared skills in [`.agents/skills/`](.agents/skills/)
for routine work on this repo: `check` (the local quality gate), `review`,
`commit`, `pr`, `release`, and a few more. Codex reads them from that folder,
Claude Code through the `.claude/skills` symlink, and any other assistant can
follow the `SKILL.md` files as plain instructions. They are optional: CI does
not depend on them.

Whatever tool wrote the code, the author of the pull request is responsible for
it: run the quality gate, read the diff, and be ready to explain any line.

## Review

- **During development** — the deep review happens before a pull request is
  opened. Review your own changes with an AI assistant, by hand, or both; a model
  from a different vendor than the one that wrote the code tends to catch more.
  The checklist is the *Review guidelines* section of `AGENTS.md`.
- **On the pull request** — CI must pass. [CodeRabbit](https://www.coderabbit.ai)
  posts a light automated review focused on bugs, security and the rules in
  `AGENTS.md`. Its comments are suggestions; a maintainer decides what to merge.
