#!/usr/bin/env python3
"""Follow-up arms the first study left ambiguous.

Headless Chromium omitted Accept-Language. These arms set it, and they
send a Nikto-shaped request with both headers actually absent. Scores
still come from the live gate.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from fp_study import BASE, OUT, _ip, record

PROBES = ["/.env", "/admin", "/backup", "/wp-login.php", "/config.php", "/.git/config"]


def curl_nikto(ip: str, path: str) -> str:
    cmd = [
        "curl",
        "-sS",
        "-D",
        "-",
        "-o",
        "/dev/null",
        "--max-time",
        "1.2",
        "-A",
        "Nikto/2.5.0",
        "-H",
        "Accept:",
        "-H",
        "Accept-Language:",
        "-H",
        f"X-Forwarded-For: {ip}",
        BASE + path,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    status = "timeout" if completed.returncode == 28 else "error"
    for line in (completed.stdout or "").splitlines():
        if line.startswith("HTTP/"):
            status = line.split()[1]
            break
    return status


def main() -> None:
    points: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        n = 40
        for i in range(4):
            ip = _ip("198.51.100", n)
            n += 1
            context = browser.new_context(
                extra_http_headers={
                    "X-Forwarded-For": ip,
                    "Accept-Language": "en-IN,en;q=0.9",
                }
            )
            page = context.new_page()
            for step, path in enumerate(["/", "/about", "/login", "/api/health", "/robots.txt", "/healthz"]):
                try:
                    response = page.goto(BASE + path, wait_until="domcontentloaded", timeout=8000)
                    status = str(response.status) if response else "no-response"
                except Exception as exc:
                    status = type(exc).__name__
                record(points, "chrome_with_language", i, ip, step, path, status)
                time.sleep(1.2)
            context.close()
        for i in range(4):
            ip = _ip("198.51.100", n)
            n += 1
            context = browser.new_context(
                extra_http_headers={
                    "X-Forwarded-For": ip,
                    "Accept-Language": "en-IN,en;q=0.9",
                }
            )
            page = context.new_page()
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=8000)
            record(points, "chrome_lang_burst_100", i, ip, 0, "/", "200")
            summary = page.evaluate(
                """async () => {
                    const paths = Array.from({length: 100}, (_, k) => "/assets/locale." + k + ".js");
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
                    for (const item of results) tally[String(item)] = (tally[String(item)] || 0) + 1;
                    return tally;
                }"""
            )
            record(points, "chrome_lang_burst_100", i, ip, 1, "/100-parallel-misses", json.dumps(summary))
            context.close()
        browser.close()

    n = 160
    for i in range(6):
        ip = _ip("203.0.113", n)
        n += 1
        for step in range(70):
            path = PROBES[step % len(PROBES)] + f"?z={step}"
            status = curl_nikto(ip, path)
            record(points, "nikto_headers", i, ip, step, path, status)

    dest = OUT / "fp_points_extra.json"
    dest.write_text(json.dumps({"points": points}, indent=2))
    print(f"wrote {len(points)} points")
    # print a compact summary
    from collections import defaultdict
    import statistics
    by = defaultdict(list)
    for p in points:
        by[p["persona"]].append(p)
    for name, rows in by.items():
        last = {}
        for p in rows:
            last[p["session"]] = p
        fin = list(last.values())
        scores = [p["score"] for p in fin]
        print(name, "final", [round(s, 4) for s in scores], "explain", fin[-1].get("explain"), "missing", fin[-1].get("missing"), "status", fin[-1].get("client_status"))


if __name__ == "__main__":
    main()
