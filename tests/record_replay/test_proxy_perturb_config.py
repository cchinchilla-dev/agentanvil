"""Faults at the transport proxy's HTTP layer (#36): what a session refuses, requests in flight."""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from agentanvil.record_replay.normalize import JSONObject
from agentanvil.record_replay.proxy import ProxyServer
from agentanvil.record_replay.proxy_log import RoleConfig, SessionConfig
from tests.record_replay.test_proxy import Proxy, proxy  # noqa: F401 (the proxy fixture)

ROLES = {"agent": RoleConfig(upstream="http://a")}


def test_abort_on_divergence_is_rejected_with_faults(proxy: Proxy) -> None:  # noqa: F811
    loop = {"op": "loop", "role": "agent", "at": 0}
    assert proxy.open("e1", on_divergence="abort", perturb=[loop]).status_code == 422
    assert proxy.open("e2", perturb=[{**loop, "role": "user"}]).status_code == 422
    assert proxy.open("e3", perturb=[loop, {**loop, "op": "inflate"}]).status_code == 422
    assert proxy.open("e4", perturb=[loop]).status_code == 201


@pytest.mark.parametrize(
    "fault",
    [
        {"op": "tool_result", "role": "agent", "at": 0, "params": {"unknown": 1}},
        {"op": "drop_instruction", "role": "agent", "at": 0, "params": {"pattern": "("}},
        {
            "op": "tool_call",
            "role": "agent",
            "at": 0,
            "params": {"rename_to": "a", "argument": "q"},
        },
        {"op": "output_rewrite", "role": "agent", "at": 0, "params": {}},
        {"op": "delay", "role": "agent", "at": 0, "params": {}},
        {"op": "upstream_error", "role": "agent", "at": 0, "params": {"status": 404}},
        {"op": "loop", "role": "agent", "at": -1},
        {"op": "explode", "role": "agent", "at": 0},
    ],
)
def test_invalid_faults_are_refused(fault: JSONObject) -> None:
    with pytest.raises(ValidationError):
        SessionConfig(session_id="s", roles=ROLES, perturb=[fault])


def test_the_proxy_counts_the_requests_it_serves(tmp_path: Path) -> None:
    server = ProxyServer(("127.0.0.1", 0), tmp_path)
    try:
        with server.serving(), server.serving():
            assert server.in_flight() == 2
        assert server.in_flight() == 0
    finally:
        server.server_close()


def test_a_completion_counts_as_in_flight_while_it_is_served(tmp_path: Path) -> None:
    seen: list[int] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(server.in_flight())
        message = {"role": "assistant", "content": "ok"}
        return httpx.Response(200, json={"choices": [{"index": 0, "message": message}]})

    client = httpx.Client(transport=httpx.MockTransport(upstream))
    server = ProxyServer(("127.0.0.1", 0), tmp_path, client=client)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        http = httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}")
        roles = {"agent": {"upstream": "http://up/v1"}}
        http.post("/_anvil/sessions", json={"session_id": "s", "roles": roles}).raise_for_status()
        ask = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        assert http.post("/s/s/agent/v1/chat/completions", json=ask).status_code == 200
        assert seen == [1]
        assert server.in_flight() == 0
    finally:
        server.shutdown()
        server.server_close()
