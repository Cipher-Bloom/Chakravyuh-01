"""ASGI behavior: streaming, no chunk framing, XFF, fail-open, caps."""

from __future__ import annotations

import asyncio
import time

from core.config import ChakravyuhConfig
from core.crawlers import CrawlerClaim
from core.identity import session_key
from main import create_app


class _Verifier:
    def __init__(self, verified: bool = False) -> None:
        self.verified = verified

    async def verify(self, ip: str, user_agent: str) -> CrawlerClaim:
        if self.verified and "Googlebot" in user_agent:
            return CrawlerClaim("google", True, True, "verified")
        if "Googlebot" in user_agent:
            return CrawlerClaim("google", False, True, "rdns mismatch")
        return CrawlerClaim("", False, False, "no crawler user-agent")


def _config(**overrides) -> ChakravyuhConfig:
    base = dict(
        tarpit_response_seconds=0.28,
        chunk_interval=(0.05, 0.05),
        chunk_size=(8, 16),
        preamble_bytes=512,
        session_tarpit_cap_seconds=300,
        max_concurrent_tarpits=500,
        expose_console_link=False,
    )
    base.update(overrides)
    return ChakravyuhConfig(**base)


def _scope(path="/", method="GET", headers=None, client=("203.0.113.10", 41000), raw_headers=None):
    pairs = []
    for key, value in (headers or {}).items():
        pairs.append((key.lower().encode("latin-1"), value.encode("utf-8")))
    if raw_headers:
        pairs.extend(raw_headers)
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii", errors="replace"),
        "query_string": b"",
        "headers": pairs,
        "client": client,
        "server": ("test", 80),
    }


async def _invoke(app, scope, disconnect_after=None):
    sent = []

    async def receive():
        if disconnect_after is not None:
            await asyncio.sleep(disconnect_after)
        else:
            await asyncio.sleep(30)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _bodies(sent):
    return [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]


def _status(sent):
    for message in sent:
        if message["type"] == "http.response.start":
            return message["status"], {k.decode().lower(): v.decode("latin-1", errors="replace") for k, v in message.get("headers", [])}
    return None, {}


def _seed(app, ip, headers):
    cfg = app.state.config
    key, method = session_key(ip, {k.lower(): v for k, v in headers.items()}, cfg)
    session = app.state.store.get_or_create(
        key, ip, now_wall=time.time(), identity_method=method, ip_source="peer"
    )
    session.not_found_count = 20
    session.total_requests = 20
    now = time.monotonic()
    session.timestamps.clear()
    session.timestamps.extend([now] * 150)
    return session


BROWSER = {
    "user-agent": "Mozilla/5.0",
    "accept": "text/html",
    "accept-language": "en-IN",
}


def test_phase_two_slices_never_leave_a_short_tail():
    import random

    from core.profiles import iter_stream_chunks

    payload = b"x" * 4000
    for seed in range(200):
        chunks = iter_stream_chunks(payload, 512, (8, 16), random.Random(seed))
        assert len(chunks[0]) == 512
        assert chunks[0] == payload[:512]
        assert all(8 <= len(chunk) <= 16 for chunk in chunks[1:])
        assert b"".join(chunks) == payload


def test_browser_reaches_the_origin_with_the_real_stack():
    app = create_app(_config(), crawlers=_Verifier())

    async def run():
        sent = await _invoke(app, _scope("/", headers=BROWSER))
        status, headers = _status(sent)
        body = b"".join(_bodies(sent))
        assert status == 200
        assert headers.get("server") == "uvicorn"
        assert b"Meridian Ledger" in body
        assert b"CHAKRAVYUH" not in body
        assert b"chakravyuh" not in body.lower()

    asyncio.run(run())


def test_seeded_scanner_is_distorted_without_chunk_framing():
    app = create_app(_config(), crawlers=_Verifier())
    _seed(app, "203.0.113.10", BROWSER)

    async def run():
        started = time.perf_counter()
        sent = await _invoke(app, _scope("/.env", headers=BROWSER))
        elapsed = time.perf_counter() - started
        status, headers = _status(sent)
        bodies = [b for b in _bodies(sent) if b]
        blob = b"".join(bodies)
        assert status == 200
        assert headers.get("server") in {
            "Microsoft-IIS/10.0",
            "nginx/1.18.0 (Ubuntu)",
            "Apache-Coyote/1.1",
        }
        assert "uvicorn" not in headers.get("server", "")
        assert blob.lower().startswith(b"<!doctype html>") or blob.lower().startswith(b"<html")
        assert b"chakravyuh" not in blob.lower()
        assert b"tarpit" not in blob.lower()
        assert b"honeypot" not in blob.lower()
        # The server frames chunks. A hand-rolled size prefix would show up here.
        assert not bodies[0].startswith(tuple(f"{n:x}\r\n".encode() for n in range(1, 32)))
        assert bodies[0].lower().startswith((b"<!doctype", b"<html"))
        assert len(bodies[0]) == 512
        assert sent[-1]["type"] == "http.response.body"
        assert sent[-1].get("more_body") is False
        phase2 = [chunk for chunk in bodies[1:] if chunk and not chunk.lower().startswith(b"</body")]
        assert phase2, "phase 2 did not stream"
        assert all(8 <= len(chunk) <= 16 for chunk in phase2)
        assert elapsed >= 0.18
        # Commitment is not delayed by the phase-2 interval: first body is message 2
        # and the handler returned only after the hold, so elapsed covers the hold.
        cookie = headers.get("set-cookie", "")
        if headers["server"].startswith("Microsoft-IIS"):
            assert "ASP.NET_SessionId=" in cookie
        elif headers["server"].startswith("nginx"):
            assert "PHPSESSID=" in cookie
        else:
            assert "JSESSIONID=" in cookie

    asyncio.run(run())


def test_malformed_header_does_not_crash():
    app = create_app(_config(), crawlers=_Verifier())

    async def run():
        scope = _scope("/about", headers=BROWSER, raw_headers=[(b"x-scanner", b"\xff\xfe\xfa")])
        sent = await _invoke(app, scope)
        status, headers = _status(sent)
        assert status == 200
        assert headers.get("server") == "uvicorn"

    asyncio.run(run())


def test_spoofed_xff_does_not_split_sessions():
    app = create_app(_config(), crawlers=_Verifier())

    async def run():
        peer = ("198.51.100.20", 41001)
        await _invoke(app, _scope("/.env", headers={**BROWSER, "x-forwarded-for": "8.8.8.8"}, client=peer))
        await _invoke(app, _scope("/.git/config", headers={**BROWSER, "x-forwarded-for": "1.1.1.1"}, client=peer))
        assert len(app.state.store) == 1
        session = app.state.store.values()[0]
        assert session.ip == "198.51.100.20"
        assert session.raw_requests == 2

    asyncio.run(run())


def test_trusted_proxy_uses_xff():
    from core.config import parse_trusted_networks

    cfg = _config(trusted_proxies=parse_trusted_networks("10.0.0.8"))
    app = create_app(cfg, crawlers=_Verifier())

    async def run():
        await _invoke(
            app,
            _scope(
                "/",
                headers={**BROWSER, "x-forwarded-for": "203.0.113.50"},
                client=("10.0.0.8", 443),
            ),
        )
        session = app.state.store.values()[0]
        assert session.ip == "203.0.113.50"
        assert session.ip_source == "xff"

    asyncio.run(run())


def test_verified_crawler_offset_keeps_a_hot_session_under_the_gate():
    app = create_app(_config(), crawlers=_Verifier(verified=True))
    headers = {
        "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "accept": "text/html",
        "accept-language": "en",
    }
    _seed(app, "66.249.66.1", headers)

    async def run():
        sent = await _invoke(app, _scope("/.env", headers=headers, client=("66.249.66.1", 80)))
        status, headers_out = _status(sent)
        assert status == 404
        assert headers_out.get("server") == "uvicorn"

    asyncio.run(run())


def test_unverified_googlebot_is_not_credited():
    app = create_app(_config(), crawlers=_Verifier(verified=False))
    headers = {
        "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
        "accept": "text/html",
        "accept-language": "en",
    }
    _seed(app, "203.0.113.77", headers)

    async def run():
        sent = await _invoke(app, _scope("/.env", headers=headers, client=("203.0.113.77", 80)))
        status, headers_out = _status(sent)
        assert status == 200
        assert headers_out.get("server") != "uvicorn"

    asyncio.run(run())


def test_concurrency_cap_sheds_without_calling_the_origin():
    app = create_app(_config(max_concurrent_tarpits=1, tarpit_response_seconds=2.0), crawlers=_Verifier())
    headers_a = dict(BROWSER)
    headers_b = {**BROWSER, "user-agent": "Mozilla/5.0 Other"}
    _seed(app, "203.0.113.10", headers_a)
    _seed(app, "203.0.113.11", headers_b)
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def run():
        async def receive():
            await asyncio.sleep(5)
            return {"type": "http.disconnect"}

        async def send_hold(message):
            if message["type"] == "http.response.body" and message.get("body"):
                entered.set()
                await gate.wait()

        first = asyncio.create_task(
            app(
                _scope("/.env", headers=headers_a, client=("203.0.113.10", 1)),
                receive,
                send_hold,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        second_sent = await _invoke(
            app, _scope("/admin", headers=headers_b, client=("203.0.113.11", 2))
        )
        status, headers = _status(second_sent)
        assert status == 429
        assert headers.get("server") != "uvicorn"
        assert b"Meridian" not in b"".join(_bodies(second_sent))
        gate.set()
        await first

    asyncio.run(run())


def test_disconnect_during_tarpit_does_not_raise():
    app = create_app(_config(tarpit_response_seconds=2.0), crawlers=_Verifier())
    _seed(app, "203.0.113.10", BROWSER)

    async def run():
        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        await app(_scope("/.env", headers=BROWSER), receive, send)
        assert any(m["type"] == "http.response.start" for m in sent)

    asyncio.run(run())


def test_planning_fault_fails_open_once():
    async def explode(scope):
        raise RuntimeError("planner")

    app = create_app(_config(), crawlers=_Verifier(), plan_hook=explode)

    async def run():
        sent = await _invoke(app, _scope("/about", headers=BROWSER))
        body = b"".join(_bodies(sent))
        assert body.count(b"<!DOCTYPE html>") == 1
        assert b"Meridian Ledger" in body
        assert app.state.metrics.total_fail_open == 1

    asyncio.run(asyncio.wait_for(run(), timeout=3))


def test_instrumentation_is_exempt_and_homepage_does_not_advertise_it():
    app = create_app(_config(expose_console_link=False), crawlers=_Verifier())

    async def run():
        home = await _invoke(app, _scope("/", headers=BROWSER))
        assert b"chakravyuh" not in b"".join(_bodies(home)).lower()
        for path in ("/metrics", "/chakravyuh-dashboard", "/chakravyuh-dashboard/api/snapshot"):
            await _invoke(app, _scope(path, headers=BROWSER))
        assert app.state.metrics.exempt_requests == 3
        assert app.state.metrics.total_requests == 1
        page = await _invoke(app, _scope("/chakravyuh-dashboard", headers=BROWSER))
        status, headers = _status(page)
        body = b"".join(_bodies(page))
        assert status == 200
        assert headers.get("content-type", "").startswith("text/html")
        assert b"<canvas" not in body.lower()
        assert b"keyframes" not in body
        assert b"requestAnimationFrame" not in body
        assert b"WebSocket" not in body
        assert b"Palatino" not in body
        assert b"No sessions." in body
        assert b"No decisions.</td>" in body
        assert b"last hour" not in body
        assert b"/chakravyuh-dashboard/api/snapshot" in body

    asyncio.run(run())


def test_slowdown_does_not_reopen_the_gate():
    """Tarpitting suppresses R̂. The hold must survive that, or the next
    request is served by the origin and the real stack leaks."""
    app = create_app(_config(), crawlers=_Verifier())
    _seed(app, "203.0.113.10", BROWSER)

    async def run():
        first = await _invoke(app, _scope("/.env", headers=BROWSER))
        status, headers = _status(first)
        assert status == 200
        assert headers.get("server") != "uvicorn"
        session = app.state.store.values()[0]
        assert session.hostile
        session.timestamps.clear()
        second = await _invoke(app, _scope("/admin", headers=BROWSER))
        status, headers = _status(second)
        body = b"".join(_bodies(second))
        assert headers.get("server") != "uvicorn"
        assert b"Meridian" not in body
        assert status == 200

    asyncio.run(run())


def test_clean_traffic_can_leave_the_release_band():
    app = create_app(_config(), crawlers=_Verifier())
    session = _seed(app, "203.0.113.10", BROWSER)
    session.hostile = True
    session.not_found_count = 0
    session.total_requests = 8
    session.timestamps.clear()

    async def run():
        sent = await _invoke(app, _scope("/", headers=BROWSER))
        status, headers = _status(sent)
        assert status == 200
        assert headers.get("server") == "uvicorn"
        assert app.state.store.values()[0].hostile is False

    asyncio.run(run())


def test_verified_crawler_is_not_held_by_the_release_band():
    app = create_app(_config(), crawlers=_Verifier(verified=True))
    headers = {
        "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
        "accept": "text/html",
        "accept-language": "en",
    }
    session = _seed(app, "66.249.66.1", headers)
    session.hostile = True

    async def run():
        sent = await _invoke(
            app, _scope("/.env", headers=headers, client=("66.249.66.1", 80))
        )
        _status_code, headers_out = _status(sent)
        assert headers_out.get("server") == "uvicorn"
        assert app.state.store.values()[0].hostile is False

    asyncio.run(run())


def test_session_budget_closes_fast_without_the_origin():
    app = create_app(_config(session_tarpit_cap_seconds=10), crawlers=_Verifier())
    session = _seed(app, "203.0.113.10", BROWSER)
    session.tarpit_seconds = 10

    async def run():
        started = time.perf_counter()
        sent = await _invoke(app, _scope("/.env", headers=BROWSER))
        elapsed = time.perf_counter() - started
        status, headers = _status(sent)
        body = b"".join(_bodies(sent))
        assert status == 200
        assert headers.get("server") != "uvicorn"
        assert b"Meridian" not in body
        assert elapsed < 0.4

    asyncio.run(run())
