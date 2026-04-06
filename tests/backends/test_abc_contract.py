"""Contract tests every `LLMBackend` implementation must pass.

Imported by `test_direct.py` and (later) `test_agentloom_with_extra.py` to
verify each backend honours the ABC. Use `_assert_backend_contract` as the
single entry point.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import LLMResponse, Message, Usage
from tests.backends.mock_backend import FakeBackend


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


async def test_abc_contract_complete_returns_llm_response(fake_backend: FakeBackend) -> None:
    resp = await fake_backend.complete([Message(role="user", content="hi")], model="m")
    assert isinstance(resp, LLMResponse)
    assert resp.provider == "fake"


async def test_abc_contract_stream_yields_at_least_one_chunk(
    fake_backend: FakeBackend,
) -> None:
    chunks: list[LLMResponse] = []
    async for chunk in fake_backend.stream([Message(role="user", content="hi")], model="m"):
        chunks.append(chunk)
    assert len(chunks) >= 1
    assert all(isinstance(c, LLMResponse) for c in chunks)


def test_abc_contract_cost_estimate_returns_decimal(fake_backend: FakeBackend) -> None:
    cost = fake_backend.cost_estimate("m", input_tokens=10, output_tokens=5)
    assert isinstance(cost, Decimal)
    assert cost > 0


def test_reasoning_tokens_propagate_through_cost_estimate(
    fake_backend: FakeBackend,
) -> None:
    base = fake_backend.cost_estimate("m", input_tokens=10, output_tokens=5)
    with_reasoning = fake_backend.cost_estimate(
        "m", input_tokens=10, output_tokens=5, reasoning_tokens=20
    )
    assert with_reasoning > base


def test_canned_response_round_trip() -> None:
    canned = LLMResponse(
        content="canned",
        usage=Usage(input_tokens=2, output_tokens=3),
        finish_reason="stop",
        latency_ms=7,
        cost_usd=Decimal("0.001"),
        model="m",
        provider="fake",
    )
    backend = FakeBackend(canned=canned)
    # Returned response equals the canned one (round-trip safe via Pydantic).
    assert backend._canned == canned


async def _assert_backend_contract(backend: LLMBackend, *, model: str) -> None:
    """Single entry point — call from every concrete backend test module."""
    resp = await backend.complete([Message(role="user", content="hello")], model=model)
    assert isinstance(resp, LLMResponse)
    assert resp.usage.input_tokens >= 0
    assert resp.usage.output_tokens >= 0
    assert resp.finish_reason in {"stop", "length", "tool_calls", "content_filter", "error"}
    assert resp.cost_usd >= 0

    cost = backend.cost_estimate(model, input_tokens=100, output_tokens=50)
    assert isinstance(cost, Decimal)
