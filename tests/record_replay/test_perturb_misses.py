"""Fault operators of the transport proxy (#36) that find nothing to act on: a miss."""

from __future__ import annotations

import pytest

from agentanvil.record_replay.normalize import JSONObject
from tests.record_replay.test_perturb import PLAIN, REQUEST, RESPONSE, _apply

NO_TOOLS: JSONObject = {"model": "m", "messages": [{"role": "system", "content": "Be brief."}]}
BAD_ARGUMENTS: JSONObject = {
    "choices": [{"message": {"tool_calls": [{"id": "c", "function": {"arguments": "{bad"}}]}}]
}
NOT_AN_OBJECT: JSONObject = {
    "choices": [{"message": {"tool_calls": [{"id": "c", "function": {"arguments": "[1]"}}]}}]
}
CALL_ONLY: JSONObject = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": []}}]
}


@pytest.mark.parametrize(
    ("op", "params", "request_", "response"),
    [
        ("tool_result", {"text": "x"}, NO_TOOLS, RESPONSE),
        ("drop_instruction", {"pattern": "x"}, {"model": "m"}, RESPONSE),
        ("user_rewrite", {"text": "x"}, {"model": "m"}, RESPONSE),
        ("tool_call", {}, REQUEST, {"choices": [{"message": {"tool_calls": ["not a call"]}}]}),
        ("tool_call", {"argument": "q"}, REQUEST, NOT_AN_OBJECT),
        (
            "output_rewrite",
            {"field": "a.b"},
            REQUEST,
            {"choices": [{"message": {"content": "{}"}}]},
        ),
        ("tool_error", {}, {"model": "m"}, RESPONSE),
        ("drop_instruction", {"pattern": "absent"}, REQUEST, RESPONSE),
        ("user_rewrite", {"text": "x"}, NO_TOOLS, RESPONSE),
        ("tool_call", {}, REQUEST, PLAIN),
        ("tool_call", {}, NO_TOOLS, RESPONSE),  # no other tool to rename the call to
        ("tool_call", {"argument": "q"}, REQUEST, BAD_ARGUMENTS),
        ("output_rewrite", {"text": "x"}, REQUEST, CALL_ONLY),
        ("output_rewrite", {"field": "absent"}, REQUEST, RESPONSE),
        ("output_rewrite", {"field": "price"}, REQUEST, PLAIN),  # not a JSON answer
        ("inflate", {}, REQUEST, CALL_ONLY),
        ("loop", {}, REQUEST, {"choices": []}),
    ],
)
def test_an_operator_without_a_site_misses(
    op: str, params: JSONObject, request_: JSONObject, response: JSONObject
) -> None:
    assert _apply(op, params, request=request_, response=response) is None
