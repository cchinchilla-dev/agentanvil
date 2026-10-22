"""DirectBackend streaming: vendor SSE chunks become text deltas plus one final chunk.

No real API calls. Each provider gets a `httpx.MockTransport` that serves a
canned SSE body shaped like the vendor's stream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentanvil.backends.direct import DirectBackend
from agentanvil.backends.types import LLMResponse, Message
from agentanvil.exceptions import BackendError
from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.recording import RecordingBackend

OPENAI = "gpt-4o-2024-11-20"
ANTHROPIC = "claude-3-5-sonnet-20241022"
GOOGLE = "gemini-1.5-pro-002"
HI = [Message(role="user", content="hi")]


def _sse(*events: dict[str, Any], done: bool = False) -> httpx.Response:
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    if done:
        body += "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def _backend(
    provider: str, response: httpx.Response, seen: list[dict[str, Any]] | None = None
) -> DirectBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return response

    backend = DirectBackend(provider, api_key="YOUR_API_KEY_HERE")  # type: ignore[arg-type]
    http = backend._client._http
    backend._client._http = httpx.AsyncClient(
        base_url=http.base_url, headers=http.headers, transport=httpx.MockTransport(handler)
    )
    return backend


async def _collect(backend: Any, model: str) -> list[LLMResponse]:
    return [chunk async for chunk in backend.stream(HI, model=model)]


# ---------- OpenAI ----------


def _openai_chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {"model": OPENAI, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def _fragment(index: int, *, call_id: str = "", name: str = "", arguments: str = "") -> dict:
    fragment: dict[str, Any] = {"index": index, "function": {"arguments": arguments}}
    if call_id:
        fragment.update(id=call_id, type="function")
        fragment["function"]["name"] = name
    return fragment


def _openai_tool_stream() -> httpx.Response:
    return _sse(
        _openai_chunk({"tool_calls": [_fragment(0, call_id="call_a", name="search")]}),
        _openai_chunk({"tool_calls": [_fragment(1, call_id="call_b", name="fetch")]}),
        _openai_chunk({"tool_calls": [_fragment(0, arguments='{"q": ')]}),
        _openai_chunk({"tool_calls": [_fragment(1, arguments='{"url": "u"}')]}),
        _openai_chunk({"tool_calls": [_fragment(0, arguments='"x"}')]}),
        _openai_chunk({}, finish="tool_calls"),
        done=True,
    )


async def test_openai_stream_yields_text_deltas_then_usage_and_finish() -> None:
    seen: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 12, "completion_tokens": 2}
    response = _sse(
        _openai_chunk({"role": "assistant", "content": ""}),
        _openai_chunk({"content": "hello"}),
        _openai_chunk({"content": " back"}),
        _openai_chunk({}, finish="stop"),
        {"model": OPENAI, "choices": [], "usage": usage},
        done=True,
    )
    chunks = await _collect(_backend("openai", response, seen), OPENAI)

    assert [c.content for c in chunks] == ["hello", " back", None]
    final = chunks[-1]
    assert final.finish_reason == "stop"
    assert (final.usage.input_tokens, final.usage.output_tokens) == (12, 2)
    assert final.cost_usd > 0
    assert seen[0]["stream_options"] == {"include_usage": True}


async def test_openai_stream_joins_tool_call_fragments_by_index() -> None:
    chunks = await _collect(_backend("openai", _openai_tool_stream()), OPENAI)

    assert len(chunks) == 1
    assert chunks[0].finish_reason == "tool_calls"
    assert [(c.id, c.name, c.arguments) for c in chunks[0].tool_calls] == [
        ("call_a", "search", {"q": "x"}),
        ("call_b", "fetch", {"url": "u"}),
    ]


async def test_streamed_tool_calls_survive_record_and_replay(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    recorder = RecordingBackend(_backend("openai", _openai_tool_stream()), out)
    recorded = await _collect(recorder, OPENAI)
    replayed = await _collect(MockBackend(out), OPENAI)
    assert [c.tool_calls for c in replayed] == [c.tool_calls for c in recorded]


# ---------- Anthropic ----------


def _block_delta(index: int, **delta: str) -> dict[str, Any]:
    return {"type": "content_block_delta", "index": index, "delta": delta}


async def test_anthropic_stream_yields_text_and_assembles_tool_use() -> None:
    text = {"type": "text", "text": ""}
    tool = {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {}}
    stop = {"stop_reason": "tool_use"}
    response = _sse(
        {"type": "message_start", "message": {"model": ANTHROPIC, "usage": {"input_tokens": 20}}},
        {"type": "content_block_start", "index": 0, "content_block": text},
        _block_delta(0, type="text_delta", text="Let "),
        _block_delta(0, type="text_delta", text="me."),
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": tool},
        _block_delta(1, type="input_json_delta", partial_json='{"q": '),
        _block_delta(1, type="input_json_delta", partial_json='"x"}'),
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": stop, "usage": {"output_tokens": 15}},
        {"type": "message_stop"},
    )
    chunks = await _collect(_backend("anthropic", response), ANTHROPIC)

    assert [c.content for c in chunks] == ["Let ", "me.", None]
    final = chunks[-1]
    assert final.finish_reason == "tool_calls"
    assert [(c.id, c.name, c.arguments) for c in final.tool_calls] == [
        ("toolu_1", "search", {"q": "x"})
    ]
    assert (final.usage.input_tokens, final.usage.output_tokens) == (20, 15)
    assert final.model == ANTHROPIC


# ---------- Google ----------


def _google_chunk(parts: list[dict[str, Any]], output_tokens: int) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}}],
        "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": output_tokens},
    }


async def test_google_stream_yields_text_and_keeps_function_calls_and_last_usage() -> None:
    call = {"functionCall": {"name": "search", "args": {"q": "x"}}}
    response = _sse(
        _google_chunk([{"text": "Sure"}], 1),
        _google_chunk([{"text": ", one moment."}], 4),
        _google_chunk([call], 7),
    )
    chunks = await _collect(_backend("google", response), GOOGLE)

    assert [c.content for c in chunks] == ["Sure", ", one moment.", None]
    final = chunks[-1]
    assert [(c.name, c.arguments) for c in final.tool_calls] == [("search", {"q": "x"})]
    assert (final.usage.input_tokens, final.usage.output_tokens) == (9, 7)
    assert final.model == GOOGLE


# ---------- Errors ----------


@pytest.mark.parametrize(
    ("provider", "model", "event"),
    [
        ("openai", OPENAI, {"error": {"message": "overloaded", "type": "server_error"}}),
        ("anthropic", ANTHROPIC, {"type": "error", "error": {"type": "overloaded_error"}}),
        ("google", GOOGLE, {"error": {"code": 503, "message": "unavailable"}}),
    ],
)
async def test_stream_error_event_raises_instead_of_an_empty_answer(
    provider: str, model: str, event: dict[str, Any]
) -> None:
    with pytest.raises(BackendError, match="stream error"):
        await _collect(_backend(provider, _sse(event)), model)
