"""DirectBackend streaming edge cases: empty streams, cut-off arguments, odd servers."""

from __future__ import annotations

import pytest

from agentanvil.exceptions import BackendError
from tests.backends.test_direct_stream import (
    ANTHROPIC,
    GOOGLE,
    OPENAI,
    _backend,
    _block_delta,
    _collect,
    _openai_chunk,
    _sse,
)


@pytest.mark.parametrize(("provider", "model"), [("openai", OPENAI), ("google", GOOGLE)])
async def test_stream_with_no_chunks_raises(provider: str, model: str) -> None:
    with pytest.raises(BackendError, match="without"):
        await _collect(_backend(provider, _sse(done=True)), model)


async def test_anthropic_stream_with_no_events_raises() -> None:
    with pytest.raises(BackendError, match="without an event"):
        await _collect(_backend("anthropic", _sse()), ANTHROPIC)


async def test_openai_arguments_cut_off_by_max_tokens_raise() -> None:
    fragment = {"index": 0, "id": "c1", "function": {"name": "search", "arguments": '{"q": "x'}}
    response = _sse(_openai_chunk({"tool_calls": [fragment]}), _openai_chunk({}, "length"))
    with pytest.raises(BackendError, match="inside the arguments of 'search'"):
        await _collect(_backend("openai", response), OPENAI)


async def test_anthropic_arguments_cut_off_by_max_tokens_raise() -> None:
    tool = {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {}}
    response = _sse(
        {"type": "message_start", "message": {"model": ANTHROPIC, "usage": {"input_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": tool},
        _block_delta(0, type="input_json_delta", partial_json='{"q": "x'),
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {}},
    )
    with pytest.raises(BackendError, match="inside the arguments of 'search'"):
        await _collect(_backend("anthropic", response), ANTHROPIC)


async def test_anthropic_keeps_an_input_sent_whole_in_the_start_event() -> None:
    tool = {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {"q": "x"}}
    response = _sse(
        {"type": "message_start", "message": {"model": ANTHROPIC, "usage": {"input_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": tool},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}},
    )
    chunks = await _collect(_backend("anthropic", response), ANTHROPIC)
    assert chunks[-1].tool_calls[0].arguments == {"q": "x"}


async def test_openai_fragments_without_index_split_on_a_new_id() -> None:
    def fragment(call_id: str, arguments: str, name: str = "") -> dict:
        return {"id": call_id, "function": {"name": name, "arguments": arguments}}

    response = _sse(
        _openai_chunk({"tool_calls": [fragment("a", '{"q": ', "search")]}),
        _openai_chunk({"tool_calls": [fragment("a", '"x"}')]}),
        _openai_chunk({"tool_calls": [fragment("b", "{}", "fetch")]}),
        _openai_chunk({}, "tool_calls"),
        done=True,
    )
    chunks = await _collect(_backend("openai", response), OPENAI)
    assert [(c.id, c.name, c.arguments) for c in chunks[-1].tool_calls] == [
        ("a", "search", {"q": "x"}),
        ("b", "fetch", {}),
    ]


async def test_the_requested_model_prices_a_stream_whose_chunks_omit_it() -> None:
    response = _sse({"choices": [{"index": 0, "delta": {"content": "hi"}}]}, done=True)
    chunks = await _collect(_backend("openai", response), OPENAI)
    assert chunks[-1].model == OPENAI
