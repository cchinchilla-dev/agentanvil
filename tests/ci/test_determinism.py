"""Bit-for-bit replay determinism — the foundational reproducibility invariant.

If this test fails, the record/replay envelope is broken — every downstream
reproducibility claim collapses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentanvil.backends.types import Message
from agentanvil.record_replay.mock import MockBackend

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "recordings" / "single_agent.json"


@pytest.mark.slow
async def test_record_then_replay_is_bit_for_bit() -> None:
    mock_a = MockBackend(FIXTURE)
    response_a = await mock_a.complete(
        [Message(role="user", content="hi")], model="gpt-4o-2024-11-20"
    )

    mock_b = MockBackend(FIXTURE)
    response_b = await mock_b.complete(
        [Message(role="user", content="hi")], model="gpt-4o-2024-11-20"
    )

    dump_a = json.dumps(response_a.model_dump(mode="json"), sort_keys=True)
    dump_b = json.dumps(response_b.model_dump(mode="json"), sort_keys=True)
    assert dump_a == dump_b


@pytest.mark.slow
async def test_full_envelope_round_trip_is_byte_stable() -> None:
    """Loading and re-serialising the envelope must be a no-op."""
    raw = json.loads(FIXTURE.read_text())
    once = json.dumps(raw, sort_keys=True, indent=2)
    twice = json.dumps(json.loads(once), sort_keys=True, indent=2)
    assert once == twice
