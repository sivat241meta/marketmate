"""In-memory hourly upload limits (per IP and global)."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from starlette.requests import Request

RATE_LIMIT_MESSAGE = (
    "Too many uploads in the last hour — please wait a while and try again."
)

_WINDOW_SECONDS = 3600.0


class RateLimiter:
    """Sliding-window limiter; allowed attempts are recorded, denied are not."""

    def __init__(self, per_ip_hour: int, global_hour: int) -> None:
        self._per_ip = per_ip_hour
        self._global = global_hour
        self._by_ip: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    @staticmethod
    def _stamp(now: datetime) -> float:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now.timestamp()

    @classmethod
    def _prune(cls, bucket: deque[float], now_ts: float) -> None:
        while bucket and bucket[0] <= now_ts - _WINDOW_SECONDS:
            bucket.popleft()

    def allow(self, ip: str, now: datetime) -> bool:
        """Return True and record the attempt when both caps allow it."""
        now_ts = self._stamp(now)
        bucket = self._by_ip.setdefault(ip, deque())
        self._prune(bucket, now_ts)
        self._prune(self._all, now_ts)
        if len(bucket) >= self._per_ip or len(self._all) >= self._global:
            return False
        bucket.append(now_ts)
        self._all.append(now_ts)
        return True


def client_ip(request: Request) -> str:
    """Best-effort client IP, proxy-aware via X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return "unknown"
