"""Per-call fields that servers add, and the field paths a session can ignore on top."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from agentanvil.record_replay.normalize import JSONObject, Normalizer, request_hash, response_hash
from tests.record_replay.test_normalize import _request, _response

Fields = dict[str, Any]

# Per server: (top-level fields, fields of the choice), different on every call n.
SERVERS: dict[str, Callable[[int], tuple[Fields, Fields]]] = {
    "vllm": lambda n: ({"metrics": {"queue_time_ms": n}}, {}),
    "sglang": lambda n: (
        {"sglext": {"cached_tokens_details": {"device": n}}},
        {"meta_info": {"e2e_latency": n}},
    ),
    "tensorrt-llm": lambda n: ({}, {"speculative_decoding": {"acceptance_rate": n}}),
    "groq": lambda n: ({"x_groq": {"id": f"req_{n}"}, "usage_breakdown": {"models": [n]}}, {}),
    "cerebras": lambda n: ({"time_info": {"queue_time": n}}, {}),
    "together": lambda n: ({}, {"seed": n}),
}


def _choice(body: JSONObject, **fields: Any) -> JSONObject:
    choices = body["choices"]
    assert isinstance(choices, list) and isinstance(choices[0], dict)
    return {**body, "choices": [{**choices[0], **fields}]}


def test_llama_cpp_timings_do_not_change_the_response_hash() -> None:
    def llama(prompt_ms: float, predicted_ms: float) -> JSONObject:
        timings = {"prompt_n": 12, "prompt_ms": prompt_ms, "predicted_ms": predicted_ms}
        return {**_response("chatcmpl-a"), "timings": timings, "system_fingerprint": "b10582-e85c"}

    assert response_hash(llama(20.5, 310.2)) == response_hash(llama(19.8, 298.7))


@pytest.mark.parametrize("server", sorted(SERVERS))
def test_per_call_fields_of_known_servers_are_ignored(server: str) -> None:
    def call(n: int) -> JSONObject:
        top, choice = SERVERS[server](n)
        return _choice({**_response(f"chatcmpl-{n}"), **top}, **choice)

    assert response_hash(call(1)) == response_hash(call(2))


def test_signatures_minted_per_call_are_ignored_both_ways() -> None:
    def message(signature: str) -> Fields:
        call = {
            "id": "c",
            "type": "function",
            "function": {"name": "f", "arguments": "{}"},
            "extra_content": {"google": {"thought_signature": signature}},
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}

    a, b = message("sig-a"), message("sig-b")
    assert response_hash(_choice(_response(), message=a)) == response_hash(
        _choice(_response(), message=b)
    )
    asked = {"role": "user", "content": "x"}  # the client sends the signature back next turn
    assert request_hash({"model": "m", "messages": [asked, a]}) == request_hash(
        {"model": "m", "messages": [asked, b]}
    )


def test_configured_paths_are_ignored_on_top_of_the_defaults() -> None:
    def vendor(n: int) -> JSONObject:
        return _choice({**_response(f"chatcmpl-{n}"), "x_vendor": {"trace": n}}, debug=n)

    assert response_hash(vendor(1)) != response_hash(vendor(2))
    loose = Normalizer(ignore_response=frozenset({"x_vendor", "choices[].debug"}))
    assert response_hash(vendor(1), loose) == response_hash(vendor(2), loose)

    named = _request()
    messages = named["messages"]
    assert isinstance(messages, list) and isinstance(messages[0], dict)
    messages[0] = {**messages[0], "name": "alice"}
    assert request_hash(named) != request_hash(_request())
    unnamed = Normalizer(ignore_request=frozenset({"messages[].name"}))
    assert request_hash(named, unnamed) == request_hash(_request(), unnamed)

    header = Normalizer(ignore_response=frozenset({"b", "a"})).model_dump(mode="json")
    assert header["ignore_response"] == ["a", "b"]


@pytest.mark.parametrize("path", ["", "a..b", "[].x", "a[]", "a.[]", "a b", ".a"])
def test_an_invalid_ignore_path_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError, match="invalid field paths"):
        Normalizer(ignore_response=frozenset({path}))


def test_tool_call_ids_outside_tool_calls_become_ordinals() -> None:
    def groq(call_id: str, cited: str) -> JSONObject:
        call = {"id": call_id, "type": "function", "function": {"name": "f", "arguments": "{}"}}
        citation = {"type": "function_citation", "function_citation": {"tool_call_id": cited}}
        message = {
            "role": "assistant",
            "content": "x",
            "tool_calls": [call],
            "annotations": [citation],
        }
        return _choice(_response(), message=message)

    assert response_hash(groq("call_a", "call_a")) == response_hash(groq("call_b", "call_b"))
    assert response_hash(groq("call_a", "call_a")) != response_hash(groq("call_a", "call_z"))


@pytest.mark.parametrize("where", ["content", "tool_calls"])
def test_tool_call_ids_inside_content_and_tool_calls_become_ordinals(where: str) -> None:
    def reply(call_id: str) -> JSONObject:
        call: Fields = {
            "id": call_id,
            "type": "function",
            "function": {"name": "f", "arguments": "{}"},
        }
        message: Fields = {"role": "assistant", "content": None, "tool_calls": [call]}
        if where == "content":
            message["content"] = [{"type": "text", "text": "x", "tool_call_id": call_id}]
        else:
            call["extension"] = {"tool_call_id": call_id}
        return _choice(_response(), message=message)

    assert response_hash(reply("call_a")) == response_hash(reply("call_b"))
