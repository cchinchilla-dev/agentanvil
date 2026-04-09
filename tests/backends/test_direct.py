"""DirectBackend integration tests using `httpx.MockTransport`.

No real API calls. Each provider gets a transport that returns a canned
response shaped like the vendor would.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from agentanvil.backends.direct import DirectBackend
from agentanvil.backends.pricing import cost_for, pricing_table_version
from agentanvil.backends.types import Message
from agentanvil.exceptions import BackendError


def _patch_client(backend: DirectBackend, transport: httpx.MockTransport) -> None:
    """Swap the AsyncClient inside the provider with a MockTransport-backed one."""
    base_url = backend._client._http.base_url
    headers = backend._client._http.headers
    backend._client._http = httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        transport=transport,
    )


# ---------- OpenAI ----------


def _openai_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["model"] == "gpt-4o-2024-11-20"
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "model": "gpt-4o-2024-11-20",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello back"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 4,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )


async def test_direct_backend_openai_complete_returns_normalised_response() -> None:
    backend = DirectBackend("openai", api_key="sk-test")
    _patch_client(backend, httpx.MockTransport(_openai_handler))
    resp = await backend.complete(
        [Message(role="user", content="hi")],
        model="gpt-4o-2024-11-20",
    )
    assert resp.content == "hello back"
    assert resp.provider == "openai"
    assert resp.usage.input_tokens == 12
    assert resp.usage.output_tokens == 4
    assert resp.cost_usd > 0


def _openai_o1_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "o1-2024-12-17",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "thinking done"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "completion_tokens_details": {"reasoning_tokens": 200},
            },
        },
    )


async def test_direct_backend_reasoning_tokens_propagated_for_o1() -> None:
    backend = DirectBackend("openai", api_key="sk-test")
    _patch_client(backend, httpx.MockTransport(_openai_o1_handler))
    resp = await backend.complete([Message(role="user", content="?")], model="o1-2024-12-17")
    assert resp.usage.reasoning_tokens == 200
    # Reasoning tokens billed at output rate → cost > pure I/O cost.
    base_cost = cost_for(
        "openai", "o1-2024-12-17", input_tokens=100, output_tokens=50, reasoning_tokens=0
    )
    assert resp.cost_usd > base_cost


# ---------- Anthropic ----------


def _anthropic_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "model": "claude-3-5-sonnet-20241022",
            "content": [{"type": "text", "text": "hi from claude"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 8, "output_tokens": 5},
        },
    )


async def test_direct_backend_anthropic_complete_returns_normalised_response() -> None:
    backend = DirectBackend("anthropic", api_key="sk-test")
    _patch_client(backend, httpx.MockTransport(_anthropic_handler))
    resp = await backend.complete(
        [Message(role="user", content="hi")],
        model="claude-3-5-sonnet-20241022",
    )
    assert resp.content == "hi from claude"
    assert resp.provider == "anthropic"
    assert resp.finish_reason == "stop"
    assert resp.cost_usd > 0


def _anthropic_thinking_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "claude-3-7-sonnet-20250219",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 50,
                "output_tokens": 20,
                "thinking_output_tokens": 300,
            },
        },
    )


async def test_direct_backend_reasoning_tokens_propagated_for_claude_extended_thinking() -> None:
    backend = DirectBackend("anthropic", api_key="sk-test")
    _patch_client(backend, httpx.MockTransport(_anthropic_thinking_handler))
    resp = await backend.complete(
        [Message(role="user", content="hi")],
        model="claude-3-7-sonnet-20250219",
    )
    assert resp.usage.reasoning_tokens == 300


# ---------- Google ----------


def _google_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": "hello from gemini"}], "role": "model"},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 6,
                "candidatesTokenCount": 4,
            },
        },
    )


async def test_direct_backend_google_complete_returns_normalised_response() -> None:
    backend = DirectBackend("google", api_key="sk-test")
    _patch_client(backend, httpx.MockTransport(_google_handler))
    resp = await backend.complete(
        [Message(role="user", content="hi")],
        model="gemini-1.5-pro-002",
    )
    assert resp.content == "hello from gemini"
    assert resp.provider == "google"
    assert resp.usage.output_tokens == 4


# ---------- Cost estimation ----------


def test_cost_estimate_uses_pricing_table() -> None:
    backend = DirectBackend("openai", api_key="sk-test")
    cost = backend.cost_estimate("gpt-4o-2024-11-20", input_tokens=1000, output_tokens=500)
    # 1000 * 2.5/1e6 + 500 * 10/1e6 = 0.0025 + 0.005 = 0.0075
    assert cost == Decimal("0.007500")


def test_cost_estimate_raises_on_unknown_model() -> None:
    backend = DirectBackend("openai", api_key="sk-test")
    with pytest.raises(KeyError):
        backend.cost_estimate("does-not-exist", input_tokens=1, output_tokens=1)


def test_pricing_table_version_is_pinned() -> None:
    assert pricing_table_version() == "2026-04-09"


# ---------- Unknown provider ----------


def test_direct_backend_rejects_unknown_provider() -> None:
    with pytest.raises(BackendError):
        DirectBackend("cohere", api_key="x")  # type: ignore[arg-type]


# ---------- ABC contract suite parametrised over each provider ----------


def _patched(provider: str, handler: Any) -> DirectBackend:
    backend = DirectBackend(provider, api_key="sk-test")  # type: ignore[arg-type]
    _patch_client(backend, httpx.MockTransport(handler))
    return backend


@pytest.mark.parametrize(
    ("provider", "model", "handler"),
    [
        ("openai", "gpt-4o-2024-11-20", _openai_handler),
        ("anthropic", "claude-3-5-sonnet-20241022", _anthropic_handler),
        ("google", "gemini-1.5-pro-002", _google_handler),
    ],
)
async def test_direct_backend_contract_passes_abc_suite(
    provider: str, model: str, handler: Any
) -> None:
    from tests.backends.test_abc_contract import _assert_backend_contract

    backend = _patched(provider, handler)
    await _assert_backend_contract(backend, model=model)
