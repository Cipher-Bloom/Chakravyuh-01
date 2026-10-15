#!/usr/bin/env python3
"""Small local measurement. Not a substitute for Nikto or Gobuster.

Prints whether a quiet browser sees the real stack, and whether a fast
probe burst is shown a different one and a delayed body. Run it against
a listener you started yourself.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx

PROBES = ["/.env", "/admin", "/backup", "/.git/config", "/wp-login.php", "/server-status"]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    browser = {
        "user-agent": "Mozilla/5.0",
        "accept": "text/html",
        "accept-language": "en-IN",
        "x-forwarded-for": "198.51.100.20",
    }
    scanner = {
        "user-agent": "Nikto/2.5.0",
        "x-forwarded-for": "203.0.113.10",
    }
    # Read timeout must be shorter than the production drip, or each probe
    # keeps the connection for the full 30s hold and burns the 300s session
    # cap before the timed stream starts. Headers come back immediately.
    burst_timeout = httpx.Timeout(connect=2.0, read=0.8, write=2.0, pool=2.0)
    async with httpx.AsyncClient(base_url=args.base, timeout=8) as client:
        home = await client.get("/", headers=browser)
        print(f"browser  status={home.status_code} server={home.headers.get('server')!r} bytes={len(home.content)}")
        started = time.perf_counter()
        burst = await asyncio.gather(
            *[
                client.get(PROBES[i % len(PROBES)], headers=scanner, timeout=burst_timeout)
                for i in range(90)
            ],
            return_exceptions=True,
        )
        codes = {}
        servers = {}
        for item in burst:
            if isinstance(item, Exception):
                codes["timeout"] = codes.get("timeout", 0) + 1
                continue
            codes[item.status_code] = codes.get(item.status_code, 0) + 1
            servers[item.headers.get("server", "")] = servers.get(item.headers.get("server", ""), 0) + 1
        print(f"burst    {time.perf_counter() - started:.2f}s codes={codes}")
        print(f"         servers={servers}")
        # Long read timeout: the production gap is 2–2.5s and must not abort.
        stream_timeout = httpx.Timeout(connect=2.0, read=8.0, write=2.0, pool=2.0)
        t0 = time.perf_counter()
        async with client.stream("GET", "/.env", headers=scanner, timeout=stream_timeout) as resp:
            agen = resp.aiter_bytes()
            arrivals: list[tuple[float, int, bytes]] = []
            try:
                while len(arrivals) < 4:
                    chunk = await asyncio.wait_for(agen.__anext__(), timeout=6)
                    arrivals.append((time.perf_counter() - t0, len(chunk), chunk[:24]))
            except StopAsyncIteration:
                ended = "eof"
            except TimeoutError:
                ended = "timeout"
            else:
                ended = "captured"
        print(f"stream   server={resp.headers.get('server')!r} ended={ended}")
        for index, (at, size, preview) in enumerate(arrivals):
            gap = 0.0 if index == 0 else at - arrivals[index - 1][0]
            print(f"         chunk[{index}] t={at:.3f}s gap={gap:.3f}s bytes={size} head={preview!r}")


if __name__ == "__main__":
    asyncio.run(main())
