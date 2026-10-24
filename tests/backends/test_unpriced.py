"""Models without a price: zero cost behind a custom `base_url`, an error on the vendor's API.

No real API calls: each backend gets a `httpx.MockTransport` with a canned vendor response.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentanvil.backends.direct import DirectBackend
from agentanvil.backends.types import LLMResponse, Message, Usage
from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.recording import RecordingBackend

LOCAL = "local-model"  # served by a self-hosted server, so absent from pricing.yaml
SERVER = "http://127.0.0.1:8000/v1"
HI = [Message(role="user", content="hi")]


def _answer(provider: str, model: str) -> dict[str, Any]:
    if provider == "anthropic":
        return {
            "model": model,
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "stop_reason": "end_turn",
        }
    if provider == "google":
        return {
            "candidates": [{"content": {"parts": [{"text": "hello"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
        }
    return {
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }


def _backend(provider: str, response: httpx.Response, base_url: str | None) -> DirectBackend:
    backend = DirectBackend(provider, api_key="YOUR_API_KEY_HERE", base_url=base_url)  # type: ignore[arg-type]
    http = backend._client._http
    backend._client._http = httpx.AsyncClient(
        base_url=http.base_url,
        headers=http.headers,
        transport=httpx.MockTransport(lambda _request: response),
    )
    return backend


def _complete(provider: str, model: str, base_url: str | None) -> DirectBackend:
    return _backend(provider, httpx.Response(200, json=_answer(provider, model)), base_url)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
async def test_unpriced_model_behind_base_url_costs_zero(provider: str) -> None:
    response = await _complete(provider, LOCAL, SERVER).complete(HI, model=LOCAL)

    assert response.content == "hello"
    assert response.cost_usd == Decimal(0)
    assert response.priced is False


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
async def test_unpriced_hosted_model_still_raises(provider: str) -> None:
    with pytest.raises(KeyError, match=LOCAL):
        await _complete(provider, LOCAL, None).complete(HI, model=LOCAL)


async def test_vendor_url_passed_explicitly_is_not_a_custom_server() -> None:
    backend = _complete("openai", LOCAL, "https://api.openai.com/v1/")
    with pytest.raises(KeyError, match=LOCAL):
        await backend.complete(HI, model=LOCAL)


async def test_priced_model_behind_base_url_keeps_its_cost() -> None:
    model = "gpt-4o-2024-11-20"
    response = await _complete("openai", model, SERVER).complete(HI, model=model)

    assert response.cost_usd > 0
    assert response.priced is True


@pytest.mark.parametrize(
    ("with_key", "header"), [(False, None), (True, "Bearer YOUR_API_KEY_HERE")]
)
async def test_openai_sends_authorization_only_with_a_key(
    with_key: bool, header: str | None
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_answer("openai", LOCAL))

    backend = DirectBackend(
        "openai", api_key="YOUR_API_KEY_HERE" if with_key else "", base_url=SERVER
    )
    http = backend._client._http
    backend._client._http = httpx.AsyncClient(
        base_url=http.base_url, headers=http.headers, transport=httpx.MockTransport(handler)
    )
    response = await backend.complete(HI, model=LOCAL)

    assert response.content == "hello"
    assert seen[0].headers.get("Authorization") == header


async def test_stream_final_chunk_of_unpriced_model_costs_zero() -> None:
    def chunk(**fields: Any) -> str:
        return f"data: {json.dumps({'model': LOCAL, **fields})}\n\n"

    body = (
        chunk(choices=[{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}])
        + chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}])
        + chunk(choices=[], usage={"prompt_tokens": 3, "completion_tokens": 1})
        + "data: [DONE]\n\n"
    )
    stream = httpx.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream"}
    )
    chunks = [c async for c in _backend("openai", stream, SERVER).stream(HI, model=LOCAL)]

    assert [c.content for c in chunks] == ["hello", None]
    assert (chunks[-1].cost_usd, chunks[-1].priced) == (Decimal(0), False)


def test_priced_appears_in_a_dump_only_when_false() -> None:
    response = LLMResponse(
        content="hello",
        usage=Usage(input_tokens=3, output_tokens=2),
        finish_reason="stop",
        latency_ms=1,
        cost_usd=Decimal(0),
        model=LOCAL,
        provider="openai",
    )
    unpriced = response.model_copy(update={"priced": False})

    assert "priced" not in response.model_dump(mode="json")
    assert unpriced.model_dump(mode="json")["priced"] is False
    assert LLMResponse.model_validate(unpriced.model_dump(mode="json")).priced is False


async def test_unpriced_response_survives_record_and_replay(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await RecordingBackend(_complete("openai", LOCAL, SERVER), out).complete(HI, model=LOCAL)
    replayed = await MockBackend(out).complete(HI, model=LOCAL)

    assert (replayed.cost_usd, replayed.priced) == (Decimal(0), False)
