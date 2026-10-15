"""Meridian Ledger behind CHAKRAVYUH.

Run with one worker. Session state is process-local; a second worker is a
second, half-blind gate, and it will also split the tarpit budget.

Uvicorn must not add its own Server header and must not rewrite the client
address from X-Forwarded-For. Both of those happen before middleware and
would either leak the real stack or bypass the trusted-proxy check.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.config import ChakravyuhConfig
from core.crawlers import CrawlerVerifier
from core.metrics import MetricsCollector
from core.scoring import ScoringEngine, SessionStore
from observability.routes import register_observability
from demo.site import register_demo
from middleware.identity import RealIdentityMiddleware
from middleware.middleware import ChakravyuhMiddleware

logger = logging.getLogger("chakravyuh")


def warn_resource_envelope(config: ChakravyuhConfig, limit_concurrency: int | None = None) -> None:
    """Log the descriptor budget. Do not pretend 2048 concurrency fits in 1024 fds."""
    import resource

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ValueError, OSError):
        logger.warning("could not read RLIMIT_NOFILE")
        return
    headroom = soft - config.max_concurrent_tarpits
    logger.info(
        "nofile soft=%s hard=%s tarpit_cap=%s headroom_after_tarpits=%s",
        soft,
        hard,
        config.max_concurrent_tarpits,
        headroom,
    )
    if soft < config.max_concurrent_tarpits * 2:
        logger.warning(
            "nofile soft limit %s is under twice the tarpit cap (%s). "
            "A full tarpit plus legitimate traffic can exhaust descriptors "
            "before the HTTP concurrency cap matters. Raise ulimit -n, or lower "
            "CHAKRAVYUH_MAX_TARPITS.",
            soft,
            config.max_concurrent_tarpits,
        )
    if limit_concurrency is not None and limit_concurrency > max(soft - 64, 1):
        logger.warning(
            "requested concurrency %s is above the nofile headroom (%s). "
            "The process will hit EMFILE first. Clamping at launch.",
            limit_concurrency,
            soft,
        )


def create_app(
    config: ChakravyuhConfig | None = None,
    crawlers: CrawlerVerifier | None = None,
    plan_hook=None,
) -> FastAPI:
    config = config or ChakravyuhConfig.from_env()
    store = SessionStore(config)
    engine = ScoringEngine(config)
    metrics = MetricsCollector()
    app = FastAPI(
        title="Meridian Ledger",
        version="1.3.2",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    register_demo(app, expose_console_link=config.expose_console_link)
    register_observability(app, store, metrics, config)
    # Last added is outermost. Identity must stay inside the gate so a
    # distorted response never receives the real Server token.
    app.add_middleware(
        RealIdentityMiddleware,
        server_header=config.real_server_header,
        skip_prefixes=config.exempt_prefixes,
    )
    app.add_middleware(
        ChakravyuhMiddleware,
        config=config,
        store=store,
        engine=engine,
        metrics=metrics,
        crawlers=crawlers,
        plan_hook=plan_hook,
    )
    warn_resource_envelope(config)
    app.state.store = store
    app.state.engine = engine
    app.state.metrics = metrics
    app.state.config = config
    proxies = ", ".join(str(net) for net in config.trusted_proxies) or "none (X-Forwarded-For ignored)"
    logger.info(
        "ready threshold=%.2f tarpit=%.0fs concurrent_cap=%s trusted_proxies=%s",
        config.threshold,
        config.tarpit_response_seconds,
        config.max_concurrent_tarpits,
        proxies,
    )
    return app


app = create_app()

# This serves the game at the URL: http://127.0.0.1:8000/training
app.mount("/training", StaticFiles(directory="training_game", html=True), name="training")

def _concurrency_within_nofile() -> int:
    """2048 is a wish. The soft nofile limit is the real cap."""
    import resource

    requested = int(os.environ.get("CHAKRAVYUH_LIMIT_CONCURRENCY", "2048"))
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ValueError, OSError):
        return requested
    ceiling = max(int(soft) - 64, 64)
    if requested > ceiling:
        logger.warning(
            "clamping limit_concurrency from %s to %s because nofile soft limit is %s",
            requested,
            ceiling,
            soft,
        )
        return ceiling
    return requested


def run() -> None:
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    kwargs: dict = {
        "host": host,
        "port": port,
        # In-memory sessions and the tarpit counter are process-local.
        "workers": 1,
        "server_header": False,
        "proxy_headers": False,
        "forwarded_allow_ips": "",
        "timeout_keep_alive": 5,
        "limit_concurrency": _concurrency_within_nofile(),
        "backlog": 2048,
        "timeout_graceful_shutdown": 35,
        "access_log": True,
        "log_level": os.environ.get("LOG_LEVEL", "info"),
        "ws": "auto",
    }
    try:
        import uvloop  # noqa: F401

        kwargs["loop"] = "uvloop"
    except ImportError:
        kwargs["loop"] = "asyncio"
    try:
        import httptools  # noqa: F401

        kwargs["http"] = "httptools"
    except ImportError:
        kwargs["http"] = "h11"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("metrics http://%s:%s/metrics", host, port)
    logger.info("protected application http://%s:%s/", host, port)
    uvicorn.run("main:app", **kwargs)


if __name__ == "__main__":
    run()
