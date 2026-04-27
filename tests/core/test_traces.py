"""Round-trip and aggregation tests for `Step` and `Trace`."""

from __future__ import annotations

from decimal import Decimal

from agentanvil.core.traces import (
    ErrorStep,
    InterAgentStep,
    LLMCallStep,
    StateStep,
    Step,
    ToolCallStep,
    Trace,
)


def _llm_step(step_id: str, *, cost: str, duration_ms: int = 100) -> Step:
    return Step(
        step_id=step_id,
        type="llm_call",
        timestamp_ns=1,
        duration_ms=duration_ms,
        llm_call=LLMCallStep(
            provider="openai",
            model="gpt-4o-2024-11-20",
            prompt_hash="abc",
            prompt_tokens=10,
            output_tokens=5,
            cost_usd=Decimal(cost),
            finish_reason="stop",
        ),
    )


def test_step_round_trip_llm_call() -> None:
    s = _llm_step("s1", cost="0.001")
    assert Step.model_validate(s.model_dump()) == s


def test_step_round_trip_tool_call() -> None:
    s = Step(
        step_id="s2",
        type="tool_call",
        timestamp_ns=2,
        tool_call=ToolCallStep(
            tool_name="search", args_hash="abc", success=True, result_hash="def"
        ),
    )
    assert Step.model_validate(s.model_dump()) == s


def test_step_round_trip_inter_agent() -> None:
    s = Step(
        step_id="s3",
        type="inter_agent_message",
        timestamp_ns=3,
        agent_id="agent-1",
        inter_agent_message=InterAgentStep(
            sender_id="agent-1",
            recipient_id="agent-2",
            message_type="task_sent",
            payload_hash="abc",
        ),
    )
    assert Step.model_validate(s.model_dump()) == s


def test_step_round_trip_state_and_error() -> None:
    state = Step(
        step_id="s4",
        type="state_transition",
        timestamp_ns=4,
        state_transition=StateStep(key="user.name", new_value_hash="abc"),
    )
    err = Step(
        step_id="s5",
        type="error",
        timestamp_ns=5,
        error=ErrorStep(kind="ValueError", message="boom"),
    )
    assert Step.model_validate(state.model_dump()) == state
    assert Step.model_validate(err.model_dump()) == err


def test_trace_total_duration_sums_step_durations() -> None:
    trace = Trace(
        run_id="r1",
        steps=[
            _llm_step("s1", cost="0.001", duration_ms=100),
            _llm_step("s2", cost="0.002", duration_ms=200),
        ],
    )
    assert trace.total_duration_ms == 300


def test_trace_total_cost_sums_llm_call_costs() -> None:
    trace = Trace(
        run_id="r1",
        steps=[_llm_step("s1", cost="0.001"), _llm_step("s2", cost="0.0025")],
    )
    assert trace.total_cost_usd == Decimal("0.0035")


def test_trace_counts() -> None:
    trace = Trace(
        run_id="r1",
        steps=[
            _llm_step("s1", cost="0.001"),
            Step(
                step_id="s2",
                type="tool_call",
                timestamp_ns=2,
                tool_call=ToolCallStep(tool_name="t", args_hash="a", success=True),
            ),
            _llm_step("s3", cost="0.002"),
        ],
    )
    assert trace.llm_call_count == 2
    assert trace.tool_call_count == 1


def test_trace_empty_aggregations() -> None:
    trace = Trace(run_id="r1", steps=[])
    assert trace.total_duration_ms == 0
    assert trace.total_cost_usd == Decimal(0)
