"""MockBackend — replays a `Recording` envelope deterministically.

Lookup order:

1. `step_id` exact match (preferred when the caller passes a stable id).
2. SHA-256 `key` over the normalised request (fallback).

A miss raises `KeyError` — silent fallthroughs would defeat the determinism
guarantee.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import LLMResponse, Message, ToolDef
from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.recording import RECORDING_VERSION, request_key


class MockBackend(LLMBackend):
    """Reads a `Recording` envelope; serves canned responses without network I/O."""

    name = "mock"

    def __init__(self, recording_path: str | Path) -> None:
        self._path = Path(recording_path)
        envelope = json.loads(self._path.read_text())
        if envelope.get("recording_version") != RECORDING_VERSION:
            raise RecordingError(
                f"Recording at {self._path} has version "
                f"{envelope.get('recording_version')!r}; expected {RECORDING_VERSION!r}"
            )
        self._envelope = envelope
        self._by_step_id = {
            entry["step_id"]: entry for entry in envelope["entries"] if entry.get("step_id")
        }
        self._by_key = {entry["key"]: entry for entry in envelope["entries"]}

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
        # Streaming over a recording yields the full canned response as one chunk.
        response = await self.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
        )
        yield response

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
            entry: dict[str, Any] = self._by_step_id[step_id]
            return entry
        key = request_key(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
        )
        hit: dict[str, Any] | None = self._by_key.get(key)
        if hit is None:
            raise KeyError(f"No recording for step_id={step_id!r} key={key} in {self._path}")
        return hit
