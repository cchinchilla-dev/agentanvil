---
name: pr
description: Create a pull request from the current branch, matching the repo's PR conventions (What/Why/Testing for features, Summary/Test-plan for small PRs).
---

Open a PR for the current branch.

## Process

1. **Pre-flight** — run `/check`. Warn (don't block); the user may want a draft anyway.

2. **Gather context**
   - `git log main..HEAD --oneline`
   - `git diff main...HEAD --stat`
   - `git diff main...HEAD` — read the actual diff
   - Look at the last 3–5 merged PRs for title/label conventions: `gh pr list --state merged --limit 5 --json number,title,labels`

3. **Title** — Conventional Commits with scope (matches the commit-message convention enforced in `CLAUDE.md`):

   ```
   <type>(<scope>): <imperative lowercase description>
   ```

   - Types: `feat`, `fix`, `chore`, `ci`, `test`, `docs`, `refactor`, `perf`, `build`, `style`.
   - Scope: pick the most representative scope of the PR. Common scopes: `backends`, `core`, `runner`, `record-replay`, `cli`, `release`, `deps`, `version`, `a2a`, `evaluator`, `analyzer`, `reporter`, `runtime`, `contracts`, `foundation` (for cross-cutting bootstrap PRs).
   - The PR title becomes the squash-merge commit on `main`, so consistency with the commit-message style matters.
   - If the PR closes an issue, append `(#<issue>)` — e.g. `feat(backends): add streaming support for LLM responses (#81)`.
   - Under 70 chars.

4. **Body** — pick the format by PR size. The repo template is at `.github/PULL_REQUEST_TEMPLATE.md`; preserve its four sections.

   **Feature / substantive PRs** (new functionality, non-trivial refactor):
   ```
   ## What

   <1–2 sentence summary>

   - <bullet describing change 1>
   - <bullet describing change 2>

   ## Why

   <motivation, link to related issues/PRs>

   Closes #<issue>

   ## Testing

   - [x] `uv run pytest` passes (<N> tests)
   - [x] `uv run ruff check src/ tests/` clean
   - [x] `uv run mypy src/` clean
   - [x] <any extra check actually run, e.g. portability invariant, end-to-end smoke>

   ## Notes

   <2–4 bullets max — only deferrals, cross-repo coupling, or non-obvious choices>
   ```

   **Small PRs** (docs, single-file fixes, coverage bumps):
   ```
   ## Summary

   - <1–3 behavior-focused bullets>

   ## Test plan

   - [x] <auto-check if /check passed, else manual>
   ```

   No emojis. Drop `Closes #<issue>` if the PR has no public issue (the repo's default tracking lives in `plans/issues/`, gitignored — explain in Notes if a reviewer might wonder).

   Notes guidance:
   - Keep concise (2–4 bullets for substantive PRs, 0–2 for small ones).
   - Surface deferred items, cross-repo coupling, intentional inconsistencies, or non-obvious caveats.
   - Skip restating what's already in `What` / `Why`.

5. **Labels** — `pr-labeler` auto-applies labels from `.github/labeler.yml` based on changed paths (`core`, `cli`, `providers`, `ci`, `dependencies`, `documentation`, `release`). Add general categories (`enhancement`, `bug`, `breaking`) explicitly via `--label` because the labeler does not infer them from paths.

6. **Push** (ask authorization first)
   - New branch: `git push --set-upstream origin <branch>`
   - Existing: `git push`

7. **Create**
   ```
   gh pr create --title "..." --body "$(cat <<'EOF'
   ...
   EOF
   )" --label "..."
   ```
   Add `--draft` if `$ARGUMENTS` contains "draft".

8. **Report** the PR URL. Don't poll CI — let the user run `/ci-status`.
