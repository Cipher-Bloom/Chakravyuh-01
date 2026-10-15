"""Operator-facing counters. Not part of the suspicion formula.

Everything here is bounded: timestamp deques, a fixed sparkline, and a
ring buffer of recent decisions. Active tarpits are tracked so a scrape
can report duration without reading process tables. Prometheus renders
these fields. It does not keep a second copy of them.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

from core.scoring import ScoreBreakdown, SessionState


def process_rss_bytes() -> int:
    """Resident set size. Linux reports ru_maxrss in kilobytes; macOS in bytes."""
    try:
        import platform
        import resource

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        return 0
    if platform.system() == "Darwin":
        return rss
    return rss * 1024


# Histogram bounds for the score. Cumulative counts are computed at scrape
# time. +Inf is the decisions that did not fall in one of these.
SCORE_BOUNDS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def _num(value: float, places: int = 4) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, places)


@dataclass
class DecisionEvent:
    wall: float
    ip: str
    method: str
    path: str
    score: float
    r_hat: float
    d: float
    h: float
    c: float
    classification: str
    action: str
    profile_id: str
    status: int
    user_agent: str
    explain: str
    ip_source: str
    session_id: str = ""


@dataclass
class ActiveTarpit:
    tarpit_id: int
    session_key: str
    ip: str
    path: str
    profile_id: str
    score: float
    started_wall: float
    started_mono: float


@dataclass
class MetricsCollector:
    started_wall: float = field(default_factory=time.time)
    total_requests: int = 0
    total_passed: int = 0
    total_distorted: int = 0
    total_shed: int = 0
    total_budget_closed: int = 0
    total_fail_open: int = 0
    exempt_requests: int = 0
    bytes_streamed: int = 0
    peak_tarpits: int = 0
    peak_rps: float = 0.0
    score_sum: float = 0.0
    score_count: int = 0
    score_buckets: list[int] = field(default_factory=lambda: [0] * len(SCORE_BOUNDS))
    tarpit_seconds_total: float = 0.0
    _app_times: deque[float] = field(default_factory=deque)
    _buckets: deque[list[int]] = field(default_factory=lambda: deque(maxlen=90))
    feed: deque[DecisionEvent] = field(default_factory=lambda: deque(maxlen=80))
    active: dict[int, ActiveTarpit] = field(default_factory=dict)
    _next_tarpit: int = 1

    def note_app_request(self, now_mono: float, now_wall: float) -> None:
        self.total_requests += 1
        self._app_times.append(now_mono)
        cutoff = now_mono - 5.0
        while self._app_times and self._app_times[0] < cutoff:
            self._app_times.popleft()
        overflow = len(self._app_times) - 2000
        if overflow > 0:
            for _ in range(overflow):
                self._app_times.popleft()
        sec = int(now_wall)
        if not self._buckets or self._buckets[-1][0] != sec:
            self._buckets.append([sec, 1])
        else:
            self._buckets[-1][1] += 1
        rps = self.rps(now_mono)
        if rps > self.peak_rps:
            self.peak_rps = rps

    def note_exempt(self) -> None:
        self.exempt_requests += 1

    def rps(self, now_mono: float, window: float = 5.0) -> float:
        cutoff = now_mono - window
        while self._app_times and self._app_times[0] < cutoff:
            self._app_times.popleft()
        if not self._app_times:
            return 0.0
        return len(self._app_times) / window

    def record_decision(self, event: DecisionEvent) -> None:
        self.feed.append(event)
        if event.action == "pass":
            self.total_passed += 1
        elif event.action == "distort":
            self.total_distorted += 1
        elif event.action == "shed":
            self.total_shed += 1
        elif event.action == "budget_close":
            self.total_budget_closed += 1
        score = event.score
        if isinstance(score, (int, float)) and math.isfinite(score):
            self.score_sum += float(score)
            self.score_count += 1
            for index, bound in enumerate(SCORE_BOUNDS):
                if score <= bound:
                    self.score_buckets[index] += 1
                    break

    def record_fail_open(self) -> None:
        self.total_fail_open += 1

    def begin_tarpit(
        self,
        session: SessionState,
        path: str,
        score: float,
        now_wall: float,
        now_mono: float,
    ) -> ActiveTarpit:
        tarpit_id = self._next_tarpit
        self._next_tarpit += 1
        item = ActiveTarpit(
            tarpit_id=tarpit_id,
            session_key=session.key,
            ip=session.ip,
            path=path[:180],
            profile_id=session.profile_id,
            score=score,
            started_wall=now_wall,
            started_mono=now_mono,
        )
        self.active[tarpit_id] = item
        if len(self.active) > self.peak_tarpits:
            self.peak_tarpits = len(self.active)
        return item

    def end_tarpit(self, tarpit_id: int, nbytes: int) -> None:
        item = self.active.pop(tarpit_id, None)
        if item is not None:
            elapsed = time.monotonic() - item.started_mono
            if elapsed > 0:
                self.tarpit_seconds_total += elapsed
        if nbytes > 0:
            self.bytes_streamed += nbytes

    def sparkline(self, now_wall: float) -> list[int]:
        """Requests per second for the last 60 wall-clock seconds."""
        by_sec = {sec: count for sec, count in self._buckets}
        current = int(now_wall)
        return [int(by_sec.get(current - age, 0)) for age in range(59, -1, -1)]

    def snapshot(
        self,
        sessions: list[SessionState],
        *,
        now_mono: float,
        now_wall: float,
        threshold: float,
        weights: dict[str, float],
        max_tarpits: int,
        tarpit_response_seconds: float,
        session_tarpit_cap: float,
    ) -> dict:
        ranked = sorted(
            sessions,
            key=lambda s: (
                -(s.last_score.score if s.last_score else 0.0),
                -s.last_wall,
            ),
        )
        session_rows = []
        for session in ranked[:18]:
            score = session.last_score
            session_rows.append(
                {
                    "id": session.key[:16],
                    "key": session.key,
                    "ip": session.ip,
                    "score": _num(score.score if score else 0.0),
                    "r": _num(score.r_hat if score else 0.0),
                    "d": _num(score.d if score else 0.0),
                    "h": _num(score.h if score else 0.0),
                    "c": _num(score.c if score else 0.0),
                    "rps": _num(score.requests_per_second if score else 0.0, 2),
                    "not_found": _num(session.not_found_count, 3),
                    "total": _num(session.total_requests, 3),
                    "classification": (
                        score.classification_for(threshold) if score else "legitimate"
                    ),
                    "hostile": session.hostile,
                    "profile": session.profile_id,
                    "ua": session.user_agent_preview,
                    "last_path": session.last_path,
                    "method": session.last_method,
                    "requests": session.raw_requests,
                    "distorted": session.distorted,
                    "tarpit_seconds": _num(session.tarpit_seconds, 1),
                    "age_s": _num(max(0.0, now_wall - session.created_wall), 1),
                    "idle_s": _num(max(0.0, now_wall - session.last_wall), 1),
                    "unique_paths": len(session.unique_paths),
                    "identity": session.identity_method,
                    "ip_source": session.ip_source,
                    "explain": score.explain(threshold) if score else "",
                    "missing": list(score.missing_headers) if score else [],
                    "crawler_family": score.crawler_family if score else "",
                    "crawler_verified": bool(score.crawler_verified) if score else False,
                    "crawler_reason": score.crawler_reason if score else "",
                }
            )
        feed = []
        for event in reversed(self.feed):
            feed.append(
                {
                    "ts": event.wall,
                    "ip": event.ip,
                    "method": event.method,
                    "path": event.path,
                    "score": _num(event.score),
                    "r": _num(event.r_hat),
                    "d": _num(event.d),
                    "h": _num(event.h),
                    "c": _num(event.c),
                    "classification": event.classification,
                    "action": event.action,
                    "profile": event.profile_id,
                    "status": event.status,
                    "ua": event.user_agent,
                    "explain": event.explain,
                    "ip_source": event.ip_source,
                    # Same 16-character id as the session row. Not unique per event.
                    "id": event.session_id,
                }
            )
        tarpits = []
        for item in self.active.values():
            tarpits.append(
                {
                    "id": item.tarpit_id,
                    "ip": item.ip,
                    "path": item.path,
                    "profile": item.profile_id,
                    "score": _num(item.score),
                    "started": item.started_wall,
                    "duration_s": _num(max(0.0, now_mono - item.started_mono), 1),
                    "session": item.session_key[:16],
                }
            )
        tarpits.sort(key=lambda row: -row["duration_s"])
        rps = self.rps(now_mono)
        return {
            "now": now_wall,
            "uptime_s": _num(max(0.0, now_wall - self.started_wall), 1),
            "threshold": threshold,
            "watch_threshold": 0.40,  # console band; the gate itself is `threshold`
            "decay": 0.9,
            "weights": weights,
            "tarpit_response_seconds": tarpit_response_seconds,
            "session_tarpit_cap": session_tarpit_cap,
            "global": {
                "rps": _num(rps, 2),
                "peak_rps": _num(self.peak_rps, 2),
                "sparkline": self.sparkline(now_wall),
                "total_requests": self.total_requests,
                "total_passed": self.total_passed,
                "total_distorted": self.total_distorted,
                "total_shed": self.total_shed,
                "total_budget_closed": self.total_budget_closed,
                "total_fail_open": self.total_fail_open,
                "exempt_requests": self.exempt_requests,
                "active_tarpits": len(self.active),
                "peak_tarpits": self.peak_tarpits,
                "max_tarpits": max_tarpits,
                "tracked_sessions": len(sessions),
                "bytes_streamed": self.bytes_streamed,
                "rss_bytes": process_rss_bytes(),
            },
            "tarpits": tarpits[:40],
            "feed": feed[:40],
            "sessions": session_rows,
        }
