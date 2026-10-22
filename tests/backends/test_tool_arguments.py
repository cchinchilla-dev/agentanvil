"""Tool-call arguments that are not a JSON object raise `BackendError`, streamed or not."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentanvil.exceptions import BackendError
from tests.backends.test_direct_stream import (
    ANTHROPIC,
    GOOGLE,
    HI,
    OPENAI,
    _backend,
    _block_delta,
    _collect,
    _openai_chunk,
    _sse,
)


def _openai(arguments: str) -> dict[str, Any]:
    call = {"id": "c1", "type": "function", "function": {"name": "search", "arguments": arguments}}
    message = {"role": "assistant", "content": None, "tool_calls": [call]}
    return {"model": OPENAI, "choices": [{"message": message, "finish_reason": "tool_calls"}]}


def _anthropic(arguments: Any) -> dict[str, Any]:
    block = {"type": "tool_use", "id": "toolu_1", "name": "search", "input": arguments}
    return {"model": ANTHROPIC, "content": [block], "stop_reason": "tool_use"}


def _google(arguments: Any) -> dict[str, Any]:
    part = {"functionCall": {"name": "search", "args": arguments}}
    return {"candidates": [{"content": {"parts": [part]}, "finishReason": "STOP"}]}


# Per provider: the model and a response whose one tool call has a list as arguments.
NOT_AN_OBJECT = {
    "openai": (OPENAI, _openai("[1, 2]")),
    "anthropic": (ANTHROPIC, _anthropic([1, 2])),
    "google": (GOOGLE, _google([1, 2])),
}


@pytest.mark.parametrize("provider", sorted(NOT_AN_OBJECT))
async def test_complete_rejects_arguments_that_are_not_an_object(provider: str) -> None:
    model, body = NOT_AN_OBJECT[provider]
    with pytest.raises(BackendError, match="'search' that are not a JSON object"):
        await _backend(provider, httpx.Response(200, json=body)).complete(HI, model=model)


async def test_complete_rejects_openai_arguments_that_are_not_json() -> None:
    backend = _backend("openai", httpx.Response(200, json=_openai('{"q": ')))
    with pytest.raises(BackendError, match="'search' that are not valid JSON"):
        await backend.complete(HI, model=OPENAI)


async def test_openai_stream_rejects_arguments_that_are_not_an_object() -> None:
    fragment = {"index": 0, "id": "c1", "function": {"name": "search", "arguments": "[1, 2]"}}
    response = _sse(_openai_chunk({"tool_calls": [fragment]}), _openai_chunk({}, "tool_calls"))
    with pytest.raises(BackendError, match="'search' that are not a JSON object"):
        await _collect(_backend("openai", response), OPENAI)


async def test_anthropic_stream_rejects_arguments_that_are_not_an_object() -> None:
    tool = {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {}}
    response = _sse(
        {"type": "message_start", "message": {"model": ANTHROPIC, "usage": {"input_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": tool},
        _block_delta(0, type="input_json_delta", partial_json="[1, 2]"),
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}},
    )
    with pytest.raises(BackendError, match="'search' that are not a JSON object"):
        await _collect(_backend("anthropic", response), ANTHROPIC)
