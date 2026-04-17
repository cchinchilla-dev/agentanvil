"""Tests for AgentContract parsing and validation."""

from agentanvil.core.contracts import AgentContract, Constraints, Policy, Severity, Task
from agentanvil.core.models import OracleType, Scenario, ScenarioCategory


def test_contract_minimal() -> None:
    c = AgentContract(name="my-agent")
    assert c.version == "1.0"
    assert c.policies == []
    assert c.tasks == []


def test_contract_with_policies() -> None:
    c = AgentContract(
        name="support-agent",
        policies=[Policy(id="no_pii", description="Never reveal PII", severity=Severity.CRITICAL)],
    )
    assert len(c.policies) == 1
    assert c.policies[0].severity == Severity.CRITICAL


def test_contract_from_yaml(tmp_path) -> None:
    yaml_content = """
name: test-agent
version: "1.2"
policies:
  - id: no_pii_leak
    description: Never reveal customer PII
    severity: critical
    check: llm
tasks:
  - id: answer_billing
    description: Resolve billing questions
    inputs:
      - billing question
    success_criteria:
      - Provides correct billing information
    oracle: hybrid
"""
    path = tmp_path / "contract.yaml"
    path.write_text(yaml_content)

    c = AgentContract.from_yaml(path)
    assert c.name == "test-agent"
    assert c.version == "1.2"
    assert len(c.policies) == 1
    assert c.policies[0].id == "no_pii_leak"
    assert len(c.tasks) == 1
    assert c.tasks[0].oracle == OracleType.HYBRID


def test_contract_roundtrip(tmp_path) -> None:
    original = AgentContract(
        name="roundtrip-agent",
        policies=[Policy(id="p1", description="Test policy")],
        tasks=[Task(id="t1", description="Test task")],
        constraints=Constraints(max_latency_ms=3000),
    )
    path = tmp_path / "contract.yaml"
    original.to_yaml(path)
    loaded = AgentContract.from_yaml(path)

    assert loaded.name == original.name
    assert loaded.policies[0].id == "p1"
    assert loaded.constraints.max_latency_ms == 3000


def test_scenario_defaults() -> None:
    s = Scenario(
        id="s1",
        input="Hello",
        expected_behavior="Greet the user",
        category=ScenarioCategory.HAPPY_PATH,
    )
    assert s.oracle == OracleType.HYBRID
    assert s.policies_tested == []
