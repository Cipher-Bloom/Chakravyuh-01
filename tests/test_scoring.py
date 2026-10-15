"""Formula, decay, identity, and crawler-offset tests. No network."""

from __future__ import annotations

import asyncio
import time

from core.config import ChakravyuhConfig
from core.crawlers import CrawlerClaim, CrawlerVerifier, match_family
from core.identity import resolve_client_ip, session_key
from core.profiles import PROFILES, select_profile
from core.scoring import ScoringEngine, SessionStore, combine_score, crossed


def test_formula_matches_the_published_weights():
    cfg = ChakravyuhConfig()
    # A fast, all-miss probe with no crawler credit.
    score = combine_score(cfg, 1.0, 1.0, 1.0, 0.0)
    assert score == combine_score(cfg, 1, 1, 1, 0)
    assert crossed(score, 0.70)
    assert abs(score - (0.35 + 0.35 + 0.20)) < 1e-9

    # Verified crawler at the same extremes is pulled under the gate.
    credited = combine_score(cfg, 1.0, 1.0, 0.0, 1.0)
    assert abs(credited - 0.60) < 1e-9
    assert not crossed(credited, 0.70)

    # The negative term cannot push the score below zero.
    assert combine_score(cfg, 0.0, 0.0, 0.0, 1.0) == 0.0


def test_boundary_is_not_lost_to_float_error():
    cfg = ChakravyuhConfig()
    score = combine_score(cfg, 1.0, 1.0, 0.0, 0.0)
    assert crossed(score, cfg.threshold)
    assert abs(score - 0.70) < 1e-9


def test_decay_and_rate_window():
    cfg = ChakravyuhConfig()
    engine = ScoringEngine(cfg)
    store = SessionStore(cfg)
    now = 1_000.0
    session = store.get_or_create(
        "fp:test", "203.0.113.9", now_wall=now, identity_method="fingerprint", ip_source="peer"
    )
    engine.observe(
        session, now_mono=now, now_wall=now, path="/.env", method="GET", user_agent="x", is_probe=True
    )
    assert session.not_found_count == 1.0
    assert session.total_requests == 1.0
    engine.observe(
        session, now_mono=now + 0.1, now_wall=now, path="/.git", method="GET", user_agent="x", is_probe=True
    )
    assert abs(session.not_found_count - 1.9) < 1e-9
    assert abs(session.total_requests - 1.9) < 1e-9
    engine.observe(
        session, now_mono=now + 0.2, now_wall=now, path="/", method="GET", user_agent="x", is_probe=False
    )
    # 1.9 * 0.9 = 1.71, no probe increment. total = 1.9 * 0.9 + 1 = 2.71
    assert abs(session.not_found_count - 1.71) < 1e-9
    assert abs(session.total_requests - 2.71) < 1e-9

    claim = CrawlerClaim("", False, False, "no crawler user-agent")
    breakdown = engine.score(
        session,
        {"user-agent": "x", "accept": "*/*", "accept-language": "en"},
        claim,
        now + 0.2,
    )
    assert breakdown.h == 0.0
    assert abs(breakdown.requests_per_second - (3 / 5)) < 1e-9
    assert abs(breakdown.r_hat - (3 / 5) / 20) < 1e-9

    # Old timestamps leave the window.
    engine.observe(
        session,
        now_mono=now + 10,
        now_wall=now,
        path="/.env",
        method="GET",
        user_agent="x",
        is_probe=True,
    )
    breakdown = engine.score(session, {"user-agent": "x"}, claim, now + 10)
    assert breakdown.window_count == 1
    assert abs(breakdown.h - (2 / 3)) < 1e-9


def test_status_correction_uses_the_callers_guess():
    cfg = ChakravyuhConfig()
    engine = ScoringEngine(cfg)
    store = SessionStore(cfg)
    session = store.get_or_create(
        "fp:corr", "203.0.113.8", now_wall=1, identity_method="fingerprint", ip_source="peer"
    )
    engine.observe(
        session, now_mono=1, now_wall=1, path="/login", method="GET", user_agent="", is_probe=False
    )
    engine.correct_status(session, guessed_probe=False, actual_not_found=True)
    assert session.not_found_count == 1.0
    engine.correct_status(session, guessed_probe=True, actual_not_found=False)
    assert session.not_found_count == 0.0


def test_xff_is_ignored_unless_the_peer_is_trusted():
    from core.config import parse_trusted_networks

    trusted = parse_trusted_networks("10.0.0.0/8, 127.0.0.1")
    # Untrusted peer, spoofed XFF. The spoof must not become the client.
    ip, source = resolve_client_ip("198.51.100.4", "8.8.8.8", trusted)
    assert ip == "198.51.100.4"
    assert source == "peer"
    # Trusted peer. Walk from the right, skip other trusted hops.
    ip, source = resolve_client_ip("10.0.0.8", "1.1.1.1, 10.1.1.1", trusted)
    assert ip == "1.1.1.1"
    assert source == "xff"
    # Garbage XFF falls back to the peer rather than throwing.
    ip, source = resolve_client_ip("10.0.0.8", "not-an-ip, ???", trusted)
    assert ip == "10.0.0.8"
    # IPv4-mapped peer and bracketed IPv6.
    ip, source = resolve_client_ip("::ffff:10.0.0.8", "[2001:db8::5]", trusted)
    assert ip == "2001:db8::5"


def test_cookie_rotation_does_not_reset_identity_by_default():
    cfg = ChakravyuhConfig()
    headers_a = {"user-agent": "Nikto/2.5.0", "accept-language": "en", "cookie": "session=one"}
    headers_b = {"user-agent": "Nikto/2.5.0", "accept-language": "en", "cookie": "session=two"}
    assert session_key("203.0.113.10", headers_a, cfg)[0] == session_key("203.0.113.10", headers_b, cfg)[0]
    opted = ChakravyuhConfig(trust_session_cookie=True)
    assert session_key("203.0.113.10", headers_a, opted)[0] != session_key("203.0.113.10", headers_b, opted)[0]


def test_profile_is_stable_and_coherent():
    first = select_profile("fp:abc")
    assert select_profile("fp:abc") is first
    assert first in PROFILES
    headers = dict(first.header_pairs("fp:abc"))
    assert headers["server"] == first.server
    assert first.cookie_name in headers["set-cookie"]
    body = first.document("fp:abc", status=200)
    lowered = body.decode("utf-8").lower()
    for banned in ("chakravyuh", "tarpit", "honeypot", "decoy"):
        assert banned not in lowered
    assert lowered.startswith("<!doctype html>") or lowered.startswith("<html")
    error = first.document("fp:abc", status=404)
    assert b"00000000" not in error[:80]


def test_private_crawler_claim_does_not_touch_dns():
    verifier = CrawlerVerifier(timeout=0.2)

    async def run():
        return await verifier.verify("127.0.0.1", "Mozilla/5.0 (compatible; Googlebot/2.1)")

    claim = asyncio.run(run())
    assert match_family("Googlebot/2.1") == "google"
    assert claim.ua_match is True
    assert claim.verified is False
    assert "private" in claim.reason


def test_session_cache_is_bounded():
    cfg = ChakravyuhConfig(max_sessions=10, session_ttl_seconds=60)
    store = SessionStore(cfg)
    now = time.time()
    for i in range(30):
        store.get_or_create(f"ip:{i}", f"203.0.113.{i}", now_wall=now, identity_method="ip", ip_source="peer")
    assert len(store) <= 10
