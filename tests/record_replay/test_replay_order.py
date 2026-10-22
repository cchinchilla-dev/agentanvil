"""Repeated calls replay in recorded order; streamed calls record and replay every chunk."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import LLMResponse, Message, ToolDef, Usage
from agentanvil.exceptions import RecordingError, ReplayMissError
from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.recording import RecordingBackend

MODEL = "gpt-4o-2024-11-20"
ASK = [Message(role="user", content="same question")]


def _response(content: str | None) -> LLMResponse:
    return LLMResponse(
        content=content,
        usage=Usage(input_tokens=1, output_tokens=1),
        finish_reason="stop",
        latency_ms=1,
        cost_usd=Decimal("0"),
        model=MODEL,
        provider="fake",
    )


class SequenceBackend(LLMBackend):
    """Answers each call with the next content of a list; streams it word by word."""

    name = "sequence"

    def __init__(self, contents: list[str]) -> None:
        self._contents = iter(contents)

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[ToolDef] | None = None,
        seed: int | None = None,
        timeout_s: float | None = None,
        step_id: str | None = None,
    ) -> LLMResponse:
        return _response(next(self._contents))

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[ToolDef] | None = None,
        seed: int | None = None,
    ) -> AsyncIterator[LLMResponse]:
        for piece in next(self._contents).split():
            yield _response(piece)
        yield _response(None)  # the stream contract: the last chunk has no text

    def cost_estimate(
        self, model: str, input_tokens: int, output_tokens: int, reasoning_tokens: int = 0
    ) -> Decimal:
        return Decimal(0)


async def _record(out: Path, contents: list[str], step_id: str | None = None) -> None:
    rec = RecordingBackend(SequenceBackend(contents), out)
    for _ in contents:
        await rec.complete(ASK, model=MODEL, step_id=step_id)


async def test_repeated_requests_replay_in_order(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["a", "b", "c"])
    mock = MockBackend(out)
    replies = [(await mock.complete(ASK, model=MODEL)).content for _ in range(4)]
    assert replies == ["a", "b", "c", "c"]  # exhausted: the last one again


async def test_repeated_step_id_replays_in_order(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["first", "second"], step_id="loop")
    mock = MockBackend(out)
    other = [Message(role="user", content="unrelated")]
    replies = [(await mock.complete(other, model="m", step_id="loop")).content for _ in range(2)]
    assert replies == ["first", "second"]


async def test_strict_replay_fails_when_exhausted(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["only"])
    mock = MockBackend(out, strict=True)
    assert (await mock.complete(ASK, model=MODEL)).content == "only"
    with pytest.raises(ReplayMissError) as exc_info:
        await mock.complete(ASK, model=MODEL)
    assert isinstance(exc_info.value, KeyError)
    assert isinstance(exc_info.value, RecordingError)
    assert str(exc_info.value).startswith("No recording left")  # not quoted like a KeyError


async def test_strict_step_id_never_falls_back_to_another_steps_entry(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["from a"], step_id="a")
    await _record(out, ["from b"], step_id="b")  # the same request from another step
    mock = MockBackend(out, strict=True)
    assert (await mock.complete(ASK, model=MODEL, step_id="a")).content == "from a"
    with pytest.raises(ReplayMissError):
        await mock.complete(ASK, model=MODEL, step_id="a")
    assert (await mock.complete(ASK, model=MODEL, step_id="b")).content == "from b"


async def test_re_recording_replaces_the_entries_of_an_earlier_run(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["old 1", "old 2"])
    await _record(out, ["new 1", "new 2"])  # a new recorder on the same file
    mock = MockBackend(out, strict=True)
    assert [(await mock.complete(ASK, model=MODEL)).content for _ in range(2)] == ["new 1", "new 2"]


async def test_key_lookup_leaves_a_steps_entries_to_it(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    rec = RecordingBackend(SequenceBackend(["free", "for s"]), out)
    await rec.complete(ASK, model=MODEL)
    await rec.complete(ASK, model=MODEL, step_id="s")  # same request, under a step_id
    mock = MockBackend(out, strict=True)
    assert (await mock.complete(ASK, model=MODEL)).content == "free"
    with pytest.raises(ReplayMissError):
        await mock.complete(ASK, model=MODEL)  # the step's entry is not taken
    assert (await mock.complete(ASK, model=MODEL, step_id="s")).content == "for s"


async def test_step_id_and_key_lookups_share_replayed_entries(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["once"], step_id="s")
    mock = MockBackend(out, strict=True)
    assert (await mock.complete(ASK, model=MODEL, step_id="s")).content == "once"
    with pytest.raises(ReplayMissError):
        await mock.complete(ASK, model=MODEL)  # same request, already replayed


async def test_stream_is_one_entry_with_every_chunk(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    rec = RecordingBackend(SequenceBackend(["one two three"]), out)
    recorded = [c.content async for c in rec.stream(ASK, model=MODEL)]
    assert recorded == ["one", "two", "three", None]
    entries = json.loads(out.read_text())["entries"]
    assert len(entries) == 1
    assert [c["content"] for c in entries[0]["chunks"]] == recorded
    assert (
        entries[0]["response"]["content"] == "onetwothree"
    )  # the whole answer, not the last chunk
    replayed = [c.content async for c in MockBackend(out).stream(ASK, model=MODEL)]
    assert replayed == recorded
    assert (await MockBackend(out).complete(ASK, model=MODEL)).content == "onetwothree"


async def test_stream_stopped_at_its_last_chunk_is_recorded(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    rec = RecordingBackend(SequenceBackend(["one two"]), out)
    async for chunk in rec.stream(ASK, model=MODEL):
        if chunk.content is None:
            break  # the caller has what it needs and stops pulling
    assert len(json.loads(out.read_text())["entries"]) == 1


async def test_abandoned_stream_is_not_recorded(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    rec = RecordingBackend(SequenceBackend(["one two three"]), out)
    stream = rec.stream(ASK, model=MODEL)
    assert (await stream.__anext__()).content == "one"
    await stream.aclose()
    assert not out.exists()


async def test_non_streamed_entry_streams_as_a_delta_and_a_final_chunk(tmp_path: Path) -> None:
    out = tmp_path / "rec.json"
    await _record(out, ["whole"])
    replayed = [c async for c in MockBackend(out).stream(ASK, model=MODEL)]
    assert [c.content for c in replayed] == ["whole", None]
    assert replayed[-1].usage.output_tokens == 1  # usage rides on the final chunk
