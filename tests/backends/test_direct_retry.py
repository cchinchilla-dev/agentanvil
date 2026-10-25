"""`DirectBackend` retries transient failures and honours the server's delay (#8)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from agentanvil.backends import retry
from agentanvil.backends.direct import DirectBackend
from agentanvil.backends.retry import RetryPolicy
from agentanvil.exceptions import BackendError
from tests.backends.test_direct import _openai_handler
from tests.backends.test_direct_stream import GOOGLE, HI, OPENAI, _google_chunk, _sse

Reply = httpx.Response | httpx.TransportError


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The delays slept, with no real sleep; full jitter draws its upper bound."""
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(retry.anyio, "sleep", sleep)
    monkeypatch.setattr(retry.random, "uniform", lambda low, high: high)
    return slept


def _backend(
    provider: str, *replies: Reply, policy: RetryPolicy | None = None
) -> tuple[DirectBackend, list[httpx.Request]]:
    """A backend whose server answers with ``replies`` in order, then succeeds."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) <= len(replies):
            reply = replies[len(requests) - 1]
            if isinstance(reply, httpx.TransportError):
                raise reply
            return reply
        if provider == "google":
            return _sse(_google_chunk([{"text": "hi"}], 1))
        return _openai_handler(request)

    backend = DirectBackend(provider, api_key="YOUR_API_KEY_HERE", retry=policy)  # type: ignore[arg-type]
    http = backend._client._http
    backend._client._http = httpx.AsyncClient(
        base_url=http.base_url, headers=http.headers, transport=httpx.MockTransport(handler)
    )
    return backend, requests


def _status(code: int, **headers: str) -> httpx.Response:
    return httpx.Response(code, headers=headers, json={"error": {"message": "try later"}})


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504, 529])
async def test_transient_statuses_are_retried(waits: list[float], code: int) -> None:
    backend, requests = _backend("openai", _status(code))

    response = await backend.complete(HI, model=OPENAI)

    assert response.content == "hello back"
    assert (len(requests), waits) == (2, [1.0])


async def test_retry_bounded_by_max_attempts(
    waits: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    backend, requests = _backend("openai", *[_status(529)] * 3)

    with pytest.raises(BackendError, match=r"^openai returned 529 after 3 attempt\(s\)$") as info:
        await backend.complete(HI, model=OPENAI)

    assert isinstance(info.value.__cause__, httpx.HTTPStatusError)
    assert (len(requests), waits) == (3, [1.0, 2.0])
    assert "openai call failed (attempt 1 of 3); retrying in 1.00 s" in caplog.text


async def test_retry_exponential_backoff_with_jitter(
    waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn: list[tuple[float, float]] = []
    monkeypatch.setattr(retry.random, "uniform", lambda low, high: drawn.append((low, high)) or 0.5)
    policy = RetryPolicy(max_attempts=5, base_delay_s=1.0, max_delay_s=3.0)
    backend, _ = _backend("openai", *[_status(503)] * 4, policy=policy)

    await backend.complete(HI, model=OPENAI)

    assert drawn == [(0, 1.0), (0, 2.0), (0, 3.0), (0, 3.0)]  # doubled, then capped
    assert waits == [0.5] * 4


async def test_retry_stops_on_4xx_non_429(waits: list[float]) -> None:
    backend, requests = _backend("openai", _status(400))

    with pytest.raises(BackendError, match=r"^openai returned 400 Bad Request$"):
        await backend.complete(HI, model=OPENAI)

    assert (len(requests), waits) == (1, [])


async def test_retry_honours_retry_after_header(waits: list[float]) -> None:
    backend, _ = _backend("openai", _status(429, **{"retry-after": "7"}))

    await backend.complete(HI, model=OPENAI)

    assert waits == [7.0]


async def test_a_longer_wait_than_max_delay_fails_at_once(waits: list[float]) -> None:
    backend, requests = _backend("openai", _status(429, **{"retry-after": "60"}))

    with pytest.raises(BackendError, match="asks to wait 60 s, longer than max_delay_s=30"):
        await backend.complete(HI, model=OPENAI)

    assert (len(requests), waits) == (1, [])


async def test_network_errors_are_retried(waits: list[float]) -> None:
    backend, requests = _backend("openai", httpx.ConnectError("refused"))
    assert (await backend.complete(HI, model=OPENAI)).content == "hello back"
    assert len(requests) == 2

    backend, _ = _backend("openai", *[httpx.ReadTimeout("slow")] * 3)
    with pytest.raises(BackendError, match=r"could not be reached \(ReadTimeout\) after 3"):
        await backend.complete(HI, model=OPENAI)


async def test_one_attempt_turns_retries_off(waits: list[float]) -> None:
    backend, requests = _backend("openai", _status(503), policy=RetryPolicy(max_attempts=1))

    with pytest.raises(BackendError, match="after 1 attempt"):
        await backend.complete(HI, model=OPENAI)

    assert (len(requests), waits) == (1, [])
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=0)


async def test_stream_retries_until_the_first_chunk(waits: list[float]) -> None:
    google = {"error": {"details": [{"@type": "RetryInfo", "retryDelay": "4s"}]}}
    unread = httpx.ByteStream(json.dumps(google).encode())  # as off the network, not yet read
    backend, requests = _backend("google", httpx.Response(429, stream=unread))

    chunks = [chunk async for chunk in backend.stream(HI, model=GOOGLE)]

    assert [c.content for c in chunks] == ["hi", None]
    assert (len(requests), waits) == (2, [4.0])  # the delay was read from the stream's body


class _Broken(httpx.AsyncByteStream):
    """One SSE chunk, then the connection drops."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        chunk = {"model": OPENAI, "choices": [{"index": 0, "delta": {"content": "par"}}]}
        yield f"data: {json.dumps(chunk)}\n\n".encode()
        raise httpx.ReadError("connection reset")


async def test_stream_error_after_the_first_chunk_is_not_retried(waits: list[float]) -> None:
    backend, requests = _backend("openai", httpx.Response(200, stream=_Broken()))
    seen: list[Any] = []

    with pytest.raises(BackendError, match=r"^openai stream broke \(ReadError\)$"):
        async for chunk in backend.stream(HI, model=OPENAI):
            seen.append(chunk.content)

    assert seen == ["par"]  # a retry would have sent it twice
    assert (len(requests), waits) == (1, [])
