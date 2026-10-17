"""Runner abstraction — executes the agent under test inside a controlled sandbox.

`SubprocessRunner` ships in 0.1.x. `DockerRunner` is planned for 0.2.0 (#7)
and a `K8sRunner` for a later release. All of them implement the same `Runner`
ABC so higher layers swap them transparently.
"""

from agentanvil.runner.base import Runner, RunnerResult
from agentanvil.runner.subprocess import SubprocessRunner

__all__ = ["Runner", "RunnerResult", "SubprocessRunner"]
