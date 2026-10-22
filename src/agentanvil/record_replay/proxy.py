"""Transport proxy: an OpenAI-compatible endpoint that records and replays LLM calls.

It sits in front of any OpenAI-compatible server (vLLM, SGLang, a hosted API) and
works with any client that lets you set its base URL, with no code inside the
agent's runtime. Each boundary of an episode gets its own base URL:

    http://127.0.0.1:8090/s/<session>/<role>/v1

and a driver opens and closes sessions around each episode:

    POST   /_anvil/sessions        SessionConfig as JSON   -> 201 {"session_id", "log"}
    DELETE /_anvil/sessions/<id>                           -> 200 {"session_id", "log", "missing"}

Only `POST .../v1/chat/completions` is proxied, without streaming. The proxy is a
transport layer: it forwards the JSON body with `httpx` instead of going through
`LLMBackend`, because the payload on the wire is what it records. It has no
authentication, so it binds to localhost by default. `Authorization` headers are
forwarded upstream and never logged.
"""

from __future__ import annotations

import contextlib
import json
import re
import socket
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from pydantic import ValidationError

from agentanvil.exceptions import RecordingError, ReplayDivergenceError
from agentanvil.record_replay.normalize import JSONObject
from agentanvil.record_replay.proxy_log import SessionConfig
from agentanvil.record_replay.proxy_session import Forward, ProxySession

MAX_BODY = 64 * 1024 * 1024  # long agent histories are large, but not this large
_COMPLETIONS = re.compile(r"^/s/([A-Za-z0-9_-]{1,64})/([A-Za-z0-9_-]{1,64})/v1/chat/completions$")
_SESSION = re.compile(r"^/_anvil/sessions/([A-Za-z0-9_-]{1,64})$")


class ProxyServer(ThreadingHTTPServer):
    """Threaded HTTP server holding the open sessions; one thread per connection."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        log_dir: Path,
        *,
        timeout: float = 600.0,
        client: httpx.Client | None = None,
    ) -> None:
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, _Handler)
        self.log_dir = log_dir
        self.sessions: dict[str, ProxySession] = {}
        self.sessions_lock = threading.Lock()
        self.client = client or httpx.Client(timeout=timeout)

    def server_close(self) -> None:
        super().server_close()
        self.client.close()

    def forward(self, authorization: str | None) -> Forward:
        """Upstream call for one client request, carrying its `Authorization` header."""
        headers = {"Authorization": authorization} if authorization else {}

        def send(base_url: str, body: JSONObject) -> tuple[int, JSONObject]:
            url = base_url.rstrip("/") + "/chat/completions"
            try:
                response = self.client.post(url, json=body, headers=headers)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                return 502, _error(f"upstream unreachable: {type(exc).__name__}")
            try:
                data = response.json()
            except ValueError:
                # A success without a JSON body must not become a recorded crossing.
                status = 502 if response.is_success else response.status_code
                return status, _error(response.text[:2000])
            if not isinstance(data, dict):
                return 502, _error("upstream returned a non-object JSON body")
            return response.status_code, data

        return send


class _Handler(BaseHTTPRequestHandler):
    server: ProxyServer
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        self._guarded(self._post)

    def do_DELETE(self) -> None:  # noqa: N802
        self._guarded(self._delete)

    def log_message(self, format: str, *args: object) -> None:
        """Silence per-request logging: the session logs are the record."""

    # ----- routes -----

    def _post(self) -> None:
        body = self._body()
        if body is None:
            return
        if self.path == "/_anvil/sessions":
            self._open(body)
        elif match := _COMPLETIONS.match(self.path):
            self._complete(match.group(1), match.group(2), body)
        else:
            self._send(404, _error(f"no route for POST {self.path}"))

    def _delete(self) -> None:
        if not (match := _SESSION.match(self.path)):
            self._send(404, _error(f"no route for DELETE {self.path}"))
            return
        with self.server.sessions_lock:
            session = self.server.sessions.pop(match.group(1), None)
        if session is None:
            self._send(404, _error(f"no open session {match.group(1)!r}"))
            return
        log, missing = str(session.log_path), session.close()  # close waits for a call in flight
        self._send(200, {"session_id": match.group(1), "log": log, "missing": dict(missing)})

    def _open(self, body: JSONObject) -> None:
        try:
            config = SessionConfig.model_validate(body)
        except ValidationError as exc:
            self._send(422, _error(f"invalid session config: {exc.error_count()} error(s)"))
            return
        taken = _error(f"session {config.session_id!r} is already open")
        with self.server.sessions_lock:
            if config.session_id in self.server.sessions:
                self._send(409, taken)
                return
        try:  # loads the reference: outside the lock, so other sessions keep their pace
            session = ProxySession(config, self.server.log_dir)
        except RecordingError as exc:
            self._send(409, _error(str(exc)))
            return
        with self.server.sessions_lock:
            if self.server.sessions.setdefault(config.session_id, session) is not session:
                self._send(409, taken)
                return
        self._send(201, {"session_id": config.session_id, "log": str(session.log_path)})

    def _complete(self, session_id: str, role: str, body: JSONObject) -> None:
        if body.get("stream"):
            self._send(400, _error("streaming is not supported by the proxy"))
            return
        with self.server.sessions_lock:
            session = self.server.sessions.get(session_id)
        if session is None:
            self._send(404, _error(f"no open session {session_id!r}"))
            return
        forward = self.server.forward(self.headers.get("Authorization"))
        try:
            status, response = session.handle(role, body, forward)
        except ReplayDivergenceError as exc:
            self._send(409, _error(str(exc)))
        except RecordingError as exc:
            self._send(404, _error(str(exc)))
        else:
            self._send(status, response)

    # ----- plumbing -----

    def _guarded(self, route: Callable[[], None]) -> None:
        # Anything unexpected (a full disk, a bug) answers 500 instead of a dropped connection.
        try:
            route()
        except Exception as exc:  # noqa: BLE001 — last resort, the client must get an answer
            self.close_connection = True
            with contextlib.suppress(OSError):
                self._send(500, _error(f"proxy error: {type(exc).__name__}: {exc}"))

    def _body(self) -> JSONObject | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True  # the unread body would be parsed as the next request
            self._send(400, _error("invalid Content-Length"))
            return None
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self._send(413, _error("request body too large"))
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, _error("request body is not valid JSON"))
            return None
        if not isinstance(data, dict):
            self._send(400, _error("request body must be a JSON object"))
            return None
        return data

    def _send(self, status: int, body: JSONObject) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8", "backslashreplace")
        self.send_response(status)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _error(message: str) -> JSONObject:
    return {"error": {"message": message, "type": "agentanvil_proxy_error"}}
