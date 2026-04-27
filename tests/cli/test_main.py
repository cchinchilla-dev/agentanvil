"""Tests for the AgentAnvil Typer CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentanvil import __version__
from agentanvil.cli.main import app

runner = CliRunner()


def test_cli_version_reports_installed_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "agentanvil" in result.stdout
    assert __version__ in result.stdout


def test_cli_validate_accepts_valid_contract(tmp_path: Path) -> None:
    yaml_path = tmp_path / "contract.yaml"
    yaml_path.write_text(
        """
name: test-agent
version: "1.0"
policies:
  - id: no_pii
    description: Never reveal PII
    severity: critical
    check: llm
tasks:
  - id: greet
    description: Greet user
    oracle: hybrid
constraints:
  max_latency_ms: 3000
"""
    )
    result = runner.invoke(app, ["validate", str(yaml_path)])
    assert result.exit_code == 0
    assert "test-agent" in result.stdout
    assert "valid" in result.stdout.lower()
    assert "1 policies" in result.stdout
    assert "1 tasks" in result.stdout


def test_cli_validate_rejects_unparseable_file(tmp_path: Path) -> None:
    yaml_path = tmp_path / "broken.yaml"
    yaml_path.write_text(": : not valid yaml [unclosed")
    result = runner.invoke(app, ["validate", str(yaml_path)])
    assert result.exit_code == 1
    assert "Invalid" in result.stdout or "✗" in result.stdout


def test_cli_validate_rejects_missing_required_field(tmp_path: Path) -> None:
    yaml_path = tmp_path / "no_name.yaml"
    yaml_path.write_text('version: "1.0"\n')
    result = runner.invoke(app, ["validate", str(yaml_path)])
    assert result.exit_code == 1


def test_cli_run_prints_placeholder(tmp_path: Path) -> None:
    yaml_path = tmp_path / "contract.yaml"
    yaml_path.write_text('name: stub-agent\nversion: "1.0"\n')
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    result = runner.invoke(
        app,
        ["run", str(agent_dir), "--contract", str(yaml_path)],
    )
    assert result.exit_code == 0
    assert "evaluating" in result.stdout
    assert "not yet implemented" in result.stdout


def test_cli_run_threshold_and_budget_flags_render(tmp_path: Path) -> None:
    yaml_path = tmp_path / "contract.yaml"
    yaml_path.write_text('name: stub-agent\nversion: "1.0"\n')
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    result = runner.invoke(
        app,
        [
            "run",
            str(agent_dir),
            "--contract",
            str(yaml_path),
            "--threshold",
            "0.9",
            "--budget",
            "5.5",
        ],
    )
    assert result.exit_code == 0
    assert "0.9" in result.stdout
    assert "5.50" in result.stdout


def test_cli_help_lists_three_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.stdout
    assert "validate" in result.stdout
    assert "run" in result.stdout


def test_cli_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # Typer with `no_args_is_help=True` prints the help and exits with code 2
    # (Click convention for "missing required argument").
    assert result.exit_code == 2
    assert "Commands" in result.stdout or "Usage" in result.stdout
