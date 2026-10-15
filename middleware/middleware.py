"""CHAKRAVYUH pure ASGI middleware.

This is not ``BaseHTTPMiddleware``. That class buffers the response body
and would collapse the tarpit into a single delayed blob, which both
breaks streaming and defeats the commitment phase.

The decision to distort is made before the real application is called.
Otherwise the genuine Server header, cookie, and error page leak to the
client we are trying to mislead.

Chunk framing is the server's job. Body messages are raw HTML bytes with
``more_body=True``. Manually prefixing hex sizes corrupts the stream
(the server frames those bytes a second time).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass

from core.config import ChakravyuhConfig
from core.crawlers import CrawlerClaim, CrawlerVerifier
from core.identity import (
    headers_as_dict,
    is_known_path,
    peer_ip_from_scope,
    resolve_client_ip,
    session_key,
)
from core.metrics import DecisionEvent, MetricsCollector
from core.profiles import iter_stream_chunks, split_document, take_filler
from core.scoring import (
    ScoreBreakdown,
    ScoringEngine,
    SessionState,
    SessionStore,
    crossed,
    profile_for,
)

logger = logging.getLogger("chakravyuh.middleware")


@dataclass
class _Plan:
    session: SessionState
    breakdown: ScoreBreakdown
    path: str
    method: str
    ip_source: str
    probe_guess: bool
    action: str
    duration: float


class ChakravyuhMiddleware:
    """Starlette constructs this as ``Middleware(app, **kwargs)``."""

    def __init__(
        self,
        app,
        config: ChakravyuhConfig,
        store: SessionStore,
        engine: ScoringEngine,
        metrics: MetricsCollector,
        crawlers: CrawlerVerifier | None = None,
        plan_hook=None,
    ) -> None:
        self.app = app
        self.config = config
        self.store = store
        self.engine = engine
        self.metrics = metrics
        self.crawlers = crawlers or CrawlerVerifier(
            timeout=config.crawler_dns_timeout,
            cache_ttl=config.crawler_cache_ttl,
            max_concurrent=config.max_concurrent_dns,
            enabled=config.crawler_dns_enabled,
        )
        self._active_tarpits = 0
        self._saturated = False
        # Tests pass a hook so a planning fault does not depend on how
        # Starlette wraps the middleware stack. Production leaves this None.
        self._plan_hook = plan_hook

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not self.config.enabled:
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or "/"
        if _is_exempt(path, self.config.exempt_prefixes):
            self.metrics.note_exempt()
            await self.app(scope, receive, send)
            return
        # Planning failures fail open once. Exceptions after this point must
        # not call the origin again: the pass-through path may already have
        # started a response, and a second call would corrupt the stream.
        try:
            planner = self._plan_hook or self._plan
            plan = await planner(scope)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("planning fault before a response; failing open")
            self.metrics.record_fail_open()
            await self.app(scope, receive, send)
            return
        if plan.action == "pass":
            await self._pass_through(scope, receive, send, plan)
            return
        await self._distort(receive, send, plan)

    async def _plan(self, scope) -> _Plan:
        cfg = self.config
        headers = headers_as_dict(scope.get("headers"))
        peer = peer_ip_from_scope(scope)
        client_ip, ip_source = resolve_client_ip(
            peer, headers.get("x-forwarded-for"), cfg.trusted_proxies
        )
        key, method = session_key(client_ip, headers, cfg)
        now_wall = time.time()
        now_mono = time.monotonic()
        path = scope.get("path") or "/"
        http_method = str(scope.get("method") or "GET").upper()
        session = self.store.get_or_create(
            key,
            client_ip,
            now_wall=now_wall,
            identity_method=method,
            ip_source=ip_source,
        )
        probe_guess = not is_known_path(path, cfg)
        # Synchronous. Must not await inside observe/score or two requests
        # could interleave a decay.
        self.engine.observe(
            session,
            now_mono=now_mono,
            now_wall=now_wall,
            path=path,
            method=http_method,
            user_agent=headers.get("user-agent", ""),
            is_probe=probe_guess,
        )
        claim = await self._claim(client_ip, headers.get("user-agent", ""))
        breakdown = self.engine.score(session, headers, claim, now_mono)
        self.metrics.note_app_request(now_mono, now_wall)

        # Verified crawlers are never held, including by the release band.
        # A failed lookup that later succeeds must be able to leave.
        if claim.verified:
            if session.hostile:
                session.hostile = False
                logger.info("verified crawler released ip=%s family=%s", client_ip, claim.family)
            return _Plan(session, breakdown, path, http_method, ip_source, probe_guess, "pass", 0.0)

        entered = crossed(breakdown.score, cfg.threshold)
        held = session.hostile and breakdown.score >= cfg.release_threshold
        distort = entered or held
        if distort and not session.hostile:
            session.hostile = True
            logger.info(
                "threshold crossed ip=%s score=%.3f profile=%s path=%s",
                client_ip,
                breakdown.score,
                session.profile_id,
                path[:120],
            )
        elif not distort and session.hostile:
            session.hostile = False
            logger.info("session released ip=%s score=%.3f", client_ip, breakdown.score)

        if not distort:
            return _Plan(session, breakdown, path, http_method, ip_source, probe_guess, "pass", 0.0)

        if self._active_tarpits >= cfg.max_concurrent_tarpits:
            if not self._saturated:
                self._saturated = True
                logger.warning("tarpit concurrency cap reached (%s)", cfg.max_concurrent_tarpits)
            return _Plan(session, breakdown, path, http_method, ip_source, probe_guess, "shed", 0.0)

        remaining = cfg.session_tarpit_cap_seconds - session.tarpit_seconds
        if remaining < 1.0:
            # Still mutate. Falling through to the origin here would publish
            # the real stack after the session has already been classified.
            return _Plan(
                session, breakdown, path, http_method, ip_source, probe_guess, "budget_close", 0.0
            )
        duration = min(cfg.tarpit_response_seconds, remaining)
        return _Plan(
            session, breakdown, path, http_method, ip_source, probe_guess, "distort", duration
        )

    async def _claim(self, ip: str, user_agent: str) -> CrawlerClaim:
        try:
            return await self.crawlers.verify(ip, user_agent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("crawler check failed closed", exc_info=True)
            return CrawlerClaim("", False, False, "verifier error")

    async def _pass_through(self, scope, receive, send, plan: _Plan) -> None:
        status_box: dict[str, int | None] = {"status": None}

        async def send_wrap(message):
            if message["type"] == "http.response.start" and status_box["status"] is None:
                status_box["status"] = int(message.get("status") or 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrap)
        finally:
            status = status_box["status"]
            breakdown = plan.breakdown
            if status is not None:
                self.engine.correct_status(
                    plan.session,
                    guessed_probe=plan.probe_guess,
                    actual_not_found=(status == 404),
                )
                breakdown = self.engine.refresh_diversity(plan.session, breakdown)
            self._record(plan, "pass", int(status or 0), breakdown)

    async def _distort(self, receive, send, plan: _Plan) -> None:
        if plan.action == "shed":
            await self._send_simple(
                receive,
                send,
                plan.session,
                status=429,
                title="429 Too Many Requests",
                detail="The server is busy. Try again shortly.",
                extra_headers=((b"retry-after", b"30"),),
            )
            self._record(plan, "shed", 429, plan.breakdown)
            return
        if plan.action == "budget_close":
            status = self.config.distort_status
            await self._send_simple(
                receive,
                send,
                plan.session,
                status=status,
                title="Unavailable",
                detail="The requested resource is unavailable.",
            )
            self._record(plan, "budget_close", status, plan.breakdown)
            return
        await self._tarpit(receive, send, plan)

    async def _tarpit(self, receive, send, plan: _Plan) -> None:
        cfg = self.config
        session = plan.session
        profile = profile_for(session)
        disconnected = asyncio.Event()
        watcher = asyncio.create_task(_drain_until_disconnect(receive, disconnected))
        started = False
        closed = False
        streamed = 0
        now_wall = time.time()
        now_mono = time.monotonic()
        # Reserve before the first await inside this coroutine so the cap
        # check in _plan and this increment cannot interleave.
        self._active_tarpits += 1
        session.distorted += 1
        handle = self.metrics.begin_tarpit(
            session, plan.path, plan.breakdown.score, now_wall, now_mono
        )
        # Publish the decision now. Recording in the finally would hide the
        # hit from the console for the whole hold (up to 30 seconds).
        self._record(plan, "distort", cfg.distort_status, plan.breakdown)
        rng = random.Random(session.key)
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": cfg.distort_status,
                    "headers": profile.asgi_headers(session.key),
                }
            )
            started = True
            if plan.method == "HEAD":
                await _wait_disconnect(disconnected, plan.duration)
            else:
                streamed = await self._stream_body(
                    send, session.key, profile, rng, disconnected, plan.duration
                )
            await _end_body(send, started, closed)
            closed = True
        except asyncio.CancelledError:
            await _end_body(send, started, closed)
            raise
        except Exception:
            logger.exception("tarpit failed after start=%s", started)
            await _end_body(send, started, closed)
        finally:
            session.tarpit_seconds += max(0.0, time.monotonic() - now_mono)
            self._active_tarpits = max(0, self._active_tarpits - 1)
            if self._active_tarpits < cfg.max_concurrent_tarpits:
                self._saturated = False
            self.metrics.end_tarpit(handle.tarpit_id, streamed)
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass

    async def _stream_body(self, send, session_key: str, profile, rng, disconnected, duration: float) -> int:
        cfg = self.config
        payload = profile.document(session_key, status=cfg.distort_status)
        opened, closing = split_document(payload)
        chunks = iter_stream_chunks(opened, cfg.preamble_bytes, cfg.chunk_size, rng)
        cursor = [0]
        streamed = 0
        deadline = time.monotonic() + duration
        index = 0
        while not disconnected.is_set() and time.monotonic() < deadline:
            if index == 0:
                chunk = chunks[0] if chunks else b"<!DOCTYPE html>"
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                wait = min(rng.uniform(*cfg.chunk_interval), remaining)
                if await _wait_disconnect(disconnected, wait):
                    break
                if time.monotonic() >= deadline:
                    break
                if index < len(chunks):
                    chunk = chunks[index]
                else:
                    chunk = take_filler(rng, cfg.chunk_size, cursor)
            index += 1
            try:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("tarpit send failed; client likely gone")
                return streamed
            streamed += len(chunk)
        if disconnected.is_set():
            return streamed
        if closing:
            try:
                await send({"type": "http.response.body", "body": closing, "more_body": True})
                streamed += len(closing)
            except Exception:
                return streamed
        return streamed

    async def _send_simple(
        self,
        receive,
        send,
        session: SessionState,
        *,
        status: int,
        title: str,
        detail: str,
        extra_headers: tuple[tuple[bytes, bytes], ...] = (),
    ) -> None:
        profile = profile_for(session)
        disconnected = asyncio.Event()
        watcher = asyncio.create_task(_drain_until_disconnect(receive, disconnected))
        body = profile.short_message(title, detail)
        headers = profile.asgi_headers(session.key)
        headers.extend(extra_headers)
        try:
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body, "more_body": False})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("short response failed", exc_info=True)
        finally:
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass

    def _record(self, plan: _Plan, action: str, status: int, breakdown: ScoreBreakdown) -> None:
        session = plan.session
        if action == "pass":
            session.passed += 1
        self.metrics.record_decision(
            DecisionEvent(
                wall=time.time(),
                ip=session.ip,
                method=plan.method,
                path=plan.path[:180],
                score=breakdown.score,
                r_hat=breakdown.r_hat,
                d=breakdown.d,
                h=breakdown.h,
                c=breakdown.c,
                classification=breakdown.classification_for(self.config.threshold),
                action=action,
                profile_id="" if action == "pass" else session.profile_id,
                status=status,
                user_agent=session.user_agent_preview,
                explain=_explain(breakdown, action, self.config),
                ip_source=plan.ip_source,
                session_id=session.key[:16],
            )
        )


def _explain(breakdown: ScoreBreakdown, action: str, config: ChakravyuhConfig) -> str:
    text = breakdown.explain(config.threshold)
    if action in {"distort", "shed", "budget_close"} and not crossed(breakdown.score, config.threshold):
        return text + f" · held until S < {config.release_threshold:.2f}"
    return text


def _is_exempt(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


async def _drain_until_disconnect(receive, event: asyncio.Event) -> None:
    """Consume the request stream so a disconnect is observed and a large
    body is not buffered by the server for the whole tarpit."""
    try:
        while not event.is_set():
            message = await receive()
            if not isinstance(message, dict):
                event.set()
                return
            if message.get("type") == "http.disconnect":
                event.set()
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        event.set()


async def _wait_disconnect(event: asyncio.Event, seconds: float) -> bool:
    if event.is_set() or seconds <= 0:
        return event.is_set()
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False


async def _end_body(send, started: bool, closed: bool) -> None:
    if not started or closed:
        return
    try:
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    except Exception:
        return
