---
name: roadmap
description: Create a release-tracking issue that organizes open issues into a phased roadmap. Pass a target version (e.g., `0.5.0`) to scope the plan.
---

Create a release-tracking issue (a "roadmap") that organizes open issues into a phased implementation plan. Matches the pattern used in AgentLoom's reference roadmap issue (`cchinchilla-dev/agentloom#133`).

`$ARGUMENTS` is the target version (e.g., `0.2.0`, `0.5.0`). If missing, ask.

## When to use this

For minor or major releases with coordinated scope — multiple issues with interdependencies, parallelization decisions worth communicating, or deferred items that need to be explicitly listed so they're not forgotten. Skip for patch releases (hotfixes, small cleanups); those ship directly from the Unreleased CHANGELOG section via `/release`.

## Process

1. **Scope conversation** — ask:
   - What drives this release? (foundational primitives, observability, security, new capabilities, mix?)
   - What is explicitly in-scope vs. deferred?
   - Critical path driver if any (e.g., a downstream consumer that needs specific features).

2. **Inventory** — run `gh issue list --state open --limit 200 --json number,title,labels`. Read bodies of non-trivial issues to understand cross-refs. Flag closed issues still referenced in open work.

3. **Phase structure** — organize issues by:
   - Criticality (correctness/security first).
   - Dependencies (foundations before features).
   - Parallelizability (independent work batched).
   - User-visible outcomes (what each phase unlocks).

   Typical shape for AgentAnvil milestones:
   - Phase 0: hygiene / foundation cleanup.
   - Phase 1: contract layer or evaluator layer (whichever the release targets).
   - Phase 2: backends / runners / record-replay extensions.
   - Phase 3+: feature waves (multi-agent, A2A, corpus, stats).
   - Last phase: case studies + reproducibility envelope hardening.

4. **Draft** — follow the body format used by the reference roadmap:
   - `### Description` with scope drivers and version-jump justification.
   - `### How to use this issue` explaining the task-list convention.
   - `## Phase N — <title>` per phase with rationale, task list of `- [ ] #NNN …`, parallelization notes.
   - `## Cross-phase dependency map` in ASCII.
   - `## What is deliberately not in <version>` with deferred issues grouped by category.
   - `## What <version> unlocks` with 3–5 concrete outcomes.
   - `## Issue inventory` table with per-phase counts.
   - `## Notes` — living document caveat.

   GitHub renders `- [ ] #NNN` as tracked tasks; use that syntax for every child reference.

   **Formatting constraints:**
   - No emojis, no colored markers (red/yellow/green dots). Plain text only.
   - ASCII arrows (`->`, `|`, `+`) in dependency maps, not unicode arrows.
   - Title format: `ship <version>: <short description>` — brief, lowercase imperative.

5. **Confirm** — show the full draft. Iterate on phase membership, deferred items, outcomes before creating.

6. **Create** — `gh issue create --title "ship <version>: …" --body-file /tmp/roadmap.md --label "release,enhancement"`. Return the issue URL.

## Notes

- The planning issue is a living document — editable after creation as scope clarifies.
- Task-list checkboxes auto-update when child issues close; progress aggregates at the top of the issue.
- `/release` references this issue for pre-flight validation: all referenced sub-tasks must be closed (or explicitly demoted from scope) before cutting the release.
- For AgentAnvil specifically: distinguish portable items (no AgentLoom dependency) from items that require the optional `agentanvil[agentloom]` extra. Note this in each issue's body and in the roadmap's "What is deliberately not in" section.
