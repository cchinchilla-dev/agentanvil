"""Shared provider client scaffolding extracted from the per-vendor modules.

Each concrete provider (`OpenAIClient`, `AnthropicClient`, `GoogleClient`)
inherits from `ProviderClientBase` to share:

- `httpx.AsyncClient` lifecycle and default timeout.
- Server-Sent-Events (SSE) line iteration helper.
- Provider name field used by `DirectBackend`.

Vendor-specific concerns (auth header shape, payload encoding, response
normalisation) stay in the per-provider module.
"""

from __future__ import annotations

import abc
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from agentanvil.backends.types import LLMResponse, Message, ToolDef

_DEFAULT_TIMEOUT_S = 60.0


class ProviderClientBase(abc.ABC):
    """Shared httpx scaffolding + abstract surface every vendor client implements."""

    provider: str = ""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_base_url: str,
        auth_headers: Mapping[str, str] | None = None,
        extra_headers: Mapping[str, str] | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or default_base_url).rstrip("/")
        headers: dict[str, str] = {}
        if auth_headers:
            headers.update(auth_headers)
        if extra_headers:
            headers.update(extra_headers)
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    async def _iter_sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded JSON payloads from a `data: ` SSE stream.

        Stops on the canonical `[DONE]` sentinel. Lines that do not start with
        `data: ` are ignored (keep-alives, comments).
        """
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                return
            yield json.loads(payload)

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
        seed: int | None,
        timeout_s: float | None,
    ) -> dict[str, Any]:
        """Issue a non-streaming completion. Returns the raw vendor response."""

    @abc.abstractmethod
    def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
        seed: int | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Issue a streaming completion. Yields raw vendor SSE chunks."""

    @abc.abstractmethod
    def normalise(self, raw: dict[str, Any], *, latency_ms: int) -> LLMResponse:
        """Convert a raw vendor response into the canonical `LLMResponse`."""
