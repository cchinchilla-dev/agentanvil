"""Pydantic primitives shared by every `LLMBackend` implementation.

These types form the public surface of the LLM boundary — they are what flows
in and out of `LLMBackend.complete` / `LLMBackend.stream`. Keeping them
backend-agnostic is what guarantees AgentAnvil's portability invariant.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ContentBlock(BaseModel):
    """A single content fragment inside a `Message`.

    Multimodal-capable but optional — a plain text message uses a `str` for
    `Message.content` and skips this entirely.
    """

    type: Literal["text", "image", "audio"]
    text: str | None = None
    image_url: str | None = None
    image_data: bytes | None = None

    @model_validator(mode="after")
    def _exclusive_image_source(self) -> ContentBlock:
        if self.type == "image" and (self.image_url is None) == (self.image_data is None):
            raise ValueError("image content blocks require exactly one of image_url or image_data")
        return self


class ToolDef(BaseModel):
    """A tool the agent may invoke during a completion."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema fragment


class ToolCall(BaseModel):
    """A tool invocation emitted by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


class Message(BaseModel):
    """One conversational turn passed to or returned by the backend."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentBlock]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """Token-level cost accounting for a single completion."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0  # o1, o3, Claude extended thinking
    cached_tokens: int = 0


class LLMResponse(BaseModel):
    """The normalised return shape of every backend."""

    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "error"]
    latency_ms: int
    cost_usd: Decimal
    model: str
    provider: str
    raw: dict[str, Any] = Field(default_factory=dict)  # opaque provider payload for debugging
