"""Stream normalisers for the provider clients.

Each one turns a vendor's raw SSE chunks into the `LLMBackend.stream`
contract: text deltas as they arrive, then one final chunk with
``content=None`` built by the client's non-streaming `normalise`. Kept apart
from the clients so each provider module stays a thin wrapper.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from agentanvil.backends._providers._base import ProviderClientBase, elapsed_ms
from agentanvil.backends.types import LLMResponse
from agentanvil.exceptions import BackendError


async def openai_stream(
    client: ProviderClientBase,
    chunks: AsyncIterator[dict[str, Any]],
    *,
    model: str,
    start_ns: int,
) -> AsyncIterator[LLMResponse]:
    finish, seen = None, False
    usage: dict[str, Any] = {}
    # Tool calls arrive as fragments keyed by `index`: id and name once,
    # the JSON arguments split across chunks.
    calls: dict[int, dict[str, Any]] = {}
    async for chunk in chunks:
        seen = True
        if "error" in chunk:
            raise BackendError(f"OpenAI stream error: {chunk['error']}")
        model = chunk.get("model") or model
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or []:
            finish = choice.get("finish_reason") or finish
            delta = choice.get("delta") or {}
            for fragment in delta.get("tool_calls") or []:
                call = calls.setdefault(
                    _call_index(fragment, calls),
                    {"id": "", "function": {"name": "", "arguments": ""}},
                )
                function = fragment.get("function") or {}
                call["id"] = fragment.get("id") or call["id"]
                call["function"]["name"] = function.get("name") or call["function"]["name"]
                call["function"]["arguments"] += function.get("arguments") or ""
            if delta.get("content"):
                yield client._text_delta(
                    delta["content"], model=model, raw=chunk, start_ns=start_ns
                )
    if not seen:
        raise BackendError("OpenAI stream ended without a chunk")
    for call in calls.values():
        parse_arguments("OpenAI", call["function"]["name"], call["function"]["arguments"])
    message = {"content": None, "tool_calls": [calls[i] for i in sorted(calls)]}
    final = {
        "model": model,
        "usage": usage,
        "choices": [{"message": message, "finish_reason": finish}],
    }
    yield client.normalise(final, latency_ms=elapsed_ms(start_ns))


async def anthropic_stream(
    client: ProviderClientBase,
    chunks: AsyncIterator[dict[str, Any]],
    *,
    model: str,
    start_ns: int,
) -> AsyncIterator[LLMResponse]:
    # Rebuild the non-streaming message from its events, minus the text
    # already yielded, and normalise it as the final chunk.
    message: dict[str, Any] = {"model": model, "usage": {}, "stop_reason": None}
    blocks: dict[int, dict[str, Any]] = {}
    seen = False
    async for event in chunks:
        seen = True
        kind = event.get("type")
        if kind == "error":
            raise BackendError(f"Anthropic stream error: {event.get('error')}")
        if kind == "message_start":
            start = event.get("message") or {}
            message["model"] = start.get("model") or model
            message["usage"].update(start.get("usage") or {})
        elif kind == "content_block_start":
            block = dict(event.get("content_block") or {})
            blocks[event.get("index", len(blocks))] = block
            if block.get("text"):
                yield client._text_delta(
                    block["text"], model=message["model"], raw=event, start_ns=start_ns
                )
        elif kind == "content_block_delta":
            block = blocks.setdefault(event.get("index", 0), {})
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield client._text_delta(
                    delta["text"], model=message["model"], raw=event, start_ns=start_ns
                )
            elif delta.get("type") == "input_json_delta":
                block["partial_json"] = block.get("partial_json", "") + delta.get(
                    "partial_json", ""
                )
        elif kind == "message_delta":
            message["stop_reason"] = (event.get("delta") or {}).get("stop_reason")
            # Output tokens here are cumulative and replace the opening count.
            message["usage"].update(event.get("usage") or {})
    if not seen:
        raise BackendError("Anthropic stream ended without an event")
    # Without input_json_delta events, keep the input the start event carried.
    message["content"] = [
        {
            **block,
            "input": parse_arguments("Anthropic", block.get("name", ""), block["partial_json"]),
        }
        if "partial_json" in block
        else block
        for _, block in sorted(blocks.items())
        if block.get("type") == "tool_use"
    ]
    yield client.normalise(message, latency_ms=elapsed_ms(start_ns))


async def google_stream(
    client: ProviderClientBase,
    chunks: AsyncIterator[dict[str, Any]],
    *,
    model: str,
    start_ns: int,
) -> AsyncIterator[LLMResponse]:
    finish, seen = None, False
    usage: dict[str, Any] = {}
    calls: list[dict[str, Any]] = []
    async for chunk in chunks:
        seen = True
        if "error" in chunk:
            raise BackendError(f"Google stream error: {chunk['error']}")
        model = chunk.get("model") or model
        # Each chunk repeats the running totals; the last one wins.
        usage = chunk.get("usageMetadata") or usage
        candidate = (chunk.get("candidates") or [{}])[0]
        finish = candidate.get("finishReason") or finish
        for part in (candidate.get("content") or {}).get("parts") or []:
            if "functionCall" in part:
                calls.append(part)
            elif part.get("text"):
                yield client._text_delta(part["text"], model=model, raw=chunk, start_ns=start_ns)
    if not seen:
        raise BackendError("Google stream ended without a chunk")
    final = {
        "model": model,
        "usageMetadata": usage,
        "candidates": [{"content": {"parts": calls}, "finishReason": finish}],
    }
    yield client.normalise(final, latency_ms=elapsed_ms(start_ns))


def parse_arguments(provider: str, tool: str, raw: str) -> dict[str, Any]:
    """Streamed tool-call arguments; JSON cut off (max_tokens hit mid-call) is a `BackendError`."""
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise BackendError(f"{provider} stream ended inside the arguments of {tool!r}") from exc
    return arguments if isinstance(arguments, dict) else {}


def _call_index(fragment: dict[str, Any], calls: dict[int, dict[str, Any]]) -> int:
    """Slot of a tool-call fragment; when `index` is missing, a new id opens one."""
    if (index := fragment.get("index")) is not None:
        return int(index)
    if call_id := fragment.get("id"):
        return next((i for i, call in calls.items() if call["id"] == call_id), len(calls))
    return max(calls, default=0)
