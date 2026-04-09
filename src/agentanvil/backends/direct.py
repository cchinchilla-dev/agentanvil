"""DirectBackend — httpx-only `LLMBackend` for OpenAI, Anthropic and Google.

Zero vendor SDKs, zero AgentLoom dependency. The portability target.

Hardening (rate limits, retries, reconnect, multi-modal routing, full streaming
robustness) lands in 0.2.0 #015. This is the skeleton.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Literal

from agentanvil.backends._providers import anthropic, google, openai
from agentanvil.backends._providers._base import ProviderClientBase
from agentanvil.backends.base import LLMBackend
from agentanvil.backends.pricing import cost_for
from agentanvil.backends.types import LLMResponse, Message, ToolDef

ProviderName = Literal["openai", "anthropic", "google"]


class DirectBackend(LLMBackend):
    """Provider-direct backend. Dispatches to a thin httpx wrapper per vendor."""

    name = "direct"

    def __init__(
        self,
        provider: ProviderName,
        api_key: str,
        *,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self._client: ProviderClientBase
        if provider == "openai":
            self._client = openai.OpenAIClient(api_key=api_key, base_url=base_url)
        elif provider == "anthropic":
            self._client = anthropic.AnthropicClient(api_key=api_key, base_url=base_url)
        elif provider == "google":
            self._client = google.GoogleClient(api_key=api_key, base_url=base_url)
        else:
            raise ValueError(
                f"Unknown provider {provider!r}; expected one of ('openai', 'anthropic', 'google')"
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
        step_id: str | None = None,  # noqa: ARG002 — ABC contract; not used by network backends
    ) -> LLMResponse:
        start = time.monotonic_ns()
        raw = await self._client.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
            timeout_s=timeout_s,
        )
        latency_ms = (time.monotonic_ns() - start) // 1_000_000
        return self._client.normalise(raw, latency_ms=latency_ms)

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
        async for chunk in self._client.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
        ):
            yield self._client.normalise(chunk, latency_ms=0)

    def cost_estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> Decimal:
        return cost_for(
            self.provider,
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )
