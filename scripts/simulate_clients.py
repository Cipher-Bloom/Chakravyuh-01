#!/usr/bin/env python3
"""Local traffic for the operator console.

Hits this process's own listener only. Uses the documentation addresses
from RFC 5737 so the console never displays a real person's address.

The listener must trust the peer that runs this script (typically
127.0.0.1) or every client collapses into one session. That trust is a
demo setting. Leave CHAKRAVYUH_TRUSTED_PROXIES empty in production unless
the peer really is your TLS terminator.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys

import httpx

PROBES = (
    "/.env",
    "/admin",
    "/backup",
    "/wp-login.php",
    "/config.php",
    "/.git/config",
    "/server-status",
    "/phpmyadmin",
    "/actuator/health",
    "/console",
    "/.aws/credentials",
    "/id_rsa",
)
PAGES = ("/", "/about", "/login", "/api/health", "/api/users")


async def _get(client: httpx.AsyncClient, ip: str, path: str, headers: dict[str, str], timeout: float) -> None:
    try:
        await client.get(path, headers={**headers, "x-forwarded-for": ip}, timeout=timeout)
    except (httpx.TimeoutException, httpx.TransportError):
        return


async def main() -> None:
    parser = argparse.ArgumentParser(description="Drive local demo traffic at CHAKRAVYUH")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--loops", type=int, default=0, help="0 means until interrupted")
    args = parser.parse_args()
    browser = {
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml",
        "accept-language": "en-IN,en;q=0.9",
    }
    firefox = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
        "accept": "text/html",
        "accept-language": "hi-IN,en;q=0.8",
    }
    # Missing Accept and Accept-Language. That, plus a fast 404 burst, is what
    # crosses 0.70. A full browser header set at this pace does not.
    nikto = {"user-agent": "Nikto/2.5.0"}
    gobuster = {"user-agent": "gobuster/3.6"}

    async with httpx.AsyncClient(base_url=args.base, follow_redirects=True) as client:

        async def hold() -> None:
            while True:
                await _get(client, "203.0.113.10", "/.env", nikto, 18)

        async def bursts() -> None:
            loops = 0
            while True:
                await asyncio.gather(
                    _get(client, "198.51.100.20", random.choice(PAGES), browser, 4),
                    _get(client, "198.51.100.21", random.choice(PAGES), firefox, 4),
                    *[
                        _get(client, "203.0.113.10", random.choice(PROBES), nikto, 1.2)
                        for _ in range(90)
                    ],
                    *[
                        _get(client, "203.0.113.11", random.choice(PROBES), gobuster, 1.2)
                        for _ in range(110)
                    ],
                )
                loops += 1
                print(f"wave {loops} complete", file=sys.stderr)
                if args.loops and loops >= args.loops:
                    return
                await asyncio.sleep(8)

        holder = asyncio.create_task(hold())
        try:
            await bursts()
        finally:
            holder.cancel()
            try:
                await holder
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
