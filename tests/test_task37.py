"""Task 37: settings, UPI QR payments, cash helper, round-off, public bill link."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

QUOTE = "t37 secret quote"
CLIP = "/tmp/clips/t37.m4a"


def draft(name_en, price, per_amount=1, unit="kg"):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en,
        name_local=CANONICAL_NAMES[name_en],
        name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None,
        qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[1], start_ms=0, end_ms=1000,
                    audio_clip=CLIP),
    )


def make_shop(conn, name="T37 Stall", currency="INR", language="ta",
              phone="+914400000037"):
    return db.create_shop(
        conn, name=name, phone=phone, area="Koyambedu",
        language=language, currency=currency, shop_type="vegetable",
        listed=True)


def publish(conn, shop_id, drafts):
    session_id = db.create_session(conn, shop_id, "video")
    version_id = db.approve(conn, session_id, drafts)
    db.set_published(conn, version_id, True)
    return version_id


def seed_standard(conn, currency="INR", name="T37 Stall"):
    shop_id, slug, token = make_shop(conn, name=name, currency=currency)
    publish(conn, shop_id, [
        draft("tomato", 18, 1, "kg"),
        draft("banana", 60, 1, "dozen"),
        draft("coconut", 15, 1, "piece"),
    ])
    return shop_id, slug, token


def seed_published(tmp_path, currency="INR", name="T37 Stall"):
    conn = db.connect(tmp_path / "data")
    try:
        return seed_standard(conn, currency=currency, name=name)
    finally:
        conn.close()


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    return client


def seed_bill_id(tmp_path, shop_id, lines=None):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        wanted = lines or [WantedLine("tomato", Decimal(1), "kg", "text")]
        quote = build_quote(conn, shop_id, wanted)
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                source="seller", kind="bill", status="billed")
        return db.get_quote_by_token(conn, token)["id"]
    finally:
        conn.close()


# --- settings page ---

def test_settings_page_has_fields_and_seller_link(tmp_path):
    client = make_client(tmp_path)
    _, _, token = seed_published(tmp_path)
    html = client.get(f"/e/{token}/settings").text
    assert "Shop name" in html or "shop name" in html.lower()
    assert "UPI ID" in html
    assert "Round bills to the nearest rupee" in html
    assert "Your seller link" in html
    assert "anyone with this link can change your prices" in html
    assert "Copy" in html
    # Sidebar enabled, no soon badge on this page.
    assert f'href="/e/{token}/settings"' in html
    assert "soon" not in html.lower()
    # 25-language select.
    assert html.count("<option value=") >= 25


def test_settings_save_and_validation(tmp_path):
    client = make_client(tmp_path)
    _shop_id, slug, token = seed_published(tmp_path)
    # Valid save.
    resp = client.post(f"/e/{token}/settings", data={
        "name": "New Name", "area": "Anna Nagar", "phone": "+919876543210",
        "language": "hi", "currency": "INR", "type": "vegetable",
        "upi_id": "shop@okbank", "upi_payee": "New Name", "round_bills": "on",
    })
    assert resp.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        assert shop["name"] == "New Name"
        assert shop["area"] == "Anna Nagar"
        assert shop["language"] == "hi"
        assert shop["upi_id"] == "shop@okbank"
        assert shop["slug"] == slug  # slug never changes
    finally:
        conn.close()
    # Invalid UPI ID rejected.
    bad = client.post(f"/e/{token}/settings", data={
        "name": "New Name", "area": "Anna Nagar", "phone": "+919876543210",
        "language": "hi", "currency": "INR", "type": "vegetable",
        "upi_id": "not-a-upi", "upi_payee": "", "round_bills": "on",
    })
    assert bad.status_code == 400
    # Invalid phone rejected.
    bad2 = client.post(f"/e/{token}/settings", data={
        "name": "New Name", "area": "Anna Nagar", "phone": "abc",
        "language": "hi", "currency": "INR", "type": "vegetable",
        "upi_id": "", "upi_payee": "",
    })
    assert bad2.status_code == 400


def test_settings_migration_on_old_db(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "marketmate.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE shops (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,"
        " area TEXT NOT NULL, language TEXT NOT NULL, currency TEXT NOT NULL,"
        " type TEXT NOT NULL, edit_token_hash TEXT NOT NULL,"
        " is_demo INTEGER NOT NULL DEFAULT 0, is_judge INTEGER NOT NULL DEFAULT 0,"
        " listed INTEGER NOT NULL DEFAULT 0, expires_at TEXT, created_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,"
        " message TEXT NOT NULL DEFAULT '', cost REAL NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE drafts (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id INTEGER NOT NULL, item_index INTEGER NOT NULL, data TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE versions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER NOT NULL, created_at TEXT NOT NULL,"
        " published INTEGER NOT NULL DEFAULT 0)")
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " version_id INTEGER NOT NULL, name_local TEXT NOT NULL, name_en TEXT NOT NULL,"
        " variety TEXT, qty TEXT, qty_unit TEXT, photo TEXT,"
        " sold_out INTEGER NOT NULL DEFAULT 0, proof TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE price_lines (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " item_id INTEGER NOT NULL, price TEXT, per_amount TEXT, unit TEXT,"
        " said TEXT NOT NULL DEFAULT '')")
    conn.execute(
        "CREATE TABLE photo_checks (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER NOT NULL, created_at TEXT NOT NULL, image_path TEXT NOT NULL,"
        " report_json TEXT NOT NULL, cost REAL NOT NULL DEFAULT 0)")
    conn.execute(
        "CREATE TABLE quotes (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER NOT NULL, token TEXT UNIQUE NOT NULL, source TEXT NOT NULL,"
        " kind TEXT NOT NULL, status TEXT NOT NULL, lines_json TEXT NOT NULL,"
        " total TEXT NOT NULL, customer_note TEXT, created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL)")
    import hashlib

    digest = hashlib.sha256(b"oldtoken123").hexdigest()
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO shops (slug, name, phone, area, language, currency, type,"
        " edit_token_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("old-shop", "Old Shop", "+911234567890", "Koyambedu", "ta",
         "INR", "vegetable", digest, now))
    conn.execute(
        "INSERT INTO quotes (shop_id, token, source, kind, status, lines_json,"
        " total, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (1, "qtoken123456", "seller", "bill", "billed", "[]", "18.00", now, now))
    conn.commit()
    conn.close()
    # Opening via app migrates safely, preserving rows.
    app_conn = db.connect(data_dir)
    try:
        shop_cols = {r[1] for r in app_conn.execute("PRAGMA table_info(shops)")}
        assert "upi_id" in shop_cols
        assert "upi_payee" in shop_cols
        assert "round_bills" in shop_cols
        quote_cols = {r[1] for r in app_conn.execute("PRAGMA table_info(quotes)")}
        assert "payment_mode" in quote_cols
        assert "paid_at" in quote_cols
        assert "total_exact" in quote_cols
        assert "bill_token" in quote_cols
        shop = app_conn.execute("SELECT * FROM shops WHERE id=1").fetchone()
        assert shop["name"] == "Old Shop"
        quote = app_conn.execute("SELECT * FROM quotes WHERE id=1").fetchone()
        assert quote["total"] == "18.00"
    finally:
        app_conn.close()
    client = make_client(tmp_path)
    assert client.get("/e/oldtoken123/settings").status_code == 200


# --- UPI link ---

def test_upi_link_encoding_and_decimals():
    from app.web.bills import build_upi_url

    url = build_upi_url("shop@okbank", "My Shop & Sons",
                        Decimal("220.00"), 7, "My Shop & Sons")
    assert url.startswith("upi://pay?")
    assert "pa=shop%40okbank" in url or "pa=shop@okbank" in url
    assert "am=220.00" in url
    assert "cu=INR" in url
    assert "pn=" in url and "My" in url
    # Bill note encoded.
    assert "Bill" in url


def test_upi_link_uses_rounded_amount(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE shops SET upi_id=?, upi_payee=?, round_bills=1 WHERE id=?",
                     ("shop@okbank", "T37 Stall", shop_id))
        # Exact 219.60 bill.
        from app.market.quote import Quote, QuoteLine
        quote = Quote(lines=[QuoteLine("tomato", "", Decimal(1), "kg",
                                       Decimal("219.60"), Decimal(1),
                                       Decimal("219.60"), "priced")],
                      total=Decimal("219.60"), priced_count=1,
                      unpriced_count=0, prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                 source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "am=220.00" in html
    assert "Round off" in html


def test_qr_svg_only_with_upi_id(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = seed_bill_id(tmp_path, shop_id)
    # No UPI ID: friendly prompt linking to settings, no UPI scan text.
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Collect payment" in html
    assert f"/e/{token}/settings" in html
    assert "Scan with any UPI app" not in html
    # With UPI ID: SVG QR + scan text + big amount.
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE shops SET upi_id=? WHERE id=?",
                     ("shop@okbank", shop_id))
        conn.commit()
    finally:
        conn.close()
    html2 = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Scan with any UPI app" in html2
    assert "<svg" in html2


# --- payments + dashboard ---

def test_paid_by_cash_upi_stores_mode(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    cash_id = seed_bill_id(tmp_path, shop_id)
    upi_id = seed_bill_id(tmp_path, shop_id)
    assert client.post(f"/e/{token}/bills/{cash_id}/paid",
                       data={"mode": "cash"}).status_code in (302, 303)
    assert client.post(f"/e/{token}/bills/{upi_id}/paid",
                       data={"mode": "upi"}).status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        cash = conn.execute("SELECT * FROM quotes WHERE id=?", (cash_id,)).fetchone()
        upi = conn.execute("SELECT * FROM quotes WHERE id=?", (upi_id,)).fetchone()
        assert cash["status"] == "paid" and cash["payment_mode"] == "cash"
        assert cash["paid_at"] not in (None, "")
        assert upi["payment_mode"] == "upi"
        assert upi["paid_at"] not in (None, "")
    finally:
        conn.close()
    # Old "Mark paid" label is gone.
    html = client.get(f"/e/{token}/bills/{cash_id}").text
    assert "Mark paid" not in html


def test_dashboard_splits_cash_upi(tmp_path):
    from app.web.bills import bills_tiles

    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        for total, mode in (("36.00", "cash"), ("30.00", "upi")):
            q = Quote(lines=[QuoteLine("tomato", "", Decimal(1), "kg",
                                       Decimal(total), Decimal(1),
                                       Decimal(total), "priced")],
                      total=Decimal(total), priced_count=1, unpriced_count=0,
                      prices_set_at=datetime.now(UTC))
            qt = db.create_quote(conn, shop_id=shop_id, quote=q,
                                 source="seller", kind="bill", status="paid")
            bid = db.get_quote_by_token(conn, qt)["id"]
            conn.execute(
                "UPDATE quotes SET payment_mode=?, paid_at=? WHERE id=?",
                (mode, datetime.now(UTC).isoformat(), bid))
        conn.commit()
        tiles = bills_tiles(conn, shop_id, now=datetime.now(UTC))
        assert tiles["sales_cash"] == Decimal("36.00")
        assert tiles["sales_upi"] == Decimal("30.00")
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills").text
    assert "Cash" in html and "UPI" in html
    assert "cash" in html.lower() or "Cash" in html


def test_round_off_math():
    from app.web.bills import round_bill_total

    rounded, off = round_bill_total(Decimal("219.60"))
    assert rounded == Decimal("220.00")
    assert off == Decimal("0.40")
    rounded2, off2 = round_bill_total(Decimal("219.40"))
    assert rounded2 == Decimal("219.00")
    assert off2 == Decimal("-0.40")


def test_bill_page_round_off_display(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE shops SET round_bills=1 WHERE id=?", (shop_id,))
        q = Quote(lines=[QuoteLine("tomato", "", Decimal(1), "kg",
                                   Decimal("219.40"), Decimal(1),
                                   Decimal("219.40"), "priced")],
                  total=Decimal("219.40"), priced_count=1, unpriced_count=0,
                  prices_set_at=datetime.now(UTC))
        qt = db.create_quote(conn, shop_id=shop_id, quote=q,
                             source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, qt)["id"]
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Round off" in html
    assert "219" in html  # rounded total shown
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id=?", (bill_id,)).fetchone()
        assert row["total_exact"] == "219.40"
        assert row["total"] == "219.00"
    finally:
        conn.close()


def test_cash_helper_present(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = seed_bill_id(tmp_path, shop_id)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Customer gave" in html
    assert "Give back" in html


# --- public bill link ---

def test_public_bill_link(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path)
    bill_id = seed_bill_id(tmp_path, shop_id)
    # Visiting the bill page mints the public token; QR shown.
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Customer can scan to get the bill" in html
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id=?", (bill_id,)).fetchone()
        bill_token = row["bill_token"]
        assert bill_token and len(bill_token) >= 10
    finally:
        conn.close()
    pub = client.get(f"/b/{bill_token}")
    assert pub.status_code == 200
    assert "T37 Stall" in pub.text
    assert "Tomato" in pub.text or "tomato" in pub.text
    assert token not in pub.text
    assert "<form" not in pub.text.lower()
    assert client.get("/b/does-not-exist-123").status_code == 404


def test_non_inr_no_upi_card(tmp_path):
    client = make_client(tmp_path)
    shop_id, _, token = seed_published(tmp_path, currency="USD",
                                       name="T37 USD Stall")
    bill_id = seed_bill_id(tmp_path, shop_id)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Scan with any UPI app" not in html
    assert "Paid by cash" in html
    assert "Paid by card" in html
    assert "Paid by UPI" not in html
