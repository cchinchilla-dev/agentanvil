"""Transport proxy over HTTP: session lifecycle, routing, errors and header handling."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from agentanvil.record_replay.proxy import ProxyServer
from agentanvil.record_replay.proxy_session import ProxySession, derive_seed

AUTH = "Bearer placeholder-token"


class Proxy:
    def __init__(self, server: ProxyServer, seen: list[tuple[str, str | None, dict[str, object]]]):
        host, port = server.server_address[:2]
        self.http = httpx.Client(base_url=f"http://{host!s}:{port}")
        self.server = server
        self.seen = seen

    def open(self, session_id: str, **extra: object) -> httpx.Response:
        roles = {"agent": {"upstream": "http://up/v1", "seed": 3}}
        return self.http.post(
            "/_anvil/sessions", json={"session_id": session_id, "roles": roles, **extra}
        )

    def complete(
        self, session_id: str, body: dict[str, object], role: str = "agent"
    ) -> httpx.Response:
        url = f"/s/{session_id}/{role}/v1/chat/completions"
        return self.http.post(url, json=body, headers={"Authorization": AUTH})


@pytest.fixture
def proxy(tmp_path: Path) -> Iterator[Proxy]:
    seen: list[tuple[str, str | None, dict[str, object]]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((str(request.url), request.headers.get("Authorization"), body))
        if body.get("model") == "boom":
            return httpx.Response(500, json={"error": {"message": "boom"}})
        if body.get("model") == "text":
            return httpx.Response(200, content=b"not json")
        message = {
            "role": "assistant",
            "content": f"seed {body.get('seed')} n {len(body['messages'])}",
        }
        return httpx.Response(200, json={"id": "x", "choices": [{"index": 0, "message": message}]})

    client = httpx.Client(transport=httpx.MockTransport(upstream))
    server = ProxyServer(("127.0.0.1", 0), tmp_path / "logs", client=client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Proxy(server, seen)
    finally:
        server.shutdown()
        server.server_close()


def _ask(n: int = 1, model: str = "m") -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": str(i)} for i in range(n)]}


def test_session_roundtrip(proxy: Proxy) -> None:
    opened = proxy.open("e1")
    assert opened.status_code == 201
    reply = proxy.complete("e1", _ask())
    assert reply.status_code == 200
    content = reply.json()["choices"][0]["message"]["content"]
    assert content == f"seed {derive_seed(3, 'agent', 0)} n 1"
    url, auth, _ = proxy.seen[0]
    assert url == "http://up/v1/chat/completions"
    assert auth == AUTH
    log = Path(opened.json()["log"]).read_text(encoding="utf-8")
    assert "placeholder-token" not in log
    assert proxy.http.delete("/_anvil/sessions/e1").status_code == 200
    assert proxy.complete("e1", _ask()).status_code == 404


def test_request_errors(proxy: Proxy) -> None:
    proxy.open("e2")
    assert proxy.http.post("/nowhere", json={}).status_code == 404
    bad_json = proxy.http.post("/s/e2/agent/v1/chat/completions", content=b"{oops")
    assert bad_json.status_code == 400
    assert proxy.http.post("/s/e2/agent/v1/chat/completions", json=[1]).status_code == 400
    assert proxy.complete("e2", {**_ask(), "stream": True}).status_code == 400
    assert proxy.complete("e2", _ask(), role="judge").status_code == 404
    assert proxy.complete("../x", _ask()).status_code == 404
    assert proxy.http.delete("/_anvil/sessions/missing").status_code == 404
    assert proxy.seen == []


def test_session_config_errors(proxy: Proxy) -> None:
    assert proxy.open("bad/id").status_code == 422
    assert proxy.open("e3", replay_until=2).status_code == 422
    assert proxy.open("e3").status_code == 201
    assert proxy.open("e3").status_code == 409  # already open
    proxy.http.delete("/_anvil/sessions/e3")
    assert proxy.open("e3").status_code == 409  # its log exists: never mixed with a new run


def test_upstream_error_is_passed_through_and_logged(proxy: Proxy) -> None:
    log = Path(proxy.open("e4").json()["log"])
    reply = proxy.complete("e4", _ask(model="boom"))
    assert reply.status_code == 500
    kinds = [json.loads(line)["kind"] for line in log.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["session", "failure"]


def test_success_without_json_is_not_recorded(proxy: Proxy) -> None:
    log = Path(proxy.open("e5").json()["log"])
    assert proxy.complete("e5", _ask(model="text")).status_code == 502
    kinds = [json.loads(line)["kind"] for line in log.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["session", "failure"]


def test_divergence_abort_returns_409(proxy: Proxy) -> None:
    reference = proxy.open("ref").json()["log"]
    proxy.complete("ref", _ask(1))
    proxy.http.delete("/_anvil/sessions/ref")
    proxy.open("chk", reference=reference, on_divergence="abort")
    assert proxy.complete("chk", _ask(2)).status_code == 409
    assert proxy.complete("chk", _ask(1)).status_code == 409  # aborted for good
    assert len(proxy.seen) == 1


def test_replay_skips_upstream(proxy: Proxy) -> None:
    reference = proxy.open("rec").json()["log"]
    first = proxy.complete("rec", _ask(1)).json()
    proxy.http.delete("/_anvil/sessions/rec")
    proxy.open("rep", reference=reference, replay_until=1)
    assert proxy.complete("rep", _ask(1)).json() == first
    assert len(proxy.seen) == 1


def test_close_returns_the_reference_crossings_left(proxy: Proxy) -> None:
    reference = proxy.open("full").json()["log"]
    proxy.complete("full", _ask(1))
    proxy.complete("full", _ask(2))
    assert proxy.http.delete("/_anvil/sessions/full").json()["missing"] == {}
    log = Path(proxy.open("half", reference=reference).json()["log"])
    proxy.complete("half", _ask(1))
    assert proxy.http.delete("/_anvil/sessions/half").json()["missing"] == {"agent": 1}
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["kind"] == "close"


def test_an_unexpected_error_answers_500(proxy: Proxy, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> None:
        raise OSError(28, "No space left on device")

    proxy.open("e7")
    monkeypatch.setattr(ProxySession, "handle", broken)
    reply = proxy.complete("e7", _ask())
    assert reply.status_code == 500
    assert reply.headers["connection"] == "close"
    assert "OSError" in reply.json()["error"]["message"]


def test_a_request_from_a_browser_is_refused(proxy: Proxy) -> None:
    config = {"session_id": "web", "roles": {"agent": {"upstream": "http://up/v1"}}}
    reply = proxy.http.post(
        "/_anvil/sessions",
        content=json.dumps(config),
        headers={"Content-Type": "text/plain", "Origin": "https://page.example"},
    )
    assert reply.status_code == 403
    assert reply.headers["connection"] == "close"
    assert proxy.http.delete("/_anvil/sessions/web", headers={"Origin": "null"}).status_code == 403
    assert proxy.open("web").status_code == 201  # nothing was opened by the refused call


def test_an_upstream_that_is_not_a_url_is_refused_at_open(proxy: Proxy) -> None:
    config = {"session_id": "e8", "roles": {"agent": {"upstream": "localhost:8000"}}}
    assert proxy.http.post("/_anvil/sessions", json=config).status_code == 422


@pytest.mark.skipif(not socket.has_ipv6, reason="no IPv6")
def test_an_ipv6_host_binds(tmp_path: Path) -> None:
    server = ProxyServer(("::1", 0), tmp_path)
    try:
        assert server.socket.family == socket.AF_INET6
    finally:
        server.server_close()
