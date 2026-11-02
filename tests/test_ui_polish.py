"""Task 32: receipt-style bill and quote, method tabs, photo polish.

Templates, CSS and small JS only: routes, form field names, JSON shapes
and business logic are unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.names import CANONICAL_NAMES
from app.web.main import create_app


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "web" / "templates"


def make_client(tmp_path):
    settings = load_settings(
        {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    return client


def seed_shop(tmp_path, *, name="Polish Stall", items=(("tomato", 20, 1, "kg"),
                                                       ("onion", 30, 1, "kg"),
                                                       ("ginger", 150, 1, "kg"))):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name=name, phone="+914400000001", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable",
            is_demo=False, is_judge=False, listed=True)
        if items:
            drafts = [
                DraftItem(
                    name_spoken=n, name_local=CANONICAL_NAMES[n], name_en=n,
                    variety=None,
                    price_lines=[PriceLine(Decimal(p), Decimal(a), u)],
                    qty=None, qty_unit=None,
                    proof=Proof(quote=f"{n} {p}", turn_ids=[1],
                                start_ms=0, end_ms=1000),
                )
                for n, p, a, u in items
            ]
            session_id = db.create_session(conn, shop_id, "video")
            version_id = db.approve(conn, session_id, drafts)
            db.set_published(conn, version_id, True)
        return slug, token, shop_id
    finally:
        conn.close()


def seed_bill(tmp_path, shop_id, *, kind="bill", status="billed"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        quote = Quote(
            lines=[
                QuoteLine(name_en="tomato", name_local="தக்காளி",
                          qty=Decimal(2), unit="kg", unit_price=Decimal(20),
                          per_amount=Decimal(1), line_total=Decimal("40.00"),
                          status="priced"),
                QuoteLine(name_en="ginger", name_local="இஞ்சி",
                          qty=Decimal("0.5"), unit="kg",
                          unit_price=Decimal(150), per_amount=Decimal(1),
                          line_total=Decimal("75.00"), status="priced"),
            ],
            total=Decimal("115.00"), priced_count=2, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                source="seller", kind=kind, status=status)
        return db.get_quote_by_token(conn, token)["id"]
    finally:
        conn.close()


def seed_quote(tmp_path, shop_id):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        quote = Quote(
            lines=[
                QuoteLine(name_en="tomato", name_local="தக்காளி",
                          qty=Decimal(2), unit="kg", unit_price=Decimal(20),
                          per_amount=Decimal(1), line_total=Decimal("40.00"),
                          status="priced"),
                QuoteLine(name_en="onion", name_local="வெங்காயம்",
                          qty=Decimal(1), unit="kg", unit_price=Decimal(30),
                          per_amount=Decimal(1), line_total=Decimal("30.00"),
                          status="priced"),
                QuoteLine(name_en="dragonfruit", name_local="",
                          qty=Decimal(1), unit=None, unit_price=None,
                          per_amount=None, line_total=None,
                          status="unknown"),
            ],
            total=Decimal("70.00"), priced_count=2, unpriced_count=1,
            prices_set_at=datetime.now(UTC))
        return db.create_quote(conn, shop_id=shop_id, quote=quote)
    finally:
        conn.close()


def seed_photo_check(tmp_path, shop_id):
    conn = db.connect(tmp_path / "data")
    try:
        report = {
            "quality": "good", "image_w": 64, "image_h": 48,
            "products": [
                {"name_en": "tomato", "name_local": "தக்காளி",
                 "countable": True, "count": 2, "count_range": None,
                 "needs_check": False, "count_spark": 2, "count_sam": 2,
                 "boxes": [{"x1": 1, "y1": 2, "x2": 10, "y2": 20,
                            "w": 64, "h": 48, "confidence": None},
                           {"x1": 12, "y1": 4, "x2": 22, "y2": 26,
                            "w": 64, "h": 48, "confidence": None}],
                 "condition": None},
                {"name_en": "onion", "name_local": "வெங்காயம்",
                 "countable": True, "count": 1, "count_range": None,
                 "needs_check": False, "count_spark": 1, "count_sam": 1,
                 "boxes": [{"x1": 30, "y1": 4, "x2": 40, "y2": 26,
                            "w": 64, "h": 48, "confidence": None}],
                 "condition": None},
            ],
            "suggestions": [],
        }
        return db.save_photo_check(
            conn, shop_id=shop_id, image_path="p1.jpg",
            report_json=json.dumps(report), cost=0.01)
    finally:
        conn.close()


# --- bill page ---

def test_bill_page_receipt_and_actions(tmp_path):
    _slug, token, shop_id = seed_shop(tmp_path)
    bill_id = seed_bill(tmp_path, shop_id)
    html = make_client(tmp_path).get(f"/e/{token}/bills/{bill_id}").text
    assert 'class="receipt"' in html or "receipt-card" in html
    assert "bill-actions" in html or "action-panel" in html
    assert "receipt-total" in html or "bill-total-row" in html
    assert f"Bill #{bill_id}" in html or f"Bill {bill_id}" in html
    assert "Paid by cash" in html


def test_bill_page_posts_same_fields(tmp_path):
    _slug, token, shop_id = seed_shop(tmp_path)
    bill_id = seed_bill(tmp_path, shop_id)
    html = make_client(tmp_path).get(f"/e/{token}/bills/{bill_id}").text
    assert f'action="/e/{token}/bills/{bill_id}/lines"' in html
    assert 'name="qty_0"' in html
    assert 'name="name_en_0"' in html
    assert 'name="unit_0"' in html
    assert f'action="/e/{token}/bills/{bill_id}/phone"' in html
    assert 'name="customer_phone"' in html
    assert f'action="/e/{token}/bills/{bill_id}/add"' in html
    assert 'name="name_en"' in html
    assert f'action="/e/{token}/bills/{bill_id}/paid"' in html
    assert f'action="/e/{token}/bills/{bill_id}/remove"' in html
    assert 'name="index"' in html


# --- quote page ---

def test_quote_total_card_before_lines(tmp_path):
    _slug, _token, shop_id = seed_shop(tmp_path)
    quote_token = seed_quote(tmp_path, shop_id)
    html = make_client(tmp_path).get(f"/q/{quote_token}").text
    total_at = html.find("quote-total")
    assert total_at != -1
    assert "Your total" in html
    first_line = html.find("receipt-line")
    assert first_line != -1
    assert total_at < first_line


def test_quote_groups_unpriced_after_priced(tmp_path):
    _slug, _token, shop_id = seed_shop(tmp_path)
    quote_token = seed_quote(tmp_path, shop_id)
    html = make_client(tmp_path).get(f"/q/{quote_token}").text
    priced_tomato = html.find("Tomato")
    priced_onion = html.find("Onion")
    unpriced = html.find("Dragonfruit")
    assert priced_tomato != -1 and priced_onion != -1 and unpriced != -1
    assert priced_tomato < unpriced and priced_onion < unpriced
    assert "not on this shop" in html
    assert "Send on WhatsApp" in html


# --- method tabs ---

def test_quote_start_has_segmented_control(tmp_path):
    slug, _token, _shop_id = seed_shop(tmp_path)
    html = make_client(tmp_path).get(f"/s/{slug}/quote").text
    assert "segmented" in html
    for panel in ("speak", "type", "photo"):
        assert f'data-panel="{panel}"' in html
    assert 'name="audio"' in html
    assert 'name="items"' in html
    assert 'name="photo"' in html
    assert html.count(f'action="/s/{slug}/quote') >= 3


def test_bills_new_has_tap_first_segmented_control(tmp_path):
    _slug, token, _shop_id = seed_shop(tmp_path)
    html = make_client(tmp_path).get(f"/e/{token}/bills/new").text
    assert "segmented" in html
    for panel in ("tap", "speak", "photo"):
        assert f'data-panel="{panel}"' in html
    assert 'data-panel="type"' not in html, \
        "type tab is the composer text mode now"
    tap_at = html.find('data-panel="tap"')
    speak_at = html.find('data-panel="speak"')
    assert tap_at != -1 and tap_at < speak_at
    assert 'name="qty_0"' in html
    assert 'name="audio"' in html
    assert 'name="items"' in html
    assert 'name="photo"' in html


# --- photo page ---

def test_photo_boxes_coloured_per_product_with_badges(tmp_path):
    _slug, token, shop_id = seed_shop(tmp_path)
    check_id = seed_photo_check(tmp_path, shop_id)
    html = make_client(tmp_path).get(f"/e/{token}/photos/{check_id}").text
    assert "box-c0" in html
    assert "box-c1" in html
    assert html.count("box-badge") >= 3


# --- shop empty state ---

def test_shop_empty_state_has_call_and_whatsapp(tmp_path):
    import html as html_lib

    slug, _token, _shop_id = seed_shop(tmp_path, items=())
    html = html_lib.unescape(make_client(tmp_path).get(f"/s/{slug}").text)
    assert "hasn't shared today's prices yet" in html
    assert "tel:" in html
    assert "wa.me/" in html
    assert "Call" in html and "WhatsApp" in html


# --- global template rules ---

def test_no_inline_styles_in_templates():
    offenders = [path.name for path in sorted(TEMPLATES.glob("*.html"))
                 if "style=" in path.read_text()]
    assert offenders == []


def test_every_svg_has_icon_class():
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text()
        pos = 0
        while True:
            at = text.find("<svg", pos)
            if at == -1:
                break
            end = text.find(">", at)
            assert end != -1, path.name
            tag = text[at:end]
            assert 'class="icon' in tag or "class='icon" in tag, (
                f"{path.name}: {tag[:80]}")
            pos = end + 1
