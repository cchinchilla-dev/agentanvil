"""The wait a server asks for before a retry: headers, HTTP dates and Google's body (#8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from agentanvil.backends.retry import asked_delay


def _in(seconds: int, *, zone: bool = True) -> str:
    when = datetime.now(UTC) + timedelta(seconds=seconds)
    # Without a zone the date ends in "-0000", which parses to a naive datetime.
    return (
        format_datetime(when, usegmt=True) if zone else format_datetime(when.replace(tzinfo=None))
    )


@pytest.mark.parametrize(
    ("headers", "body", "expected"),
    [
        ({"retry-after-ms": "1500", "retry-after": "9"}, None, 1.5),
        ({"retry-after": "2.5"}, None, 2.5),
        ({"retry-after": _in(-60)}, None, 0.0),
        ({"retry-after": "soon"}, None, None),
        ({"retry-after": "-5"}, None, None),
        ({"retry-after": "inf"}, None, None),
        ({}, {"error": {"details": [{"@type": "x"}, {"retryDelay": "30.5s"}]}}, 30.5),
        ({}, {"error": {"details": [{"retryDelay": "30sec"}]}}, None),
        ({}, {"error": {"details": [{"retryDelay": 30}]}}, None),
        ({}, {"error": {"details": ["RetryInfo"]}}, None),
        ({}, {"error": {"details": "RetryInfo"}}, None),
        ({}, {"error": "busy"}, None),
        ({}, ["busy"], None),
        ({}, None, None),
    ],
)
def test_asked_delay(headers: dict[str, str], body: Any, expected: float | None) -> None:
    if body is None:
        response = httpx.Response(429, headers=headers)
    else:
        response = httpx.Response(429, headers=headers, json=body)

    assert asked_delay(response) == expected


@pytest.mark.parametrize("zone", [True, False])
def test_asked_delay_reads_an_http_date(zone: bool) -> None:
    response = httpx.Response(429, headers={"retry-after": _in(20, zone=zone)})

    assert asked_delay(response) == pytest.approx(20, abs=2)


def test_asked_delay_skips_an_unread_body() -> None:
    assert asked_delay(httpx.Response(429, stream=httpx.ByteStream(b'{"error": {}}'))) is None
