"""AgentContract — defines what is expected from an agent before testing it."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

from agentanvil.core.models import OracleType

if TYPE_CHECKING:
    from pathlib import Path


class PolicyCheck(StrEnum):
    RULE = "rule"
    LLM = "llm"
    METRIC = "metric"
    HUMAN = "human"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Policy(BaseModel):
    id: str
    description: str
    severity: Severity = Severity.MEDIUM
    check: PolicyCheck = PolicyCheck.LLM


class Task(BaseModel):
    id: str
    description: str
    inputs: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    oracle: OracleType = OracleType.HYBRID


class Constraints(BaseModel):
    max_latency_ms: int | None = None
    max_cost_per_interaction_usd: float | None = None
    max_tool_calls: int | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)


class AgentContract(BaseModel):
    """Contract that defines the expected behaviour of an agent under test."""

    name: str
    version: str = "1.0"
    policies: list[Policy] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AgentContract:
        """Load a contract from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def to_yaml(self, path: str | Path) -> None:
        """Persist this contract to a YAML file."""
        with open(path, "w") as f:
            # mode="json" converts Enum members to their string values
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False)
