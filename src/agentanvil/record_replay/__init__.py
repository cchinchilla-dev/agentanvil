"""Record/replay envelope for deterministic LLM interaction.

Three surfaces:

- `RecordingBackend` wraps any concrete `LLMBackend` and captures every call
  to disk in the canonical envelope (`recording_version=1`).
- `MockBackend` reads an envelope and serves responses keyed by `step_id` (when
  available) or by SHA-256 of the normalised request.
- The transport proxy (`ProxyServer`, `agentanvil proxy`) records and replays any
  runtime at the HTTP boundary, in front of an OpenAI-compatible server, with
  per-session seeds, tool-order permutation and k-th crossing replay.

The combination is what guarantees that `pytest tests/ci/test_determinism.py`
passes byte-for-byte across machines.
"""

from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.normalize import Normalizer, request_hash, response_hash
from agentanvil.record_replay.proxy import ProxyServer
from agentanvil.record_replay.proxy_log import Crossing, RoleConfig, SessionConfig, load_reference
from agentanvil.record_replay.proxy_session import ProxySession
from agentanvil.record_replay.recording import RecordingBackend, request_key

__all__ = [
    "Crossing",
    "MockBackend",
    "Normalizer",
    "ProxyServer",
    "ProxySession",
    "RecordingBackend",
    "RoleConfig",
    "SessionConfig",
    "load_reference",
    "request_hash",
    "request_key",
    "response_hash",
]
