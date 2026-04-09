"""OpenAI Chat Completions wrapper used by `DirectBackend`."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from agentanvil.backends._providers._base import ProviderClientBase
from agentanvil.backends.pricing import cost_for
from agentanvil.backends.types import LLMResponse, Message, ToolCall, ToolDef, Usage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIClient(ProviderClientBase):
    """Thin async wrapper over OpenAI's Chat Completions endpoint."""

    provider = "openai"

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url or _DEFAULT_BASE_URL,
            default_base_url=_DEFAULT_BASE_URL,
            auth_headers={"Authorization": f"Bearer {api_key}"},
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
            seed=seed,
            stream=False,
        )
        timeout = httpx.Timeout(timeout_s) if timeout_s is not None else None
        response = await self._http.post("/chat/completions", json=payload, timeout=timeout)
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
            seed=seed,
            stream=True,
        )
        async with self._http.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for chunk in self._iter_sse(response):
                yield chunk

    def normalise(self, raw: dict[str, Any], *, latency_ms: int) -> LLMResponse:
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = raw.get("usage", {}) or {}
        details = usage.get("completion_tokens_details", {}) or {}
        reasoning_tokens = int(details.get("reasoning_tokens", 0))
        cached_tokens = int((usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0))
        usage_obj = Usage(
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
        )
        tool_calls = [
            ToolCall(
                id=str(call["id"]),
                name=call["function"]["name"],
                arguments=json.loads(call["function"].get("arguments") or "{}"),
            )
            for call in message.get("tool_calls", []) or []
        ]
        cost = cost_for(
            "openai",
            raw.get("model", ""),
            input_tokens=usage_obj.input_tokens,
            output_tokens=usage_obj.output_tokens,
            reasoning_tokens=usage_obj.reasoning_tokens,
        )
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            usage=usage_obj,
            finish_reason=_normalise_finish_reason(choice.get("finish_reason")),
            latency_ms=latency_ms,
            cost_usd=cost,
            model=str(raw.get("model", "")),
            provider="openai",
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
        seed: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_message_to_openai(m) for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = [
                {"type": "function", "function": tool.model_dump()} for tool in tools
            ]
        if seed is not None:
            payload["seed"] = seed
        return payload


def _message_to_openai(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role}
    if isinstance(message.content, str):
        payload["content"] = message.content
    else:
        payload["content"] = [block.model_dump(exclude_none=True) for block in message.content]
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return payload


def _normalise_finish_reason(reason: str | None) -> FinishReason:
    mapping: dict[str, FinishReason] = {
        "stop": "stop",
        "length": "length",
        "tool_calls": "tool_calls",
        "function_call": "tool_calls",
        "content_filter": "content_filter",
    }
    return mapping.get(reason or "", "stop")


__all__ = ["OpenAIClient"]
