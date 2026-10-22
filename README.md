<p align="center">
  <a href="https://github.com/cchinchilla-dev/agentanvil">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/cchinchilla-dev/agentanvil/main/docs/images/header_dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/cchinchilla-dev/agentanvil/main/docs/images/header_light.svg">
      <img src="https://raw.githubusercontent.com/cchinchilla-dev/agentanvil/main/docs/images/header_light.svg" alt="AgentAnvil">
    </picture>
  </a>
</p>
<p align="center">
  <strong>Testing and evaluation framework for LLM agents.</strong>
</p>

AgentAnvil tests LLM agents against a formal contract. The target design takes an agent (any Python code, any framework), runs it under the contract, exercises it with test scenarios, checks its behaviour with **several oracles** (contract checks, environment state and protocol conformance, replay-based regression, and a panel of LLM judges backed by human annotation with active sampling), and keeps every run reproducible through a deterministic record/replay envelope. Only part of that pipeline ships today; the status note below says which.

> **Status: early alpha (0.1.x).** The contract model, the LLM backend boundary, the subprocess runner, and record/replay are implemented; a transport proxy that records and replays any runtime at the HTTP boundary is unreleased. Scenario generation, evaluation, and reporting are planned for 0.2.0; the [0.2.0 roadmap](https://github.com/cchinchilla-dev/agentanvil/issues/18) tracks them. Each item below is marked as available or planned.

AgentAnvil is portable across the LLM ecosystem. All LLM access goes through one `LLMBackend` boundary with two implementations:

- **Direct providers** (available) — OpenAI, Anthropic, and Google through `DirectBackend`, a thin httpx adapter. No AgentLoom required, so it fits agents built with LangChain, LangGraph, CrewAI, or AutoGen without extra dependencies.
- **AgentLoom** (planned, [#9](https://github.com/cchinchilla-dev/agentanvil/issues/9)) — [cchinchilla-dev/agentloom](https://github.com/cchinchilla-dev/agentloom) as backend, adding resilience (circuit breaker, rate limiter, fallback), observability (OpenTelemetry, Prometheus), and cost control.

## Install

```bash
# Core: contracts, DirectBackend, SubprocessRunner, record/replay
pip install agentanvil

# Installs AgentLoom alongside; the backend that uses it lands in 0.2.0 (#9)
pip install "agentanvil[agentloom]"

# All optional extras
pip install "agentanvil[all]"
```

## Quick start

**1. Define a contract:**

```yaml
# contract.yaml
name: my-agent
version: "1.0"
policies:
  - id: no_pii_leak
    description: Never reveal customer PII
    severity: critical
    check: llm
tasks:
  - id: answer_question
    description: Answer user questions accurately
    oracle: hybrid
constraints:
  max_latency_ms: 3000
  max_cost_per_interaction_usd: 0.05
```

**2. Validate it:**

```bash
agentanvil validate contract.yaml
```

**3. Use the building blocks from Python:**

```python
import os

import anyio

from agentanvil import AgentContract
from agentanvil.backends import Message
from agentanvil.backends.direct import DirectBackend

contract = AgentContract.from_yaml("contract.yaml")
backend = DirectBackend("openai", api_key=os.environ["OPENAI_API_KEY"])


async def main() -> None:
    reply = await backend.complete(
        [Message(role="user", content="Say hello in one word.")],
        model="gpt-4o-mini",
    )
    print(contract.name, reply.content, reply.cost_usd)


anyio.run(main)
```

`agentanvil run` exists but is a placeholder until the evaluation pipeline lands in 0.2.0 ([#18](https://github.com/cchinchilla-dev/agentanvil/issues/18)).

## Record and replay at the HTTP boundary (unreleased)

`agentanvil proxy` runs an OpenAI-compatible proxy in front of any server (vLLM, SGLang, a hosted API), so agents that do not call AgentAnvil's backend can be recorded too: point the agent's base URL at it and every call is logged. A later session can replay those calls, replay only the first ones and continue live, or compare a new run with the recorded one call by call. Per session, it also fixes or varies the sampling seed and the order of tools. Details in [docs/transport-proxy.md](docs/transport-proxy.md).

```bash
agentanvil proxy --log-dir recordings
# open a session (POST /_anvil/sessions), then use
# http://127.0.0.1:8090/s/<session>/agent/v1 as the agent's base URL
```

## Architecture

```
AgentAnvil
├── Contracts      — formal model of expected agent behaviour (YAML ↔ Pydantic)        available
│                    static consistency analysis                                        planned (#4)
├── Backends       — LLMBackend boundary: DirectBackend                                 available
│                    AgentLoomBackend                                                   planned (#9)
├── Runner         — SubprocessRunner                                                   available
│                    DockerRunner (#7); K8sRunner later                                 planned
├── Record/Replay  — deterministic replay envelope for LLM responses                    available
│                    transport proxy: any runtime, at the HTTP boundary                 unreleased
├── Analyzer       — static analysis of agent code (AST, no LLM required)               planned (#5)
├── Generator      — test scenarios from contract + agent profile                       planned (#6)
├── Evaluator      — oracles: objective + LLM-judge panel + human (active sampling)     planned (#10, #11)
└── Reporter       — HTML, JSON, and Markdown reports + CI quality gate                 planned (#12)
```

## Ecosystem

```
agentanvil
├── pydantic, httpx, pyyaml, typer, rich, anyio
└── [extra: agentloom]
    └── agentloom
        └── agentloom.contracts   (planned for AgentLoom 0.5.0 — shared types and observability names)
```

`agentloom.contracts` will be the typed boundary between AgentLoom (which emits OTel traces and Prometheus metrics) and AgentAnvil (which consumes them). Its design is tracked in [agentloom#159](https://github.com/cchinchilla-dev/agentloom/issues/159); the `agentloom` extra will require it once AgentLoom 0.5.0 is on PyPI.

With `DirectBackend`, AgentAnvil does not depend on AgentLoom at all; OpenTelemetry GenAI support for that path is planned.

## What AgentAnvil is not

- Not a replacement for DSPy / TextGrad / ProTeGi. Automatic prompt optimisation is out of scope.
- Not a replacement for LangSmith / LangFuse / Phoenix. It is a testing layer that consumes observability, not a production observability platform.
- Not a replacement for Docker or Kubernetes — it uses them.

## Status

Early alpha. The [0.2.0 roadmap](https://github.com/cchinchilla-dev/agentanvil/issues/18) covers the single-agent MVP: AgentLoom backend, analyzer, generator, evaluator, reporter, and a LangChain quickstart.

## License

MIT
