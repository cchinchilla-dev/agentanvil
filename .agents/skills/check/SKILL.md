---
name: check
description: Run the local quality gate (format, lint, types, tests) with the same checks as CI. Use after any code change and before committing or opening a PR.
---

Run the gate in this order, stopping at the first real failure. Each step mirrors a job in `.github/workflows/ci.yml`; exact commands also live in AGENTS.md.

1. **Format** — `uv run ruff format src/ tests/`. Reformatted files are expected; list them and leave staging to the user (or the `commit` skill).
2. **Lint** — `uv run ruff check src/ tests/`. Auto-fix when safe (`--fix`); escalate anything that needs a design call.
3. **Types** — `uv run mypy src/`. Report offending files and lines.
4. **Tests** — `uv run pytest -q --cov=agentanvil`. CI fails below the 85% `fail_under` in `pyproject.toml`; report the total. On failure, identify the test and the root cause — don't just relay the traceback.
5. **Determinism** — `uv run pytest tests/ci/test_determinism.py -m slow -q` (the `slow` tests are a separate CI job).
6. **Version linearity** — `uv run python scripts/check_version_linearity.py` (`pyproject.toml` and `CHANGELOG.md` must agree).

`make check` runs the same gates non-interactively (check-only, no auto-fix). Fix what you can. Only escalate when a failure needs a decision. If coverage drops below the threshold, use the `coverage` skill.

If everything passes, one line: `<N> passed, coverage <X>%, format+lint+types+determinism+version clean`.
