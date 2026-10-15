#!/usr/bin/env python3
"""Local scanner timings. Prints JSON. Does not invent a slowdown.

Each protected gobuster run gets a fresh process so the 300s session
cannot leak from one run into the next. Bare runs share one process with
the gate disabled. Nikto and h2load are single shots, not 10-run sets.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDLIST = Path(__file__).resolve().parent / "bench_wordlist.txt"
NIKTO = Path("/tmp/nikto-2.5.0/program/nikto.pl")
OUT = ROOT / "bench_runs"


def _wait_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"port {port} did not open")


def _start(port: int, extra: dict[str, str], log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    env.pop("CHAKRAVYUH_TRUSTED_PROXIES", None)
    env.pop("CHAKRAVYUH_EXPOSE_CONSOLE_LINK", None)
    env.update(extra)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w")
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=ROOT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    proc._log = handle  # type: ignore[attr-defined]
    try:
        _wait_port(port)
    except Exception:
        _stop(proc)
        raise
    return proc


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    handle = getattr(proc, "_log", None)
    if handle is not None:
        handle.close()


def _status_counts(log_path: Path) -> dict:
    text = log_path.read_text(errors="replace") if log_path.exists() else ""
    return {
        "http_200": text.count('HTTP/1.1" 200'),
        "http_404": text.count('HTTP/1.1" 404'),
        "http_429": text.count('HTTP/1.1" 429'),
        "threshold_crossed": text.count("threshold crossed"),
    }


def _summarize(samples: list[dict]) -> dict:
    times = [row["seconds"] for row in samples]
    return {
        "n": len(samples),
        "seconds_mean": statistics.fmean(times) if times else None,
        "seconds_stdev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "seconds_min": min(times) if times else None,
        "seconds_max": max(times) if times else None,
        "runs": samples,
    }


def _gobuster(url: str, timeout: str, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "gobuster",
        "dir",
        "-u",
        url,
        "-w",
        str(WORDLIST),
        "-t",
        "10",
        "--timeout",
        timeout,
        "-q",
        "--no-color",
        "--no-progress",
        "-o",
        str(dest),
    ]
    started = time.perf_counter()
    completed = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - started
    text = dest.read_text() if dest.exists() else ""
    hits = [line for line in text.splitlines() if line.strip()]
    err = completed.stderr or ""
    (dest.with_suffix(".stderr")).write_text(err)
    return {
        "seconds": round(elapsed, 3),
        "returncode": completed.returncode,
        "hits": len(hits),
        "hit_lines": hits,
        "timeout_mentions": err.lower().count("timeout"),
        "stderr_lines": len([line for line in err.splitlines() if line.strip()]),
        "stderr_head": "\n".join(err.splitlines()[:8]),
    }


def _nikto(url: str, dest: Path, extra: list[str], proc_timeout: float) -> dict:
    if not NIKTO.exists():
        return {"error": f"nikto not at {NIKTO}"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "perl",
        str(NIKTO),
        "-nointeractive",
        "-ask",
        "no",
        "-nolookup",
        "-host",
        url,
        "-output",
        str(dest),
        "-Format",
        "txt",
        *extra,
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=proc_timeout)
    except subprocess.TimeoutExpired as exc:
        return {
            "seconds": round(time.perf_counter() - started, 3),
            "returncode": None,
            "command": cmd,
            "error": f"process killed after {proc_timeout}s",
            "stdout_tail": exc.stdout if isinstance(exc.stdout, str) else "",
            "signature_lines": [],
        }
    elapsed = time.perf_counter() - started
    text = dest.read_text(errors="replace") if dest.exists() else completed.stdout
    (dest.with_suffix(".stderr")).write_text(completed.stderr or "")
    interesting = [
        line
        for line in text.splitlines()
        if "Server" in line or "server" in line or "Target" in line or "0 host" in line or "host(s)" in line
    ]
    return {
        "seconds": round(elapsed, 3),
        "returncode": completed.returncode,
        "command": cmd,
        "signature_lines": interesting[:30],
        "stdout_tail": "\n".join((completed.stdout or "").splitlines()[-15:]),
        "stderr_tail": "\n".join((completed.stderr or "").splitlines()[-10:]),
    }


def _h2load(url: str, extra: list[str] | None = None) -> dict:
    # This h2load has no --h2c flag. Cleartext HTTP defaults to h2c.
    # Pass ["-p", "http/1.1"] for an HTTP/1.1 control. That is not an HTTP/2 result.
    cmd = ["h2load", "-n", "1", "-c", "1", *(extra or []), url]
    started = time.perf_counter()
    completed = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "seconds": round(time.perf_counter() - started, 3),
        "returncode": completed.returncode,
        "command": cmd,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--skip-nikto", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    words = [line for line in WORDLIST.read_text().splitlines() if line.strip()]
    report: dict = {
        "wordlist": str(WORDLIST),
        "wordlist_entries": len(words),
        "gobuster": "3.6",
        "threads": 10,
        "note": "Protected runs restart the listener. Trusted proxies empty. Peer is 127.0.0.1.",
    }

    bare = _start(8001, {"CHAKRAVYUH_ENABLED": "0"}, OUT / "bare_server.log")
    bare_rows = []
    try:
        for i in range(args.runs):
            bare_rows.append(_gobuster("http://127.0.0.1:8001", "10s", OUT / f"bare_{i:02d}.txt"))
            print(f"bare {i} {bare_rows[-1]['seconds']}s hits={bare_rows[-1]['hits']}", flush=True)
    finally:
        _stop(bare)
    report["gobuster_bare_timeout_10s"] = _summarize(bare_rows)

    protected_rows = []
    for i in range(args.runs):
        proc = _start(8000, {}, OUT / f"protected_server_{i:02d}.log")
        log_path = OUT / f"protected_server_{i:02d}.log"
        try:
            row = _gobuster("http://127.0.0.1:8000", "10s", OUT / f"protected_{i:02d}.txt")
        finally:
            _stop(proc)
        row["listener"] = _status_counts(log_path)
        protected_rows.append(row)
        print(f"protected {i} {row['seconds']}s hits={row['hits']} timeouts={row['timeout_mentions']}", flush=True)
    report["gobuster_protected_timeout_10s"] = _summarize(protected_rows)

    short_rows = []
    for i in range(args.runs):
        proc = _start(8000, {}, OUT / f"short_server_{i:02d}.log")
        log_path = OUT / f"short_server_{i:02d}.log"
        try:
            row = _gobuster("http://127.0.0.1:8000", "2s", OUT / f"short_{i:02d}.txt")
        finally:
            _stop(proc)
        row["listener"] = _status_counts(log_path)
        short_rows.append(row)
        print(f"timeout2s {i} {row['seconds']}s hits={row['hits']} timeouts={row['timeout_mentions']}", flush=True)
    report["gobuster_protected_timeout_2s"] = _summarize(short_rows)
    (OUT / "summary.json").write_text(json.dumps(report, indent=2))

    proc = _start(8000, {}, OUT / "nikto_protected_server.log")
    bare = _start(8001, {"CHAKRAVYUH_ENABLED": "0"}, OUT / "nikto_bare_server.log")
    try:
        report["h2load_h2c"] = _h2load("http://127.0.0.1:8000/")
        report["h2load_http1"] = _h2load("http://127.0.0.1:8000/", ["-p", "http/1.1"])
        print("h2load", report["h2load_h2c"]["returncode"], flush=True)
        if not args.skip_nikto:
            report["nikto_bare_tuning_b"] = _nikto(
                "http://127.0.0.1:8001",
                OUT / "nikto_bare_b.txt",
                ["-Tuning", "b", "-timeout", "10", "-maxtime", "90s"],
                120,
            )
            print("nikto bare", report["nikto_bare_tuning_b"]["seconds"], flush=True)
            report["nikto_protected_tuning_b"] = _nikto(
                "http://127.0.0.1:8000",
                OUT / "nikto_protected_b.txt",
                ["-Tuning", "b", "-timeout", "10", "-maxtime", "90s"],
                120,
            )
            print("nikto protected b", report["nikto_protected_tuning_b"]["seconds"], flush=True)
            report["nikto_protected_default_capped"] = _nikto(
                "http://127.0.0.1:8000",
                OUT / "nikto_protected_default.txt",
                ["-timeout", "10", "-maxtime", "45s"],
                70,
            )
            print("nikto protected default", report["nikto_protected_default_capped"]["seconds"], flush=True)
    finally:
        _stop(proc)
        _stop(bare)

    dest = OUT / "summary.json"
    dest.write_text(json.dumps(report, indent=2))
    print(dest)


if __name__ == "__main__":
    main()
