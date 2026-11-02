"""Task 38: price tags PDF, board photo to price list, purchases and margin."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

IST = ZoneInfo("Asia/Kolkata")


def pl(price, per_amount, unit, said=""):
    return PriceLine(
        Decimal(price) if price is not None else None,
        Decimal(per_amount) if per_amount is not None else None,
        unit,
        said,
    )


def make_client(tmp_path, monkeypatch=None):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    app = create_app(load_settings(env))
    if monkeypatch is not None:
        monkeypatch.setattr("app.web.seller.jobs.submit", lambda fn, *a: fn(*a))
        monkeypatch.setattr("app.web.purchases.jobs.submit", lambda fn, *a: fn(*a))
    client = TestClient(app, follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client):
    response = client.post("/new", data={
        "name": "Kannan Store", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"]


def token_of(location):
    return location.split("/e/")[1]


def seed_published(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def draft_tomato(price=40):
    return DraftItem(
        name_spoken="thakkali", name_local="தக்காளி", name_en="tomato",
        variety=None, price_lines=[pl(price, 1, "kg", "kilo forty")],
        qty=None, qty_unit=None,
        proof=Proof(quote="thakkali kilo forty", turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def draft_onion(price=30):
    return DraftItem(
        name_spoken="vengayam", name_local="வெங்காயம்", name_en="onion",
        variety=None, price_lines=[pl(price, 1, "kg", "kilo thirty")],
        qty=None, qty_unit=None,
        proof=Proof(quote="vengayam kilo thirty", turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def pypdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def jpeg_bytes(size=(64, 48), color="white"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


# --- 1. price tags PDF ---

def test_tags_pdf_renders_eight_per_page_with_tamil_and_money(tmp_path):
    from app.outputs.pdf import price_tags_pdf

    shop = {"name": "Kannan Store", "slug": "kannan-store", "area": "Koyambedu",
            "phone": "+914400000000", "currency": "INR"}
    from app.models import Item
    items = [
        Item(id=1, version_id=1, name_local="தக்காளி", name_en="tomato",
             variety=None, qty=None, qty_unit=None, photo=None, sold_out=False,
             price_lines=[pl(40, 1, "kg")],
             proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0)),
        Item(id=2, version_id=1, name_local="வெங்காயம்", name_en="onion",
             variety=None, qty=None, qty_unit=None, photo=None, sold_out=False,
             price_lines=[pl(30, 1, "kg")],
             proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0)),
    ]
    pdf = price_tags_pdf(
        shop, items, datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/kannan-store")
    assert pdf[:5] == b"%PDF-"
    text = pypdf_text(pdf)
    assert "₹40" in text and "₹30" in text
    assert "tomato" in text and "onion" in text
    assert "Today," in text


def test_tags_pdf_skips_sold_out(tmp_path):
    from app.outputs.pdf import price_tags_pdf

    shop = {"name": "S", "slug": "s", "area": "A", "phone": "1", "currency": "INR"}
    from app.models import Item
    items = [
        Item(id=1, version_id=1, name_local="தக்காளி", name_en="tomato",
             variety=None, qty=None, qty_unit=None, photo=None, sold_out=True,
             price_lines=[pl(40, 1, "kg")],
             proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0)),
        Item(id=2, version_id=1, name_local="வெங்காயம்", name_en="onion",
             variety=None, qty=None, qty_unit=None, photo=None, sold_out=False,
             price_lines=[pl(30, 1, "kg")],
             proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0)),
    ]
    pdf = price_tags_pdf(
        shop, items, datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/s")
    text = pypdf_text(pdf)
    assert "₹30" in text
    assert "₹40" not in text


def test_tags_template_has_grid_qr_cutlines_and_money():
    src = (Path("app/web/templates/tags.html")).read_text()
    assert "money" in src
    assert "qr_data_uri" in src or "qr" in src.lower()
    # Task 40: date line is translated via the tags.today catalogue key.
    assert "tags.today" in src
    # 2 columns x 4 rows layout + cut lines between tags.
    assert "2" in src and "4" in src or "grid" in src.lower()
    assert "dashed" in src.lower() or "cut" in src.lower()


def test_tags_route_and_dashboard_tile(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    token = token_of(location)
    seed_published(tmp_path, token, [draft_tomato(), draft_onion()])
    resp = client.get(f"/e/{token}/tags.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"
    text = pypdf_text(resp.content)
    assert "₹40" in text
    html = client.get(f"/e/{token}").text
    assert "Print price tags" in html
    assert "Print board" in html
    assert f"/e/{token}/tags.pdf" in html


# --- 2. board photo to price list ---

BOARD_JSON = {
    "lines": [
        {"name_as_written": "தக்காளி", "name_en": "tomato",
         "name_local": "தக்காளி", "price": 40, "read": "40",
         "per_amount": 1, "unit": "kg"},
        {"name_as_written": "வெங்காயம்", "name_en": "onion",
         "name_local": "வெங்காயம்", "price": 30, "read": "30",
         "per_amount": 1, "unit": "kg"},
    ]
}


def test_board_prompt_reads_only_written_never_guesses(tmp_path):
    from app.pipeline.board import build_board_messages

    board = tmp_path / "board.jpg"
    board.write_bytes(jpeg_bytes())
    messages = build_board_messages(board)
    blob = json.dumps(messages).lower()
    assert "read only what is written" in blob
    assert "never guess" in blob
    # image part forces Meta vision.
    assert "image_url" in json.dumps(messages)


def test_board_parse_adds_confirm_flag_on_every_line(tmp_path):
    from app.pipeline.board import parse_board_json

    items = parse_board_json(BOARD_JSON, "/tmp/board.jpg")
    assert len(items) == 2
    for item in items:
        assert item.proof.source == "board_photo"
        assert len(item.price_lines) == 1
        codes = [f.code for f in item.flags if f.blocking]
        assert "BOARD_CONFIRM" in codes
        flag = next(f for f in item.flags if f.code == "BOARD_CONFIRM")
        assert "read from your board" in flag.message.lower()
        assert flag.options == [str(item.price_lines[0].price)]
        # exact characters read kept in said.
        assert item.price_lines[0].said == str(item.price_lines[0].price)


def test_board_unreadable_gets_not_read(tmp_path):
    from app.pipeline.board import parse_board_json

    data = {"lines": [
        {"name_as_written": "???", "name_en": "tomato",
         "name_local": "தக்காளி", "price": None, "read": "",
         "per_amount": 1, "unit": "kg"},
    ]}
    items = parse_board_json(data, "/tmp/board.jpg")
    assert items[0].price_lines[0].price is None
    codes = [f.code for f in items[0].flags if f.blocking]
    assert "NOT_READ" in codes


def test_board_unit_normalised_and_canonical_name(tmp_path):
    from app.pipeline.board import parse_board_json

    data = {"lines": [
        {"name_as_written": "thakkali", "name_en": "Tomato",
         "name_local": "", "price": 40, "read": "40",
         "per_amount": 1, "unit": "kilo"},
    ]}
    items = parse_board_json(data, "/tmp/board.jpg")
    assert items[0].name_en == "tomato"
    assert items[0].price_lines[0].unit == "kg"
    assert items[0].name_local == "தக்காளி"


def test_board_never_fills_missing_price(tmp_path):
    from app.pipeline.board import parse_board_json

    data = {"lines": [
        {"name_as_written": "tomato", "name_en": "tomato",
         "name_local": "தக்காளி", "price": None, "read": None,
         "per_amount": None, "unit": None},
    ]}
    items = parse_board_json(data, "/tmp/board.jpg")
    line = items[0].price_lines[0]
    assert line.price is None
    assert line.per_amount is None
    assert line.unit is None


def test_board_upload_creates_session_and_review(tmp_path, monkeypatch):
    from app.pipeline.board import BOARD_JSON_EXAMPLE  # noqa: F401  (exists)
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    # Prices area advertises the board photo.
    assert "Photo of your price board" in client.get(f"{location}/update").text
    monkeypatch.setattr(
        "app.pipeline.board.chat_json", lambda messages, **kw: dict(BOARD_JSON))
    resp = client.post(
        f"{location}/board",
        files={"photo": ("board.jpg", jpeg_bytes(), "image/jpeg")})
    assert resp.status_code in (302, 303)
    session_url = resp.headers["location"]
    assert "/s/" in session_url
    conn = db.connect(tmp_path / "data")
    try:
        session_id = int(session_url.rsplit("/s/", 1)[1])
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row["kind"] == "board"
        assert row["status"] == "review"
        drafts = db.load_drafts(conn, session_id)
        assert len(drafts) == 2
        assert all(d.proof.source == "board_photo" for d in drafts)
        assert all(any(f.code == "BOARD_CONFIRM" and f.blocking
                       for f in d.flags) for d in drafts)
    finally:
        conn.close()
    html = client.get(session_url).text
    assert "Read from your board" in html
    assert "Play what you said" not in html


def test_board_approve_needs_confirm_then_publishes(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    token = token_of(location)
    monkeypatch.setattr(
        "app.pipeline.board.chat_json", lambda messages, **kw: dict(BOARD_JSON))
    session_url = client.post(
        f"{location}/board",
        files={"photo": ("board.jpg", jpeg_bytes(), "image/jpeg")},
    ).headers["location"]
    conn = db.connect(tmp_path / "data")
    try:
        session_id = int(session_url.rsplit("/s/", 1)[1])
        drafts = db.load_drafts(conn, session_id)
        raw_items = [json.loads(db._draft_to_json(d)) for d in drafts]
        shop = db.shop_by_token(conn, token)
    finally:
        conn.close()
    # Nothing visible before approval.
    assert client.get(f"/s/{shop['slug']}").status_code == 200
    assert "₹40" not in client.get(f"/s/{shop['slug']}").text
    # Approve without ticks is rejected with needs_confirm.
    denied = client.post(session_url + "/approve",
                         json={"items": raw_items, "confirmed": []})
    assert denied.status_code == 400
    assert "needs_confirm" in denied.json()
    # Ticking every card publishes.
    ok = client.post(session_url + "/approve",
                     json={"items": raw_items,
                           "confirmed": list(range(len(raw_items)))})
    assert ok.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"])
        db.set_published(conn, version_id, True)
        slug = shop["slug"]
    finally:
        conn.close()
    assert "₹40" in client.get(f"/s/{slug}").text


# --- 3. purchases ---

PURCHASE_JSON = {
    "items": [
        {"name_spoken": "vengayam", "name_en": "onion",
         "name_local": "வெங்காயம்", "qty": 50, "unit": "kg",
         "total_cost": 1200, "quote": "vengayam 50 kilo 1200 rupees",
         "turn_ids": [1]},
    ]
}


def test_purchase_extract_heard_numbers(tmp_path, monkeypatch):
    from app.models import Transcript, Turn
    from app.pipeline.purchase import parse_purchase_json

    transcript = Transcript(
        text="vengayam 50 kilo 1200 rupees", duration_ms=2000,
        turns=[Turn(id=1, start_ms=0, end_ms=2000,
                    text="vengayam 50 kilo 1200 rupees")])
    drafts = parse_purchase_json(dict(PURCHASE_JSON), transcript, language="ta")
    assert len(drafts) == 1
    assert drafts[0].qty == Decimal(50)
    assert drafts[0].unit == "kg"
    assert drafts[0].total_cost == Decimal(1200)
    assert drafts[0].flags == [] or all(not f.blocking for f in drafts[0].flags)


def test_purchase_unheard_number_flagged(tmp_path):
    from app.models import Transcript, Turn
    from app.pipeline.purchase import parse_purchase_json

    transcript = Transcript(
        text="vengayam kilo rupees", duration_ms=2000,
        turns=[Turn(id=1, start_ms=0, end_ms=2000,
                    text="vengayam kilo rupees")])
    data = {"items": [
        {"name_spoken": "vengayam", "name_en": "onion",
         "name_local": "வெங்காயம்", "qty": 50, "unit": "kg",
         "total_cost": 1200, "quote": "vengayam kilo rupees",
         "turn_ids": [1]},
    ]}
    drafts = parse_purchase_json(data, transcript, language="ta")
    assert any(f.blocking for f in drafts[0].flags)


def test_purchase_cost_and_margin_math():
    from app.purchases import cost_per_unit, margin_text

    cost, unit = cost_per_unit(Decimal(50), "kg", Decimal(1200))
    assert cost == Decimal(24)
    assert unit == "kg"
    text = margin_text(Decimal(24), "kg", Decimal(40), "kg", currency="INR")
    assert "₹24" in text and "₹40" in text
    assert "+₹16" in text
    assert "67%" in text


def test_purchases_voice_and_typed_rows(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    token = token_of(location)
    seed_published(tmp_path, token, [draft_onion(price=40)])
    assert client.get(f"{location}/purchases").status_code == 200

    from app.models import Transcript, Turn

    def fake_transcribe(wav, **kwargs):
        return Transcript(
            text="onion 50 kilo 1200 rupees", duration_ms=2000,
            turns=[Turn(id=1, start_ms=0, end_ms=2000,
                        text="onion 50 kilo 1200 rupees")])

    monkeypatch.setattr("app.pipeline.purchase.transcribe_wav", fake_transcribe)
    monkeypatch.setattr(
        "app.pipeline.purchase.chat_json", lambda messages, **kw: dict(PURCHASE_JSON))
    monkeypatch.setattr(
        "app.pipeline.purchase.extract_audio",
        lambda src, dst: Path(dst).touch() or Path(dst))
    resp = client.post(
        f"{location}/purchases/voice",
        files={"audio": ("buy.webm", b"fakeaudio", "audio/webm")})
    assert resp.status_code in (302, 303)
    confirm_url = resp.headers["location"]
    html = client.get(confirm_url).text
    assert "1200" in html or "₹" in html
    # confirm URL is /e/{token}/purchases/{session_id}
    done = client.post(confirm_url + "/confirm", data={"confirmed": "on"})
    assert done.status_code in (302, 303)
    page = client.get(f"{location}/purchases").text
    assert "₹24" in page or "24" in page

    # Typed row.
    typed = client.post(f"{location}/purchases/add", data={
        "item": "tomato", "quantity": "10", "unit": "kg", "total_paid": "200"})
    assert typed.status_code in (302, 303)
    page2 = client.get(f"{location}/purchases").text
    assert "tomato" in page2.lower()


def test_purchases_stock_left_after_bills_kg_g(tmp_path):
    from app import purchases as pur

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000000", area="A", language="ta",
            currency="INR", shop_type="vegetable")
        today = datetime.now(UTC).astimezone(IST).date().isoformat()
        pur.add_purchase(conn, shop_id, today, "onion", Decimal(50), "kg",
                         Decimal(1200), source="voice")
        # Sold 2000 g across billed/paid bills.
        from app.market.quote import Quote, QuoteLine
        quote = Quote(lines=[QuoteLine("onion", "", Decimal(2000), "g",
                                       Decimal(40), Decimal(1),
                                       Decimal("80.00"), "priced")],
                      total=Decimal("80.00"), priced_count=1, unpriced_count=0,
                      prices_set_at=datetime.now(UTC))
        db.create_quote(conn, shop_id=shop_id, quote=quote, source="seller",
                        kind="bill", status="billed")
        left, unit = pur.stock_left(conn, shop_id, "onion", today)
        assert unit == "kg"
        assert left == Decimal(48)
    finally:
        conn.close()


def test_dashboard_spent_and_margin_chip(tmp_path, monkeypatch):
    from app import purchases as pur

    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    token = token_of(location)
    seed_published(tmp_path, token, [draft_onion(price=40)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        today = datetime.now(UTC).astimezone(IST).date().isoformat()
        pur.add_purchase(conn, shop["id"], today, "onion", Decimal(50), "kg",
                         Decimal(1200), source="voice")
    finally:
        conn.close()
    html = client.get(f"/e/{token}").text
    # Task 52 merged the tile grid into one quick-links grid: the spent
    # figure lives on the purchases page; the margin chip stays here.
    assert "67%" in html or "margin" in html.lower()
    pur_html = client.get(f"/e/{token}/purchases").text
    assert "Spent today" in pur_html
    assert "₹1,200" in pur_html or "₹1200" in pur_html or "1200" in pur_html
