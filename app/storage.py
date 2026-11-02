"""Persist Modal Volume writes. No-op when not running on Modal."""

from __future__ import annotations

import logging
import os
import threading
import time

VOLUME_NAME = "marketmate-data"

#: Request-triggered commits coalesce to at most one real commit per window.
COMMIT_MIN_INTERVAL_S = 3.0

_log = logging.getLogger(__name__)

_commit_lock = threading.Lock()
_last_commit_at = 0.0
_pending_timer: threading.Timer | None = None


def _do_commit() -> None:
    """One real volume commit. Never raises."""
    if os.environ.get("MARKETMATE_ON_MODAL") != "1":
        return
    try:
        import modal

        modal.Volume.from_name(VOLUME_NAME).commit()
    except Exception as exc:  # noqa: BLE001 - a failed commit must not break requests/jobs
        _log.warning("volume commit failed: %s", exc)


def _commit_pending() -> None:
    """Timer callback: commit the last pending request-triggered write."""
    global _last_commit_at, _pending_timer
    try:
        with _commit_lock:
            _last_commit_at = time.monotonic()
            _pending_timer = None
        _do_commit()
    except Exception as exc:  # noqa: BLE001 - timer threads must not die loudly
        _log.warning("volume commit failed: %s", exc)


def commit() -> None:
    """Throttled commit for request-triggered writes. Never raises.

    At most one real commit every COMMIT_MIN_INTERVAL_S per process;
    calls inside the window schedule a background timer that commits
    the last pending one.
    """
    global _last_commit_at, _pending_timer
    try:
        run_now = False
        with _commit_lock:
            now = time.monotonic()
            if now - _last_commit_at >= COMMIT_MIN_INTERVAL_S:
                _last_commit_at = now
                run_now = True
            elif _pending_timer is None or not _pending_timer.is_alive():
                delay = COMMIT_MIN_INTERVAL_S - (now - _last_commit_at)
                timer = threading.Timer(delay, _commit_pending)
                timer.daemon = True
                _pending_timer = timer
                timer.start()
        if run_now:
            _do_commit()
    except Exception as exc:  # noqa: BLE001 - a failed commit must not break requests/jobs
        _log.warning("volume commit failed: %s", exc)


def commit_now() -> None:
    """Immediate commit for a finished background job. Never raises."""
    global _last_commit_at, _pending_timer
    try:
        with _commit_lock:
            timer, _pending_timer = _pending_timer, None
            _last_commit_at = time.monotonic()
        if timer is not None:
            timer.cancel()
        _do_commit()
    except Exception as exc:  # noqa: BLE001 - a failed commit must not break requests/jobs
        _log.warning("volume commit failed: %s", exc)


def reset_throttle_for_tests() -> None:
    """Drop throttle state (pending timer + last-commit time). Tests only."""
    global _last_commit_at, _pending_timer
    with _commit_lock:
        timer, _pending_timer = _pending_timer, None
        _last_commit_at = 0.0
    if timer is not None:
        timer.cancel()
