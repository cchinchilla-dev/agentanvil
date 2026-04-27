"""Runner ABC — the agent-execution boundary."""

from __future__ import annotations

import abc
from pathlib import Path

from pydantic import BaseModel


class RunnerResult(BaseModel):
    """Outcome of executing one scenario against one agent."""

    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int
    timed_out: bool
    image_digest: str | None = None  # populated by DockerRunner / K8sRunner


class Runner(abc.ABC):
    """Run the agent under test for a single scenario.

    Concrete runners differ in isolation strength (subprocess → docker → k8s)
    but share the same input/output protocol: JSON over stdin/stdout. See
    `docs/runner-protocol.md` for the wire format.
    """

    name: str

    @abc.abstractmethod
    async def run(
        self,
        *,
        agent_path: Path,
        scenario_json: str,
        timeout_ms: int,
        env: dict[str, str] | None = None,
    ) -> RunnerResult:
        """Execute one scenario and return the captured `RunnerResult`."""
