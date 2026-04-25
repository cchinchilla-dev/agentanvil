"""Edge cases for the record/replay envelope: hash collisions, concurrent flushes."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import anyio
import pytest

from agentanvil.backends.types import LLMResponse, Message, ToolDef, Usage
from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.recording import RecordingBackend, request_key
from tests.backends.mock_backend import FakeBackend


def _canned(content: str = "canned") -> LLMResponse:
    return LLMResponse(
        content=content,
        usage=Usage(input_tokens=4, output_tokens=2),
        finish_reason="stop",
        latency_ms=10,
        cost_usd=Decimal("0.0001"),
        model="gpt-4o-2024-11-20",
        provider="fake",
    )


# ---------- Hash key sensitivity ----------


def test_request_key_differs_on_temperature() -> None:
    msgs = [Message(role="user", content="hi")]
    a = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=None)
    b = request_key(msgs, model="m", temperature=0.7, max_tokens=None, tools=None, seed=None)
    assert a != b


def test_request_key_differs_on_max_tokens() -> None:
    msgs = [Message(role="user", content="hi")]
    a = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=None)
    b = request_key(msgs, model="m", temperature=0.0, max_tokens=1024, tools=None, seed=None)
    assert a != b


def test_request_key_differs_on_seed() -> None:
    msgs = [Message(role="user", content="hi")]
    a = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=None)
    b = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=42)
    assert a != b


def test_request_key_differs_on_tools() -> None:
    msgs = [Message(role="user", content="hi")]
    tool = ToolDef(name="search", description="search the web", parameters={"type": "object"})
    a = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=None, seed=None)
    b = request_key(msgs, model="m", temperature=0.0, max_tokens=None, tools=[tool], seed=None)
    assert a != b


def test_request_key_differs_on_model() -> None:
    msgs = [Message(role="user", content="hi")]
    a = request_key(msgs, model="m1", temperature=0.0, max_tokens=None, tools=None, seed=None)
    b = request_key(msgs, model="m2", temperature=0.0, max_tokens=None, tools=None, seed=None)
    assert a != b


# ---------- Step-id wins over hash collision ----------


async def test_step_id_lookup_overrides_request_hash(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned("by-step-id"))
    out = tmp_path / "rec.json"
    rec = RecordingBackend(fake, out)
    await rec.complete(
        [Message(role="user", content="canonical-prompt")],
        model="gpt-4o-2024-11-20",
        step_id="step_x",
    )

    mock = MockBackend(out)
    # Request unrelated to the recorded one → would miss by hash, hits by step_id.
    response = await mock.complete(
        [Message(role="user", content="totally different")],
        model="some-other-model",
        step_id="step_x",
    )
    assert response.content == "by-step-id"


# ---------- Concurrent flush safety ----------


async def test_concurrent_complete_calls_serialise_writes(tmp_path: Path) -> None:
    """Multiple concurrent calls must not corrupt the envelope on disk."""
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"
    rec = RecordingBackend(fake, out)

    async def call(i: int) -> None:
        await rec.complete(
            [Message(role="user", content=f"q-{i}")],
            model="gpt-4o-2024-11-20",
            step_id=f"step_{i}",
        )

    async with anyio.create_task_group() as tg:
        for i in range(20):
            tg.start_soon(call, i)

    envelope = json.loads(out.read_text())
    assert len(envelope["entries"]) == 20
    step_ids = {entry["step_id"] for entry in envelope["entries"]}
    assert step_ids == {f"step_{i}" for i in range(20)}


# ---------- Append-existing recording ----------


async def test_recording_backend_appends_to_existing_envelope(tmp_path: Path) -> None:
    fake = FakeBackend(canned=_canned())
    out = tmp_path / "rec.json"

    rec_a = RecordingBackend(fake, out)
    await rec_a.complete(
        [Message(role="user", content="a")], model="gpt-4o-2024-11-20", step_id="s1"
    )

    rec_b = RecordingBackend(fake, out)  # re-open
    await rec_b.complete(
        [Message(role="user", content="b")], model="gpt-4o-2024-11-20", step_id="s2"
    )

    envelope = json.loads(out.read_text())
    step_ids = {entry["step_id"] for entry in envelope["entries"]}
    assert step_ids == {"s1", "s2"}


# ---------- Atomic-rename guarantee on partial-write crash ----------


def test_recording_backend_atomic_rename_no_truncated_file_on_disk(tmp_path: Path) -> None:
    """The flush goes through `.tmp` + rename, so the destination is never half-written."""
    out = tmp_path / "rec.json"
    fake = FakeBackend(canned=_canned())
    rec = RecordingBackend(fake, out)
    rec._envelope["entries"].append({"key": "x", "step_id": "s", "request": {}, "response": {}})
    rec._flush()
    # After flush, the .tmp sibling should not exist (it was renamed away).
    assert not out.with_suffix(out.suffix + ".tmp").exists()
    # And the destination must be parseable JSON.
    json.loads(out.read_text())


def test_request_key_does_not_depend_on_timeout_s() -> None:
    """timeout_s changes runtime behaviour but never the response — must NOT shift the key."""
    # request_key signature has no timeout_s parameter — this test asserts that
    # design by attempting and failing to pass it.
    with pytest.raises(TypeError):
        request_key(  # type: ignore[call-arg]
            [Message(role="user", content="hi")],
            model="m",
            temperature=0.0,
            max_tokens=None,
            tools=None,
            seed=None,
            timeout_s=10.0,
        )
