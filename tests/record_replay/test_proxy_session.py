"""Transport-proxy sessions: k-th crossing replay, layer rewrites, divergences, failures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentanvil.exceptions import RecordingError, ReplayDivergenceError
from agentanvil.record_replay.normalize import JSON, JSONObject
from agentanvil.record_replay.proxy_log import RoleConfig, SessionConfig, load_reference
from agentanvil.record_replay.proxy_session import ProxySession, derive_seed

ROLES = {"agent": RoleConfig(upstream="http://a", seed=1), "user": RoleConfig(upstream="http://u")}


class Upstream:
    """Fake upstream: answers with the number of messages it saw; can fail first."""

    def __init__(self, fail_first: int = 0, suffix: str = "") -> None:
        self.calls: list[tuple[str, JSONObject]] = []
        self.fail_first = fail_first
        self.suffix = suffix

    def __call__(self, url: str, body: JSONObject) -> tuple[int, JSONObject]:
        self.calls.append((url, body))
        if len(self.calls) <= self.fail_first:
            return 503, {"error": "busy"}
        messages = body.get("messages")
        n = len(messages) if isinstance(messages, list) else 0
        message = {"role": "assistant", "content": f"seen {n}{self.suffix}"}
        return 200, {"id": f"x{len(self.calls)}", "choices": [{"index": 0, "message": message}]}


def _body(n: int, **extra: JSON) -> JSONObject:
    body: JSONObject = {
        "model": "m",
        "messages": [{"role": "user", "content": str(i)} for i in range(n)],
    }
    body.update(extra)
    return body


def _lines(path: Path) -> list[JSONObject]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _record(tmp_path: Path) -> Path:
    session = ProxySession(SessionConfig(session_id="ref", roles=ROLES), tmp_path)
    upstream = Upstream()
    for role, n in (("agent", 1), ("user", 2), ("agent", 3)):
        session.handle(role, _body(n), upstream)
    session.close()
    return session.log_path


def test_crossings_count_per_role_and_rewrite_seed(tmp_path: Path) -> None:
    session = ProxySession(SessionConfig(session_id="s", roles=ROLES), tmp_path)
    upstream = Upstream()
    session.handle("agent", _body(1, seed=99), upstream)
    session.handle("user", _body(2, seed=99), upstream)
    session.handle("agent", _body(3, seed=99), upstream)
    assert [b["seed"] for _, b in upstream.calls] == [
        derive_seed(1, "agent", 0),
        99,  # no seed configured for the user: the client's passes through
        derive_seed(1, "agent", 1),
    ]
    crossings = [x for x in _lines(session.log_path) if x["kind"] == "crossing"]
    assert [(c["role"], c["k"], c["index"]) for c in crossings] == [
        ("agent", 0, 0),
        ("user", 0, 1),
        ("agent", 1, 2),
    ]
    assert crossings[0]["request"]["seed"] == 99  # the log keeps the client's request


def test_upstream_error_does_not_consume_a_crossing(tmp_path: Path) -> None:
    session = ProxySession(SessionConfig(session_id="s", roles=ROLES), tmp_path)
    upstream = Upstream(fail_first=1)
    assert session.handle("agent", _body(1), upstream)[0] == 503
    assert session.handle("agent", _body(1), upstream)[0] == 200
    kinds = [(x["kind"], x.get("k")) for x in _lines(session.log_path)]
    assert kinds == [("session", None), ("failure", 0), ("crossing", 0)]


def test_prefix_is_replayed_and_the_rest_goes_live(tmp_path: Path) -> None:
    ref = _record(tmp_path)
    config = SessionConfig(session_id="r", roles=ROLES, reference=ref, replay_until=2)
    session = ProxySession(config, tmp_path)
    upstream = Upstream(suffix=" live")
    first = session.handle("agent", _body(1), upstream)[1]
    session.handle("user", _body(2), upstream)
    third = session.handle("agent", _body(3), upstream)[1]
    assert len(upstream.calls) == 1  # only the third crossing reached upstream
    assert first == load_reference(ref)["agent"][0].response
    assert third["choices"][0]["message"]["content"] == "seen 3 live"
    sources = [x["source"] for x in _lines(session.log_path) if x["kind"] == "crossing"]
    assert sources == ["replay", "replay", "live"]


def test_divergences_are_logged(tmp_path: Path) -> None:
    ref = _record(tmp_path)
    config = SessionConfig(session_id="v", roles=ROLES, reference=ref, replay_until=1)
    session = ProxySession(config, tmp_path)
    session.handle("agent", _body(1, temperature=0.5), Upstream())  # request differs, replayed
    session.handle("user", _body(2), Upstream(suffix="!"))  # response differs, live
    crossings = [x for x in _lines(session.log_path) if x["kind"] == "crossing"]
    assert [c["divergence"] for c in crossings] == [["request"], ["response"]]


def test_abort_on_divergence_refuses_later_calls(tmp_path: Path) -> None:
    ref = _record(tmp_path)
    config = SessionConfig(session_id="c", roles=ROLES, reference=ref, on_divergence="abort")
    session = ProxySession(config, tmp_path)
    upstream = Upstream()
    with pytest.raises(ReplayDivergenceError):
        session.handle("agent", _body(5), upstream)
    with pytest.raises(ReplayDivergenceError):
        session.handle("agent", _body(1), upstream)
    assert upstream.calls == []
    assert _lines(session.log_path)[-1]["reason"] == "divergence"


def test_order_permutation_is_seeded_and_stable(tmp_path: Path) -> None:
    def run(session_id: str, permute_seed: int) -> list[JSONObject]:
        config = SessionConfig(session_id=session_id, roles=ROLES, permute_seed=permute_seed)
        session = ProxySession(config, tmp_path)
        upstream = Upstream()
        tools = [{"name": str(i)} for i in range(6)]
        results = [{"role": "tool", "tool_call_id": str(i), "content": str(i)} for i in range(5)]
        history = [{"role": "user", "content": "q"}, *results]
        session.handle("agent", {"model": "m", "messages": history, "tools": tools}, upstream)
        grown = [*history, {"role": "assistant", "content": "a"}, {"role": "user", "content": "q2"}]
        session.handle("agent", {"model": "m", "messages": grown, "tools": tools}, upstream)
        return [b for _, b in upstream.calls]

    a, b, c = run("p1", 7), run("p2", 7), run("p3", 8)
    assert a == b
    assert a[0]["tools"] != c[0]["tools"]
    assert a[0]["messages"] == a[1]["messages"][:6]  # a run keeps its order as the history grows
    assert a[0]["messages"][0] == {"role": "user", "content": "q"}


def test_session_errors(tmp_path: Path) -> None:
    session = ProxySession(SessionConfig(session_id="e", roles=ROLES), tmp_path)
    with pytest.raises(RecordingError):
        session.handle("judge", _body(1), Upstream())
    with pytest.raises(RecordingError):
        ProxySession(SessionConfig(session_id="e", roles=ROLES), tmp_path)  # log already exists
    with pytest.raises(ValidationError):
        SessionConfig(session_id="../x", roles=ROLES)
    with pytest.raises(ValidationError):
        SessionConfig(session_id="x", roles={"a/b": RoleConfig(upstream="http://a")})
    with pytest.raises(ValidationError):
        SessionConfig(session_id="x", roles=ROLES, replay_until=2)


def test_incomplete_reference_is_rejected(tmp_path: Path) -> None:
    ref = _record(tmp_path)
    lines = ref.read_text(encoding="utf-8").splitlines()
    gap = tmp_path / "gap.jsonl"
    gap.write_text("\n".join([lines[0], lines[2], lines[3], lines[4]]) + "\n", encoding="utf-8")
    with pytest.raises(RecordingError, match="gaps"):
        load_reference(gap)
    truncated = tmp_path / "cut.jsonl"
    truncated.write_text("\n".join(lines)[:-10], encoding="utf-8")
    with pytest.raises(RecordingError, match="malformed"):
        load_reference(truncated)


def test_a_reference_without_its_close_record_is_rejected(tmp_path: Path) -> None:
    session = ProxySession(SessionConfig(session_id="open", roles=ROLES), tmp_path)
    session.handle("agent", _body(1), Upstream())  # never closed: a run cut short
    with pytest.raises(RecordingError, match="close"):
        load_reference(session.log_path)


def test_a_record_after_the_close_is_rejected(tmp_path: Path) -> None:
    ref = _record(tmp_path)
    lines = ref.read_text(encoding="utf-8").splitlines()
    tail = tmp_path / "tail.jsonl"
    tail.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")  # a second close
    with pytest.raises(RecordingError, match="after the close"):
        load_reference(tail)
