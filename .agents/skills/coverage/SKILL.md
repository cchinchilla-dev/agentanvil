---
name: coverage
description: Close coverage gaps below the 85% `fail_under` threshold with real tests, or with a reasoned no-cover pragma when code is untestable. Use when the test job fails on coverage or new code lacks it.
---

Close gaps reported by `pytest --cov-report=term-missing` (CI fails below `fail_under = 85` in `pyproject.toml`).

## Process

1. **Find the gaps**
   ```
   uv run pytest tests/<area>/ --cov=agentanvil.<module> --cov-report=term-missing -q --no-cov-on-fail
   ```
   Read the `Missing` column — each number is a line or a range.

2. **Classify each gap**
   - **Testable** (real branch reachable from public API) → write a test. Prefer `FakeBackend` (`tests/backends/mock_backend.py`) for LLM calls, `httpx.MockTransport` for HTTP, and the recordings in `tests/fixtures/` for replay.
   - **Defensive / unreachable in practice** (a guard the caller already enforces) → `# pragma: no cover — <reason>`.
   - **Optional-extra path** (code that only runs with an extra such as `agentanvil[agentloom]` installed) → test it in a job that installs the extra if it exists; otherwise `# pragma: no cover — needs <extra>`.

3. **Always include a reason** after the `—`. A bare `# pragma: no cover` is a smell.

4. **Prefer tests over pragmas** when the branch is reachable from unit tests in under ~20 lines of setup. Use pragmas for:
   - Protocol/adapter entrypoints that only run under real sockets/processes
   - `if TYPE_CHECKING:` blocks
   - Defensive returns that exist only for type narrowing

5. **Verify**
   ```
   uv run pytest tests/<area>/ --cov=agentanvil.<module> --cov-report=term-missing -q --no-cov-on-fail
   ```
   Then run the `check` skill once the module is clean.
