"""Normalisation of OpenAI-compatible chat payloads before hashing.

The transport proxy keys every crossing by a hash of the request the client sent.
Two runs of the same conversation must hash the same even when the client or the
server mints fresh identifiers, so the hash is taken over a normalised copy:

- request fields that never change the completion (or that the proxy rewrites
  itself, such as `seed`) are dropped;
- tool-call ids become ordinals in order of first appearance (`call_0`, ...),
  wherever a message carries them;
- tool-call arguments are parsed and re-serialised with sorted keys;
- response fields minted per call (`id`, `created`, `usage`, the timings and
  metrics some servers add, ...) are dropped.

Ignored fields are paths: `timings` is a top-level key, `choices[].meta_info` a
key of every choice. `Normalizer.ignore_request` and `ignore_response` add paths
for servers the defaults do not cover.

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

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from agentanvil.record_replay.normalize_fields import (
    FIELD_PATH,
    REQUEST_IGNORED,
    RESPONSE_IGNORED,
    drop,
)

JSON: TypeAlias = "str | int | float | bool | None | list[JSON] | dict[str, JSON]"
JSONObject: TypeAlias = dict[str, JSON]

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
    ignore_request: frozenset[str] = frozenset()  # field paths, on top of REQUEST_IGNORED
    ignore_response: frozenset[str] = frozenset()  # field paths, on top of RESPONSE_IGNORED

    @field_validator("ignore_request", "ignore_response")
    @classmethod
    def _check_paths(cls, paths: frozenset[str]) -> frozenset[str]:
        bad = sorted(p for p in paths if FIELD_PATH.fullmatch(p) is None)
        if bad:
            raise ValueError(f"invalid field paths: {bad}")
        return paths

    @field_serializer("ignore_request", "ignore_response")
    def _sorted_paths(self, paths: frozenset[str]) -> list[str]:
        # A set dumps in hash-randomised order: keep the log header byte-stable.
        return sorted(paths)

    def request(self, body: JSONObject) -> JSONObject:
        """Normalised copy of a `/chat/completions` request body."""
        ids: dict[str, str] = {}
        out = drop(body, REQUEST_IGNORED | self.ignore_request)
        if isinstance(messages := out.get("messages"), list):
            out["messages"] = [self._message(m, ids) for m in messages]
        return out

    def response(self, body: JSONObject) -> JSONObject:
        """Normalised copy of a `/chat/completions` response body (ids local to each choice)."""
        out = drop(body, RESPONSE_IGNORED | self.ignore_response)
        if isinstance(choices := out.get("choices"), list):
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
        for key in sorted(out.keys() - {"tool_call_id"}):  # citations, reasoning, extensions
            out[key] = self._nested_ids(out[key], ids)
        return out

    def _nested_ids(self, node: JSON, ids: dict[str, str]) -> JSON:
        if isinstance(node, list):
            return [self._nested_ids(x, ids) for x in node]
        if not isinstance(node, dict):
            return node
        out: JSONObject = {}
        for k in sorted(node):  # sorted: ordinals must not depend on the server's key order
            v = node[k]
            out[k] = (
                self._id(v, ids)
                if k == "tool_call_id" and isinstance(v, str)
                else self._nested_ids(v, ids)
            )
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
