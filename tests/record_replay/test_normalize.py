"""Normalisation before hashing: what must and must not change the transport-proxy key."""

from __future__ import annotations

from agentanvil.record_replay.normalize import (
    JSONObject,
    Normalizer,
    request_hash,
    response_hash,
)


def _request(call_id: str = "call_abc", args: str = '{"b": 2, "a": 1}') -> JSONObject:
    return {
        "model": "m",
        "temperature": 0.7,
        "messages": [
            {"role": "user", "content": "book flight 2024-05-15 10:00:00"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "f", "arguments": args},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call_id, "content": "ok"},
        ],
        "tools": [{"type": "function", "function": {"name": "f"}}],
    }


def _response(rid: str = "chatcmpl-1", created: int = 1) -> JSONObject:
    return {
        "id": rid,
        "created": created,
        "model": "m",
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"{rid}-tool",
                            "type": "function",
                            "function": {"name": "f", "arguments": "{}"},
                        }
                    ],
                },
            }
        ],
    }


# ---------- Requests ----------


def test_fresh_tool_call_ids_hash_the_same() -> None:
    assert request_hash(_request("call_abc")) == request_hash(_request("call_xyz"))


def test_tool_call_ids_kept_when_disabled() -> None:
    strict = Normalizer(tool_call_ids=False)
    assert request_hash(_request("call_abc"), strict) != request_hash(_request("call_xyz"), strict)


def test_argument_key_order_does_not_matter() -> None:
    a = request_hash(_request(args='{"b": 2, "a": 1}'))
    b = request_hash(_request(args='{"a":1,"b":2}'))
    assert a == b


def test_malformed_arguments_are_kept_verbatim() -> None:
    assert request_hash(_request(args="{oops")) != request_hash(_request(args="{oops "))


def test_ignored_request_fields_do_not_matter() -> None:
    noisy = {**_request(), "seed": 7, "stream": False, "num_retries": 3, "user": "u"}
    assert request_hash(noisy) == request_hash(_request())


def test_content_change_changes_hash() -> None:
    other = _request()
    messages = other["messages"]
    assert isinstance(messages, list)
    messages[0] = {"role": "user", "content": "book flight 2024-05-16 10:00:00"}
    assert request_hash(other) != request_hash(_request())


def test_tools_order_is_visible() -> None:
    a = {**_request(), "tools": [{"name": "f"}, {"name": "g"}]}
    b = {**_request(), "tools": [{"name": "g"}, {"name": "f"}]}
    assert request_hash(a) != request_hash(b)


def test_timestamps_are_data_by_default() -> None:
    earlier = _request()
    later = _request()
    messages = later["messages"]
    assert isinstance(messages, list)
    messages[0] = {"role": "user", "content": "book flight 2024-05-15 11:30:00"}
    assert request_hash(earlier) != request_hash(later)
    loose = Normalizer(timestamps=True)
    assert request_hash(earlier, loose) == request_hash(later, loose)


def test_uuids_and_whitespace_switches() -> None:
    def with_text(text: str) -> JSONObject:
        return {"model": "m", "messages": [{"role": "user", "content": text}]}

    a = with_text("id 123e4567-e89b-12d3-a456-426614174000  ok")
    b = with_text("id 00000000-0000-4000-8000-000000000000 ok ")
    assert request_hash(a) != request_hash(b)
    assert request_hash(a, Normalizer(uuids=True, whitespace=True)) == request_hash(
        b, Normalizer(uuids=True, whitespace=True)
    )


def test_text_parts_are_normalised() -> None:
    def parts(text: str) -> JSONObject:
        return {
            "model": "m",
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
        }

    loose = Normalizer(whitespace=True)
    assert request_hash(parts("a  b"), loose) == request_hash(parts("a b"), loose)


def test_malformed_request_is_kept_as_is() -> None:
    body: JSONObject = {"model": "m", "messages": "not a list"}
    assert Normalizer().request(body) == body


# ---------- Responses ----------


def test_per_call_response_fields_do_not_matter() -> None:
    assert response_hash(_response("chatcmpl-1", 1)) == response_hash(_response("chatcmpl-2", 2))


def test_response_content_change_changes_hash() -> None:
    other = _response()
    choices = other["choices"]
    assert isinstance(choices, list)
    choices[0] = {
        "index": 0,
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": "x"},
    }
    assert response_hash(other) != response_hash(_response())
