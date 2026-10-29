"""Task 99: the check-page rename saves again.

The rename dialog moves the card's sheet under document.body, so review.js
must find the card by the sheet's data-item (never by DOM ancestry), and the
dialog must put the sheet back into the card on close. The node test drives
that whole flow; the tests below run it and extend the approve-side cover
for edited names (a variety-only edit on one of two cards).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
QUOTE = "t99 kathari kilo forty rupees"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)),
                      follow_redirects=False)


def _create_shop(client) -> str:
    resp = client.post("/new", data={
        "name": "T99 Stall", "phone": "+914400000099",
        "area": "Koyambedu", "language": "ta", "currency": "INR",
        "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en="brinjal", price=40, local="கத்தரி",
           variety="oothu", quote=QUOTE):
    return DraftItem(
        name_spoken=name_en, name_local=local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg",
                               "kilo forty")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[1], start_ms=0, end_ms=1000),
        confirmed=True)


def _start_review_session(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review",
                              f"{len(drafts)} items need review")
        return session_id
    finally:
        conn.close()


def _approve_body(drafts, varieties):
    items = []
    for draft, variety in zip(drafts, varieties):
        items.append({
            "name_spoken": draft.name_en,
            "name_local": draft.name_local,
            "name_en": draft.name_en,
            "variety": variety,
            "price_lines": [{
                "said": "", "price": str(line.price),
                "per_amount": str(line.per_amount), "unit": line.unit}
                for line in draft.price_lines],
            "range_said": False, "qty": None, "qty_unit": None,
            "proof": {"quote": "", "turn_ids": [], "start_ms": 0,
                      "end_ms": 0, "frame": None, "audio_clip": None,
                      "source": None},
            "flags": [], "photo": None, "condition_hint": None,
            "confirmed": False,
        })
    return {"items": items,
            "confirmed": list(range(len(items))), "carried": []}


def test_changed_js_passes_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    for name in ("app/web/static/review.js",
                 "tests/js/review_rename_dialog.test.mjs"):
        proc = subprocess.run(
            [node, "--check", name], cwd=ROOT,
            check=False, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"{name}: {proc.stderr}"


def test_review_rename_dialog_js_behaviour():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/review_rename_dialog.test.mjs"], cwd=ROOT,
        check=False, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_rename_sheet_carries_its_card_index(tmp_path):
    """Each check-page rename sheet has the data-item the save path
    uses to find its card."""
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _start_review_session(
        tmp_path, token, [_draft(), _draft("tomato", 20, "தக்காளி",
                                           "nattu")])
    html = client.get(f"/e/{token}/s/{session_id}").text
    cards = re.findall(r'data-card="(\d+)"', html)
    sheets = re.findall(r'data-rename-form data-item="(\d+)"', html)
    assert len(cards) == 2
    assert sorted(sheets) == sorted(cards)


def test_approve_stores_variety_only_edit(tmp_path):
    """A variety-only rename on one card persists; the other card keeps
    its names and variety."""
    client = _client(tmp_path)
    token = _create_shop(client)
    drafts = [_draft(), _draft("tomato", 20, "தக்காளி", "nattu")]
    session_id = _start_review_session(tmp_path, token, drafts)
    body = _approve_body(drafts, ["green long", "nattu"])
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"],
                                       published_only=True)
        items = db.version_items(conn, version_id)
        assert items[0].name_local == "கத்தரி"
        assert items[0].name_en == "brinjal"
        assert items[0].variety == "green long"
        assert items[1].name_local == "தக்காளி"
        assert items[1].name_en == "tomato"
        assert items[1].variety == "nattu"
    finally:
        conn.close()
