---
name: pr
description: Open a pull request for the current branch following the repo's title, body and label conventions. Use when the user asks to open or draft a PR.
---

Open a PR for the current branch.

## Process

1. **Pre-flight**
   - Run the `check` skill. Warn (don't block); the user may want a draft anyway.
   - Verify the lockfile is in sync: `uv lock --check`. If it fails, run `uv lock` and include `uv.lock` in the branch (its own commit when it's housekeeping, folded in when a dependency change caused it).

2. **Gather context**
   - `git log main..HEAD --oneline`
   - `git diff main...HEAD --stat`
   - `git diff main...HEAD` — read the actual diff
   - Look at the last 3–5 merged PRs for title/label conventions: `gh pr list --state merged --limit 5 --json number,title,labels`

3. **Title** — Conventional Commits with scope (matches the commit-message convention enforced in `AGENTS.md`):

   ```
   <type>(<scope>): <imperative lowercase description>
   ```

   - Types: `feat`, `fix`, `chore`, `ci`, `test`, `docs`, `refactor`, `perf`, `build`, `style`.
   - Scope: pick the most representative scope of the PR. Common scopes: `backends`, `core`, `runner`, `record-replay`, `cli`, `release`, `deps`, `version`, `meta`, `evaluator`, `analyzer`, `reporter`, `runtime`, `contracts`, `foundation` (for cross-cutting bootstrap PRs).
   - Several scopes go comma-separated, no spaces: `feat(core,steps): …`.
   - The PR title becomes the squash-merge commit title on `main` (repo setting), so consistency with the commit-message style matters.
   - Release PRs are the exception: exactly `bump version to <X.Y.Z>`, no type or scope (see the `release` skill).
   - If the PR closes an issue, append `(#<issue>)` — e.g. `feat(backends): add streaming support for LLM responses (#81)`.
   - Under 72 chars.

4. **Body** — pick the format by PR size. Substantive PRs follow the repo template (`.github/PULL_REQUEST_TEMPLATE.md`, four sections); small PRs may use the short format.

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

   - [x] <auto-check if the `check` skill passed, else manual>
   ```

   No emojis. Drop `Closes #<issue>` if the PR has no linked issue.

   Notes guidance:
   - Keep concise (2–4 bullets for substantive PRs, 0–2 for small ones).
   - Surface deferred items, cross-repo coupling, intentional inconsistencies, or non-obvious caveats.
   - Skip restating what's already in `What` / `Why`.

5. **Labels** — `pr-labeler` auto-applies labels from `.github/labeler.yml` based on changed paths and branch (`core`, `cli`, `backends`, `runner`, `ci`, `dependencies`, `documentation`, `release` for `release/*` branches). Add general categories (`enhancement`, `bug`) explicitly via `--label` because the labeler does not infer them from paths.

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
   Add `--draft` if the argument contains "draft".

8. **Report** the PR URL. Don't poll CI — let the user run the `ci-status` skill.
