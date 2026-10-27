"""Background jobs: a shared 2-worker pool.

Every background job opens its own database connection with
``connect(settings.data_dir)`` and never reuses the web request's connection
(SQLite WAL mode allows the concurrent writers).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="marketmate")


def submit(fn: Callable, *args) -> None:
    """Run ``fn(*args)`` in the background pool. ``fn`` opens its own connection."""
    _EXECUTOR.submit(fn, *args)
