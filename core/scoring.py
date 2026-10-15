"""Suspicion score and the TTL session store.

    S = 0.35·R̂ + 0.35·D + 0.20·H − 0.10·C

All terms are in [0, 1]. S is clamped to [0, 1]. Weights are fixed a priori.

R̂  request rate over a 5-second window, divided by 20, capped at 1.
D   decayed 404 count / decayed request count.
H   fraction of {User-Agent, Accept, Accept-Language} that are missing.
C   1.0 only for a reverse-DNS-verified good crawler, else 0.

404 and request counters are multiplied by 0.9 before each observation so
recent behavior dominates. The store is a size-capped TTL cache: inactivity
and cardinality are both bounded, which closes the memory-exhaustion path.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

from cachetools import TTLCache

from core.config import ChakravyuhConfig
from core.crawlers import CrawlerClaim
from core.profiles import StackProfile, select_profile

EXPECTED_HEADERS: tuple[str, ...] = ("user-agent", "accept", "accept-language")
WATCH_THRESHOLD = 0.40


def crossed(score: float, threshold: float) -> bool:
    """Threshold test stable at the published 0.70 boundary.

    0.35 + 0.35 is not a clean binary fraction. Rounding to 6 places keeps
    the gate on the mathematical value instead of a float hair under it.
    """
    if not math.isfinite(score) or not math.isfinite(threshold):
        return False
    return round(score, 6) >= round(threshold, 6)


def clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass
class ScoreBreakdown:
    r_hat: float
    d: float
    h: float
    c: float
    score: float
    requests_per_second: float
    missing_headers: tuple[str, ...]
    crawler_family: str
    crawler_verified: bool
    crawler_reason: str
    window_count: int

    @property
    def classification(self) -> str:
        return self.classification_for(0.70)

    def classification_for(self, threshold: float) -> str:
        if crossed(self.score, threshold):
            return "scanner"
        if self.score >= WATCH_THRESHOLD:
            return "watch"
        return "legitimate"

    def explain(self, threshold: float) -> str:
        missing = ", ".join(self.missing_headers) if self.missing_headers else "none"
        crawler = self.crawler_reason if self.crawler_family else "not a crawler ua"
        return (
            f"S={self.score:.3f} (threshold {threshold:.2f}) "
            f"R={self.r_hat:.3f} ({self.requests_per_second:.2f} rps, n={self.window_count}) "
            f"D={self.d:.3f} H={self.h:.3f} missing=[{missing}] "
            f"C={self.c:.1f} ({crawler})"
        )


@dataclass
class SessionState:
    key: str
    ip: str
    created_wall: float
    last_wall: float
    timestamps: deque[float] = field(default_factory=deque)
    not_found_count: float = 0.0
    total_requests: float = 0.0
    raw_requests: int = 0
    distorted: int = 0
    passed: int = 0
    tarpit_seconds: float = 0.0
    unique_paths: set[str] = field(default_factory=set)
    last_path: str = ""
    last_method: str = ""
    user_agent_preview: str = ""
    last_score: ScoreBreakdown | None = None
    profile_id: str = ""
    identity_method: str = ""
    ip_source: str = "peer"
    hostile: bool = False

    def touch_wall(self, now_wall: float) -> None:
        self.last_wall = now_wall


class SessionStore:
    """In-process sliding TTL map. Safe on a single asyncio thread.

    ``cachetools.TTLCache`` does not refresh expiry on read, and it does not
    expire purely by wall-clock inactivity unless touched. ``touch`` reassigns
    the entry so the 300-second inactivity timer slides. Dashboard reads must
    not touch, or a watched session would never expire.
    """

    def __init__(self, config: ChakravyuhConfig) -> None:
        self.config = config
        self._cache: TTLCache[str, SessionState] = TTLCache(
            maxsize=config.max_sessions,
            ttl=config.session_ttl_seconds,
            timer=time.monotonic,
        )

    def expire(self) -> None:
        self._cache.expire()

    def __len__(self) -> int:
        self.expire()
        return len(self._cache)

    def get(self, key: str) -> SessionState | None:
        return self._cache.get(key)

    def get_or_create(
        self,
        key: str,
        ip: str,
        *,
        now_wall: float,
        identity_method: str,
        ip_source: str,
    ) -> SessionState:
        existing = self._cache.get(key)
        if existing is not None:
            self._cache[key] = existing  # slide the inactivity TTL
            return existing
        profile = select_profile(key)
        session = SessionState(
            key=key,
            ip=ip,
            created_wall=now_wall,
            last_wall=now_wall,
            profile_id=profile.profile_id,
            identity_method=identity_method,
            ip_source=ip_source,
        )
        self._cache[key] = session
        return session

    def values(self) -> list[SessionState]:
        self.expire()
        return list(self._cache.values())


class ScoringEngine:
    def __init__(self, config: ChakravyuhConfig) -> None:
        self.config = config

    def observe(
        self,
        session: SessionState,
        *,
        now_mono: float,
        now_wall: float,
        path: str,
        method: str,
        user_agent: str,
        is_probe: bool,
    ) -> None:
        """Decay, then record this request. Synchronous. Do not await mid-call."""
        cfg = self.config
        session.not_found_count *= cfg.decay
        session.total_requests *= cfg.decay
        session.total_requests += 1.0
        if is_probe:
            session.not_found_count += 1.0
        session.pending_probe_guess = is_probe
        session.raw_requests += 1
        session.last_path = path[:180]
        session.last_method = method[:16]
        session.user_agent_preview = user_agent[:160]
        session.touch_wall(now_wall)
        if path and len(session.unique_paths) < 256:
            session.unique_paths.add(path[:180])
        self._note_timestamp(session, now_mono)

    def correct_status(
        self,
        session: SessionState,
        *,
        guessed_probe: bool,
        actual_not_found: bool,
    ) -> None:
        """Fix this request's provisional 404 bit from the real status.

        The guess is passed in, not read off the session: a second concurrent
        request may already have overwritten any session-level flag. Distorted
        requests never call this — answering them from the origin would leak
        the real stack, so the probe guess stands.
        """
        if guessed_probe and not actual_not_found:
            session.not_found_count = max(0.0, session.not_found_count - 1.0)
        elif actual_not_found and not guessed_probe:
            session.not_found_count += 1.0

    def refresh_diversity(self, session: SessionState, breakdown: ScoreBreakdown) -> ScoreBreakdown:
        """Recompute D and S after the origin status arrives. Leaves R, H, C."""
        if session.total_requests > 0.0:
            breakdown.d = clamp01(session.not_found_count / session.total_requests)
        else:
            breakdown.d = 0.0
        breakdown.score = combine_score(
            self.config, breakdown.r_hat, breakdown.d, breakdown.h, breakdown.c
        )
        session.last_score = breakdown
        return breakdown

    def score(self, session: SessionState, headers: dict[str, str], claim: CrawlerClaim, now_mono: float) -> ScoreBreakdown:
        rps, window_count = self._rate(session, now_mono)
        r_hat = clamp01(rps / self.config.rate_cap_rps)
        if session.total_requests > 0:
            diversity = clamp01(session.not_found_count / session.total_requests)
        else:
            diversity = 0.0
        missing = tuple(name for name in EXPECTED_HEADERS if not headers.get(name, "").strip())
        header_dev = clamp01(len(missing) / len(EXPECTED_HEADERS))
        crawler = clamp01(claim.offset)
        breakdown = ScoreBreakdown(
            r_hat=r_hat,
            d=diversity,
            h=header_dev,
            c=crawler,
            score=combine_score(self.config, r_hat, diversity, header_dev, crawler),
            requests_per_second=rps if math.isfinite(rps) else 0.0,
            missing_headers=missing,
            crawler_family=claim.family,
            crawler_verified=claim.verified,
            crawler_reason=claim.reason,
            window_count=window_count,
        )
        session.last_score = breakdown
        return breakdown

    def _note_timestamp(self, session: SessionState, now_mono: float) -> None:
        window = self.config.window_seconds
        stamps = session.timestamps
        stamps.append(now_mono)
        cutoff = now_mono - window
        while stamps and stamps[0] < cutoff:
            stamps.popleft()
        # Saturation cap. Past this, R̂ is already 1.0 for any sane window.
        overflow = len(stamps) - self.config.max_timestamps
        if overflow > 0:
            for _ in range(overflow):
                stamps.popleft()

    def _rate(self, session: SessionState, now_mono: float) -> tuple[float, int]:
        window = self.config.window_seconds
        cutoff = now_mono - window
        stamps = session.timestamps
        while stamps and stamps[0] < cutoff:
            stamps.popleft()
        count = len(stamps)
        if count == 0:
            return 0.0, 0
        return count / window, count


def combine_score(config: ChakravyuhConfig, r_hat: float, diversity: float, header_dev: float, crawler: float) -> float:
    """The published formula. Terms are already normalized; result is clamped."""
    raw = (
        config.w_rate * r_hat
        + config.w_diversity * diversity
        + config.w_headers * header_dev
        - config.w_crawler * crawler
    )
    return clamp01(raw)


def profile_for(session: SessionState) -> StackProfile:
    return select_profile(session.key)
