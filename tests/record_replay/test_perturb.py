"""Fault operators of the transport proxy (#36): what each changes, and when it misses."""

from __future__ import annotations

import json

import pytest

from agentanvil.record_replay.normalize import JSON, JSONObject
from agentanvil.record_replay.perturb import Change, Fault
from agentanvil.record_replay.perturb_request import REQUEST_OPS, TOOL_ERRORS
from agentanvil.record_replay.perturb_response import RESPONSE_OPS


def _call(call_id: str, name: str, arguments: JSONObject) -> JSONObject:
    function: JSONObject = {"name": name, "arguments": json.dumps(arguments)}
    return {"id": call_id, "type": "function", "function": function}


def _tool(name: str) -> JSONObject:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


REQUEST: JSONObject = {
    "model": "m",
    "tools": [_tool("search"), _tool("calc"), _tool("mail")],
    "messages": [
        {"role": "system", "content": "Be brief. Never email anyone."},
        {"role": "user", "content": "Find the price."},
        {"role": "assistant", "content": None, "tool_calls": [_call("c1", "search", {"q": "p"})]},
        {"role": "tool", "tool_call_id": "c1", "content": "42 EUR"},
        {"role": "tool", "tool_call_id": "c2", "content": [{"type": "text", "text": "1"}]},
    ],
}
ANSWER = {"role": "assistant", "content": '{"price": 42, "currency": "EUR"}'}
RESPONSE: JSONObject = {
    "id": "r",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {**ANSWER, "tool_calls": [_call("c3", "search", {"q": "tax"})]},
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}
PREVIOUS: list[JSON] = [_call("c0", "calc", {"x": 2})]

CASES: list[tuple[str, JSONObject]] = [
    ("tool_result", {"mode": "replace", "text": "0 EUR"}),
    ("tool_result", {"mode": "empty"}),
    ("tool_result", {"mode": "append", "text": " (stale)"}),
    ("tool_error", {"error": "http_500"}),
    ("drop_instruction", {"pattern": r" Never email anyone\."}),
    ("user_rewrite", {"text": "Find the tax."}),
    ("tool_call", {}),
    ("tool_call", {"argument": "q", "value": "refund"}),
    ("output_rewrite", {"text": "done"}),
    ("output_rewrite", {"field": "price", "value": 0}),
    ("inflate", {"factor": 3}),
    ("loop", {}),
]


def _apply(
    op: str,
    params: JSONObject,
    seed: int = 0,
    request: JSONObject = REQUEST,
    response: JSONObject = RESPONSE,
) -> Change | None:
    fault = Fault.model_validate({"op": op, "role": "agent", "at": 0, "params": params})
    if op in REQUEST_OPS:
        return REQUEST_OPS[op](request, fault, seed)
    return RESPONSE_OPS[op](response, request, fault, seed, PREVIOUS)


def _changed(a: JSON, b: JSON, path: str = "") -> set[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        keys = a.keys() | b.keys()
        return {p for k in keys for p in _changed(a.get(k), b.get(k), f"{path}.{k}".lstrip("."))}
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        pairs = enumerate(zip(a, b, strict=True))
        return {p for i, (x, y) in pairs for p in _changed(x, y, f"{path}[{i}]")}
    return set() if a == b else {path}


@pytest.mark.parametrize(("op", "params"), CASES)
def test_each_operator_changes_only_its_site(op: str, params: JSONObject) -> None:
    change = _apply(op, params)
    assert change is not None
    body, site, _ = change
    changed = _changed(REQUEST if op in REQUEST_OPS else RESPONSE, body)
    sites = site.split(",")
    assert changed
    assert all(any(p.startswith(s) or s.startswith(p) for s in sites) for p in changed)


def test_request_operators_write_what_their_parameters_say() -> None:
    def content(change: Change | None, i: int) -> JSON:
        assert change is not None
        messages = change[0]["messages"]
        assert isinstance(messages, list) and isinstance(messages[i], dict)
        return messages[i]["content"]

    # Seed 0 picks the first of the two tool results; seed 1 the second, given as parts
    assert content(_apply("tool_result", {"text": "0 EUR"}), 3) == "0 EUR"
    assert content(_apply("tool_result", {"mode": "empty"}), 3) == ""
    appended = content(_apply("tool_result", {"mode": "append", "text": "!"}, seed=1), 4)
    assert appended == [{"type": "text", "text": "1"}, {"type": "text", "text": "!"}]
    assert content(_apply("tool_error", {"error": "timeout"}), 3) == TOOL_ERRORS["timeout"]
    dropped = content(_apply("drop_instruction", {"pattern": r" Never email anyone\."}), 0)
    assert dropped == "Be brief."
    assert content(_apply("user_rewrite", {"text": "Hi"}), 1) == "Hi"
    only_results: JSONObject = {"messages": [{"role": "tool", "content": "x"}]}
    assert content(_apply("tool_result", {"text": "y"}, request=only_results), 0) == "y"
    parts = [{"type": "text", "text": "Never do X"}, {"type": "image_url"}]
    system = [
        {"role": "system", "content": parts},
        {"role": "developer", "content": "Never do Y"},
        {"role": "developer", "content": None},
    ]
    dropped_all = _apply("drop_instruction", {"pattern": "Never "}, request={"messages": system})
    assert content(dropped_all, 0) == [{"type": "text", "text": "do X"}, {"type": "image_url"}]
    assert content(dropped_all, 1) == "do Y"  # developer messages too


def test_response_operators_write_what_their_parameters_say() -> None:
    def message(change: Change | None) -> JSONObject:
        assert change is not None
        choices = change[0]["choices"]
        assert isinstance(choices, list) and isinstance(choices[0], dict)
        assert isinstance(m := choices[0]["message"], dict)
        return m

    renamed = _apply("tool_call", {})
    assert renamed is not None and renamed[2]["rename_to"] in ("calc", "mail")
    hosted = {**REQUEST, "tools": [{"type": "web_search"}, _tool("calc")]}
    assert _apply("tool_call", {}, request=hosted) == _apply("tool_call", {"rename_to": "calc"})
    mail = message(_apply("tool_call", {"rename_to": "mail"}))
    assert mail["tool_calls"][0]["function"]["name"] == "mail"
    arguments = message(_apply("tool_call", {"argument": "q", "value": "refund"}))
    assert json.loads(arguments["tool_calls"][0]["function"]["arguments"]) == {"q": "refund"}
    field = message(_apply("output_rewrite", {"field": "price", "value": 0}))
    assert json.loads(str(field["content"])) == {"price": 0, "currency": "EUR"}
    nested = {"choices": [{"message": {"content": '{"a": {"b": 1}}'}}]}
    deep = message(_apply("output_rewrite", {"field": "a.b", "value": 2}, response=nested))
    assert json.loads(str(deep["content"])) == {"a": {"b": 2}}
    for usage in ({}, {"usage": {"completion_tokens": 2}}):  # no usage, or no prompt tokens
        inflated_plain = _apply("inflate", {}, response={**PLAIN, **usage})
        assert inflated_plain is not None and inflated_plain[0].get("usage") == (
            {"completion_tokens": 4} if usage else None
        )
    inflated = _apply("inflate", {"factor": 3})
    assert inflated is not None and inflated[0]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 15,
        "total_tokens": 25,
    }
    looped = _apply("loop", {}, seed=255)
    assert looped is not None and looped[0]["choices"][0]["finish_reason"] == "tool_calls"
    calls = message(looped)["tool_calls"]
    assert calls == [{**_call("c0", "calc", {"x": 2}), "id": "call_000000ff_0"}]
    assert message(looped)["content"] is None


PLAIN: JSONObject = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}]}


def test_fault_parameters_are_deterministic_for_a_seed() -> None:
    sites = {seed: _apply("tool_result", {"text": "x"}, seed=seed) for seed in range(8)}
    assert all(_apply("tool_result", {"text": "x"}, seed=s) == c for s, c in sites.items())
    assert {c[1] for c in sites.values() if c} == {"messages[3].content", "messages[4].content"}
    # Only the results this request delivers: not a tool result of an earlier turn
    earlier: list[JSON] = [{"role": "tool", "content": "old"}, {"role": "assistant", "content": ""}]
    later = {"messages": [*earlier, {"role": "tool", "content": "new"}]}
    assert {c[1] for s in range(8) if (c := _apply("tool_error", {}, seed=s, request=later))} == {
        "messages[2].content"
    }
