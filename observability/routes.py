"""Scrape endpoint, the snapshot the score study reads, and a table page.

`/chakravyuh-dashboard/api/snapshot` keeps the shape the study used:
eighteen sessions, ranked by score, and forty feed events. The page at
`/chakravyuh-dashboard` only renders that document. It does not score.
"""

from __future__ import annotations

import hmac
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from core.config import ChakravyuhConfig
from core.metrics import MetricsCollector
from core.scoring import SessionStore
from observability.exporter import PROMETHEUS_TEXT, render

_PAGE = (Path(__file__).resolve().parent / "console.html").read_text(encoding="utf-8")


def _authorized(config: ChakravyuhConfig, headers, token: str | None) -> bool:
    expected = config.dashboard_token
    if not expected:
        return True
    supplied = token or ""
    auth = ""
    if headers is not None:
        auth = headers.get("authorization", "") or ""
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    try:
        return hmac.compare_digest(supplied, expected)
    except (TypeError, ValueError):
        return False


def _formula(config: ChakravyuhConfig) -> str:
    return (
        f"S = {config.w_rate:.2f}·R̂ + {config.w_diversity:.2f}·D + "
        f"{config.w_headers:.2f}·H − {config.w_crawler:.2f}·C"
    )


def build_snapshot(
    store: SessionStore,
    metrics: MetricsCollector,
    config: ChakravyuhConfig,
) -> dict:
    """Same document the score study polled. Do not drop fields it reads."""
    from core import __version__

    now_wall = time.time()
    now_mono = time.monotonic()
    payload = metrics.snapshot(
        store.values(),
        now_mono=now_mono,
        now_wall=now_wall,
        threshold=config.threshold,
        weights={
            "R": config.w_rate,
            "D": config.w_diversity,
            "H": config.w_headers,
            "C": config.w_crawler,
        },
        max_tarpits=config.max_concurrent_tarpits,
        tarpit_response_seconds=config.tarpit_response_seconds,
        session_tarpit_cap=config.session_tarpit_cap_seconds,
    )
    payload["release_threshold"] = config.release_threshold
    payload["decay"] = config.decay
    payload["rate_cap_rps"] = config.rate_cap_rps
    payload["window_seconds"] = config.window_seconds
    payload["formula"] = _formula(config)
    payload["enabled"] = config.enabled
    payload["version"] = __version__
    return payload


def register_observability(
    app: FastAPI,
    store: SessionStore,
    metrics: MetricsCollector,
    config: ChakravyuhConfig,
) -> None:
    def _locked(request: Request) -> bool:
        return not _authorized(config, request.headers, request.query_params.get("token"))

    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint(request: Request) -> Response:
        if _locked(request):
            return PlainTextResponse("unauthorized\n", status_code=401)
        body = render(metrics, sessions=len(store), config=config)
        return Response(
            content=body,
            media_type=PROMETHEUS_TEXT,
            headers={"cache-control": "no-store", "x-content-type-options": "nosniff"},
        )

    @app.get("/chakravyuh-dashboard/api/snapshot", include_in_schema=False)
    def snapshot(request: Request) -> JSONResponse:
        if _locked(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return JSONResponse(build_snapshot(store, metrics, config), headers={"cache-control": "no-store"})

    def page(request: Request) -> HTMLResponse:
        if _locked(request):
            return HTMLResponse("unauthorized\n", status_code=401)
        return HTMLResponse(
            _PAGE,
            headers={
                "cache-control": "no-store",
                "x-content-type-options": "nosniff",
                "referrer-policy": "no-referrer",
            },
        )

    for path in ("/chakravyuh-dashboard", "/chakravyuh-dashboard/"):
        app.add_api_route(path, page, methods=["GET"], include_in_schema=False)
