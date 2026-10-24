"""Faults that the transport proxy injects into a crossing (#36): configuration and log.

A session's `perturb` list names, for one crossing of one role, an operator and its
parameters. Operators are pure functions of the JSON they change, their fault and a
seed derived from the fault's seed, its op and k, so the session log is enough to
know what the proxy did. An operator returns `None` when the crossing has nothing
for it to act on (a miss), and the crossing then goes through unchanged. The
operators are in `perturb_request` and `perturb_response`; `proxy_faults` applies
them to a session.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentanvil.record_replay.normalize import JSON, JSONObject

Op = Literal[
    "tool_result",
    "tool_error",
    "drop_instruction",
    "user_rewrite",
    "tool_call",
    "output_rewrite",
    "inflate",
    "loop",
    "delay",
    "upstream_error",
]

Change = tuple[JSONObject, str, dict[str, JSON]]
"""The changed body, the path of what changed, and the choices the seed made."""


class Params(BaseModel):
    """Parameters of one operator; unknown keys are refused when the session opens."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolResultParams(Params):
    mode: Literal["replace", "empty", "append"] = "replace"
    text: str = ""


class ToolErrorParams(Params):
    error: Literal["timeout", "http_500"] = "timeout"


class DropInstructionParams(Params):
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid pattern {value!r}: {exc}") from exc
        return value


class UserRewriteParams(Params):
    text: str


class ToolCallParams(Params):
    rename_to: str | None = None  # None: another tool of the request, chosen by the seed
    argument: str | None = None  # set: change this argument instead of renaming the call
    value: Any = None

    @model_validator(mode="after")
    def _one_change(self) -> ToolCallParams:
        if self.argument is not None and self.rename_to is not None:
            raise ValueError("tool_call renames a call or changes an argument, not both")
        return self


class OutputRewriteParams(Params):
    text: str | None = None
    field: str | None = None  # dotted path of a field in a JSON answer
    value: Any = None

    @model_validator(mode="after")
    def _one_target(self) -> OutputRewriteParams:
        if (self.text is None) == (self.field is None):
            raise ValueError("output_rewrite takes either text or field")
        return self


class InflateParams(Params):
    factor: int = Field(default=2, ge=2, le=100)


class LoopParams(Params):
    pass


class DelayParams(Params):
    ms: int = Field(default=0, ge=0)
    per_request_ms: int = Field(default=0, ge=0)  # added for each other request in flight

    @model_validator(mode="after")
    def _some_delay(self) -> DelayParams:
        if not (self.ms or self.per_request_ms):
            raise ValueError("delay needs ms or per_request_ms")
        return self


class UpstreamErrorParams(Params):
    status: Literal[429, 500, "timeout"] = 429
    times: int = Field(default=1, ge=1, le=100)


PARAMS: dict[str, type[Params]] = {
    "tool_result": ToolResultParams,
    "tool_error": ToolErrorParams,
    "drop_instruction": DropInstructionParams,
    "user_rewrite": UserRewriteParams,
    "tool_call": ToolCallParams,
    "output_rewrite": OutputRewriteParams,
    "inflate": InflateParams,
    "loop": LoopParams,
    "delay": DelayParams,
    "upstream_error": UpstreamErrorParams,
}


class Fault(BaseModel):
    """One fault: `op` applied to the `at`-th crossing (k) of `role`."""

    model_config = ConfigDict(frozen=True)

    op: Op
    role: str
    at: int = Field(ge=0)
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int = 0  # seeds the operator's own choices, such as which tool result it changes

    @model_validator(mode="after")
    def _check_params(self) -> Fault:
        PARAMS[self.op].model_validate(self.params)
        return self


class Perturbation(BaseModel):
    """A fault the proxy applied to a crossing, as the crossing logs it."""

    op: Op
    params: dict[str, Any]  # as configured, plus the choices the seed made
    site: str  # where it acted: a path into the request or the response
    before_hash: str
    after_hash: str


def pick(n: int, seed: int) -> int:
    """One of `n` sites, chosen by `seed`."""
    return seed % n
