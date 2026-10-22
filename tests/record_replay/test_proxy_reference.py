"""Transport-proxy sessions against a reference: extra and missing crossings, close, rehashing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.normalize import JSONObject, Normalizer
from agentanvil.record_replay.proxy_log import RoleConfig, SessionConfig
from agentanvil.record_replay.proxy_session import ProxySession
from tests.record_replay.test_proxy_session import ROLES, Upstream, _body, _lines, _record


def _against(tmp_path: Path, session_id: str, **config: object) -> ProxySession:
    reference = _record(tmp_path)
    return ProxySession(
        SessionConfig.model_validate(
            {"session_id": session_id, "roles": ROLES, "reference": reference, **config}
        ),
        tmp_path,
    )


def test_a_crossing_the_reference_does_not_have_is_extra(tmp_path: Path) -> None:
    session = _against(tmp_path, "x")
    for role, n in (("agent", 1), ("user", 2), ("agent", 3), ("user", 4)):
        session.handle(role, _body(n), Upstream())
    crossings = [x for x in _lines(session.log_path) if x["kind"] == "crossing"]
    assert [c["divergence"] for c in crossings] == [[], [], [], ["extra"]]


def test_close_logs_the_crossings_the_reference_had_left(tmp_path: Path) -> None:
    session = _against(tmp_path, "short")
    session.handle("agent", _body(1), Upstream())
    assert session.close() == {"agent": 1, "user": 1}
    assert _lines(session.log_path)[-1] == {
        "kind": "close",
        "session_id": "short",
        "crossings": {"agent": 1},
        "missing": {"agent": 1, "user": 1},
    }
    with pytest.raises(RecordingError, match="closed"):
        session.handle("agent", _body(3), Upstream())


def test_a_session_without_reference_closes_with_nothing_missing(tmp_path: Path) -> None:
    session = ProxySession(SessionConfig(session_id="free", roles=ROLES), tmp_path)
    session.handle("agent", _body(1), Upstream())
    assert session.close() == {}
    assert _lines(session.log_path)[-1]["crossings"] == {"agent": 1}


def test_the_reference_is_hashed_under_the_session_normalizer(tmp_path: Path) -> None:
    def ask(text: str) -> JSONObject:
        return {"model": "m", "messages": [{"role": "user", "content": text}]}

    recorder = ProxySession(SessionConfig(session_id="ref", roles=ROLES), tmp_path)
    recorder.handle("agent", ask("a  b"), Upstream())  # recorded under the default normalizer
    config = SessionConfig(
        session_id="w",
        roles=ROLES,
        reference=recorder.log_path,
        normalizer=Normalizer(whitespace=True),
    )
    session = ProxySession(config, tmp_path)
    session.handle("agent", ask("a b"), Upstream())
    assert _lines(session.log_path)[-1]["divergence"] == []


def test_a_lone_surrogate_is_hashed_and_logged_as_its_escape(tmp_path: Path) -> None:
    session = ProxySession(SessionConfig(session_id="raw", roles=ROLES), tmp_path)
    body: JSONObject = {"model": "m", "messages": [{"role": "tool", "content": "bad \udcff"}]}
    assert session.handle("agent", body, Upstream())[0] == 200
    line = session.log_path.read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(line)["request"] == body


def test_the_header_lists_permuted_roles_in_order(tmp_path: Path) -> None:
    config = SessionConfig(session_id="h", roles=ROLES, permute_roles=frozenset({"user", "agent"}))
    session = ProxySession(config, tmp_path)
    assert _lines(session.log_path)[0]["config"]["permute_roles"] == ["agent", "user"]


@pytest.mark.parametrize("upstream", ["ftp://a/v1", "http:///v1", "http://a:99999/v1", "a/v1"])
def test_an_upstream_that_is_not_an_http_url_is_rejected(upstream: str) -> None:
    with pytest.raises(ValidationError):
        RoleConfig(upstream=upstream)
