"""Runtime configuration.

Weights and the 0.70 threshold are a priori design choices from the project
digest, not values fitted to a test set. Override them only to measure the
trade-off, and record that you did.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_trusted_networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse a comma-separated list of IPs or CIDRs. Empty means trust nobody."""
    networks = []
    for part in _csv(raw):
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError as exc:
            raise ValueError(f"invalid trusted proxy entry {part!r}") from exc
    return tuple(networks)


@dataclass(frozen=True)
class ChakravyuhConfig:
    """All knobs for the middleware. Frozen so a running process cannot drift."""

    threshold: float = 0.70
    # Once S has crossed the gate, keep distorting until S falls below this.
    # Tarpitting suppresses the rate term that closed the gate. Without a
    # release band the next request, now slow, would be handed to the origin
    # and the real stack would leak. This is gate policy, not a new formula.
    release_threshold: float = 0.30
    w_rate: float = 0.35
    w_diversity: float = 0.35
    w_headers: float = 0.20
    w_crawler: float = 0.10
    rate_cap_rps: float = 20.0
    window_seconds: float = 5.0
    decay: float = 0.9

    session_ttl_seconds: float = 300.0
    max_sessions: int = 10_000
    max_timestamps: int = 256

    max_concurrent_tarpits: int = 500
    tarpit_response_seconds: float = 30.0
    session_tarpit_cap_seconds: float = 300.0
    chunk_interval: tuple[float, float] = (2.0, 2.5)
    chunk_size: tuple[int, int] = (8, 16)
    preamble_bytes: int = 512
    # Spec pipeline: distorted responses are HTTP 200 with a slow HTML body.
    # Set to 404 only when measuring error-page fingerprinting.
    distort_status: int = 200

    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    # Cookie-primary identity is opt-in. It is trivially reset by rotating the
    # cookie, so the default key is hash(IP + User-Agent + Accept-Language).
    trust_session_cookie: bool = False
    session_cookie_name: str = "session"

    # /metrics is reserved. startswith() also covers the snapshot under the
    # dashboard prefix. Do not put an application route on either.
    exempt_prefixes: tuple[str, ...] = ("/chakravyuh-dashboard", "/metrics")
    known_paths: tuple[str, ...] = (
        "/",
        "/login",
        "/about",
        "/api/health",
        "/api/users",
        "/robots.txt",
        "/favicon.ico",
        "/healthz",
        "/docs",
        "/redoc",
        "/openapi.json",
    )
    known_prefixes: tuple[str, ...] = ()

    dashboard_token: str = ""
    expose_console_link: bool = False
    real_server_header: str = "uvicorn"
    crawler_dns_timeout: float = 1.2
    crawler_cache_ttl: float = 600.0
    max_concurrent_dns: int = 8
    # Off means a Googlebot User-Agent never triggers an outbound lookup.
    # Fail closed: C stays 0. See the DNS amplification note in the README.
    crawler_dns_enabled: bool = True
    enabled: bool = True

    def __post_init__(self) -> None:
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        if not 0.0 <= self.release_threshold < self.threshold:
            raise ValueError("release_threshold must be in [0, threshold)")
        if self.rate_cap_rps <= 0:
            raise ValueError("rate_cap_rps must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not 0.0 < self.decay < 1.0:
            raise ValueError("decay must be in (0, 1)")
        if self.max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        if self.max_concurrent_tarpits < 1:
            raise ValueError("max_concurrent_tarpits must be >= 1")
        if self.tarpit_response_seconds <= 0:
            raise ValueError("tarpit_response_seconds must be positive")
        if self.session_tarpit_cap_seconds <= 0:
            raise ValueError("session_tarpit_cap_seconds must be positive")
        lo, hi = self.chunk_interval
        if lo <= 0 or hi < lo:
            raise ValueError("chunk_interval must be positive and ordered")
        clo, chi = self.chunk_size
        if clo < 1 or chi < clo:
            raise ValueError("chunk_size must be positive and ordered")
        if self.preamble_bytes < 64:
            raise ValueError("preamble_bytes must be >= 64")
        if self.distort_status not in (200, 404):
            raise ValueError("distort_status must be 200 or 404")
        if any(ord(ch) > 127 for ch in self.real_server_header):
            raise ValueError("real_server_header must be latin-1")

    @classmethod
    def from_env(cls) -> ChakravyuhConfig:
        interval = _env("CHAKRAVYUH_CHUNK_INTERVAL", "2.0,2.5")
        parts = [p.strip() for p in interval.split(",") if p.strip()]
        if len(parts) != 2:
            raise ValueError("CHAKRAVYUH_CHUNK_INTERVAL must be 'min,max'")
        sizes = _env("CHAKRAVYUH_CHUNK_SIZE", "8,16")
        sp = [p.strip() for p in sizes.split(",") if p.strip()]
        if len(sp) != 2:
            raise ValueError("CHAKRAVYUH_CHUNK_SIZE must be 'min,max'")
        return cls(
            threshold=float(_env("CHAKRAVYUH_THRESHOLD", "0.70")),
            release_threshold=float(_env("CHAKRAVYUH_RELEASE_THRESHOLD", "0.30")),
            session_ttl_seconds=float(_env("CHAKRAVYUH_SESSION_TTL", "300")),
            max_sessions=int(_env("CHAKRAVYUH_MAX_SESSIONS", "10000")),
            max_concurrent_tarpits=int(_env("CHAKRAVYUH_MAX_TARPITS", "500")),
            tarpit_response_seconds=float(_env("CHAKRAVYUH_TARPIT_SECONDS", "30")),
            session_tarpit_cap_seconds=float(_env("CHAKRAVYUH_SESSION_TARPIT_CAP", "300")),
            chunk_interval=(float(parts[0]), float(parts[1])),
            chunk_size=(int(sp[0]), int(sp[1])),
            distort_status=int(_env("CHAKRAVYUH_DISTORT_STATUS", "200")),
            trusted_proxies=parse_trusted_networks(_env("CHAKRAVYUH_TRUSTED_PROXIES", "")),
            trust_session_cookie=_env("CHAKRAVYUH_TRUST_SESSION_COOKIE", "0") in {"1", "true", "yes"},
            session_cookie_name=_env("CHAKRAVYUH_SESSION_COOKIE", "session"),
            dashboard_token=_env("CHAKRAVYUH_DASHBOARD_TOKEN", ""),
            expose_console_link=_env("CHAKRAVYUH_EXPOSE_CONSOLE_LINK", "0") in {"1", "true", "yes"},
            real_server_header=_env("CHAKRAVYUH_REAL_SERVER", "uvicorn"),
            crawler_dns_enabled=_env("CHAKRAVYUH_CRAWLER_DNS_ENABLED", "1") not in {"0", "false", "no"},
            enabled=_env("CHAKRAVYUH_ENABLED", "1") not in {"0", "false", "no"},
        )
