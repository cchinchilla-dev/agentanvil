"""Exception hierarchy for AgentAnvil.

Mirrors the shape of `agentloom.exceptions` so consumers can write a single
``except AgentAnvilError`` clause to catch any framework error. Concrete
subclasses are domain-scoped: backends, runner, record/replay, contract.
"""

from __future__ import annotations


class AgentAnvilError(Exception):
    """Base class for every AgentAnvil exception."""


class BackendError(AgentAnvilError):
    """Raised when an `LLMBackend` cannot fulfil a request.

    Used for misconfiguration (unknown provider, missing credentials) and
    transport-level failures the backend cannot recover from.
    """


class RunnerError(AgentAnvilError):
    """Raised when a `Runner` cannot execute a scenario."""


class RecordingError(AgentAnvilError):
    """Raised when the record/replay envelope is malformed or unreadable.

    Examples: schema-version mismatch, corrupt JSON, missing keys.
    """


class ReplayDivergenceError(RecordingError):
    """Raised when a crossing differs from its reference and the session aborts on divergence."""


class ContractValidationError(AgentAnvilError):
    """Raised when an `AgentContract` fails validation."""
