"""Per-episode state of the transport proxy: crossings, layer rewrites and replay.

A session is one episode. Each role named in the client's base URL (for example
`agent` and `user`) is a boundary, and the k-th crossing of a boundary is its
k-th completed call. Upstream errors do not consume a crossing: they are logged
and the client's retry takes the same k.

What a session does to each crossing (configured in `SessionConfig`):

- seed: with `RoleConfig.seed`, `seed` becomes a value derived from it, the role
  and k: the same seed gives the same realisation, a new seed a new one;
- order: with `permute_seed`, `tools` is permuted once per session and each run of
  consecutive tool results by where it starts, so the history stays stable;
- replay: crossings whose reference index is below `replay_until` get the
  reference response without calling upstream (the k-th gets the k-th);
- divergence: with a reference, every crossing is compared by request hash (and
  by response hash when live) under this session's normalizer, a crossing the
  reference does not have is `extra`, and the result logged;
  `on_divergence="abort"` raises `ReplayDivergenceError` and refuses every later
  call of the session. Closing logs the crossings the reference had left;
- faults: the `perturb` list changes live crossings (`proxy_faults`, #36). The
  divergence checks compare the client's request and the upstream's response,
  never what a fault changed.

Calls within a session are serialised, so crossing order never depends on timing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from agentanvil.exceptions import RecordingError, ReplayDivergenceError
from agentanvil.record_replay.normalize import JSONObject, request_hash, response_hash
from agentanvil.record_replay.perturb import Fault, Perturbation
from agentanvil.record_replay.proxy_faults import SessionFaults
from agentanvil.record_replay.proxy_layers import derive_seed, permutation, permute_tool_runs
from agentanvil.record_replay.proxy_log import (
    Close,
    Crossing,
    Divergence,
    Failure,
    SessionConfig,
    append,
    create,
    load_reference,
)

__all__ = ["Forward", "ProxySession", "derive_seed", "permutation"]

Forward = Callable[[str, JSONObject], tuple[int, JSONObject]]
"""Sends a body to an upstream base URL; returns the HTTP status and the JSON body."""


class ProxySession:
    """One episode behind the proxy."""

    def __init__(
        self,
        config: SessionConfig,
        log_dir: Path,
        *,
        in_flight: Callable[[], int] = lambda: 1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.log_path = log_dir / f"{config.session_id}.jsonl"
        self._reference = (
            load_reference(config.reference, config.normalizer) if config.reference else {}
        )
        self._faults = SessionFaults(
            config.perturb, config.normalizer, sleep=sleep, in_flight=in_flight
        )
        self._faults.refuse_replayed(self._reference, config.replay_until)
        self._k: dict[str, int] = {}
        self._index = 0
        self._aborted = self._closed = False
        self._lock = threading.Lock()
        log_dir.mkdir(parents=True, exist_ok=True)
        create(self.log_path, {"kind": "session", "config": config.model_dump(mode="json")})

    def handle(self, role: str, body: JSONObject, forward: Forward) -> tuple[int, JSONObject]:
        """Serve one call of `role`; returns the status and body to send back to the client."""
        if role not in self.config.roles:
            raise RecordingError(f"session {self.config.session_id!r} has no role {role!r}")
        with self._lock:
            if self._closed:
                raise RecordingError(f"session {self.config.session_id!r} is closed")
            if self._aborted:
                raise ReplayDivergenceError(f"session {self.config.session_id!r} already aborted")
            k = self._k.get(role, 0)
            refs = self._reference.get(role, [])
            ref = refs[k] if k < len(refs) else None
            req_hash = request_hash(body, self.config.normalizer)
            diverged: Divergence = []
            if self.config.reference is not None and ref is None:
                diverged = ["extra"]
            elif ref is not None and ref.request_hash != req_hash:
                diverged = ["request"]
            self._guard(role, k, req_hash, diverged, {})
            if ref is not None and ref.index < self.config.replay_until:
                return 200, self._commit(role, k, body, req_hash, ref.response, diverged)
            fault = self._faults.at(role, k)
            if (injected := self._faults.injected_error(fault)) is not None:
                status, resp = injected
                self._fail(role, k, req_hash, status, resp, fault=fault)
                return status, resp
            sent, applied = self._faults.on_request(fault, k, body)
            upstream, seed, order = self._rewrite(role, k, sent)
            start = time.perf_counter()
            status, resp = forward(self.config.roles[role].upstream, upstream)
            latency_ms = round((time.perf_counter() - start) * 1000)
            if status != 200:
                self._fail(role, k, req_hash, status, resp)
                return status, resp
            if ref is not None and ref.response_hash != response_hash(resp, self.config.normalizer):
                diverged.append("response")
            self._guard(role, k, req_hash, diverged, resp)
            answer, answered = self._faults.on_response(fault, k, body, resp)
            applied = applied or answered or self._faults.delay(fault, answer)
            if fault is not None and applied is None and fault.op != "upstream_error":
                self._fail(role, k, req_hash, 200, {}, fault=fault, reason="perturbation_miss")
            live = (seed, order, latency_ms)
            changed = (sent if sent is not body else None, resp if answer is not resp else None)
            return 200, self._commit(
                role, k, body, req_hash, answer, diverged, live, applied, changed
            )

    def close(self) -> dict[str, int]:
        """End the session after any call in flight; returns reference crossings left per role."""
        with self._lock:
            self._closed = True
            missing = {
                role: len(refs) - self._k.get(role, 0)
                for role, refs in self._reference.items()
                if len(refs) > self._k.get(role, 0)
            }
            append(
                self.log_path,
                Close(session_id=self.config.session_id, crossings=dict(self._k), missing=missing),
            )
            return missing

    # ----- internals -----

    def _guard(
        self, role: str, k: int, req_hash: str, diverged: Divergence, resp: JSONObject
    ) -> None:
        if not diverged or self.config.on_divergence != "abort":
            return
        self._aborted = True
        failure = Failure(
            reason="divergence",
            session_id=self.config.session_id,
            role=role,
            k=k,
            status=409,
            request_hash=req_hash,
            divergence=diverged,
            response=resp,
        )
        append(self.log_path, failure)
        raise ReplayDivergenceError(
            f"session {self.config.session_id!r}: {role} crossing {k} diverged ({diverged})"
        )

    def _fail(
        self,
        role: str,
        k: int,
        req_hash: str,
        status: int,
        resp: JSONObject,
        *,
        fault: Fault | None = None,
        reason: Literal["upstream", "perturbation_miss"] = "upstream",
    ) -> None:
        failure = Failure(
            reason=reason,
            session_id=self.config.session_id,
            role=role,
            k=k,
            status=status,
            request_hash=req_hash,
            response=resp,
            fault=fault,
        )
        append(self.log_path, failure)

    def _commit(
        self,
        role: str,
        k: int,
        body: JSONObject,
        req_hash: str,
        resp: JSONObject,
        diverged: Divergence,
        live: tuple[int | None, list[int] | None, int] | None = None,
        perturbation: Perturbation | None = None,
        changed: tuple[JSONObject | None, JSONObject | None] = (None, None),
    ) -> JSONObject:
        seed, order, latency_ms = live if live else (None, None, 0)
        crossing = Crossing(
            session_id=self.config.session_id,
            role=role,
            k=k,
            index=self._index,
            source="live" if live else "replay",
            seed=seed,
            tools_order=order,
            request_hash=req_hash,
            response_hash=response_hash(resp, self.config.normalizer),
            request=body,
            response=resp,
            latency_ms=latency_ms,
            divergence=diverged,
            perturbation=perturbation,
            upstream_request=changed[0],
            upstream_response=changed[1],
        )
        append(self.log_path, crossing)
        self._faults.remember(role, resp)
        self._k[role] = k + 1
        self._index += 1
        return resp

    def _rewrite(
        self, role: str, k: int, body: JSONObject
    ) -> tuple[JSONObject, int | None, list[int] | None]:
        out = dict(body)
        seed = None
        if (base := self.config.roles[role].seed) is not None:
            seed = derive_seed(base, role, k)
            out["seed"] = seed
        order = None
        if (p := self.config.permute_seed) is not None and role in self.config.permute_roles:
            if isinstance(tools := body.get("tools"), list):
                order = permutation(len(tools), derive_seed(p, role, "tools"))
                out["tools"] = [tools[i] for i in order]
            if isinstance(messages := body.get("messages"), list):
                out["messages"] = permute_tool_runs(messages, derive_seed(p, role, "results"))
        return out, seed, order
