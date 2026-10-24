"""The faults of one transport-proxy session, applied crossing by crossing (#36).

At each live crossing, `ProxySession` asks `SessionFaults` in order: for an error to
answer instead of calling the upstream, for the request to send, for the response
to return and for a delay. It keeps what faults need across crossings: how many
upstream errors each fault has injected, and each role's last tool calls, which
`loop` repeats. A fault never applies to a crossing served from the reference: the
session refuses it when it opens.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from agentanvil.exceptions import RecordingError
from agentanvil.record_replay.normalize import (
    JSON,
    JSONObject,
    Normalizer,
    request_hash,
    response_hash,
)
from agentanvil.record_replay.perturb import DelayParams, Fault, Perturbation, UpstreamErrorParams
from agentanvil.record_replay.perturb_request import REQUEST_OPS
from agentanvil.record_replay.perturb_response import RESPONSE_OPS, tool_calls_of
from agentanvil.record_replay.proxy_layers import derive_seed

if TYPE_CHECKING:
    from agentanvil.record_replay.proxy_log import Crossing


class SessionFaults:
    """The faults of one session, and the state they keep between crossings."""

    def __init__(
        self,
        faults: Iterable[Fault],
        normalizer: Normalizer,
        *,
        sleep: Callable[[float], None] = time.sleep,
        in_flight: Callable[[], int] = lambda: 1,
    ) -> None:
        self._faults = {(f.role, f.at): f for f in faults}
        self._normalizer = normalizer
        self._sleep = sleep
        self._in_flight = in_flight  # requests the proxy is serving, this one included
        self._injected: dict[tuple[str, int], int] = {}
        self._calls: dict[str, list[JSON]] = {}

    def refuse_replayed(self, reference: dict[str, list[Crossing]], replay_until: int) -> None:
        """Raise if a fault falls on a crossing that the session serves from its reference."""
        for (role, k), fault in self._faults.items():
            refs = reference.get(role, [])
            if k < len(refs) and refs[k].index < replay_until:
                raise RecordingError(
                    f"fault {fault.op!r} on {role} crossing {k} falls in the replayed prefix"
                    f" (replay_until={replay_until})"
                )

    def at(self, role: str, k: int) -> Fault | None:
        return self._faults.get((role, k))

    def injected_error(self, fault: Fault | None) -> tuple[int, JSONObject] | None:
        """The error to answer instead of calling the upstream, `times` times."""
        if fault is None or fault.op != "upstream_error":
            return None
        params = UpstreamErrorParams.model_validate(fault.params)
        key = (fault.role, fault.at)
        if (done := self._injected.get(key, 0)) >= params.times:
            return None
        self._injected[key] = done + 1
        status = 504 if params.status == "timeout" else params.status
        what = "timed out" if params.status == "timeout" else f"answered {status}"
        message = f"upstream {what} (injected by the proxy)"
        return status, {"error": {"message": message, "type": "agentanvil_injected_error"}}

    def on_request(
        self, fault: Fault | None, k: int, body: JSONObject
    ) -> tuple[JSONObject, Perturbation | None]:
        """The request to send upstream, and what the fault did to it."""
        if fault is None or (op := REQUEST_OPS.get(fault.op)) is None:
            return body, None
        if (change := op(body, fault, self._seed(fault, k))) is None:
            return body, None
        sent, site, choices = change
        before, after = (request_hash(b, self._normalizer) for b in (body, sent))
        return sent, self._applied(fault, site, choices, before, after)

    def on_response(
        self, fault: Fault | None, k: int, request: JSONObject, response: JSONObject
    ) -> tuple[JSONObject, Perturbation | None]:
        """The response to return to the client, and what the fault did to it."""
        if fault is None or (op := RESPONSE_OPS.get(fault.op)) is None:
            return response, None
        previous = self._calls.get(fault.role, [])
        if (change := op(response, request, fault, self._seed(fault, k), previous)) is None:
            return response, None
        answer, site, choices = change
        before, after = (response_hash(r, self._normalizer) for r in (response, answer))
        return answer, self._applied(fault, site, choices, before, after)

    def delay(self, fault: Fault | None, response: JSONObject) -> Perturbation | None:
        """Hold the answer: `ms`, plus `per_request_ms` for each other request in flight."""
        if fault is None or fault.op != "delay":
            return None
        params = DelayParams.model_validate(fault.params)
        ms = params.ms + params.per_request_ms * max(self._in_flight() - 1, 0)
        self._sleep(ms / 1000)
        digest = response_hash(response, self._normalizer)
        return self._applied(fault, "latency", {"delay_ms": ms}, digest, digest)

    def remember(self, role: str, response: JSONObject) -> None:
        """Keep the tool calls the client got from this crossing, for a later `loop`."""
        self._calls[role] = tool_calls_of(response)

    @staticmethod
    def _seed(fault: Fault, k: int) -> int:
        return derive_seed(fault.seed, fault.op, k)

    @staticmethod
    def _applied(
        fault: Fault, site: str, choices: dict[str, JSON], before: str, after: str
    ) -> Perturbation:
        return Perturbation(
            op=fault.op,
            params={**fault.params, **choices},
            site=site,
            before_hash=before,
            after_hash=after,
        )
