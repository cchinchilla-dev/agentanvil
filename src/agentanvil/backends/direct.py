"""DirectBackend — httpx-only `LLMBackend` for OpenAI, Anthropic and Google.

Zero vendor SDKs, zero AgentLoom dependency. The portability target.

Network errors and transient statuses are retried as its `RetryPolicy` says;
a failure that stays raises `BackendError`. No circuit breaker or shared rate
limiter: `AgentLoomBackend` (#9) brings those.
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
from agentanvil.backends.retry import RetryPolicy, open_stream, with_retry
from agentanvil.backends.types import LLMResponse, Message, ToolDef
from agentanvil.exceptions import BackendError

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
        retry: RetryPolicy | None = None,
    ) -> None:
        self.provider = provider
        self._retry = retry or RetryPolicy()
        self._client: ProviderClientBase
        if provider == "openai":
            self._client = openai.OpenAIClient(api_key=api_key, base_url=base_url)
        elif provider == "anthropic":
            self._client = anthropic.AnthropicClient(api_key=api_key, base_url=base_url)
        elif provider == "google":
            self._client = google.GoogleClient(api_key=api_key, base_url=base_url)
        else:
            raise BackendError(
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
        start = time.monotonic_ns()  # the latency includes any retries: the caller waited for them
        raw = await with_retry(
            self.provider,
            lambda: self._client.complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                seed=seed,
                timeout_s=timeout_s,
            ),
            self._retry,
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
        start = time.monotonic_ns()
        chunks = open_stream(
            self.provider,
            lambda: self._client.stream(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                seed=seed,
            ),
            self._retry,
        )
        async for response in self._client.normalise_stream(chunks, model=model, start_ns=start):
            yield response

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
