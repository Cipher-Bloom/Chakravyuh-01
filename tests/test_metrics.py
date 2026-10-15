"""Prometheus text. No client address, no second copy of the formula."""

from __future__ import annotations

import asyncio
import json
import time

from core.metrics import SCORE_BOUNDS, DecisionEvent, MetricsCollector
from main import create_app
from observability.exporter import render
from tests.test_middleware import BROWSER, _Verifier, _bodies, _config, _invoke, _scope, _status


def _event(score: float, action: str = "pass") -> DecisionEvent:
    return DecisionEvent(
        wall=time.time(),
        ip="203.0.113.44",
        method="GET",
        path="/.env",
        score=score,
        r_hat=0.1,
        d=0.0,
        h=0.0,
        c=0.0,
        classification="legitimate",
        action=action,
        profile_id="",
        status=200,
        user_agent="Mozilla/5.0",
        explain="test",
        ip_source="peer",
    )


def test_histogram_is_cumulative_and_render_has_no_client_label():
    metrics = MetricsCollector()
    for score in (0.05, 0.45, 0.72):
        metrics.record_decision(_event(score))
    config = _config()
    text = render(metrics, sessions=3, config=config).decode()
    assert "203.0.113.44" not in text
    assert "Mozilla" not in text
    assert "/.env" not in text
    assert "chakravyuh_requests_total" in text
    assert 'chakravyuh_decisions_total{action="pass"}' in text
    assert 'chakravyuh_decisions_total{action="distort"}' in text

    def bucket(le: str) -> float:
        needle = f'chakravyuh_score_bucket{{le="{le}"}}'
        for line in text.splitlines():
            if line.startswith(needle):
                return float(line.split()[-1])
        raise AssertionError(needle)

    assert bucket("0.1") == 1
    assert bucket("0.4") == 1
    assert bucket("0.5") == 2
    assert bucket("0.7") == 2
    assert bucket("1.0") == 3
    assert bucket("+Inf") == 3
    assert len(metrics.score_buckets) == len(SCORE_BOUNDS)
    assert "chakravyuh_score_sum" in text
    assert "chakravyuh_build_info{" in text
    assert "chakravyuh_shed_total" in text
    assert "chakravyuh_budget_closed_total" in text


def test_scrape_does_not_label_the_client_and_snapshot_shape_holds():
    app = create_app(_config(dashboard_token=""), crawlers=_Verifier())

    async def run():
        await _invoke(app, _scope("/.env", headers=BROWSER, client=("203.0.113.44", 41000)))
        sent = await _invoke(app, _scope("/metrics", headers=BROWSER))
        status, headers = _status(sent)
        body = b"".join(_bodies(sent)).decode()
        assert status == 200
        assert "203.0.113.44" not in body
        assert "user_agent" not in body
        assert "chakravyuh_requests_total" in body
        assert 'action="pass"' in body
        assert "<html" not in body.lower()
        assert headers.get("content-type", "").startswith("text/plain; version=0.0.4")

        snap = await _invoke(app, _scope("/chakravyuh-dashboard/api/snapshot", headers=BROWSER))
        payload = json.loads(b"".join(_bodies(snap)))
        assert len(payload["sessions"]) <= 18
        assert len(payload["feed"]) <= 40
        assert "score" in payload["sessions"][0]
        assert payload["sessions"][0]["ip"] == "203.0.113.44"

    asyncio.run(run())


def test_snapshot_cap_and_feed_id_are_per_session():
    """Two clients can share an address. The feed id is the session id, not the IP."""
    app = create_app(_config(), crawlers=_Verifier())

    async def run():
        await _invoke(app, _scope("/.env", headers=BROWSER, client=("203.0.113.44", 41000)))
        scanner = {**BROWSER, "user-agent": "Nikto/2.5.0"}
        await _invoke(app, _scope("/admin", headers=scanner, client=("203.0.113.44", 41001)))
        sent = await _invoke(app, _scope("/chakravyuh-dashboard/api/snapshot", headers=BROWSER))
        payload = json.loads(b"".join(_bodies(sent)))
        assert payload["global"]["max_tarpits"] == app.state.config.max_concurrent_tarpits
        assert payload["global"]["active_tarpits"] == 0
        by_ip = [row for row in payload["sessions"] if row["ip"] == "203.0.113.44"]
        assert len(by_ip) == 2
        assert len({row["id"] for row in by_ip}) == 2
        feed_ids = {event["id"] for event in payload["feed"] if event["ip"] == "203.0.113.44"}
        assert feed_ids == {row["id"] for row in by_ip}

    asyncio.run(run())


def test_metrics_and_snapshot_honor_the_token():
    app = create_app(_config(dashboard_token="s3cret"), crawlers=_Verifier())

    async def run():
        locked = await _invoke(app, _scope("/metrics", headers=BROWSER))
        assert _status(locked)[0] == 401
        assert b"chakravyuh_requests_total" not in b"".join(_bodies(locked))
        opened = await _invoke(
            app,
            _scope("/metrics", headers={**BROWSER, "authorization": "Bearer s3cret"}),
        )
        assert _status(opened)[0] == 200
        snap = await _invoke(app, _scope("/chakravyuh-dashboard/api/snapshot", headers=BROWSER))
        assert _status(snap)[0] == 401

    asyncio.run(run())
