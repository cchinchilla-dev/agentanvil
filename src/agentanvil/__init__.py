"""AgentAnvil — testing and evaluation platform for LLM agents.

Receives an agent (any Python code, any framework), runs it in an isolated
environment, subjects it to test scenarios, evaluates its behaviour with hybrid
metrics (objective + LLM-as-judge + human annotation), and proposes iterative
improvements to its instructions.

Uses AgentLoom as the LLM gateway for all model interactions.
"""

from agentanvil.core.contracts import AgentContract
from agentanvil.core.models import EvalResult, Scenario

__version__ = "0.1.0"

__all__ = [
    "AgentContract",
    "EvalResult",
    "Scenario",
]
