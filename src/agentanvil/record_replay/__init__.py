"""Record/replay envelope for deterministic LLM interaction.

Two surfaces:

- `RecordingBackend` wraps any concrete `LLMBackend` and captures every call
  to disk in the canonical envelope (`recording_version=1`).
- `MockBackend` reads an envelope and serves responses keyed by `step_id` (when
  available) or by SHA-256 of the normalised request.

The combination is what guarantees that `pytest tests/ci/test_determinism.py`
passes byte-for-byte across machines.
"""

from agentanvil.record_replay.mock import MockBackend
from agentanvil.record_replay.recording import RecordingBackend, request_key

__all__ = ["MockBackend", "RecordingBackend", "request_key"]
