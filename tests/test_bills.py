"""Task 28: seller bills dashboard, new bill, bill PDF (fakes, no network)."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import load_settings
from app.costs import IST
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.names import CANONICAL_NAMES

QUOTE = "bill tomato secret"
CLIP = "/tmp/clips/bill_item.m4a"


def draft(name_en, price, per_amount=1, unit="kg", variety=None):
    return DraftItem(
        name_spoken=name_en,
        name_local=CANONICAL_NAMES[name_en],
        name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None,
        qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[1], start_ms=0, end_ms=1000,
                    audio_clip=CLIP),
    )


def make_shop(conn, name="Bill Stall", area="Koyambedu", listed=True):
    return db.create_shop(
        conn, name=name, phone="+914400000001", area=area,
        language="ta", currency="INR", shop_type="vegetable",
        is_demo=False, is_judge=False, listed=listed)


def publish(conn, shop_id, drafts):
    session_id = db.create_session(conn, shop_id, "video")
    version_id = db.approve(conn, session_id, drafts)
    db.set_published(conn, version_id, True)
    return version_id


def seed_standard(conn):
    shop_id, slug, token = make_shop(conn)
    publish(conn, shop_id, [
        draft("tomato", 18, 1, "kg"),
        draft("banana", 60, 1, "dozen"),
        draft("coconut", 15, 1, "piece"),
    ])
    return shop_id, slug, token


def make_client(tmp_path, **kwargs):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    env.update(kwargs.get("extra_env") or {})
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def seed_published(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        return seed_standard(conn)
    finally:
        conn.close()


def _ist_noon_utc_iso(days_ago=0):
    noon = datetime.now(IST).replace(hour=12, minute=0, second=0,
                                    microsecond=0) - timedelta(days=days_ago)
    return noon.astimezone(UTC).isoformat()


def _make_quote(conn, shop_id, lines, total):
    from app.market.quote import Quote

    return Quote(lines=lines, total=total, priced_count=len(lines),
                 unpriced_count=0, prices_set_at=datetime.now(UTC))


def _make_line(name_en, qty, unit, unit_price, per_amount, line_total,
               status="priced"):
    from app.market.quote import QuoteLine

    return QuoteLine(name_en=name_en, name_local="", qty=Decimal(qty),
                     unit=unit, unit_price=Decimal(unit_price),
                     per_amount=Decimal(per_amount),
                     line_total=Decimal(line_total), status=status)


def seed_tiles(conn, shop_id):
    """Two bills today (36 + 30), one quote waiting, one bill yesterday."""
    from app.market.quote import QuoteLine

    bill1 = _make_quote(conn, shop_id, [
        _make_line("tomato", 2, "kg", 18, 1, "36.00"),
    ], Decimal("36.00"))
    t1 = db.create_quote(conn, shop_id=shop_id, quote=bill1, source="seller",
                         kind="bill", status="billed")
    bill2 = _make_quote(conn, shop_id, [
        _make_line("coconut", 2, "piece", 15, 1, "30.00"),
    ], Decimal("30.00"))
    t2 = db.create_quote(conn, shop_id=shop_id, quote=bill2, source="seller",
                         kind="bill", status="paid")
    quote = _make_quote(conn, shop_id, [
        QuoteLine(name_en="tomato", name_local="", qty=Decimal(1), unit="kg",
                  unit_price=Decimal(18), per_amount=Decimal(1),
                  line_total=Decimal("18.00"), status="priced"),
    ], Decimal("18.00"))
    t3 = db.create_quote(conn, shop_id=shop_id, quote=quote, source="customer",
                         kind="quote", status="new")
    old = _make_quote(conn, shop_id, [
        _make_line("banana", 1, "dozen", 60, 1, "60.00"),
    ], Decimal("60.00"))
    t4 = db.create_quote(conn, shop_id=shop_id, quote=old, source="seller",
                         kind="bill", status="billed")
    conn.execute("UPDATE quotes SET created_at = ? WHERE token = ?",
                 (_ist_noon_utc_iso(0), t1))
    conn.execute("UPDATE quotes SET created_at = ? WHERE token = ?",
                 (_ist_noon_utc_iso(0), t2))
    conn.execute("UPDATE quotes SET created_at = ? WHERE token = ?",
                 (_ist_noon_utc_iso(0), t3))
    conn.execute("UPDATE quotes SET created_at = ? WHERE token = ?",
                 (_ist_noon_utc_iso(1), t4))
    conn.commit()
    ids = {}
    for token in (t1, t2, t3, t4):
        row = db.get_quote_by_token(conn, token)
        ids[token] = row["id"]
    return {"today_billed": t1, "today_paid": t2, "waiting": t3,
            "yesterday": t4, "ids": ids}


# --- tiles math ---

def test_tiles_math_today_vs_other_days(tmp_path):
    from app.web.bills import bills_tiles

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        seed_tiles(conn, shop_id)
        # An 8-day-old bill must not leak into today's sales.
        old = _make_quote(conn, shop_id, [
            _make_line("tomato", 10, "kg", 18, 1, "180.00"),
        ], Decimal("180.00"))
        token = db.create_quote(conn, shop_id=shop_id, quote=old,
                                source="seller", kind="bill", status="paid")
        conn.execute("UPDATE quotes SET created_at = ? WHERE token = ?",
                     (_ist_noon_utc_iso(8), token))
        conn.commit()
        tiles = bills_tiles(conn, shop_id, now=datetime.now(UTC))
        assert tiles["bills_today"] == 2
        assert tiles["sales_today"] == Decimal("66.00")
        assert tiles["quotes_waiting"] == 1
        assert tiles["average_bill"] == Decimal("33.00")
    finally:
        conn.close()


def test_tiles_empty_shop_is_zero(tmp_path):
    from app.web.bills import bills_tiles

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn)
        tiles = bills_tiles(conn, shop_id, now=datetime.now(UTC))
        assert tiles["bills_today"] == 0
        assert tiles["sales_today"] == Decimal("0.00")
        assert tiles["average_bill"] == Decimal("0.00")
        assert tiles["quotes_waiting"] == 0
    finally:
        conn.close()


# --- bills list page, filters, auth ---

def test_bills_page_needs_seller_token(tmp_path):
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    assert client.get("/e/badtoken123/bills").status_code == 404
    assert client.get("/e/badtoken123/bills/new").status_code == 404
    assert client.get("/e/badtoken123/bills/1").status_code == 404
    assert client.get(f"/e/{token}/bills/99999").status_code == 404
    assert client.get(f"/e/{token}/bills").status_code == 200


def test_bills_page_tiles_filters_and_top_items(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        tokens = seed_tiles(conn, shop_id)
        ids = tokens["ids"]
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills").text
    assert "Bills" in html
    assert "Today" in html and "Yesterday" in html and "Last 7 days" in html
    assert "New bill" in html
    assert "All" in html and "Quotes waiting" in html
    assert "Billed" in html and "Paid" in html
    assert "Walk-in" in html
    assert "Top items today" in html
    assert "Tomato" in html or "tomato" in html
    assert "style=" not in html
    # Status filter: paid shows only the paid bill link.
    paid_html = client.get(f"/e/{token}/bills",
                           params={"status": "paid"}).text
    assert f"/e/{token}/bills/{ids[tokens['today_paid']]}" in paid_html
    assert f"/e/{token}/bills/{ids[tokens['today_billed']]}" not in paid_html
    waiting_html = client.get(f"/e/{token}/bills",
                              params={"status": "waiting"}).text
    assert f"/e/{token}/bills/{ids[tokens['waiting']]}" in waiting_html
    assert f"/e/{token}/bills/{ids[tokens['today_paid']]}" not in waiting_html
    billed_html = client.get(f"/e/{token}/bills",
                             params={"status": "billed"}).text
    assert f"/e/{token}/bills/{ids[tokens['today_billed']]}" in billed_html
    assert f"/e/{token}/bills/{ids[tokens['today_paid']]}" not in billed_html
    # Date range: yesterday shows only yesterday's bill.
    yesterday_html = client.get(f"/e/{token}/bills",
                                params={"range": "yesterday"}).text
    assert f"/e/{token}/bills/{ids[tokens['yesterday']]}" in yesterday_html
    assert f"/e/{token}/bills/{ids[tokens['today_paid']]}" not in yesterday_html
    week_html = client.get(f"/e/{token}/bills",
                           params={"range": "week"}).text
    assert f"/e/{token}/bills/{ids[tokens['yesterday']]}" in week_html
    assert f"/e/{token}/bills/{ids[tokens['today_paid']]}" in week_html


def test_bills_page_empty_state(tmp_path):
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    html = client.get(f"/e/{token}/bills").text
    assert "No bills yet" in html or "no bills" in html.lower()
    assert "New bill" in html


# --- new bill by tapping ---

def test_new_bill_page_has_four_ways(tmp_path):
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    html = client.get(f"/e/{token}/bills/new").text
    assert "Tap items" in html or "tap" in html.lower()
    assert "Speak" in html
    assert "Type" in html
    assert "Photo" in html
    assert "Tomato" in html or "tomato" in html
    assert "style=" not in html


def test_new_bill_by_tapping_computes_totals_server_side(tmp_path):
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    response = client.post(
        f"/e/{token}/bills/new",
        data={"name_en_0": "tomato", "qty_0": "2", "unit_0": "kg",
              "name_en_1": "coconut", "qty_1": "1", "unit_1": "piece",
              "unit_price_0": "1", "line_total_0": "1", "total": "1"})
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    assert location.startswith(f"/e/{token}/bills/")
    html = client.get(location).text
    assert "₹36" in html and "₹15" in html and "₹51" in html
    conn = db.connect(tmp_path / "data")
    try:
        bill_id = int(location.rsplit("/", 1)[1])
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        assert row["source"] == "seller"
        assert row["kind"] == "bill"
        assert row["status"] == "billed"
        assert row["total"] == "51.00"
        lines = json.loads(row["lines_json"])
        assert [line["line_total"] for line in lines] == ["36.00", "15.00"]
    finally:
        conn.close()


def test_new_bill_tap_needs_one_item(tmp_path):
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    response = client.post(f"/e/{token}/bills/new",
                           data={"name_en_0": "tomato", "qty_0": "0",
                                 "unit_0": "kg"})
    assert response.status_code == 400


def test_new_bill_by_typing_uses_quote_engine(tmp_path, monkeypatch):
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [{"name": "tomato", "amount": 1, "unit": "kg",
                        "max_rate": None}],
             "budget": None, "area": None}))
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    response = client.post(f"/e/{token}/bills/new",
                           data={"items": "1 kg tomato"})
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    conn = db.connect(tmp_path / "data")
    try:
        bill_id = int(location.rsplit("/", 1)[1])
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        assert row["source"] == "seller" and row["kind"] == "bill"
        assert row["total"] == "18.00"
    finally:
        conn.close()


# --- bill page actions ---

def _seed_bill_id(tmp_path, shop_id):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        quote = build_quote(
            conn, shop_id,
            [WantedLine("tomato", Decimal(1), "kg", "text")])
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                source="seller", kind="bill", status="billed")
        row = db.get_quote_by_token(conn, token)
        return row["id"]
    finally:
        conn.close()


def test_bill_page_edits_recompute_and_add_remove(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = _seed_bill_id(tmp_path, shop_id)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Paid by cash" in html and "Paid by UPI" in html
    assert "WhatsApp" in html
    assert "Print" in html or "PDF" in html
    assert "style=" not in html
    # Edit qty server side; smuggled totals ignored.
    response = client.post(
        f"/e/{token}/bills/{bill_id}/lines",
        data={"name_en_0": "tomato", "qty_0": "3", "unit_0": "kg",
              "line_total_0": "1", "total": "1"})
    assert response.status_code in (302, 303)
    assert "₹54" in client.get(f"/e/{token}/bills/{bill_id}").text
    # Add a coconut line.
    response = client.post(
        f"/e/{token}/bills/{bill_id}/add",
        data={"name_en": "coconut", "qty": "2", "unit": "piece",
              "unit_price": "999"})
    assert response.status_code in (302, 303)
    assert "₹84" in client.get(f"/e/{token}/bills/{bill_id}").text
    # Remove the tomato line (index 0); coconut remains.
    response = client.post(f"/e/{token}/bills/{bill_id}/remove",
                           data={"index": "0"})
    assert response.status_code in (302, 303)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "₹30" in html


def test_accept_quote_converts_kind_status(tmp_path):
    from app.market.quote import WantedLine, build_quote

    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        quote = build_quote(
            conn, shop_id, [WantedLine("tomato", Decimal(1), "kg", "text")])
        quote_token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                      source="customer", kind="quote",
                                      status="new")
        quote_id = db.get_quote_by_token(conn, quote_token)["id"]
    finally:
        conn.close()
    assert "Accept quote" in client.get(f"/e/{token}/bills/{quote_id}").text
    response = client.post(f"/e/{token}/bills/{quote_id}/accept")
    assert response.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (quote_id,)).fetchone()
        assert row["kind"] == "bill"
        assert row["status"] == "billed"
    finally:
        conn.close()
    assert "Paid by cash" in client.get(f"/e/{token}/bills/{quote_id}").text


def test_mark_paid(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = _seed_bill_id(tmp_path, shop_id)
    response = client.post(f"/e/{token}/bills/{bill_id}/paid")
    assert response.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        assert row["status"] == "paid"
    finally:
        conn.close()
    assert "Paid" in client.get(f"/e/{token}/bills/{bill_id}").text


def test_customer_phone_and_whatsapp_link(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = _seed_bill_id(tmp_path, shop_id)
    response = client.post(f"/e/{token}/bills/{bill_id}/phone",
                           data={"customer_phone": "+91 98765 43210"})
    assert response.status_code in (302, 303)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "98765" in html
    assert "https://wa.me/919876543210?text=" in html
    assert "18" in html
    # Bill text is URL-encoded in the link.
    assert "%20" in html or "%0A" in html


def test_bill_pdf_renders_receipt(tmp_path):
    from pypdf import PdfReader

    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = _seed_bill_id(tmp_path, shop_id)
    pdf = client.get(f"/e/{token}/bills/{bill_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"
    text = "\n".join(page.extract_text() or ""
                     for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Thank you" in text
    assert "18" in text
    assert str(bill_id) in text


def test_bill_prices_only_from_shop_list(tmp_path, monkeypatch):
    import random

    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, token = seed_standard(conn)
        version_id = db.latest_version(conn, shop_id, published_only=True)
        shop_prices = {
            (line.price, line.per_amount, line.unit)
            for item in db.version_items(conn, version_id)
            for line in item.price_lines if line.price is not None
        }
        shop_values = {price for price, _, _ in shop_prices}
        rng = random.Random(28)
        names = ["tomato", "banana", "coconut", "dragonfruit", "onion"]
        units = ["kg", "g", "dozen", "piece", None]
        for _ in range(20):
            wanted = [WantedLine(rng.choice(names),
                                 Decimal(rng.randint(1, 4)), rng.choice(units),
                                 "seller")
                      for _ in range(rng.randint(1, 3))]
            quote = build_quote(conn, shop_id, wanted)
            db.create_quote(conn, shop_id=shop_id, quote=quote,
                            source="seller", kind="bill", status="billed")
            for line in quote.lines:
                if line.unit_price is not None:
                    assert line.unit_price in shop_values
                if line.status in ("not_on_list", "sold_out"):
                    assert line.line_total is None
    finally:
        conn.close()
    # Unknown tap item is shown without a price, never priced.
    client = make_client(tmp_path)
    response = client.post(
        f"/e/{token}/bills/new",
        data={"name_en_0": "dragonfruit", "qty_0": "2", "unit_0": "kg",
              "name_en_1": "tomato", "qty_1": "1", "unit_1": "kg"})
    assert response.status_code in (302, 303)
    html = client.get(response.headers["location"]).text
    assert "not on this shop's list" in html
    assert "₹18" in html


# --- voice/photo background ---

def test_bill_voice_background_creates_seller_bill(tmp_path, monkeypatch):
    from app.models import Transcript, Turn

    monkeypatch.setattr("app.web.bills.jobs.submit", lambda fn, *a: fn(*a))
    monkeypatch.setattr(
        "app.web.bills.extract_audio",
        lambda src, out: Path(out).write_bytes(b"wav") or Path(out))
    monkeypatch.setattr(
        "app.web.bills.transcribe_wav",
        lambda wav, **kw: Transcript(text="1 kg tomato", duration_ms=1000,
                                     turns=[Turn(1, 0, 1000, "1 kg tomato")]))
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [{"name": "tomato", "amount": 1, "unit": "kg",
                        "max_rate": None}],
             "budget": None, "area": None}))
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    response = client.post(
        f"/e/{token}/bills/new",
        files={"audio": ("order.webm", b"fake-audio", "audio/webm")})
    assert response.status_code in (302, 303)
    assert "/bills/new/" in response.headers["location"]
    payload = client.get(response.headers["location"] + "/status").json()
    assert [s["key"] for s in payload["steps"]] == [
        "received", "listening", "matching", "ready"]
    assert payload["bill_id"]
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (payload["bill_id"],)).fetchone()
        assert row["source"] == "seller" and row["kind"] == "bill"
        assert row["total"] == "18.00"
    finally:
        conn.close()


def test_bill_photo_background_creates_seller_bill(tmp_path, monkeypatch):
    from app.pipeline.vision import DetectedProduct, PhotoReport

    monkeypatch.setattr("app.web.bills.jobs.submit", lambda fn, *a: fn(*a))
    monkeypatch.setattr(
        "app.market.quote.chat_json",
        lambda messages, **kw: {"kind": "items",
                                "products": [{"name_en": "coconut",
                                              "countable": True}]})
    monkeypatch.setattr(
        "app.market.quote.analyse_photo",
        lambda photo, **kw: PhotoReport(
            products=[DetectedProduct(name_en="coconut", countable=True,
                                      count=2)],
            quality="good", suggestions=[], cost_usd=0.0))
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(buf, "JPEG")
    response = client.post(
        f"/e/{token}/bills/new",
        files={"photo": ("basket.jpg", buf.getvalue(), "image/jpeg")})
    assert response.status_code in (302, 303)
    payload = client.get(response.headers["location"] + "/status").json()
    assert [s["key"] for s in payload["steps"]] == [
        "received", "looking", "matching", "ready"]
    assert payload["bill_id"]


# --- seller dashboard ---

def test_seller_dashboard_links_bills_and_tile(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        seed_tiles(conn, shop_id)
    finally:
        conn.close()
    html = client.get(f"/e/{token}").text
    assert f'href="/e/{token}/bills"' in html
    assert "Bills" in html
    assert "66" in html
