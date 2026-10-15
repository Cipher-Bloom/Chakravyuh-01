#!/usr/bin/env python3
"""Score-separation study. Records what the live gate computed.

Clients are a real headless Chromium (Playwright), the curl binary, and
HTTP requests with the header shapes named in the output. Documentation
addresses (RFC 5737) are passed in X-Forwarded-For. The listener must
trust 127.0.0.1. Scores are read from the console snapshot after each
request. Nothing in this file retunes the weights.
"""

from __future__ import annotations

import json
import random
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval"
BASE = "http://127.0.0.1:8010"
PAGES = ["/", "/about", "/login", "/api/health", "/api/users", "/robots.txt", "/healthz"]
PROBES = [
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
    "/id_rsa",
    "/.aws/credentials",
]


def _ip(block: str, n: int) -> str:
    # 198.51.100.0/24 and 203.0.113.0/24. Host octet stays in 1–250.
    return f"{block}.{(n % 250) + 1}"


def snapshot() -> dict:
    with urllib.request.urlopen(BASE + "/chakravyuh-dashboard/api/snapshot", timeout=3) as resp:
        return json.loads(resp.read().decode())


def session_for(ip: str) -> dict | None:
    data = snapshot()
    for row in data.get("sessions", []):
        if row.get("ip") == ip:
            return row
    for event in data.get("feed", []):
        if event.get("ip") == ip:
            return {
                "score": event.get("score"),
                "r": event.get("r"),
                "d": event.get("d"),
                "h": event.get("h"),
                "c": event.get("c"),
                "rps": None,
                "classification": event.get("classification"),
                "hostile": event.get("action") not in (None, "pass"),
                "missing": None,
                "ua": event.get("ua"),
                "crawler_family": None,
                "crawler_verified": None,
                "crawler_reason": None,
                "requests": None,
                "distorted": None,
                "ip_source": event.get("ip_source"),
                "explain": event.get("explain"),
                "from_feed": True,
            }
    return None


def _point(persona: str, session_i: int, ip: str, step: int, path: str, row: dict, client_status: str) -> dict:
    return {
        "persona": persona,
        "session": session_i,
        "ip": ip,
        "step": step,
        "path": path,
        "client_status": client_status,
        "score": row.get("score"),
        "r": row.get("r"),
        "d": row.get("d"),
        "h": row.get("h"),
        "c": row.get("c"),
        "rps": row.get("rps"),
        "classification": row.get("classification"),
        "hostile": row.get("hostile"),
        "missing": row.get("missing"),
        "ua": row.get("ua"),
        "crawler_family": row.get("crawler_family"),
        "crawler_verified": row.get("crawler_verified"),
        "crawler_reason": row.get("crawler_reason"),
        "requests": row.get("requests"),
        "distorted": row.get("distorted"),
        "ip_source": row.get("ip_source"),
        "explain": row.get("explain"),
    }


def record(points: list[dict], persona: str, session_i: int, ip: str, step: int, path: str, client_status: str) -> None:
    row = session_for(ip)
    if row is None:
        raise RuntimeError(f"session {ip} missing from snapshot after {persona} {path}")
    points.append(_point(persona, session_i, ip, step, path, row, client_status))


def curl_get(ip: str, path: str, extra: list[str] | None = None, max_time: float = 2.0) -> str:
    cmd = [
        "curl",
        "-sS",
        "-D",
        "-",
        "-o",
        "/dev/null",
        "--max-time",
        str(max_time),
        "-H",
        f"X-Forwarded-For: {ip}",
        *(extra or []),
        BASE + path,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    text = (completed.stdout or "") + (completed.stderr or "")
    status = "timeout" if completed.returncode == 28 else "error"
    for line in (completed.stdout or "").splitlines():
        if line.startswith("HTTP/"):
            status = line.split()[1]
            break
    if completed.returncode not in (0, 28) and status == "error":
        status = f"curl-{completed.returncode}"
    return status


def http_get(client: httpx.Client, ip: str, path: str, headers: dict[str, str], timeout: float) -> str:
    try:
        response = client.get(path, headers={**headers, "x-forwarded-for": ip}, timeout=timeout)
        return str(response.status_code)
    except httpx.TimeoutException:
        return "timeout"
    except httpx.TransportError as exc:
        return type(exc).__name__


def run_http_sequence(points, persona, sessions, prefix, paths, headers, gap, timeout, start_n) -> int:
    n = start_n
    with httpx.Client(base_url=BASE) as client:
        for i in range(sessions):
            ip = _ip(prefix, n)
            n += 1
            for step, path in enumerate(paths):
                status = http_get(client, ip, path, headers, timeout)
                record(points, persona, i, ip, step, path, status)
                if gap:
                    time.sleep(gap)
    return n


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    points: list[dict] = []
    notes: dict = {
        "base": BASE,
        "trusted_proxy": "127.0.0.1",
        "weights_unchanged": "0.35 R, 0.35 D, 0.20 H, 0.10 C",
        "threshold": 0.70,
        "googlebot_headers": {
            "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "omitted",
            "source": "UA is the long-published Googlebot token. Accept-Language is omitted because Google documents that the default crawler does not set it. This is not a verified crawl: the address is documentation space.",
        },
        "nikto_headers": {"user-agent": "Nikto/2.5.0", "accept": "omitted", "accept-language": "omitted"},
    }

    # Chromium first, while the store is empty, so a low score cannot be
    # pushed out of the 18-row snapshot by an earlier scanner.
    from playwright.sync_api import sync_playwright

    rng = random.Random(7)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        n = 0
        for i in range(8):
            ip = _ip("198.51.100", n)
            n += 1
            context = browser.new_context(extra_http_headers={"X-Forwarded-For": ip})
            page = context.new_page()
            for step, path in enumerate(PAGES):
                try:
                    response = page.goto(BASE + path, wait_until="domcontentloaded", timeout=8000)
                    status = str(response.status) if response else "no-response"
                except Exception as exc:
                    status = type(exc).__name__
                record(points, "chrome_human", i, ip, step, path, status)
                time.sleep(rng.uniform(0.9, 2.2))
            context.close()
        notes["chrome_human_sessions"] = 8
        notes["chrome_human_gap_s"] = "uniform 0.9–2.2"

        missing = [f"/static/chunk-{k}.js" for k in range(20)]
        for i in range(8):
            ip = _ip("198.51.100", n)
            n += 1
            context = browser.new_context(extra_http_headers={"X-Forwarded-For": ip})
            page = context.new_page()
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=8000)
            record(points, "chrome_spa_paced", i, ip, 0, "/", "200")
            for step, path in enumerate(missing, start=1):
                status = page.evaluate(
                    """async (path) => {
                        const ctrl = new AbortController();
                        const timer = setTimeout(() => ctrl.abort(), 1500);
                        try {
                            const res = await fetch(path, {signal: ctrl.signal});
                            return String(res.status);
                        } catch (err) {
                            return err.name || "error";
                        } finally {
                            clearTimeout(timer);
                        }
                    }""",
                    path,
                )
                record(points, "chrome_spa_paced", i, ip, step, path, status)
                time.sleep(0.45)
            context.close()
        notes["chrome_spa_paced"] = "home, then 20 missing /static/chunk-N.js at 0.45 s"

        for label, count in (("chrome_spa_burst_24", 24), ("chrome_spa_burst_100", 100)):
            for i in range(6):
                ip = _ip("198.51.100", n)
                n += 1
                context = browser.new_context(extra_http_headers={"X-Forwarded-For": ip})
                page = context.new_page()
                page.goto(BASE + "/", wait_until="domcontentloaded", timeout=8000)
                record(points, label, i, ip, 0, "/", "200")
                summary = page.evaluate(
                    """async (count) => {
                        const paths = Array.from({length: count}, (_, k) => "/assets/app." + k + ".js");
                        const results = await Promise.all(paths.map(async (path) => {
                            const ctrl = new AbortController();
                            const timer = setTimeout(() => ctrl.abort(), 2000);
                            try {
                                const res = await fetch(path, {signal: ctrl.signal});
                                return res.status;
                            } catch (err) {
                                return err.name || "error";
                            } finally {
                                clearTimeout(timer);
                            }
                        }));
                        const tally = {};
                        for (const item of results) {
                            const key = String(item);
                            tally[key] = (tally[key] || 0) + 1;
                        }
                        return tally;
                    }""",
                    count,
                )
                record(points, label, i, ip, 1, f"/{count}-parallel-misses", json.dumps(summary))
                context.close()
            notes[label] = f"6 sessions, home plus {count} parallel missing asset fetches"
        browser.close()

    # curl binary, so the headers are curl's, not a reconstruction.
    n = 0
    for i in range(8):
        ip = _ip("203.0.113", n)
        n += 1
        for step, path in enumerate(["/", "/about", "/healthz"]):
            status = curl_get(ip, path, max_time=3)
            record(points, "curl_browse", i, ip, step, path, status)
            time.sleep(0.4)
    notes["curl_browse"] = "curl binary, no added User-Agent, three existing paths, 0.4 s gap"

    probe_paths = [PROBES[k % len(PROBES)] + f"?n={k}" for k in range(30)]
    for i in range(8):
        ip = _ip("203.0.113", n)
        n += 1
        for step, path in enumerate(probe_paths):
            status = curl_get(ip, path, max_time=1.2)
            record(points, "curl_probe", i, ip, step, path, status)
    notes["curl_probe"] = "curl binary, 30 missing paths, --max-time 1.2, no added delay"

    gbot = {
        "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    n = 80
    run_http_sequence(
        points,
        "googlebot_polite",
        8,
        "203.0.113",
        ["/", "/robots.txt", "/about", "/login", "/healthz"],
        gbot,
        gap=0.8,
        timeout=3,
        start_n=n,
    )
    n += 8
    scan_paths = [PROBES[k % len(PROBES)] + f"?g={k}" for k in range(36)]
    run_http_sequence(
        points,
        "googlebot_scan",
        8,
        "203.0.113",
        scan_paths,
        gbot,
        gap=0.0,
        timeout=1.2,
        start_n=n,
    )
    nikto = {"user-agent": "Nikto/2.5.0"}
    n += 8
    run_http_sequence(
        points,
        "nikto_scan",
        8,
        "203.0.113",
        [PROBES[k % len(PROBES)] + f"?k={k}" for k in range(36)],
        nikto,
        gap=0.0,
        timeout=1.2,
        start_n=n,
    )

    dest = OUT / "fp_points.json"
    dest.write_text(json.dumps({"notes": notes, "points": points}, indent=2))
    print(f"wrote {len(points)} points to {dest}")


if __name__ == "__main__":
    main()
