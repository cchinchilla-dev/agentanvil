"""LLMBackend ABC — the portability boundary of AgentAnvil."""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from decimal import Decimal

from agentanvil.backends.types import LLMResponse, Message, ToolDef


class LLMBackend(abc.ABC):
    """Abstract LLM provider surface.

    Every concrete backend (`DirectBackend`, `AgentLoomBackend`, `MockBackend`,
    `RecordingBackend`) implements this contract. Higher layers — analyzer,
    runner, evaluator, reporter — never know which backend they hold.
    """

    name: str  # short identifier, e.g. "direct", "agentloom", "mock"

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[ToolDef] | None = None,
        seed: int | None = None,
        timeout_s: float | None = None,
        step_id: str | None = None,
    ) -> LLMResponse:
        """Issue a non-streaming completion.

        ``step_id`` is an optional caller-provided correlation identifier. It is
        ignored by network backends (`DirectBackend`, `AgentLoomBackend`) and
        only consumed by record/replay backends (`RecordingBackend` stores it,
        `MockBackend` looks it up before falling back to the request hash).
        """

    @abc.abstractmethod
    def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[ToolDef] | None = None,
        seed: int | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """Issue a streaming completion. Yields incremental `LLMResponse` chunks."""

    @abc.abstractmethod
    def cost_estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> Decimal:
        """Pre-call estimate. Used by the contract static analyzer's budget check."""
