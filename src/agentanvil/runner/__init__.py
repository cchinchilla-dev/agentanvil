"""Runner abstraction — executes the agent under test inside a controlled sandbox.

`SubprocessRunner` ships in 0.1.x. `DockerRunner` is added in 0.2.0 #014.
`K8sRunner` arrives in 0.4.0 #070. All three implement the same `Runner` ABC so
higher layers swap them transparently.
"""

from agentanvil.runner.base import Runner, RunnerResult
from agentanvil.runner.subprocess import SubprocessRunner

__all__ = ["Runner", "RunnerResult", "SubprocessRunner"]
