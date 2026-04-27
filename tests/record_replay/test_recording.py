"""RecordingBackend capture-fidelity tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from agentanvil.backends.types import LLMResponse, Message, Usage
from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.recording import RECORDING_VERSION, RecordingBackend, request_key
from tests.backends.mock_backend import FakeBackend


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


async def test_recording_backend_captures_every_call(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    backend = RecordingBackend(fake, out)
    await backend.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")
    await backend.complete([Message(role="user", content="ho")], model="gpt-4o-2024-11-20")
    envelope = json.loads(out.read_text())
    assert envelope["recording_version"] == RECORDING_VERSION
    assert len(envelope["entries"]) == 2
    assert envelope["entries"][0]["response"]["content"] == "canned"


async def test_recording_backend_flushes_per_call(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    backend = RecordingBackend(fake, out)
    await backend.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")
    # Simulate crash: file must already be on disk.
    assert out.exists()
    envelope = json.loads(out.read_text())
    assert len(envelope["entries"]) == 1


async def test_recording_backend_step_id_recorded(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    backend = RecordingBackend(fake, out)
    await backend.complete(
        [Message(role="user", content="hi")],
        model="gpt-4o-2024-11-20",
        step_id="step_007",
    )
    envelope = json.loads(out.read_text())
    assert envelope["entries"][0]["step_id"] == "step_007"


async def test_recording_envelope_round_trip_schema_v1(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    backend = RecordingBackend(
        fake,
        out,
        contract_hash="sha256:deadbeef",
        run_id="run_1",
        seed=42,
    )
    await backend.complete([Message(role="user", content="hi")], model="gpt-4o-2024-11-20")
    envelope = json.loads(out.read_text())
    # Required top-level fields.
    for field in (
        "recording_version",
        "agentanvil_version",
        "contract_hash",
        "run_id",
        "seed",
        "entries",
    ):
        assert field in envelope


def test_recording_key_stable_across_pydantic_minor_versions() -> None:
    """Hash relies on `model_dump(mode='json')` — explicit, not `repr`."""
    msgs = [Message(role="user", content="hello")]
    k1 = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=None)
    k2 = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=None)
    assert k1 == k2
    assert k1.startswith("sha256:")


async def test_recording_backend_rejects_envelope_with_wrong_version(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    out.write_text(json.dumps({"recording_version": "0", "entries": []}))
    fake = FakeBackend(canned=_canned())
    with pytest.raises(RecordingError):
        RecordingBackend(fake, out)
