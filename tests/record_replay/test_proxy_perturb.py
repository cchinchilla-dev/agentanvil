"""Faults in transport-proxy sessions (#36): when they apply, what the log keeps, misses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.normalize import JSON, JSONObject, request_hash
from agentanvil.record_replay.perturb_request import TOOL_ERRORS
from agentanvil.record_replay.proxy_layers import derive_seed
from agentanvil.record_replay.proxy_log import RoleConfig, SessionConfig
from agentanvil.record_replay.proxy_session import ProxySession

ROLES = {"agent": RoleConfig(upstream="http://a")}
CLOCK: JSONObject = {"type": "function", "function": {"name": "clock"}}
CALL: JSONObject = {
    "id": "c1",
    "type": "function",
    "function": {"name": "clock", "arguments": "{}"},
}
ASK: JSONObject = {
    "model": "m",
    "tools": [CLOCK],
    "messages": [{"role": "user", "content": "time?"}],
}
RESULT: JSONObject = {
    **ASK,
    "messages": [
        {"role": "user", "content": "time?"},
        {"role": "assistant", "content": None, "tool_calls": [CALL]},
        {"role": "tool", "tool_call_id": "c1", "content": "10:00"},
    ],
}


class Upstream:
    """Fake upstream: asks for the clock, and answers once the request carries its result."""

    def __init__(self) -> None:
        self.bodies: list[JSONObject] = []

    def __call__(self, url: str, body: JSONObject) -> tuple[int, JSONObject]:
        self.bodies.append(body)
        last = body["messages"][-1]
        message: JSONObject = {"role": "assistant", "content": None, "tool_calls": [CALL]}
        if last["role"] == "tool":
            message = {"role": "assistant", "content": f"It is {last['content']}."}
        return 200, {"id": "x", "choices": [{"index": 0, "message": message}]}


def _session(tmp_path: Path, *faults: JSONObject, **config: object) -> ProxySession:
    options = {"session_id": "s", "roles": ROLES, "perturb": faults, **config}
    sleep, in_flight = options.pop("sleep", None), options.pop("in_flight", None)
    session_config = SessionConfig.model_validate(options)
    if sleep is None:
        return ProxySession(session_config, tmp_path)
    return ProxySession(session_config, tmp_path, sleep=sleep, in_flight=in_flight)


def _records(session: ProxySession, kind: str) -> list[dict[str, JSON]]:
    lines = session.log_path.read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if r["kind"] == kind]


def _content(response: JSONObject) -> JSON:
    return response["choices"][0]["message"]["content"]


def test_the_request_hash_stays_the_clients(tmp_path: Path) -> None:
    session = _session(tmp_path, {"op": "tool_error", "role": "agent", "at": 0})
    upstream = Upstream()
    session.handle("agent", RESULT, upstream)
    assert upstream.bodies[0]["messages"][-1]["content"] == TOOL_ERRORS["timeout"]
    (crossing,) = _records(session, "crossing")
    assert crossing["request"] == RESULT
    assert crossing["request_hash"] == request_hash(RESULT)
    assert crossing["upstream_request"] == upstream.bodies[0]
    assert crossing["perturbation"] == {
        "op": "tool_error",
        "params": {},
        "site": "messages[2].content",
        "before_hash": request_hash(RESULT),
        "after_hash": request_hash(upstream.bodies[0]),
    }
    assert "upstream_response" not in crossing


@pytest.mark.parametrize("op", ["tool_result", "loop"])  # on the request, and on the response
def test_a_fault_with_no_site_logs_a_miss_and_changes_nothing(tmp_path: Path, op: str) -> None:
    session = _session(tmp_path, {"op": op, "role": "agent", "at": 0})
    upstream = Upstream()
    answer = session.handle("agent", ASK, upstream)[1]  # no tool result, no previous tool calls
    assert upstream.bodies == [ASK]
    assert answer["choices"][0]["message"]["tool_calls"] == [CALL]
    (miss,) = _records(session, "failure")
    assert (miss["reason"], miss["k"], miss["fault"]["op"]) == ("perturbation_miss", 0, op)
    (crossing,) = _records(session, "crossing")
    assert not {"perturbation", "upstream_request", "upstream_response"} & crossing.keys()


@pytest.mark.parametrize(("status", "sent"), [(429, 429), (500, 500), ("timeout", 504)])
def test_upstream_error_answers_without_calling_the_upstream(
    tmp_path: Path, status: JSON, sent: int
) -> None:
    fault = {"op": "upstream_error", "role": "agent", "at": 1, "params": {"status": status}}
    session = _session(tmp_path, {**fault, "params": {"status": status, "times": 2}})
    upstream = Upstream()
    session.handle("agent", ASK, upstream)
    assert [session.handle("agent", RESULT, upstream)[0] for _ in range(3)] == [sent, sent, 200]
    assert len(upstream.bodies) == 2  # the first crossing and the third try of the second
    session.handle("agent", RESULT, lambda url, body: (503, {"error": "busy"}))
    failures = _records(session, "failure")
    assert [(f["status"], f["k"], "fault" in f) for f in failures] == [
        (sent, 1, True),
        (sent, 1, True),
        (503, 2, False),  # a real upstream error carries no fault
    ]
    assert [c["k"] for c in _records(session, "crossing")] == [0, 1]


def test_faults_apply_only_from_replay_until(tmp_path: Path) -> None:
    recorded = _session(tmp_path, session_id="ref")
    for body in (ASK, RESULT):
        recorded.handle("agent", body, Upstream())
    recorded.close()
    rewrite = {"op": "output_rewrite", "role": "agent", "at": 1, "params": {"text": "never"}}
    session = _session(tmp_path, rewrite, reference=recorded.log_path, replay_until=1)
    upstream = Upstream()
    session.handle("agent", ASK, upstream)  # replayed
    assert _content(session.handle("agent", RESULT, upstream)[1]) == "never"
    assert len(upstream.bodies) == 1
    live = _records(session, "crossing")[1]
    # The divergence check compares what the upstream answered, not what the fault changed
    assert live["divergence"] == []
    assert _content(live["upstream_response"]) == "It is 10:00."
    with pytest.raises(RecordingError, match="replayed prefix"):
        _session(
            tmp_path,
            {**rewrite, "at": 0},
            session_id="t",
            reference=recorded.log_path,
            replay_until=1,
        )
    assert not (tmp_path / "t.jsonl").exists()


def test_a_delay_grows_with_the_requests_in_flight(tmp_path: Path) -> None:
    slept: list[float] = []
    delay = {"op": "delay", "role": "agent", "at": 0, "params": {"ms": 100, "per_request_ms": 50}}
    session = _session(tmp_path, delay, sleep=slept.append, in_flight=lambda: 3)
    session.handle("agent", ASK, Upstream())
    assert slept == [0.2]
    (crossing,) = _records(session, "crossing")
    applied = crossing["perturbation"]
    assert applied["params"] == {"ms": 100, "per_request_ms": 50, "delay_ms": 200}
    assert applied["before_hash"] == applied["after_hash"]


def test_loop_repeats_the_tool_calls_of_the_previous_crossing(tmp_path: Path) -> None:
    session = _session(tmp_path, {"op": "loop", "role": "agent", "at": 1})
    upstream = Upstream()
    session.handle("agent", ASK, upstream)
    looped = session.handle("agent", RESULT, upstream)[1]
    calls = looped["choices"][0]["message"]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["clock"]
    assert calls[0]["id"] == f"call_{derive_seed(0, 'loop', 1):08x}_0"  # the seed of op and k
    assert _content(_records(session, "crossing")[1]["upstream_response"]) == "It is 10:00."
