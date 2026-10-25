"""Bounded retries for `DirectBackend` (#8).

A network error or a transient status (408, 429, 5xx, Anthropic's 529) is
retried after the delay the server asks for, or else with exponential backoff
and full jitter. Any other status, the last attempt, or a server asking to wait
longer than ``max_delay_s`` raises `BackendError` from the httpx error.
"""

from __future__ import annotations

import logging
import math
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TypeVar

import anyio
import httpx
from pydantic import BaseModel, ConfigDict, Field

from agentanvil.exceptions import BackendError

logger = logging.getLogger("agentanvil.backends")

T = TypeVar("T")

_GOOGLE_DELAY = re.compile(r"(\d+(?:\.\d+)?)s")


class RetryPolicy(BaseModel):
    """How `DirectBackend` retries a call; ``max_attempts=1`` turns retries off."""

    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=3, ge=1)
    base_delay_s: float = Field(default=1.0, ge=0)
    max_delay_s: float = Field(default=30.0, ge=0)
    retryable_status_codes: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504, 529})


async def with_retry(provider: str, call: Callable[[], Awaitable[T]], policy: RetryPolicy) -> T:
    """Run ``call``, retrying it as ``policy`` says."""
    attempt = 1
    while True:
        try:
            return await call()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            delay = _next_delay(provider, exc, attempt, policy)
        logger.warning(
            "%s call failed (attempt %d of %d); retrying in %.2f s",
            provider,
            attempt,
            policy.max_attempts,
            delay,
        )
        await anyio.sleep(delay)
        attempt += 1


async def open_stream(
    provider: str, start: Callable[[], AsyncIterator[T]], policy: RetryPolicy
) -> AsyncIterator[T]:
    """The items of ``start()``, retried as ``policy`` says until the first one arrives.

    Once an item has been yielded a retry would repeat it, so a later network
    error raises `BackendError` at once.
    """

    async def first() -> tuple[AsyncIterator[T], list[T]]:
        stream = start()
        async for item in stream:
            return stream, [item]
        return stream, []

    stream, head = await with_retry(provider, first, policy)
    for item in head:
        yield item
    try:
        async for item in stream:
            yield item
    except httpx.TransportError as exc:
        raise BackendError(f"{provider} stream broke ({type(exc).__name__})") from exc


def _next_delay(
    provider: str,
    exc: httpx.HTTPStatusError | httpx.TransportError,
    attempt: int,
    policy: RetryPolicy,
) -> float:
    """Seconds to wait before attempt ``attempt + 1``; `BackendError` when there is none."""
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        what = f"{provider} returned {response.status_code} {response.reason_phrase}".rstrip()
        if response.status_code not in policy.retryable_status_codes:
            raise BackendError(what) from exc
        asked = asked_delay(response)
    else:
        what, asked = f"{provider} could not be reached ({type(exc).__name__})", None
    if attempt >= policy.max_attempts:
        raise BackendError(f"{what} after {attempt} attempt(s)") from exc
    if asked is None:
        ceiling = min(policy.max_delay_s, policy.base_delay_s * 2 ** (attempt - 1))
        return random.uniform(0, ceiling)
    if asked > policy.max_delay_s:
        # Retrying sooner than the server asked would most likely fail the same way.
        raise BackendError(
            f"{what} and asks to wait {asked:g} s, longer than max_delay_s={policy.max_delay_s:g}"
        ) from exc
    return asked


def asked_delay(response: httpx.Response) -> float | None:
    """The wait the server asks for, in seconds, or None if it names none.

    Read from ``retry-after-ms``, from ``Retry-After`` in seconds or as an HTTP
    date, or from the ``retryDelay`` in the body of a Google error.
    """
    if (millis := _seconds(response.headers.get("retry-after-ms"))) is not None:
        return millis / 1000
    header = response.headers.get("retry-after")
    if header:
        if (seconds := _seconds(header)) is not None:
            return seconds
        try:
            when = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            when = when if when.tzinfo else when.replace(tzinfo=UTC)
            return max(0.0, (when - datetime.now(UTC)).total_seconds())
    return _google_delay(response)


def _seconds(value: str | None) -> float | None:
    """A finite, non-negative number of seconds, or None for anything else."""
    try:
        number = float(value) if value is not None else math.nan
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _google_delay(response: httpx.Response) -> float | None:
    """The ``retryDelay`` (``"30s"``) of a Google ``RetryInfo`` error detail."""
    try:
        details = response.json()["error"]["details"]
    except (httpx.ResponseNotRead, ValueError, KeyError, TypeError):
        return None
    for detail in details if isinstance(details, list) else []:
        delay = detail.get("retryDelay") if isinstance(detail, dict) else None
        if isinstance(delay, str) and (match := _GOOGLE_DELAY.fullmatch(delay)):
            return float(match.group(1))
    return None
