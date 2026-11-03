"""Task 134: a remembered market must never bounce people home.

Pins: with a remembered area, page init navigates only on "/" (node
test over the real popups.js/locate.js); and the homepage service
cards still link to /market, the voice pop-up and /new.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_task84 import make_client, seed_market

ROOT = Path(__file__).resolve().parent.parent


def test_node_remembered_area_never_bounces():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/remembered_area.test.mjs"], cwd=ROOT,
        check=False, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_homepage_service_cards_link_market_voice_new(tmp_path):
    seed_market(tmp_path)
    html = make_client(tmp_path).get(
        "/", headers={"referer": "http://testserver/market"}).text
    row = re.search(r'class="svc-row".*?</div>\s*</div>',
                    html, re.DOTALL)
    assert row, "homepage must keep the three service cards"
    cards = row.group(0)
    assert 'class="svc" href="/market' in cards  # find-a-shop card
    assert 'class="svc" href="/new"' in cards  # for-sellers card
    voice = re.search(r'<button[^>]*class="svc"[^>]*>', cards)
    assert voice, "voice card must stay a pop-up button, not a link"
    assert "data-search-open" in voice.group(0)
    assert "data-search-voice" in voice.group(0)
