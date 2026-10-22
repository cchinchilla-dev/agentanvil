"""Normalisation of OpenAI-compatible chat payloads before hashing.

The transport proxy keys every crossing by a hash of the request the client sent.
Two runs of the same conversation must hash the same even when the client or the
server mints fresh identifiers, so the hash is taken over a normalised copy:

- request fields that never change the completion (or that the proxy rewrites
  itself, such as `seed`) are dropped;
- tool-call ids become ordinals in order of first appearance (`call_0`, ...);
- tool-call arguments are parsed and re-serialised with sorted keys;
- per-call response fields (`id`, `created`, `usage`, ...) are dropped.

Timestamps, UUIDs and whitespace inside message text are left alone by default:
in many benchmarks dates and identifiers are task data, not noise. Each one can
be switched on in `Normalizer`.

The hash covers the payload as the client sent it, before any proxy rewrite, so
a permutation the proxy applies (for instance to `tools`) never hides a change
made by the client. Malformed payloads are hashed as they come.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict

JSON: TypeAlias = "str | int | float | bool | None | list[JSON] | dict[str, JSON]"
JSONObject: TypeAlias = dict[str, JSON]

REQUEST_IGNORED = frozenset(
    {"seed", "stream", "stream_options", "num_retries", "timeout", "user", "metadata"}
)
RESPONSE_IGNORED = frozenset({"id", "created", "system_fingerprint", "usage", "service_tier"})

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SPACES = re.compile(r"\s+")


def canonical_json(obj: JSON) -> str:
    """Byte-stable JSON: sorted keys, no insignificant whitespace, UTF-8 kept as is."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj: JSON) -> str:
    # A lone surrogate (surrogate-escaped tool output) hashes as its escape instead of failing.
    data = canonical_json(obj).encode("utf-8", "backslashreplace")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Normalizer(BaseModel):
    """Which sources of incidental variation to erase before hashing."""

    model_config = ConfigDict(frozen=True)

    tool_call_ids: bool = True
    timestamps: bool = False
    uuids: bool = False
    whitespace: bool = False

    def request(self, body: JSONObject) -> JSONObject:
        """Normalised copy of a `/chat/completions` request body."""
        ids: dict[str, str] = {}
        out = {k: v for k, v in body.items() if k not in REQUEST_IGNORED}
        if isinstance(messages := body.get("messages"), list):
            out["messages"] = [self._message(m, ids) for m in messages]
        return out

    def response(self, body: JSONObject) -> JSONObject:
        """Normalised copy of a `/chat/completions` response body (ids local to each choice)."""
        out = {k: v for k, v in body.items() if k not in RESPONSE_IGNORED}
        if isinstance(choices := body.get("choices"), list):
            out["choices"] = [self._choice(c) for c in choices]
        return out

    # ----- internals -----

    def _choice(self, choice: JSON) -> JSON:
        if isinstance(choice, dict) and "message" in choice:
            return {**choice, "message": self._message(choice["message"], {})}
        return choice

    def _message(self, msg: JSON, ids: dict[str, str]) -> JSON:
        if not isinstance(msg, dict):
            return msg
        out = dict(msg)
        content = msg.get("content")
        if isinstance(content, str):
            out["content"] = self._text(content)
        elif isinstance(content, list):
            out["content"] = [self._part(p) for p in content]
        if isinstance(calls := msg.get("tool_calls"), list):
            out["tool_calls"] = [self._tool_call(tc, ids) for tc in calls]
        if isinstance(call_id := msg.get("tool_call_id"), str):
            out["tool_call_id"] = self._id(call_id, ids)
        return out

    def _part(self, part: JSON) -> JSON:
        if isinstance(part, dict) and isinstance(text := part.get("text"), str):
            return {**part, "text": self._text(text)}
        return part

    def _tool_call(self, call: JSON, ids: dict[str, str]) -> JSON:
        if not isinstance(call, dict):
            return call
        out = dict(call)
        if isinstance(call_id := call.get("id"), str):
            out["id"] = self._id(call_id, ids)
        fn = call.get("function")
        if isinstance(fn, dict) and isinstance(args := fn.get("arguments"), str):
            # Malformed arguments are part of what the model said: keep them verbatim.
            with contextlib.suppress(json.JSONDecodeError):
                args = canonical_json(json.loads(args))
            out["function"] = {**fn, "arguments": args}
        return out

    def _id(self, value: str, ids: dict[str, str]) -> str:
        if not self.tool_call_ids:
            return value
        return ids.setdefault(value, f"call_{len(ids)}")

    def _text(self, text: str) -> str:
        if self.timestamps:
            text = _TIMESTAMP.sub("<timestamp>", text)
        if self.uuids:
            text = _UUID.sub("<uuid>", text)
        if self.whitespace:
            text = _SPACES.sub(" ", text).strip()
        return text


DEFAULT = Normalizer()


def request_hash(body: JSONObject, normalizer: Normalizer = DEFAULT) -> str:
    return digest(normalizer.request(body))


def response_hash(body: JSONObject, normalizer: Normalizer = DEFAULT) -> str:
    return digest(normalizer.response(body))
