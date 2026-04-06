"""Tiny test-only `LLMBackend` used to exercise the ABC contract suite.

Lives under `tests/` rather than `src/` so it does not ship in the wheel. The
production-grade replay backend is `agentanvil.record_replay.mock.MockBackend`
(added in #006).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import LLMResponse, Message, ToolDef, Usage


class FakeBackend(LLMBackend):
    """Deterministic backend that always returns the same canned response."""

    name = "fake"

    def __init__(
        self,
        *,
        canned: LLMResponse | None = None,
        per_token_usd: Decimal = Decimal("0.000001"),
    ) -> None:
        self._canned = canned
        self._per_token_usd = per_token_usd

    def _default_response(self, model: str) -> LLMResponse:
        return LLMResponse(
            content="ok",
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason="stop",
            latency_ms=1,
            cost_usd=Decimal("0"),
            model=model,
            provider="fake",
        )

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
        return self._canned or self._default_response(model)

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[ToolDef] | None = None,
        seed: int | None = None,
    ) -> AsyncIterator[LLMResponse]:
        yield self._canned or self._default_response(model)

    def cost_estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> Decimal:
        return self._per_token_usd * (input_tokens + output_tokens + reasoning_tokens)
