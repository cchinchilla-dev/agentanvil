# AI Attribution

This project is built with AI-assisted tooling as part of a standard 2026
software-engineering workflow — the same tools and practices the author uses
professionally in industry.

---

## Scope of AI assistance

AI tools were used for software engineering tasks: code generation, test
scaffolding, documentation drafting, code review, and release automation.

All architectural decisions, system design, component boundaries, and API
design are the author's own work.

---

## Tools

### Claude Code (Anthropic)

General-purpose development assistant used for code generation, test
scaffolding, documentation drafting, and iterative problem-solving throughout
the development lifecycle.

The workflow relies on a set of custom skills defined in
[`.claude/skills/`](.claude/skills/), each encapsulating a repeatable
engineering task that Claude Code executes on demand:

| Skill | Purpose |
|---|---|
| [`analyze`](.claude/skills/analyze/) | Deep pre-commit analysis: logic bugs, architectural violations, security, performance |
| [`check`](.claude/skills/check/) | Full quality gate: tests, lint (`ruff`), type check (`mypy`) |
| [`ci-status`](.claude/skills/ci-status/) | Inspect GitHub Actions runs, fetch logs, and suggest fixes on failure |
| [`gen-tests`](.claude/skills/gen-tests/) | Generate tests targeting edge cases and failure modes |
| [`issue`](.claude/skills/issue/) | Create, view, or triage GitHub issues from the terminal |
| [`pr`](.claude/skills/pr/) | Create pull requests with auto-generated description and label suggestions |
| [`release`](.claude/skills/release/) | Version bump, changelog generation, tagging, and push |
| [`review`](.claude/skills/review/) | Review staged/unstaged changes for bugs, style drift, and missing coverage |

### GitHub Copilot (GitHub / Microsoft)

Automated code review integrated in the GitHub pull-request workflow.
Project-specific review rules are defined in
[`.github/copilot-instructions.md`](.github/copilot-instructions.md).
Review findings appear in the git history as *"address review"* or
*"fix review findings"* follow-up commits.

---

## Development workflow

```
                    human                          AI-assisted
               ─────────────                  ─────────────────────
                     │                                │
              Design & scope                          │
              Define roadmap                          │
                     │                                │
                     ├───────────────────────> Issue creation (issue)
                     │                                │
              Implementation planning ◄──────► Implementation planning
                     │                                │
                     ├───────────────────────> Code generation
                     │                         Test scaffolding
                     │                         Documentation drafts
                     │                                │
              Functional testing                      │
              Exploratory testing              Quality gates (check)
              Agent evaluation validation      Pre-commit analysis (analyze)
                     │                                │
                     │                         PR creation (pr)
                     │                         Copilot code review
                     │                                │
              Review AI output                        │
              Address feedback                        │
              Merge decision                          │
                     │                                │
                     │                         Release preparation (release)
              Final validation                 CI pipeline execution
                     │                                │
                     v                                v
                              Production
```

1. **Scope** — Features are designed and scoped by the author.  GitHub issues
   are created in batches via the `issue` skill from human-defined
   specifications and roadmap priorities.
2. **Plan** — Before writing code, the author and AI collaborate on an
   implementation plan: component structure, API surface, error handling
   strategy, and test approach.  The author drives the technical decisions
   and validates the final plan.
3. **Implement** — Feature branches are developed with Claude Code as coding
   assistant, using the skills above for continuous quality assurance.
4. **Test** — Each feature is tested hands-on: contract validation, scenario
   generation, evaluator behaviour, CLI flows, and integration with AgentLoom.
   Infrastructure is validated locally: Kubernetes deployments, Helm charts,
   Docker builds, and ArgoCD sync are exercised end-to-end.
5. **Review** — Pull requests are reviewed by GitHub Copilot against
   project-specific standards.  Feedback is addressed before merging.
6. **Ship** — Releases are prepared with the `release` skill and validated
   through the CI pipeline.

---

## Human contribution

| Area | Activities |
|---|---|
| **Architecture and design** | Technology choices, system architecture, component boundaries, API design |
| **Specification** | Feature definition, acceptance criteria, contract schema design, evaluation metric design |
| **Functional testing** | Contract parsing, scenario execution, evaluator output validation, CLI verification |
| **Exploratory testing** | Edge cases, adversarial scenarios, fault injection modes, multi-agent simulation configs |
| **Infrastructure validation** | Local Kubernetes deployment, Helm chart verification, Docker builds, ArgoCD sync testing |
| **Code review and judgement** | Final review of AI-generated code, merge decisions, architectural sign-off |
| **Debugging** | Bug triage, root cause analysis, resolution of issues found during testing |
| **AI tooling curation** | Project rules for Copilot and Claude Code, skill definitions, prompt engineering |

---

## Verification and quality assurance

All AI-generated code passes through multiple verification layers before
reaching the main branch:

- **Automated quality gates** — `ruff` linting, `mypy` type checking, pytest,
  executed on every commit via the `check` skill and CI pipeline.
- **Independent AI code review** — GitHub Copilot reviews every pull request
  against project-specific standards, avoiding single-model bias.
- **Human review** — The author reviews all generated code for correctness,
  design coherence, and alignment with the project's architectural goals
  before merging.
- **Hands-on validation** — Contract evaluation flows, CLI commands,
  integration with AgentLoom, and infrastructure pipelines (Kubernetes
  deployments, Helm charts, Docker builds) are exercised end-to-end.

---

## Traceability

The complete development history is publicly available in this repository:
issues, pull requests, commits, and CI runs.  Every change is traceable to a
specific issue and pull request, providing full transparency into how each
feature was developed.
