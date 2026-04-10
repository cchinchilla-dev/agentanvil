"""Round-trip tests for `RunRecord` and `Report`."""

from __future__ import annotations

import json
from decimal import Decimal

from agentanvil.core.contracts import AgentContract, Constraints, Policy, Severity, Task
from agentanvil.core.models import OracleType, Scenario, ScenarioCategory, ScoreBreakdown
from agentanvil.core.report import Report, ReportFormat
from agentanvil.core.run_record import RunMetadata, RunRecord
from agentanvil.core.traces import LLMCallStep, Step, Trace


def _sample_contract() -> AgentContract:
    return AgentContract(
        name="test-agent",
        policies=[Policy(id="p1", description="never reveal pii", severity=Severity.HIGH)],
        tasks=[Task(id="t1", description="answer questions", oracle=OracleType.HYBRID)],
        constraints=Constraints(max_latency_ms=2000),
    )


def _sample_scenario() -> Scenario:
    return Scenario(
        id="s1",
        input="hi",
        expected_behavior="greet",
        category=ScenarioCategory.HAPPY_PATH,
    )


def _sample_score() -> ScoreBreakdown:
    return ScoreBreakdown(objective=0.9, llm_judge=0.8, composite=0.85)


def _sample_trace() -> Trace:
    return Trace(
        run_id="run_1",
        steps=[
            Step(
                step_id="step_0",
                type="llm_call",
                timestamp_ns=1,
                llm_call=LLMCallStep(
                    provider="openai",
                    model="gpt-4o-2024-11-20",
                    prompt_hash="abc",
                    prompt_tokens=10,
                    output_tokens=4,
                    cost_usd=Decimal("0.0001"),
                    finish_reason="stop",
                ),
            )
        ],
    )


def _sample_metadata() -> RunMetadata:
    return RunMetadata(
        timestamp_iso="2026-04-10T17:43:00Z",
        agentanvil_version="0.1.1",
        backend="direct",
        runner="subprocess",
        python_version="3.11.10",
        platform="linux-x86_64",
        seed=42,
    )


def test_run_record_round_trip_preserves_all_fields() -> None:
    record = RunRecord(
        run_id="run_1",
        contract_hash="sha256:deadbeef",
        contract=_sample_contract(),
        scenario=_sample_scenario(),
        trace=_sample_trace(),
        score=_sample_score(),
        metadata=_sample_metadata(),
    )
    dumped = record.model_dump(mode="json")
    assert RunRecord.model_validate(dumped) == record


def test_run_record_json_round_trip_is_byte_stable() -> None:
    record = RunRecord(
        run_id="run_1",
        contract_hash="sha256:deadbeef",
        contract=_sample_contract(),
        scenario=_sample_scenario(),
        trace=_sample_trace(),
        score=_sample_score(),
        metadata=_sample_metadata(),
    )
    once = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    twice = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    assert once == twice


def test_report_format_enum_exhaustive() -> None:
    assert {f.value for f in ReportFormat} == {"json", "html", "markdown", "sarif"}


def test_report_round_trip() -> None:
    record = RunRecord(
        run_id="run_1",
        contract_hash="sha256:deadbeef",
        contract=_sample_contract(),
        scenario=_sample_scenario(),
        trace=_sample_trace(),
        score=_sample_score(),
        metadata=_sample_metadata(),
    )
    report = Report(run_record=record, rendered={ReportFormat.JSON: "{}"})
    assert Report.model_validate(report.model_dump(mode="json")) == report
