# AgentAnvil

Testing and evaluation framework for LLM agents.

Receives an agent (any Python code, any framework), runs it under a formalised contract, subjects it to test scenarios, evaluates its behaviour with **hybrid metrics** (objective + LLM-as-judge + human annotation with active sampling), and produces reproducible results with a deterministic replay envelope.

AgentAnvil is portable across the LLM ecosystem. It accepts two LLM backends:

- **AgentLoom** (recommended) — [cchinchilla-dev/agentloom](https://github.com/cchinchilla-dev/agentloom). Production-grade runtime with resilience (circuit breaker, rate limiter, fallback), observability (OpenTelemetry, Prometheus), cost control, and built-in record/replay for deterministic experiments.
- **Direct providers** — OpenAI, Anthropic, Google via `DirectBackend` (thin httpx adapter). No AgentLoom required. Use this to integrate AgentAnvil with LangChain / LangGraph / CrewAI / AutoGen agents without adopting additional dependencies.

## Install

```bash
# Minimal — works with direct LLM providers (no AgentLoom required)
pip install agentanvil

# Recommended — with AgentLoom as backend for resilience, observability, record/replay
pip install "agentanvil[agentloom]"

# With Docker runner
pip install "agentanvil[docker]"

# All extras
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

**3. Run an evaluation (direct backend, no AgentLoom):**

```bash
export OPENAI_API_KEY=sk-...
agentanvil run path/to/agent/ \
  --contract contract.yaml \
  --backend direct \
  --provider openai \
  --threshold 0.85
```

**4. Run an evaluation (AgentLoom backend with record for replay):**

```bash
agentanvil run path/to/agent/ \
  --contract contract.yaml \
  --backend agentloom \
  --record recordings/run1.json \
  --budget 10.0
```

**5. Replay offline (CI, reproducible, no API cost):**

```bash
agentanvil run path/to/agent/ \
  --contract contract.yaml \
  --replay recordings/run1.json
```

**6. As a library:**

```python
from agentanvil import AgentAnvil, AgentContract
from agentanvil.backends import DirectBackend  # or AgentLoomBackend

contract = AgentContract.from_yaml("contract.yaml")
ashut = AgentAnvil(contract=contract, backend=DirectBackend(provider="openai"))
result = ashut.run(agent_path="./my_agent/")
print(result.score, result.passed)
```

## Architecture

```
AgentAnvil
├── Contracts   — formal model of expected agent behaviour (YAML + Python + static analysis)
├── Analyzer    — static analysis of agent code (AST, no LLM required)
├── Generator   — auto-generate test scenarios from contract + agent profile
├── Runner      — execute scenarios: SubprocessRunner, DockerRunner (K8sRunner planned for 0.4.0)
├── Evaluator   — hybrid metrics: objective + LLM-judge + human (active sampling)
├── Reporter    — HTML, JSON, and Markdown reports + CI quality gate
└── Record/Replay envelope — deterministic replay of LLM responses for reproducibility
```

## Ecosystem

```
agentanvil
├── pydantic, httpx, pyyaml, typer, rich, anyio
└── [extra: agentloom]
    └── agentloom[observability]
        └── agentloom.contracts   (submodule — OTel span names, metric names, trace schemas)
```

The `agentloom.contracts` submodule is the typed contract between AgentLoom (emitter of OTel traces and Prometheus metrics) and AgentAnvil (consumer). It is installed automatically with `agentanvil[agentloom]` and can also be installed alone via `pip install agentloom[contracts]` for third-party consumers that want the schema without the runtime.

When using `DirectBackend`, AgentAnvil emits and consumes OpenTelemetry GenAI semantic conventions directly — no coupling to AgentLoom.

## What AgentAnvil is not

- Not a replacement for DSPy / TextGrad / ProTeGi. Automatic prompt optimisation is out of scope.
- Not a replacement for LangSmith / LangFuse / Phoenix. It is a testing layer that consumes observability, not a production observability platform.
- Not a replacement for Docker or Kubernetes — it uses them.

## Status

Early alpha. See the [roadmap](https://github.com/cchinchilla-dev/agentanvil/issues) for the 0.2.0 MVP plan.

## License

MIT
