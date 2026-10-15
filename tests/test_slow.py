"""Production-interval hold.

Default tests use a 50 ms drip so the suite stays fast. That does not prove
the specified 2.0–2.5 s interval. This file does. It is excluded from
``pytest`` and run with ``pytest -m slow``.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.config import ChakravyuhConfig
from tests.test_middleware import BROWSER, _Verifier, _invoke, _scope, _seed
from main import create_app

pytestmark = pytest.mark.slow


def test_production_interval_is_two_to_two_and_a_half_seconds():
    app = create_app(
        ChakravyuhConfig(
            chunk_interval=(2.0, 2.5),
            chunk_size=(8, 16),
            preamble_bytes=512,
            tarpit_response_seconds=6.5,
            session_tarpit_cap_seconds=300,
            max_concurrent_tarpits=8,
        ),
        crawlers=_Verifier(),
    )
    _seed(app, "203.0.113.10", BROWSER)

    async def run():
        started = time.perf_counter()
        sent = []

        async def receive():
            await asyncio.sleep(30)
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                message = dict(message)
                message["_t"] = time.perf_counter()
            sent.append(message)

        await app(_scope("/.env", headers=BROWSER), receive, send)
        return started, sent

    started, sent = asyncio.run(asyncio.wait_for(run(), timeout=12))
    bodies = [
        (message["_t"], message["body"])
        for message in sent
        if message["type"] == "http.response.body" and message.get("body")
    ]
    phase = [(t, body) for t, body in bodies if not body.lower().startswith(b"</body")]
    assert phase, "no body was streamed"
    assert phase[0][1].lower().startswith(b"<!doctype html>")
    assert len(phase[0][1]) == 512
    # Commitment is not delayed by the phase-2 interval.
    assert phase[0][0] - started < 0.5
    assert len(phase) >= 3, "expected the commitment plus at least two slow slices"
    for index in range(1, len(phase)):
        gap = phase[index][0] - phase[index - 1][0]
        assert 1.85 <= gap <= 2.75, f"gap {index} was {gap:.3f}s, not 2.0–2.5"
        assert 8 <= len(phase[index][1]) <= 16
    # The whole hold is the configured cap, not a 50 ms test double.
    assert phase[-1][0] - started >= 4.0
