"""RunRecord — the canonical envelope of one agent evaluation.

Combines contract + scenario + trace + score + provenance metadata. The
reporter renders it; the replayer re-creates it. All downstream artefacts
derive from this single shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentanvil.core.contracts import AgentContract
from agentanvil.core.models import Scenario, ScoreBreakdown
from agentanvil.core.traces import Trace


class RunMetadata(BaseModel):
    """Provenance — captured for reproducibility audits."""

    timestamp_iso: str
    agentanvil_version: str
    backend: str  # "direct" | "agentloom" | "mock"
    runner: str  # "subprocess" | "docker" | "k8s"
    container_digest: str | None = None
    agentloom_version: str | None = None
    python_version: str
    platform: str
    seed: int | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class RunRecord(BaseModel):
    """Single canonical record of one evaluation."""

    run_id: str
    contract_hash: str  # SHA-256 of the serialised contract
    contract: AgentContract
    scenario: Scenario
    trace: Trace
    score: ScoreBreakdown
    metadata: RunMetadata
