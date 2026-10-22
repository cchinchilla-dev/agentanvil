"""MockBackend — replays a `Recording` envelope deterministically.

Lookup order:

1. `step_id` exact match (preferred when the caller passes a stable id).
2. SHA-256 `key` over the normalised request (fallback).

Repeated calls are paired with recorded entries in order: when a run repeats a
`step_id` or sends the same request again (a loop, a retry), the k-th call gets
the k-th matching entry, and an entry replayed once is not served again. Once
the matching entries run out, the last one is served again (`strict=False`, the
default) or the call fails (`strict=True`); a `step_id` that has entries never
falls back to a key lookup. A key lookup serves entries recorded without a
`step_id` first, so it does not consume one a later step-id call needs.

A miss raises `ReplayMissError` (a `RecordingError` and a `KeyError`) — silent
fallthroughs would defeat the determinism guarantee.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import LLMResponse, Message, ToolDef, Usage
from agentanvil.exceptions import RecordingError, ReplayMissError
from agentanvil.record_replay.recording import RECORDING_VERSION, request_key


class MockBackend(LLMBackend):
    """Reads a `Recording` envelope; serves canned responses without network I/O."""

    name = "mock"

    def __init__(self, recording_path: str | Path, *, strict: bool = False) -> None:
        self._path = Path(recording_path)
        self._strict = strict
        envelope = json.loads(self._path.read_text())
        if envelope.get("recording_version") != RECORDING_VERSION:
            raise RecordingError(
                f"Recording at {self._path} has version "
                f"{envelope.get('recording_version')!r}; expected {RECORDING_VERSION!r}"
            )
        self._envelope = envelope
        self._entries: list[dict[str, Any]] = envelope["entries"]
        self._by_step_id: dict[str, list[int]] = {}
        self._by_key: dict[str, list[int]] = {}
        for i, entry in enumerate(self._entries):
            if entry.get("step_id"):
                self._by_step_id.setdefault(entry["step_id"], []).append(i)
            self._by_key.setdefault(entry["key"], []).append(i)
        self._replayed: set[int] = set()

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
        entry = self._lookup(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
            step_id=step_id,
        )
        return LLMResponse.model_validate(entry["response"])

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
        entry = self._lookup(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
            step_id=None,
        )
        if chunks := entry.get("chunks"):
            for chunk in chunks:
                yield LLMResponse.model_validate(chunk)
            return
        # A non-streamed entry follows the stream contract: its text as one
        # delta, then a final chunk with `content=None` carrying the rest.
        response = LLMResponse.model_validate(entry["response"])
        if response.content:
            yield response.model_copy(
                update={
                    "tool_calls": [],
                    "usage": Usage(input_tokens=0, output_tokens=0),
                    "cost_usd": Decimal(0),
                    "finish_reason": "stop",
                }
            )
        yield response.model_copy(update={"content": None})

    def cost_estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> Decimal:
        # Replays do not incur cost — return 0.
        return Decimal(0)

    # ----- internals -----

    def _lookup(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
        seed: int | None,
        step_id: str | None,
    ) -> dict[str, Any]:
        if step_id is not None and step_id in self._by_step_id:
            entry = self._take(self._by_step_id[step_id])
            if entry is None:
                raise ReplayMissError(f"No recording left for step_id={step_id!r} in {self._path}")
            return entry
        key = request_key(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
        )
        stepless_first = sorted(
            self._by_key.get(key, []), key=lambda i: bool(self._entries[i].get("step_id"))
        )
        hit = self._take(stepless_first)
        if hit is None:
            raise ReplayMissError(
                f"No recording left for step_id={step_id!r} key={key} in {self._path}"
            )
        return hit

    def _take(self, candidates: list[int]) -> dict[str, Any] | None:
        """First matching entry not replayed yet; once exhausted, the last one unless strict."""
        for i in candidates:
            if i not in self._replayed:
                self._replayed.add(i)
                return self._entries[i]
        if self._strict or not candidates:
            return None
        return self._entries[candidates[-1]]
