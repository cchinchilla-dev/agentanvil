"""RecordingBackend — captures every LLM call to a canonical JSON envelope.

Wraps any `LLMBackend`. On every `complete` / `stream` call:

1. Forwards to the wrapped backend.
2. Builds a stable `key = sha256(normalised request)`.
3. Appends `{key, step_id, request, response}` to the envelope. The first
   time a recorder records a `step_id` (or, without one, a key), it drops the
   entries earlier runs left for it, so a re-recorded call never replays stale
   entries; repeats within one recorder accumulate in order.
4. Flushes to disk immediately so a crash mid-run does not lose entries.

A streamed call becomes one entry once the stream ends: `chunks` keeps every
chunk in order and `response` is the whole answer (the joined text with the
last chunk's tool calls, usage and finish reason). The last chunk reaches the
caller only after the entry is recorded, so a caller that stops at it still
leaves a recording; every chunk therefore arrives one chunk late. A stream
abandoned before its end is not recorded.

Concurrent callers serialise via `anyio.Lock` (mirrors AgentLoom's #107 fix).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import anyio

from agentanvil.backends.base import LLMBackend
from agentanvil.backends.types import LLMResponse, Message, ToolDef
from agentanvil.exceptions import RecordingError

RECORDING_VERSION = "1"


def request_key(
    messages: list[Message],
    *,
    model: str,
    temperature: float,
    max_tokens: int | None,
    tools: list[ToolDef] | None,
    seed: int | None,
) -> str:
    """Stable hash key for a normalised request.

    Includes every field that could change the response. Excludes `timeout_s`
    (does not affect content) and any caller-side metadata.
    """
    payload = json.dumps(
        {
            "messages": [m.model_dump(mode="json") for m in messages],
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": [t.model_dump(mode="json") for t in (tools or [])],
            "seed": seed,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _ident(entry: dict[str, Any]) -> tuple[str, str]:
    return ("step_id", entry["step_id"]) if entry.get("step_id") else ("key", entry["key"])


class RecordingBackend(LLMBackend):
    """Wrapper that records every call to a JSON envelope."""

    def __init__(
        self,
        wrapped: LLMBackend,
        output_path: str | Path,
        *,
        contract_hash: str = "sha256:",
        run_id: str = "",
        seed: int | None = None,
        agentanvil_version: str | None = None,
    ) -> None:
        if agentanvil_version is None:
            from agentanvil import __version__ as _av_version

            agentanvil_version = _av_version
        self.name = f"recording[{wrapped.name}]"
        self._wrapped = wrapped
        self._path = Path(output_path)
        self._lock = anyio.Lock()
        self._recorded_ids: set[tuple[str, str]] = set()
        self._envelope: dict[str, Any] = {
            "recording_version": RECORDING_VERSION,
            "agentanvil_version": agentanvil_version,
            "contract_hash": contract_hash,
            "run_id": run_id,
            "seed": seed,
            "entries": [],
        }
        self._load_existing()

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
        response = await self._wrapped.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
            timeout_s=timeout_s,
        )
        await self._record(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
            response=response,
            step_id=step_id,
        )
        return response

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
        chunks: list[LLMResponse] = []
        async for chunk in self._wrapped.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
        ):
            if chunks:
                yield chunks[-1]
            chunks.append(chunk)
        if chunks:
            text = "".join(c.content for c in chunks if c.content)
            await self._record(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                seed=seed,
                response=chunks[-1].model_copy(update={"content": text or None}),
                step_id=None,
                chunks=chunks,
            )
            yield chunks[-1]

    def cost_estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> Decimal:
        return self._wrapped.cost_estimate(model, input_tokens, output_tokens, reasoning_tokens)

    # ----- internals -----

    async def _record(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[ToolDef] | None,
        seed: int | None,
        response: LLMResponse,
        step_id: str | None,
        chunks: list[LLMResponse] | None = None,
    ) -> None:
        key = request_key(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            seed=seed,
        )
        entry: dict[str, Any] = {
            "key": key,
            "step_id": step_id,
            "request": {
                "messages": [m.model_dump(mode="json") for m in messages],
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": [t.model_dump(mode="json") for t in (tools or [])],
                "seed": seed,
            },
            "response": response.model_dump(mode="json"),
        }
        if chunks is not None:
            entry["chunks"] = [c.model_dump(mode="json") for c in chunks]
        async with self._lock:
            entries = self._envelope["entries"]
            ident = ("step_id", step_id) if step_id else ("key", key)
            if ident not in self._recorded_ids:
                self._recorded_ids.add(ident)
                entries[:] = [e for e in entries if _ident(e) != ident]
            entries.append(entry)
            self._flush()

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp sibling and rename to make the swap atomic.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._envelope, sort_keys=True, indent=2))
        tmp.replace(self._path)

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        existing = json.loads(self._path.read_text())
        if existing.get("recording_version") != RECORDING_VERSION:
            raise RecordingError(
                f"Recording at {self._path} has version "
                f"{existing.get('recording_version')!r}; expected {RECORDING_VERSION!r}"
            )
        self._envelope = existing
