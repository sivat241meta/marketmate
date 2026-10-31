"""Bounded parallelism for the slow pipeline steps (Task 140).

The photo step used to process items one by one (SAM per noun phrase per
frame, plus Spark picks and checks), which stalled a 21-item video for
400+ s. The per-item photo work, the per-item frame picks and the
per-item checks now fan out over a bounded thread pool: ``PHOTO_WORKERS``
threads (default 6).

Rules the callers follow:
- workers only do API calls and file work; every SQLite write (drafts,
  progress) stays on the calling thread via the ``on_done`` callback,
  which runs on the calling thread as each task finishes;
- results always come back in input order with the same choice rules,
  so a parallel run equals the sequential run;
- every Meta API call holds one global ``api_slot``: never more than
  PHOTO_WORKERS calls are in flight, however many pools submit;
- an HTTP 429 sleeps with back-off and retries (``MAX_429_RETRIES``).
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

#: Default pool size when PHOTO_WORKERS is missing, blank or invalid.
PHOTO_WORKERS_DEFAULT = 6
#: Environment variable overriding the pool size (and the API cap).
PHOTO_WORKERS_ENV = "PHOTO_WORKERS"
#: Extra attempts after an HTTP 429 before the call fails for real.
MAX_429_RETRIES = 4
#: First 429 back-off (1 s, 2 s, 4 s, ...) and its ceiling.
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 30.0

_sleep = time.sleep  # seam for tests: monkeypatch app.parallel._sleep


def photo_workers() -> int:
    """Pool size for the parallel pipeline steps; PHOTO_WORKERS, default 6."""
    try:
        workers = int(os.environ.get(PHOTO_WORKERS_ENV, "").strip() or 0)
    except ValueError:
        return PHOTO_WORKERS_DEFAULT
    return workers if workers > 0 else PHOTO_WORKERS_DEFAULT


def map_parallel_ordered[T, S](func: Callable[[T], S], items: list[T], *,
                             workers: int | None = None,
                             on_done: Callable[[int, int], None] | None = None
                             ) -> list[S]:
    """Run ``func`` over ``items`` concurrently; results in input order.

    ``on_done(done, total)`` runs on the calling thread as each task
    finishes (``done`` counts 1..total exactly once), so callers report
    progress and write SQLite from one thread. The first exception in
    input order propagates after every task has finished.
    """
    entries = list(items)
    total = len(entries)
    if not entries:
        return []
    size = workers if workers and workers > 0 else photo_workers()
    with ThreadPoolExecutor(max_workers=size) as pool:
        futures = [pool.submit(func, entry) for entry in entries]
        if on_done is not None:
            for done, _ in enumerate(as_completed(futures), start=1):
                on_done(done, total)
        return [future.result() for future in futures]


_gate_lock = threading.Lock()
_gate: threading.BoundedSemaphore | None = None
_gate_size: int | None = None


@contextlib.contextmanager
def api_slot() -> Iterator[None]:
    """Hold one global Meta API slot (at most PHOTO_WORKERS in flight).

    Every Spark/SAM call holds this while the HTTP request runs, so the
    parallel pools plus the background jobs never exceed the cap together.
    """
    global _gate, _gate_size
    want = photo_workers()
    with _gate_lock:
        if _gate is None or _gate_size != want:
            _gate = threading.BoundedSemaphore(want)
            _gate_size = want
        gate = _gate
    with gate:
        yield


def backoff_seconds(attempt: int) -> float:
    """429 back-off for a 0-based attempt: 1 s, 2 s, 4 s ... capped at 30 s."""
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** max(attempt, 0)))


def sleep_backoff(attempt: int) -> None:
    """Sleep the 429 back-off for a 0-based attempt."""
    _sleep(backoff_seconds(attempt))
