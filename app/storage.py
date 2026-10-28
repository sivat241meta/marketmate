"""Persist Modal Volume writes. No-op when not running on Modal."""

from __future__ import annotations

import logging
import os

VOLUME_NAME = "marketmate-data"

_log = logging.getLogger(__name__)


def commit() -> None:
    """Commit the Modal volume so file/DB writes survive. Never raises."""
    if os.environ.get("MARKETMATE_ON_MODAL") != "1":
        return
    try:
        import modal

        modal.Volume.from_name(VOLUME_NAME).commit()
    except Exception as exc:  # noqa: BLE001 - a failed commit must not break requests/jobs
        _log.warning("volume commit failed: %s", exc)
