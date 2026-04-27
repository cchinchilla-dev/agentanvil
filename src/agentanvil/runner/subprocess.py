"""SubprocessRunner — local subprocess execution with timeout enforcement."""

from __future__ import annotations

import time
from pathlib import Path

import anyio

from agentanvil.runner.base import Runner, RunnerResult


class SubprocessRunner(Runner):
    """Spawn the agent under test as a local subprocess.

    Wire protocol: scenario JSON on stdin, response JSON on stdout, diagnostics
    on stderr. Exit code 0 = success. Timeout marks the result `timed_out=True`
    with `exit_code=-1`.
    """

    name = "subprocess"

    def __init__(self, interpreter: list[str] | None = None) -> None:
        # Common patterns: ["python", "-u"] (default), ["python", "-u", "-m", "my_pkg"], etc.
        self.interpreter = interpreter or ["python", "-u"]

    async def run(
        self,
        *,
        agent_path: Path,
        scenario_json: str,
        timeout_ms: int,
        env: dict[str, str] | None = None,
    ) -> RunnerResult:
        cmd = [*self.interpreter, str(agent_path)]
        start = time.monotonic_ns()
        try:
            with anyio.fail_after(timeout_ms / 1000):
                proc = await anyio.run_process(
                    cmd,
                    input=scenario_json.encode(),
                    env=env,
                    check=False,
                )
        except TimeoutError:
            elapsed_ms = (time.monotonic_ns() - start) // 1_000_000
            return RunnerResult(
                stdout="",
                stderr="timeout",
                exit_code=-1,
                elapsed_ms=elapsed_ms,
                timed_out=True,
            )
        elapsed_ms = (time.monotonic_ns() - start) // 1_000_000
        return RunnerResult(
            stdout=proc.stdout.decode("utf-8", errors="replace"),
            stderr=proc.stderr.decode("utf-8", errors="replace"),
            exit_code=proc.returncode,
            elapsed_ms=elapsed_ms,
            timed_out=False,
        )
