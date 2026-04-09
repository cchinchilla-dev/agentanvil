"""Google Gemini wrapper used by `DirectBackend`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from agentanvil.backends._providers._base import ProviderClientBase
from agentanvil.backends.pricing import cost_for
from agentanvil.backends.types import LLMResponse, Message, ToolCall, ToolDef, Usage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GoogleClient(ProviderClientBase):
    """Thin async wrapper over Gemini's `generateContent` endpoint."""

    provider = "google"

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url or _DEFAULT_BASE_URL,
            default_base_url=_DEFAULT_BASE_URL,
            # Gemini auth flows via `?key=` query param, not headers.
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
            messages, temperature=temperature, max_tokens=max_tokens, tools=tools
        )
        timeout = httpx.Timeout(timeout_s) if timeout_s is not None else None
        response = await self._http.post(
            f"/models/{model}:generateContent",
            params={"key": self._api_key},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        body.setdefault("model", model)
        return body

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
            messages, temperature=temperature, max_tokens=max_tokens, tools=tools
        )
        async with self._http.stream(
            "POST",
            f"/models/{model}:streamGenerateContent",
            params={"key": self._api_key, "alt": "sse"},
            json=payload,
        ) as response:
            response.raise_for_status()
            async for chunk in self._iter_sse(response):
                chunk.setdefault("model", model)
                yield chunk

    def normalise(self, raw: dict[str, Any], *, latency_ms: int) -> LLMResponse:
        candidate = (raw.get("candidates") or [{}])[0]
        parts = (candidate.get("content") or {}).get("parts", []) or []
        text = "".join(part.get("text", "") for part in parts if "text" in part)
        tool_calls = [
            ToolCall(
                id=str(part["functionCall"].get("name", "")),
                name=part["functionCall"]["name"],
                arguments=part["functionCall"].get("args", {}) or {},
            )
            for part in parts
            if "functionCall" in part
        ]
        usage_meta = raw.get("usageMetadata", {}) or {}
        usage = Usage(
            input_tokens=int(usage_meta.get("promptTokenCount", 0)),
            output_tokens=int(usage_meta.get("candidatesTokenCount", 0)),
            reasoning_tokens=int(usage_meta.get("thoughtsTokenCount", 0)),
            cached_tokens=int(usage_meta.get("cachedContentTokenCount", 0)),
        )
        cost = cost_for(
            "google",
            raw.get("model", ""),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
        )
        return LLMResponse(
            content=text or None,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=_normalise_finish_reason(candidate.get("finishReason")),
            latency_ms=latency_ms,
            cost_usd=cost,
            model=str(raw.get("model", "")),
            provider="google",
            raw=raw,
        )

    def _payload(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
    ) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        system_text: list[str] = []
        for m in messages:
            if m.role == "system" and isinstance(m.content, str):
                system_text.append(m.content)
                continue
            contents.append(_message_to_google(m))
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_text)}]}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        }
                        for tool in tools
                    ]
                }
            ]
        return payload


def _message_to_google(message: Message) -> dict[str, Any]:
    role = "user" if message.role == "user" else "model"
    if isinstance(message.content, str):
        return {"role": role, "parts": [{"text": message.content}]}
    parts: list[dict[str, Any]] = []
    for block in message.content:
        if block.type == "text" and block.text is not None:
            parts.append({"text": block.text})
        elif block.type == "image" and block.image_url is not None:
            parts.append({"fileData": {"fileUri": block.image_url}})
    return {"role": role, "parts": parts}


def _normalise_finish_reason(reason: str | None) -> FinishReason:
    mapping: dict[str, FinishReason] = {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
        "OTHER": "stop",
    }
    return mapping.get(reason or "", "stop")


__all__ = ["GoogleClient"]
