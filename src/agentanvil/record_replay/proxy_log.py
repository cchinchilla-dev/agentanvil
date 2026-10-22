"""Configuration and log records of the transport proxy.

A session log is JSON Lines: a `session` header with the configuration, then one
`crossing` per completed call and one `failure` per upstream error or abort, and
a `close` record when the driver closes the session. A crossing keeps the request
as the client sent it (before any rewrite) plus the seed and tool order the proxy
applied, so every rewrite can be reproduced.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.normalize import DEFAULT, Normalizer, request_hash, response_hash

NAME = r"^[A-Za-z0-9_-]{1,64}$"  # session ids and roles become file names and URL segments

Divergence = list[Literal["request", "response", "extra"]]


class RoleConfig(BaseModel):
    """One boundary of a session, such as the agent or the simulated user."""

    model_config = ConfigDict(frozen=True)

    upstream: str  # OpenAI-compatible base URL, e.g. http://127.0.0.1:8000/v1
    seed: int | None = None  # None leaves the client's seed untouched

    @field_validator("upstream")
    @classmethod
    def _check_upstream(cls, value: str) -> str:
        # Rejected when the session opens, not as a dropped connection mid-episode.
        parts = urlsplit(value)
        try:
            parts.port  # noqa: B018 — raises ValueError when out of range
        except ValueError as exc:
            raise ValueError(f"invalid port in upstream {value!r}") from exc
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"upstream must be an http(s) URL, got {value!r}")
        return value


class SessionConfig(BaseModel):
    """What the proxy does to every crossing of one episode."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(pattern=NAME)
    roles: dict[str, RoleConfig]
    permute_seed: int | None = None  # None keeps the client's order
    permute_roles: frozenset[str] = frozenset({"agent"})
    reference: Path | None = None
    replay_until: int = 0  # crossings with a lower reference index are served from the reference
    on_divergence: Literal["log", "abort"] = "log"
    normalizer: Normalizer = DEFAULT

    @model_validator(mode="after")
    def _check(self) -> SessionConfig:
        bad = [r for r in self.roles if re.fullmatch(NAME, r) is None]
        if bad:
            raise ValueError(f"invalid role names: {bad}")
        if self.replay_until and self.reference is None:
            raise ValueError("replay_until needs a reference recording")
        return self

    @field_serializer("permute_roles")
    def _sorted_roles(self, roles: frozenset[str]) -> list[str]:
        return sorted(roles)  # a set dumps in hash-randomised order: keep the header byte-stable


class Crossing(BaseModel):
    """One completed call through a boundary: the k-th of its role, the index-th of the session."""

    kind: Literal["crossing"] = "crossing"
    session_id: str
    role: str
    k: int
    index: int
    source: Literal["live", "replay"]
    seed: int | None
    tools_order: list[int] | None
    request_hash: str
    response_hash: str
    request: dict[str, Any]
    response: dict[str, Any]
    latency_ms: int
    divergence: Divergence = Field(default_factory=list)


class Failure(BaseModel):
    """A call that did not complete a crossing: an upstream error or an abort on divergence."""

    kind: Literal["failure"] = "failure"
    reason: Literal["upstream", "divergence"]
    session_id: str
    role: str
    k: int
    status: int
    request_hash: str
    divergence: Divergence = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)


class Close(BaseModel):
    """End of a session: crossings per role, and those the reference had and the run never made."""

    kind: Literal["close"] = "close"
    session_id: str
    crossings: dict[str, int]
    missing: dict[str, int] = Field(default_factory=dict)


def load_reference(path: Path, normalizer: Normalizer = DEFAULT) -> dict[str, list[Crossing]]:
    """Crossings of a session log grouped by role, in crossing order, hashed under `normalizer`.

    The reference must be complete: a log without its `close` record (a run cut
    short), a truncated line or a gap in k is an error, since replaying it would
    silently shift or invent later crossings. Hashes are recomputed from the
    stored request and response, so a session compares them under its own
    normalizer whatever the reference was recorded with.
    """
    by_role: dict[str, list[Crossing]] = {}
    closed = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RecordingError(f"cannot read reference {path}: {exc}") from exc
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("kind") == "close":
                Close.model_validate(obj)
                closed = True
            elif obj.get("kind") == "crossing":
                crossing = Crossing.model_validate(obj)
                crossing.request_hash = request_hash(crossing.request, normalizer)
                crossing.response_hash = response_hash(crossing.response, normalizer)
                by_role.setdefault(crossing.role, []).append(crossing)
        except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
            raise RecordingError(f"{path}:{n}: malformed log line ({exc})") from exc
    for role, crossings in by_role.items():
        crossings.sort(key=lambda c: c.k)
        if [c.k for c in crossings] != list(range(len(crossings))):
            raise RecordingError(f"{path}: crossings of role {role!r} have gaps")
    if not closed:
        raise RecordingError(f"{path}: no close record, the session never closed")
    return by_role


def create(path: Path, record: BaseModel | dict[str, Any]) -> None:
    """Start a log with its header; fails if it exists, so two sessions never share one."""
    try:
        with path.open("xb") as fh:
            fh.write(_line(record))
    except FileExistsError as exc:
        raise RecordingError(f"session log already exists: {path}") from exc


def append(path: Path, record: BaseModel | dict[str, Any]) -> None:
    """Append one record and flush it, so a crash loses at most the line being written."""
    with path.open("ab") as fh:
        fh.write(_line(record))
        fh.flush()


def _line(record: BaseModel | dict[str, Any]) -> bytes:
    data = record.model_dump(mode="json") if isinstance(record, BaseModel) else record
    # A lone surrogate (surrogate-escaped tool output) is written as its JSON escape.
    return (json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8", "backslashreplace"
    )
