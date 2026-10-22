"""AgentAnvil — testing and evaluation framework for LLM agents.

Receives an agent (any Python code, any framework), runs it under a formalised
contract, subjects it to test scenarios, checks its behaviour with several
oracles (contract checks, environment state and protocol conformance,
replay-based regression, and a panel of LLM judges backed by human annotation
with active sampling), and produces reproducible results with a deterministic
record/replay envelope.

LLM access flows through the `LLMBackend` abstraction. `DirectBackend`
(httpx-only, portability target — no AgentLoom required) ships today;
`AgentLoomBackend` (optional via the ``agentanvil[agentloom]`` extra, pulling
resilience and observability from AgentLoom) is planned for 0.2.0.
"""

from agentanvil.core.contracts import AgentContract
from agentanvil.core.models import EvalResult, Scenario

__version__ = "0.1.1"

__all__ = [
    "AgentContract",
    "EvalResult",
    "Scenario",
]
