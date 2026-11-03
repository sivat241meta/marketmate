"""Task 170: web app keeps one warm container (no cold starts)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODAL_APP = ROOT / "modal_app.py"


def test_modal_app_keeps_one_warm_container():
    text = MODAL_APP.read_text()
    assert "min_containers=1" in text
    assert "max_containers=1" in text
