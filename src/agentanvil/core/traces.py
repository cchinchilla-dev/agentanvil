"""Trace and Step models — typed record of what happened during an agent run.

A `Trace` is an ordered list of `Step` records. Each step is one atomic agent
action: an LLM call, a tool call, an inter-agent message (multi-agent traces),
or an internal state transition.

Hashes (`prompt_hash`, `args_hash`, `result_hash`, `payload_hash`) are SHA-256
hex prefixes (16 chars) for compact correlation. Full content is captured only
when an individual step opts in via `metadata.capture_full=True`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

StepType = Literal[
    "llm_call",
    "tool_call",
    "inter_agent_message",
    "state_transition",
    "error",
]


class LLMCallStep(BaseModel):
    provider: str
    model: str
    prompt_hash: str  # SHA-256 first 16 hex chars of rendered prompt
    prompt_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    cost_usd: Decimal
    finish_reason: str


class ToolCallStep(BaseModel):
    tool_name: str
    args_hash: str
    success: bool
    result_hash: str | None = None


class InterAgentStep(BaseModel):
    sender_id: str
    recipient_id: str
    message_type: Literal["task_sent", "task_received", "response_sent", "response_received"]
    payload_hash: str


class StateStep(BaseModel):
    key: str
    old_value_hash: str | None = None
    new_value_hash: str


class ErrorStep(BaseModel):
    kind: str
    message: str
    traceback: str | None = None


class Step(BaseModel):
    """One atomic event during an agent run.

    The matching payload field (`llm_call`, `tool_call`, …) is populated based
    on `type`. The other payload fields stay `None`.
    """

    step_id: str
    type: StepType
    timestamp_ns: int
    agent_id: str | None = None  # populated for multi-agent traces
    parent_step_id: str | None = None
    duration_ms: int | None = None

    llm_call: LLMCallStep | None = None
    tool_call: ToolCallStep | None = None
    inter_agent_message: InterAgentStep | None = None
    state_transition: StateStep | None = None
    error: ErrorStep | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Step:
        """Reject `Step(type="llm_call", llm_call=None)` and similar mismatches."""
        payloads = {
            "llm_call": self.llm_call,
            "tool_call": self.tool_call,
            "inter_agent_message": self.inter_agent_message,
            "state_transition": self.state_transition,
            "error": self.error,
        }
        if payloads[self.type] is None:
            raise ValueError(
                f"Step.type={self.type!r} requires the matching {self.type!r} payload field"
            )
        return self


class Trace(BaseModel):
    """Ordered sequence of `Step` records produced by one agent run."""

    run_id: str
    steps: list[Step] = Field(default_factory=list)

    @property
    def total_duration_ms(self) -> int:
        return sum(s.duration_ms or 0 for s in self.steps)

    @property
    def total_cost_usd(self) -> Decimal:
        return sum(
            (s.llm_call.cost_usd for s in self.steps if s.llm_call is not None),
            start=Decimal(0),
        )

    @property
    def llm_call_count(self) -> int:
        return sum(1 for s in self.steps if s.type == "llm_call")

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.steps if s.type == "tool_call")
