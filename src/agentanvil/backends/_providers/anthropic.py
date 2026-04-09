"""Anthropic Messages wrapper used by `DirectBackend`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from agentanvil.backends._providers._base import ProviderClientBase
from agentanvil.backends.pricing import cost_for
from agentanvil.backends.types import LLMResponse, Message, ToolCall, ToolDef, Usage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_API_VERSION = "2023-06-01"


class AnthropicClient(ProviderClientBase):
    """Thin async wrapper over Anthropic's Messages endpoint."""

    provider = "anthropic"

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url or _DEFAULT_BASE_URL,
            default_base_url=_DEFAULT_BASE_URL,
            auth_headers={"x-api-key": api_key},
            extra_headers={
                "anthropic-version": _API_VERSION,
                "content-type": "application/json",
            },
        )

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
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            stream=False,
        )
        timeout = httpx.Timeout(timeout_s) if timeout_s is not None else None
        response = await self._http.post("/messages", json=payload, timeout=timeout)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
        seed: int | None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            stream=True,
        )
        async with self._http.stream("POST", "/messages", json=payload) as response:
            response.raise_for_status()
            async for chunk in self._iter_sse(response):
                yield chunk

    def normalise(self, raw: dict[str, Any], *, latency_ms: int) -> LLMResponse:
        usage = raw.get("usage", {}) or {}
        # Extended thinking exposes `thinking_input_tokens` / `thinking_output_tokens`
        # in newer revisions; fall back to 0 when absent.
        reasoning_tokens = int(
            usage.get("thinking_output_tokens") or usage.get("output_tokens_thinking") or 0
        )
        usage_obj = Usage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            reasoning_tokens=reasoning_tokens,
            cached_tokens=int(usage.get("cache_read_input_tokens", 0)),
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in raw.get("content", []) or []:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=str(block["id"]),
                        name=block["name"],
                        arguments=block.get("input", {}) or {},
                    )
                )

        cost = cost_for(
            "anthropic",
            raw.get("model", ""),
            input_tokens=usage_obj.input_tokens,
            output_tokens=usage_obj.output_tokens,
            reasoning_tokens=usage_obj.reasoning_tokens,
        )
        return LLMResponse(
            content="".join(text_parts) or None,
            tool_calls=tool_calls,
            usage=usage_obj,
            finish_reason=_normalise_stop_reason(raw.get("stop_reason")),
            latency_ms=latency_ms,
            cost_usd=cost,
            model=str(raw.get("model", "")),
            provider="anthropic",
            raw=raw,
        )

    def _payload(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
        stream: bool,
    ) -> dict[str, Any]:
        system_segments = [m.content for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_message_to_anthropic(m) for m in non_system],
            "temperature": temperature,
            "max_tokens": max_tokens or 1024,
            "stream": stream,
        }
        if system_segments:
            payload["system"] = "\n\n".join(
                segment for segment in system_segments if isinstance(segment, str)
            )
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ]
        return payload


def _message_to_anthropic(message: Message) -> dict[str, Any]:
    role = "user" if message.role == "user" else "assistant"
    if isinstance(message.content, str):
        return {"role": role, "content": message.content}
    return {
        "role": role,
        "content": [block.model_dump(exclude_none=True) for block in message.content],
    }


def _normalise_stop_reason(reason: str | None) -> FinishReason:
    mapping: dict[str, FinishReason] = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }
    return mapping.get(reason or "", "stop")


__all__ = ["AnthropicClient"]
