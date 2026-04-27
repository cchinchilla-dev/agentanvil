"""SubprocessRunner tests using a tiny echo fixture agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agentanvil.runner.subprocess import SubprocessRunner

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "runner_agents"
ECHO_AGENT = FIXTURE_DIR / "echo.py"
SLEEP_AGENT = FIXTURE_DIR / "sleep.py"
ERROR_AGENT = FIXTURE_DIR / "error.py"


@pytest.fixture
def runner() -> SubprocessRunner:
    return SubprocessRunner(interpreter=[sys.executable, "-u"])


async def test_subprocess_runner_echo_agent_returns_stdout(runner: SubprocessRunner) -> None:
    scenario = json.dumps({"scenario_id": "s1", "inputs": {"q": "hi"}})
    result = await runner.run(agent_path=ECHO_AGENT, scenario_json=scenario, timeout_ms=5000)
    assert result.exit_code == 0
    assert not result.timed_out
    payload = json.loads(result.stdout)
    assert payload["received"]["scenario_id"] == "s1"


async def test_subprocess_runner_honours_timeout(runner: SubprocessRunner) -> None:
    result = await runner.run(agent_path=SLEEP_AGENT, scenario_json="{}", timeout_ms=200)
    assert result.timed_out is True
    assert result.exit_code == -1


async def test_subprocess_runner_captures_stderr(runner: SubprocessRunner) -> None:
    result = await runner.run(agent_path=ERROR_AGENT, scenario_json="{}", timeout_ms=5000)
    assert "boom" in result.stderr
    assert result.exit_code != 0


async def test_subprocess_runner_exit_code_propagated(runner: SubprocessRunner) -> None:
    result = await runner.run(agent_path=ERROR_AGENT, scenario_json="{}", timeout_ms=5000)
    assert result.exit_code == 1


async def test_subprocess_runner_env_propagated(runner: SubprocessRunner) -> None:
    scenario = json.dumps({"scenario_id": "envcheck"})
    result = await runner.run(
        agent_path=ECHO_AGENT,
        scenario_json=scenario,
        timeout_ms=5000,
        env={"PATH": "/usr/bin:/bin", "AGENTANVIL_PROBE": "yes"},
    )
    payload = json.loads(result.stdout)
    assert payload["env_probe"] == "yes"


def test_runner_result_round_trip() -> None:
    from agentanvil.runner.base import RunnerResult

    result = RunnerResult(
        stdout="ok",
        stderr="",
        exit_code=0,
        elapsed_ms=42,
        timed_out=False,
    )
    assert RunnerResult.model_validate(result.model_dump()) == result
