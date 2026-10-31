"""Task 143: a spoken quantity is never accepted as a price.

1. A real Tamil stall run produced "sweet corn Rs.5 / 1 kg" with only a
   non-blocking QTY_MISSING flag; the seller meant "5 pieces for Rs.20"
   and the Rs.5/kg line was invented from the quantity. check_item now
   raises blocking QTY_AS_PRICE when a line's price equals another line's
   per_amount and the quote shows that number before a count unit or
   repeated in two languages.
2. Two priced lines with different units raise blocking
   MULTI_PRICE_UNCLEAR unless the lines are a clear tier list
   ("1 kg 40, 2 kg 75": same unit, growing amounts).
3. The review card header shows a flagged price as uncertain with
   "Needs you", never the green tick; approve still refuses to publish
   an item with an unresolved blocking flag.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.checks import check_item
from app.web.main import create_app
from app.web.seller import _needs_decision, _price_summary

ROOT = Path(__file__).resolve().parent.parent

# Exact draft item from the real stall video (run on main 6ed7be6).
FIXTURE = {
    "name_local": "sweet corn",
    "name_en": "corn",
    "variety": "sweet",
    "price_lines": [
        {"price": "5", "per_amount": "1", "unit": "kg",
         "said": "கிலோ அஞ்சு"},
        {"price": "20", "per_amount": "5", "unit": "piece",
         "said": "five piece இருபது"},
    ],
    "proof": {"quote": "sweet corn கிலோ அஞ்சு five piece இருபது."},
}


def pl(price, per_amount, unit, said=""):
    return PriceLine(
        Decimal(price) if price is not None else None,
        Decimal(per_amount) if per_amount is not None else None,
        unit, said,
    )


def draft(quote="", lines=(), name_en="corn", **kwargs):
    return DraftItem(
        name_spoken=kwargs.get("name_spoken", name_en),
        name_local=kwargs.get("name_local", name_en),
        name_en=name_en,
        variety=kwargs.get("variety"),
        price_lines=list(lines),
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0),
    )


def fixture_item():
    return DraftItem(
        name_spoken=FIXTURE["name_local"],
        name_local=FIXTURE["name_local"],
        name_en=FIXTURE["name_en"],
        variety=FIXTURE["variety"],
        price_lines=[pl(line["price"], line["per_amount"], line["unit"],
                        line["said"])
                     for line in FIXTURE["price_lines"]],
        qty=None, qty_unit=None,
        proof=Proof(quote=FIXTURE["proof"]["quote"], turn_ids=[],
                    start_ms=0, end_ms=0),
    )


def codes(item, previous=None):
    return [flag.code for flag in check_item(item, previous or {})]


# --- 1. the real-video fixture ------------------------------------------------


def test_fixture_fires_qty_as_price():
    item = fixture_item()
    flags = {flag.code: flag for flag in check_item(item, {})}
    flag = flags["QTY_AS_PRICE"]
    assert flag.blocking is True
    assert flag.message == "Is 5 a price, or the 5 in '5 pieces for ₹20'?"
    assert flag.options == ["₹20 for 5 pieces", "₹5 per kg"]
    # The specific diagnosis wins; the generic multi-price question stays out.
    assert "MULTI_PRICE_UNCLEAR" not in flags


def test_fixture_not_just_qty_missing():
    # On main this item carried only non-blocking QTY_MISSING and showed a
    # green tick; now a blocking flag must stop it.
    item = fixture_item()
    assert any(flag.blocking for flag in check_item(item, {}))
    assert codes(item) != ["QTY_MISSING"]


def test_qty_as_price_two_language_repeat_alone():
    # No "<number> <unit>" pair here; அஞ்சு ... five is the evidence.
    item = draft(quote="kilo anju five twenty",
                 lines=[pl(5, 1, "kg"), pl(20, 5, "piece")])
    flags = {flag.code: flag for flag in check_item(item, {})}
    assert flags["QTY_AS_PRICE"].blocking is True
    assert flags["QTY_AS_PRICE"].options == ["₹20 for 5 pieces", "₹5 per kg"]


def test_qty_as_price_needs_quote_evidence():
    # Same line pair, but "five" is neither before a count unit nor
    # repeated in two languages: no QTY_AS_PRICE (MULTI still asks).
    item = draft(quote="corn five twenty",
                 lines=[pl(5, 1, "kg"), pl(20, 5, "piece")])
    found = codes(item)
    assert "QTY_AS_PRICE" not in found
    assert "MULTI_PRICE_UNCLEAR" in found


# --- 2. negative tests: no flag ------------------------------------------------


def test_tomato_kilo_no_flag():
    item = draft(quote="தக்காளி கிலோ முப்பது", lines=[pl(30, 1, "kg")],
                 name_en="tomato")
    assert codes(item) == ["QTY_MISSING"]


def test_tier_list_no_new_flag():
    # "40, 2" still groups as one span when heard (pre-existing
    # NOT_HEARD, unrelated to this task); the new codes must stay out.
    item = draft(quote="1 kg 40, 2 kg 75",
                 lines=[pl(40, 1, "kg"), pl(75, 2, "kg")],
                 name_en="tomato")
    found = codes(item)
    assert "QTY_AS_PRICE" not in found
    assert "MULTI_PRICE_UNCLEAR" not in found


def test_tier_list_clean_without_comma():
    item = draft(quote="1 kg 40 then 2 kg 75",
                 lines=[pl(40, 1, "kg"), pl(75, 2, "kg")],
                 name_en="tomato")
    assert codes(item) == ["QTY_MISSING"]


def test_convertible_tier_no_multi_price_unclear():
    item = draft(quote="500 g 20 then 1 kg 35",
                 lines=[pl(20, 500, "g"), pl(35, 1, "kg")],
                 name_en="tomato")
    assert codes(item) == ["QTY_MISSING"]


def test_coconut_qty_before_unit_no_flag():
    item = draft(quote="தேங்கா அஞ்சு பீஸ் நூறு",
                 lines=[pl(100, 5, "piece")], name_en="coconut")
    assert codes(item) == ["QTY_MISSING"]


def test_lemon_repeated_five_no_qty_as_price():
    item = draft(quote="எலுமிச்சை அஞ்சு அஞ்சு இருபது",
                 lines=[pl(20, 5, "piece")], name_en="lemon")
    found = codes(item)
    assert "QTY_AS_PRICE" not in found
    assert found == ["QTY_MISSING"]


def test_multi_price_unclear():
    item = draft(quote="thakkali kilo muppathu dozen nooru",
                 lines=[pl(30, 1, "kg"), pl(100, 1, "dozen")],
                 name_en="tomato")
    flags = {flag.code: flag for flag in check_item(item, {})}
    flag = flags["MULTI_PRICE_UNCLEAR"]
    assert flag.blocking is True
    assert flag.message == "Two different prices — which one is right?"
    assert flag.options == ["₹30 per kg", "₹100 per dozen"]


# --- 3. review header + publish gate -------------------------------------------


def make_client(tmp_path, monkeypatch, seed):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, seed)
        db.set_session_status(conn, session_id, "review", "1 item needs review")

    monkeypatch.setattr("app.web.seller.jobs.submit", fake_submit)
    monkeypatch.setattr("app.web.seller.process_video_session", fake_process)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client):
    response = client.post("/new", data={
        "name": "Kannan Store", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable",
    })
    assert response.status_code in (302, 303)
    return response.headers["location"]


def upload_session(client, location):
    return client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fake", "video/mp4")}
    ).headers["location"]


def flagged_fixture():
    item = fixture_item()
    item.flags = check_item(item, {})
    return item


def test_price_summary_uncertain_under_blocking_flag():
    item = flagged_fixture()
    assert _needs_decision(item) is True
    assert _price_summary(item, "INR") == "₹5 / 1 kg ?"
    clean = draft(quote="tomato kilo 18", lines=[pl(18, 1, "kg")],
                  name_en="tomato")
    clean.flags = check_item(clean, {})
    assert _needs_decision(clean) is False
    assert _price_summary(clean, "INR") == "₹18 / 1 kg"


def test_review_card_needs_you_never_tick(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, [flagged_fixture()])
    session_url = upload_session(client, create_shop(client))
    html = client.get(session_url).text
    assert "Needs you" in html
    assert "₹5 / 1 kg ?" in html
    assert 'class="tick"' not in html
    assert "Is 5 a price, or the 5 in &#x27;5 pieces for ₹20&#x27;?" in html \
        or "Is 5 a price" in html
    assert 'data-value="₹20 for 5 pieces"' in html
    assert 'data-value="₹5 per kg"' in html


def _shop_id(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        return conn.execute("SELECT id FROM shops").fetchone()["id"]
    finally:
        conn.close()


def _published_version(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        return db.latest_version(conn, _shop_id(tmp_path), published_only=True)
    finally:
        conn.close()


def test_approve_refuses_unresolved_blocking_flag(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, [flagged_fixture()])
    session_url = upload_session(client, create_shop(client))
    posted = json.loads(db._draft_to_json(flagged_fixture()))
    response = client.post(
        session_url + "/approve", json={"items": [posted], "confirmed": []})
    assert response.status_code == 400
    assert "Is 5 a price" in response.json()["detail"]
    assert _published_version(tmp_path) is None


def test_approve_resolved_line_publishes_only_it(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, [flagged_fixture()])
    session_url = upload_session(client, create_shop(client))
    resolved = fixture_item()
    resolved.price_lines = [pl(20, 5, "piece", "five piece இருபது")]
    posted = json.loads(db._draft_to_json(resolved))
    response = client.post(
        session_url + "/approve", json={"items": [posted], "confirmed": []})
    assert response.status_code in (302, 303)
    version_id = _published_version(tmp_path)
    assert version_id is not None
    conn = db.connect(tmp_path / "data")
    try:
        items = db.version_items(conn, version_id)
    finally:
        conn.close()
    assert len(items) == 1
    assert [(line.price, line.per_amount, line.unit)
            for line in items[0].price_lines] == [(Decimal(20), Decimal(5), "piece")]


def test_js_line_choice_keeps_tapped_line():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/review_line_choice143.test.mjs"], cwd=ROOT,
        check=False, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
