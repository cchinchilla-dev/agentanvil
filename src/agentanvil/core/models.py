"""Core Pydantic models shared across AgentAnvil modules."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ScenarioCategory(StrEnum):
    HAPPY_PATH = "happy_path"
    EDGE_CASE = "edge_case"
    ADVERSARIAL = "adversarial"
    POLICY_VIOLATION = "policy_violation"
    REGRESSION = "regression"


class OracleType(StrEnum):
    RULE = "rule"
    LLM = "llm"
    HUMAN = "human"
    HYBRID = "hybrid"


class Scenario(BaseModel):
    """A single test scenario to run against an agent."""

    id: str
    input: str
    expected_behavior: str
    category: ScenarioCategory
    policies_tested: list[str] = Field(default_factory=list)
    oracle: OracleType = OracleType.HYBRID


class ScoreBreakdown(BaseModel):
    """Per-category score breakdown inside an EvalResult."""

    objective: float | None = None
    llm_judge: float | None = None
    human: float | None = None
    composite: float


class EvalResult(BaseModel):
    """Evaluation result for a single run of an agent."""

    agent_id: str
    version: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    threshold: float
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    breakdown: dict[str, ScoreBreakdown] = Field(default_factory=dict)
    cost_usd: float = 0.0
    duration_ms: float = 0.0


class PromptSuggestion(BaseModel):
    """A prompt improvement suggested by the Debugger."""

    file: str
    line: int | None
    original: str
    suggested: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)  # trace IDs
