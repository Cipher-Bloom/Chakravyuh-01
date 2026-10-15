"""Verified-crawler offset.

A User-Agent string is not evidence. C is 1.0 only when the UA matches a
known good crawler *and* reverse DNS plus forward confirmation succeed.
Failures, timeouts, private addresses, and a saturated lookup queue all
fail closed (C = 0). Negative results are cached so a spoofed UA cannot
turn into an unbounded DNS amplifier.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass

from cachetools import TTLCache

logger = logging.getLogger("chakravyuh.crawlers")

# suffix match is anchored on a leading dot to avoid evilgooglebot.com.
CRAWLER_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("google", "googlebot", (".googlebot.com", ".google.com")),
    ("bing", "bingbot", (".search.msn.com",)),
    ("duckduck", "duckduckbot", (".duckduckgo.com",)),
    ("apple", "applebot", (".applebot.apple.com",)),
    ("yandex", "yandexbot", (".yandex.ru", ".yandex.net", ".yandex.com")),
)


@dataclass(frozen=True)
class CrawlerClaim:
    family: str
    verified: bool
    ua_match: bool
    reason: str

    @property
    def offset(self) -> float:
        return 1.0 if self.verified else 0.0


def match_family(user_agent: str) -> str | None:
    ua = user_agent.lower()
    if not ua:
        return None
    for family, needle, _suffixes in CRAWLER_RULES:
        if needle in ua:
            return family
    return None


def suffixes_for(family: str) -> tuple[str, ...]:
    for name, _needle, suffixes in CRAWLER_RULES:
        if name == family:
            return suffixes
    return ()


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def rdns_confirms(ip: str, family: str) -> bool:
    """Blocking reverse-and-forward check. Run it in a worker thread."""
    suffixes = suffixes_for(family)
    if not suffixes or not _is_public(ip):
        return False
    try:
        hostname, _aliases, _addrs = socket.gethostbyaddr(ip)
    except (socket.herror, socket.gaierror, OSError, UnicodeError):
        return False
    host = hostname.strip().rstrip(".").lower()
    if not host or not any(host.endswith(suf) or host == suf[1:] for suf in suffixes):
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError, UnicodeError):
        return False
    confirmed: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            confirmed.add(str(ipaddress.ip_address(sockaddr[0])))
        except ValueError:
            continue
    try:
        wanted = str(ipaddress.ip_address(ip))
    except ValueError:
        return False
    return wanted in confirmed


class CrawlerVerifier:
    def __init__(
        self,
        timeout: float = 1.2,
        cache_ttl: float = 600.0,
        max_concurrent: int = 8,
        enabled: bool = True,
    ) -> None:
        self.timeout = timeout
        self.enabled = enabled
        self._cache: TTLCache[tuple[str, str], bool] = TTLCache(maxsize=4096, ttl=cache_ttl)
        self._sem = asyncio.Semaphore(max_concurrent)

    def claim_sync_negative(self, user_agent: str) -> CrawlerClaim:
        family = match_family(user_agent)
        if family is None:
            return CrawlerClaim("", False, False, "no crawler user-agent")
        return CrawlerClaim(family, False, True, "unverified")

    async def verify(self, ip: str, user_agent: str) -> CrawlerClaim:
        family = match_family(user_agent)
        if family is None:
            return CrawlerClaim("", False, False, "no crawler user-agent")
        if not self.enabled:
            # No outbound query. A spoofed crawler is not credited.
            return CrawlerClaim(family, False, True, "dns disabled")
        if not _is_public(ip):
            return CrawlerClaim(family, False, True, "private address, dns skipped")
        key = (ip, family)
        cached = self._cache.get(key)
        if cached is not None:
            return CrawlerClaim(
                family,
                bool(cached),
                True,
                "verified" if cached else "cached negative",
            )
        if self._sem.locked():
            # Fail closed without queueing. A flood of spoofed UAs must not
            # pile up DNS waits on the event loop.
            return CrawlerClaim(family, False, True, "dns queue saturated")
        async with self._sem:
            cached = self._cache.get(key)
            if cached is not None:
                return CrawlerClaim(family, bool(cached), True, "verified" if cached else "cached negative")
            try:
                ok = await asyncio.wait_for(
                    asyncio.to_thread(rdns_confirms, ip, family),
                    timeout=self.timeout,
                )
            except TimeoutError:
                ok = False
                reason = "dns timeout"
            except Exception:
                logger.debug("crawler verification failed", exc_info=True)
                ok = False
                reason = "dns error"
            else:
                reason = "verified" if ok else "rdns mismatch"
            self._cache[key] = ok
            return CrawlerClaim(family, ok, True, reason)
