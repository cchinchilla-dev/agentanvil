"""AgentAnvil — testing and evaluation framework for LLM agents.

Receives an agent (any Python code, any framework), runs it under a formalised
contract, subjects it to test scenarios, evaluates its behaviour with hybrid
metrics (objective + LLM-as-judge + human annotation with active sampling),
and produces reproducible results with a deterministic record/replay envelope.

LLM access flows through the `LLMBackend` abstraction. Two backends ship today:
`DirectBackend` (httpx-only, portability target — no AgentLoom required) and
`AgentLoomBackend` (recommended, optional via the ``agentanvil[agentloom]``
extra; pulls resilience and observability from AgentLoom).
"""

from agentanvil.core.contracts import AgentContract
from agentanvil.core.models import EvalResult, Scenario

__version__ = "0.1.1"

__all__ = [
    "AgentContract",
    "EvalResult",
    "Scenario",
]
