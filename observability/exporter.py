"""Render gate counters as Prometheus text.

The collector is the source of truth. This module does not keep a second
set of counters, and it does not label by client address, path, or
User-Agent. Those are an access log. A label would also be a cardinality
problem at the session cap.
"""

from __future__ import annotations

from prometheus_client.exposition import generate_latest

# generate_latest emits the 0.0.4 text format. The library's CONTENT_TYPE_LATEST
# is OpenMetrics 1.0.0, which this body is not. Prometheus will reject the scrape
# if the header and the body disagree.
PROMETHEUS_TEXT = "text/plain; version=0.0.4; charset=utf-8"
from prometheus_client.metrics_core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)
from prometheus_client.registry import CollectorRegistry

from core.config import ChakravyuhConfig
from core.metrics import SCORE_BOUNDS, MetricsCollector

_ACTIONS = ("pass", "distort", "shed", "budget_close")


def _resident_bytes() -> int:
    """Current RSS. ru_maxrss is a high-water mark and is not this number."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        page = int(__import__("os").sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return 0
    if resident_pages <= 0 or page <= 0:
        return 0
    return resident_pages * page


class GateCollector:
    def __init__(self, metrics: MetricsCollector, sessions: int, config: ChakravyuhConfig) -> None:
        self.metrics = metrics
        self.sessions = sessions
        self.config = config

    def describe(self):
        return []

    def collect(self):
        metrics = self.metrics
        requests = CounterMetricFamily(
            "chakravyuh_requests",
            "Application requests the gate scored. Exempt paths are not included.",
        )
        requests.add_metric([], metrics.total_requests)
        yield requests

        decisions = CounterMetricFamily(
            "chakravyuh_decisions",
            "Gate decisions by action. distort, shed, and budget_close did not call the origin.",
            labels=["action"],
        )
        counts = {
            "pass": metrics.total_passed,
            "distort": metrics.total_distorted,
            "shed": metrics.total_shed,
            "budget_close": metrics.total_budget_closed,
        }
        for action in _ACTIONS:
            decisions.add_metric([action], counts[action])
        yield decisions

        # Same counts as the action labels, under the names an operator looks
        # up for the 429 and the short close. Do not sum them with decisions.
        shed = CounterMetricFamily(
            "chakravyuh_shed",
            "429 responses at the concurrency cap. Same count as decisions{action=shed}.",
        )
        shed.add_metric([], metrics.total_shed)
        yield shed

        closed = CounterMetricFamily(
            "chakravyuh_budget_closed",
            "Short fake responses after the session hold budget. Same count as decisions{action=budget_close}.",
        )
        closed.add_metric([], metrics.total_budget_closed)
        yield closed

        fail_open = CounterMetricFamily(
            "chakravyuh_fail_open",
            "Planning faults that called the origin once.",
        )
        fail_open.add_metric([], metrics.total_fail_open)
        yield fail_open

        exempt = CounterMetricFamily(
            "chakravyuh_exempt_requests",
            "Requests that skipped scoring, including this scrape.",
        )
        exempt.add_metric([], metrics.exempt_requests)
        yield exempt

        held = CounterMetricFamily(
            "chakravyuh_tarpit_seconds",
            "Seconds a distorted response held the socket, added when it ended. "
            "A client disconnect is the elapsed time, not the per-response cap.",
        )
        held.add_metric([], metrics.tarpit_seconds_total)
        yield held

        streamed = CounterMetricFamily(
            "chakravyuh_bytes_streamed",
            "Bytes written on distorted bodies.",
        )
        streamed.add_metric([], metrics.bytes_streamed)
        yield streamed

        cumulative = 0
        buckets: list[tuple[str, float]] = []
        for bound, count in zip(SCORE_BOUNDS, metrics.score_buckets):
            cumulative += count
            buckets.append((f"{bound:.1f}", cumulative))
        buckets.append(("+Inf", metrics.score_count))
        score = HistogramMetricFamily(
            "chakravyuh_score",
            "Suspicion score at each decision. The buckets are the score, not a latency.",
        )
        score.add_metric([], buckets, metrics.score_sum)
        yield score

        active = GaugeMetricFamily(
            "chakravyuh_active_tarpits",
            "Distorted responses currently held open.",
        )
        active.add_metric([], len(metrics.active))
        yield active

        sessions = GaugeMetricFamily(
            "chakravyuh_sessions",
            "Sessions in the in-memory store.",
        )
        sessions.add_metric([], self.sessions)
        yield sessions

        peak = GaugeMetricFamily(
            "chakravyuh_peak_tarpits",
            "High-water mark of concurrent tarpits since process start.",
        )
        peak.add_metric([], metrics.peak_tarpits)
        yield peak

        cap = GaugeMetricFamily(
            "chakravyuh_tarpit_cap",
            "Configured concurrent tarpit cap. A constant, not a measurement.",
        )
        cap.add_metric([], self.config.max_concurrent_tarpits)
        yield cap

        info = GaugeMetricFamily(
            "chakravyuh_build_info",
            "Process constants. The value is always 1.",
            labels=["version", "threshold", "release_threshold"],
        )
        from core import __version__

        info.add_metric(
            [__version__, f"{self.config.threshold:.2f}", f"{self.config.release_threshold:.2f}"],
            1,
        )
        yield info

        rss = _resident_bytes()
        if rss > 0:
            resident = GaugeMetricFamily(
                "chakravyuh_process_resident_bytes",
                "Current resident set from /proc/self/statm. Not ru_maxrss.",
            )
            resident.add_metric([], rss)
            yield resident


def render(metrics: MetricsCollector, *, sessions: int, config: ChakravyuhConfig) -> bytes:
    registry = CollectorRegistry(auto_describe=False)
    registry.register(GateCollector(metrics, sessions, config))
    return generate_latest(registry)
