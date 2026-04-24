"""MockBackend replay-correctness tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from agentanvil.backends.types import LLMResponse, Message, Usage
from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.recording import RecordingBackend
from tests.backends.mock_backend import FakeBackend

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "recordings" / "single_agent.json"


def _canned() -> LLMResponse:
    return LLMResponse(
        content="canned",
        usage=Usage(input_tokens=4, output_tokens=2),
        finish_reason="stop",
        latency_ms=10,
        cost_usd=Decimal("0.0001"),
        model="gpt-4o-2024-11-20",
        provider="fake",
    )


async def test_mock_backend_serves_by_step_id_when_present(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    rec = RecordingBackend(fake, out)
    await rec.complete(
        [Message(role="user", content="hi")],
        model="gpt-4o-2024-11-20",
        step_id="step_a",
    )

    mock = MockBackend(out)
    response = await mock.complete(
        [Message(role="user", content="anything-else-entirely")],
        model="ignored",
        step_id="step_a",
    )
    # step_id wins over hash mismatch.
    assert response.content == "canned"


async def test_mock_backend_serves_by_request_hash_when_step_id_missing(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    rec = RecordingBackend(fake, out)
    await rec.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")

    mock = MockBackend(out)
    response = await mock.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")
    assert response.content == "canned"


async def test_mock_backend_raises_key_error_on_unknown_request(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    out.write_text(
        json.dumps(
            {
                "recording_version": "1",
                "agentanvil_version": "0.1.1",
                "contract_hash": "sha256:",
                "run_id": "",
                "seed": None,
                "entries": [],
            }
        )
    )
    mock = MockBackend(out)
    with pytest.raises(KeyError):
        await mock.complete([Message(role="user", content="?")], model="gpt-4o-2024-11-20")


def test_mock_backend_rejects_envelope_with_wrong_version(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    out.write_text(json.dumps({"recording_version": "999", "entries": []}))
    with pytest.raises(RecordingError):
        MockBackend(out)


async def test_mock_backend_cost_estimate_is_zero(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    rec = RecordingBackend(fake, out)
    await rec.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")

    mock = MockBackend(out)
    assert mock.cost_estimate("any-model", input_tokens=1000, output_tokens=500) == Decimal(0)


async def test_mock_backend_loads_committed_fixture() -> None:
    """The single_agent.json fixture must remain a valid v1 envelope."""
    mock = MockBackend(FIXTURE)
    response = await mock.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")
    assert response.content == "Hello! How can I help you today?"
