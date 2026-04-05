"""LLM backend abstraction.

Every LLM call inside AgentAnvil flows through a concrete `LLMBackend`
implementation. Two backends are shipped:

- `DirectBackend` (this package) — httpx-only adapter for OpenAI, Anthropic and
  Google. Zero AgentLoom dependency. The portability target.
- `AgentLoomBackend` (added in 0.2.0) — delegates to AgentLoom for resilience,
  observability and budget enforcement. Optional, gated behind the
  ``agentanvil[agentloom]`` extra.
"""

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import (
    ContentBlock,
    LLMResponse,
    Message,
    ToolCall,
    ToolDef,
    Usage,
)

__all__ = [
    "ContentBlock",
    "LLMBackend",
    "LLMResponse",
    "Message",
    "ToolCall",
    "ToolDef",
    "Usage",
]
