"""Task 39: day close, Excel and general POS exports (no network)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

IST = ZoneInfo("Asia/Kolkata")


def pl(price, per_amount, unit, said=""):
    return PriceLine(
        Decimal(price) if price is not None else None,
        Decimal(per_amount) if per_amount is not None else None,
        unit,
        said,
    )


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def create_shop(client, name="Close Store", phone="+914400000011",
                currency="INR"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": "ta", "currency": currency, "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"]


def token_of(location):
    return location.split("/e/")[1]


def draft_tomato(price=40):
    return DraftItem(
        name_spoken="thakkali", name_local="தக்காளி", name_en="tomato",
        variety=None, price_lines=[pl(price, 1, "kg", "kilo forty")],
        qty=None, qty_unit=None,
        proof=Proof(quote="thakkali kilo forty", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def draft_onion(price=30):
    return DraftItem(
        name_spoken="vengayam", name_local="வெங்காயம்", name_en="onion",
        variety=None, price_lines=[pl(price, 1, "kg", "kilo thirty")],
        qty=None, qty_unit=None,
        proof=Proof(quote="vengayam kilo thirty", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


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


def seed_bill(conn, shop_id, lines, total, status="billed", created_at=None,
              mode=None, phone=None):
    from app.market.quote import Quote, QuoteLine

    quote_lines = []
    for name_en, name_local, qty, unit, unit_price, line_total in lines:
        quote_lines.append(QuoteLine(
            name_en=name_en, name_local=name_local, qty=Decimal(qty),
            unit=unit, unit_price=Decimal(unit_price),
            per_amount=Decimal(1), line_total=Decimal(line_total),
            status="priced"))
    quote = Quote(lines=quote_lines, total=Decimal(total), priced_count=len(
        quote_lines), unpriced_count=0, prices_set_at=datetime.now(UTC))
    token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                            source="seller", kind="bill", status=status)
    row = db.get_quote_by_token(conn, token)
    bill_id = row["id"]
    if created_at is not None:
        conn.execute("UPDATE quotes SET created_at = ? WHERE id = ?",
                     (created_at, bill_id))
    if status == "paid" and mode:
        conn.execute(
            "UPDATE quotes SET payment_mode = ?, paid_at = ? WHERE id = ?",
            (mode, datetime.now(UTC).isoformat(), bill_id))
    if phone:
        conn.execute("UPDATE quotes SET customer_phone = ? WHERE id = ?",
                     (phone, bill_id))
    conn.commit()
    return bill_id


def ist_iso(day, hour, minute):
    y, m, d = (int(p) for p in day.split("-"))
    local = datetime(y, m, d, hour, minute, tzinfo=IST)
    return local.astimezone(UTC).isoformat()


# --- 1. day-close math across two days, IST boundaries ---

def test_day_tiles_two_days_ist_boundaries(tmp_path):
    from app import purchases as pur
    from app.dayclose import day_tiles

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato(), draft_onion()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day1 = "2026-10-27"
        day2 = "2026-10-28"
        # Late-night IST bill still belongs to day1.
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "2", "kg", "40", "80.00")],
                  "80.00", status="paid", created_at=ist_iso(day1, 23, 59),
                  mode="cash")
        seed_bill(conn, shop["id"],
                  [("onion", "வெங்காயம்", "1", "kg", "30", "30.00")],
                  "30.00", status="billed",
                  created_at=ist_iso(day1, 10, 0))
        # Just after midnight IST belongs to day2.
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "1", "kg", "40", "40.00")],
                  "40.00", status="paid", created_at=ist_iso(day2, 0, 1),
                  mode="upi")
        pur.add_purchase(conn, shop["id"], day1, "tomato", Decimal(20),
                         "kg", Decimal(600), source="typed")
        pur.add_purchase(conn, shop["id"], day1, "onion", Decimal(50),
                         "kg", Decimal(1200), source="typed")
        shop = db.shop_by_token(conn, token)
        tiles1 = day_tiles(conn, shop, day1)
        assert tiles1["bills_count"] == 2
        assert tiles1["sales"] == Decimal("110.00")
        assert tiles1["cash"] == Decimal("80.00")
        assert tiles1["upi"] == Decimal("0.00")
        assert tiles1["unpaid"] == Decimal("30.00")
        assert tiles1["spent"] == Decimal("1800.00")
        # COGS: tomato 2kg*30=60 + onion 1kg*24=24 = 84; margin 110-84=26.
        assert tiles1["margin"] == Decimal("26.00")
        tiles2 = day_tiles(conn, shop, day2)
        assert tiles2["bills_count"] == 1
        assert tiles2["sales"] == Decimal("40.00")
        assert tiles2["upi"] == Decimal("40.00")
        # No purchases on day2: margin unknown.
        assert tiles2["margin"] is None
    finally:
        conn.close()


def test_day_tiles_cash_upi_card_unpaid_split(tmp_path):
    from app.dayclose import day_tiles

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "1", "kg", "40", "40.00")],
                  "40.00", status="paid", created_at=ist_iso(day, 9, 0),
                  mode="cash")
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "2", "kg", "40", "80.00")],
                  "80.00", status="paid", created_at=ist_iso(day, 10, 0),
                  mode="upi")
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "3", "kg", "40", "120.00")],
                  "120.00", status="paid", created_at=ist_iso(day, 11, 0),
                  mode="card")
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "1", "kg", "40", "40.00")],
                  "40.00", status="billed", created_at=ist_iso(day, 12, 0))
        tiles = day_tiles(conn, shop, day)
        assert tiles["sales"] == Decimal("280.00")
        assert tiles["cash"] == Decimal("40.00")
        assert tiles["upi"] == Decimal("80.00")
        assert tiles["card"] == Decimal("120.00")
        assert tiles["unpaid"] == Decimal("40.00")
        assert tiles["bills_count"] == 4
    finally:
        conn.close()


def test_margin_dash_without_costs_and_page_shows_dash(tmp_path):
    from app.dayclose import day_tiles

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "1", "kg", "40", "40.00")],
                  "40.00", status="paid", created_at=ist_iso(day, 9, 0),
                  mode="cash")
        tiles = day_tiles(conn, shop, day)
        assert tiles["margin"] is None
    finally:
        conn.close()
    html = client.get(f"/e/{token}/close?date=2026-10-27").text
    assert "—" in html


def test_shop_tz_inr_ist_otherwise_utc(tmp_path):
    from app.dayclose import shop_tz

    client = make_client(tmp_path)
    token_inr = token_of(create_shop(client, name="INR Shop",
                                     phone="+914400000012", currency="INR"))
    token_eur = token_of(create_shop(client, name="EU Shop",
                                     phone="+33000000001", currency="EUR"))
    conn = db.connect(tmp_path / "data")
    try:
        inr = db.shop_by_token(conn, token_inr)
        eur = db.shop_by_token(conn, token_eur)
        assert str(shop_tz(inr)) == "Asia/Kolkata"
        assert str(shop_tz(eur)) == "UTC"
    finally:
        conn.close()


# --- 2. items table + wastage ---

def test_items_table_and_wastage_reduces_stock_left(tmp_path):
    from app import purchases as pur
    from app.dayclose import items_for_day, set_wastage

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_onion()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        pur.add_purchase(conn, shop["id"], day, "onion", Decimal(50),
                         "kg", Decimal(1200), source="typed")
        seed_bill(conn, shop["id"],
                  [("onion", "வெங்காயம்", "10", "kg", "30", "300.00")],
                  "300.00", status="paid", created_at=ist_iso(day, 9, 0),
                  mode="cash")
        rows = items_for_day(conn, shop, day)
        assert len(rows) == 1
        assert rows[0]["sold_qty"] == Decimal(10)
        assert rows[0]["sales_amount"] == Decimal("300.00")
        assert rows[0]["opening"] == Decimal(50)
        assert rows[0]["stock_left"] == Decimal(40)
        set_wastage(conn, shop["id"], day, "onion", Decimal(2), "kg")
        rows2 = items_for_day(conn, shop, day)
        assert rows2[0]["stock_left"] == Decimal(38)
    finally:
        conn.close()


def test_wastage_form_post_and_carry_note(tmp_path):
    from app import purchases as pur

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_onion()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        pur.add_purchase(conn, shop["id"], day, "onion", Decimal(50),
                         "kg", Decimal(1200), source="typed")
        seed_bill(conn, shop["id"],
                  [("onion", "வெங்காயம்", "10", "kg", "30", "300.00")],
                  "300.00", status="paid", created_at=ist_iso(day, 9, 0),
                  mode="cash")
    finally:
        conn.close()
    html = client.get(f"/e/{token}/close?date=2026-10-27").text
    assert "Save wastage" in html
    assert "Carry over to tomorrow" in html
    resp = client.post(f"/e/{token}/close/wastage", data={
        "date": "2026-10-27", "wastage_onion": "2", "unit_onion": "kg"})
    assert resp.status_code in (302, 303)
    html2 = client.get(f"/e/{token}/close?date=2026-10-27").text
    assert "38" in html2


# --- 3. close page, auth, whatsapp, pdf ---

def test_close_page_needs_token_and_has_sidebar_and_tiles(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    assert client.get("/e/badtoken123/close").status_code == 404
    assert client.get("/e/badtoken123/close.pdf").status_code == 404
    assert client.get(
        "/e/badtoken123/exports/sales.xlsx").status_code == 404
    assert client.get("/e/badtoken123/exports/pos.csv").status_code == 404
    html = client.get(f"/e/{token}/close").text
    assert "Close day" in html
    assert "Sales" in html
    assert "Bills" in html
    assert "Cash" in html and "UPI" in html
    assert "Spent on purchases" in html or "Spent" in html
    assert "Gross margin" in html or "Margin" in html
    # Sidebar on bills page links to close.
    assert "Close day" in client.get(f"/e/{token}/bills").text


def test_whatsapp_link_encodes_summary(tmp_path):
    from app import purchases as pur

    client = make_client(tmp_path)
    token = token_of(create_shop(client, phone="+91 44000 00011"))
    seed_published(tmp_path, token, [draft_tomato(), draft_onion()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        pur.add_purchase(conn, shop["id"], day, "tomato", Decimal(20),
                         "kg", Decimal(600), source="typed")
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "2", "kg", "40", "80.00")],
                  "80.00", status="paid", created_at=ist_iso(day, 9, 0),
                  mode="cash")
    finally:
        conn.close()
    html = client.get(f"/e/{token}/close?date=2026-10-27").text
    assert "wa.me/914400000011" in html
    assert "Send summary on WhatsApp" in html
    # Encoded summary present (spaces/newlines encoded).
    assert "%20" in html or "%0A" in html


def test_close_pdf_renders(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato()])
    resp = client.get(f"/e/{token}/close.pdf?date=2026-10-27")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


# --- 4. date ranges ---

def test_resolve_range_keys(tmp_path):
    from app.dayclose import resolve_range

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        now = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)  # 10:30 IST
        start, end = resolve_range("today", None, None, shop, now)
        assert (start, end) == ("2026-10-28", "2026-10-28")
        start, end = resolve_range("yesterday", None, None, shop, now)
        assert (start, end) == ("2026-10-27", "2026-10-27")
        start, end = resolve_range("week", None, None, shop, now)
        assert (start, end) == ("2026-10-22", "2026-10-28")
        start, end = resolve_range("month", None, None, shop, now)
        assert (start, end) == ("2026-10-01", "2026-10-28")
        start, end = resolve_range("custom", "2026-10-01", "2026-10-05",
                                   shop, now)
        assert (start, end) == ("2026-10-01", "2026-10-05")
    finally:
        conn.close()


# --- 5. Excel export ---

def test_xlsx_four_sheets_headers_and_tamil(tmp_path):
    from app.outputs.excel import sales_workbook

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato(), draft_onion()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "2", "kg", "40", "80.00"),
                   ("onion", "வெங்காயம்", "1", "kg", "30", "30.00")],
                  "110.00", status="paid", created_at=ist_iso(day, 9, 30),
                  mode="cash", phone="+919876543210")
        shop = db.shop_by_token(conn, token)
        data = sales_workbook(conn, shop, day, day)
    finally:
        conn.close()
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(data))
    assert book.sheetnames == ["Bills", "Lines", "Items", "Summary"]
    bills_head = [c.value for c in book["Bills"][1]]
    assert bills_head == ["Bill no", "Date", "Time", "Customer",
                          "Payment mode", "Items count", "Total",
                          "Round off", "Status"]
    lines_head = [c.value for c in book["Lines"][1]]
    assert lines_head == ["Bill no", "Date", "Item (English)",
                          "Item (local)", "Qty", "Unit", "Rate",
                          "Amount"]
    items_head = [c.value for c in book["Items"][1]]
    assert items_head == ["Item", "Qty sold", "Amount"]
    summary_head = [c.value for c in book["Summary"][1]]
    assert summary_head[0] == "Date"
    assert "Sales" in summary_head and "Margin" in summary_head
    # Header bold + frozen, money 2 decimals.
    assert book["Bills"]["A1"].font.bold is True
    assert book["Bills"].freeze_panes == "A2"
    assert book["Bills"]["G2"].number_format == "0.00"
    # Tamil round-trips.
    locals_seen = [r[3].value for r in
                   list(book["Lines"].iter_rows(min_row=2))]
    assert "தக்காளி" in locals_seen
    assert "வெங்காயம்" in locals_seen
    # Route serves the file.
    resp = client.get(
        f"/e/{token}/exports/sales.xlsx?range=custom&from=2026-10-27&to=2026-10-27")
    assert resp.status_code == 200
    assert "spreadsheet" in resp.headers["content-type"]
    assert resp.content[:2] == b"PK"


# --- 6. POS CSV + price list ---

def test_pos_csv_columns_and_bom(tmp_path):
    from app.outputs.pos_csv import POS_HEADER, pos_csv

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = "2026-10-27"
        seed_bill(conn, shop["id"],
                  [("tomato", "தக்காளி", "2", "kg", "40", "80.00")],
                  "80.00", status="paid", created_at=ist_iso(day, 9, 30),
                  mode="upi", phone="+919876543210")
        shop = db.shop_by_token(conn, token)
        payload = pos_csv(conn, shop, day, day)
    finally:
        conn.close()
    assert payload[:3] == b"\xef\xbb\xbf"
    text = payload.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0].split(",") == POS_HEADER
    assert POS_HEADER == ["date", "time", "bill_no", "item_code",
                          "item_name", "item_name_local", "qty", "unit",
                          "rate", "amount", "discount", "tax",
                          "bill_total", "payment_mode", "customer_phone"]
    assert "தக்காளி" in text
    assert ",tomato," in text or ",tomato" in text
    # discount and tax are 0.
    import csv

    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0]["discount"] == "0"
    assert rows[0]["tax"] == "0"
    assert rows[0]["item_code"] == "tomato"
    assert rows[0]["payment_mode"] == "upi"
    # Route serves BOM CSV.
    resp = client.get(
        f"/e/{token}/exports/pos.csv?range=custom&from=2026-10-27&to=2026-10-27")
    assert resp.status_code == 200
    assert resp.content[:3] == b"\xef\xbb\xbf"


def test_item_code_slug_and_pricelist_csv(tmp_path):
    from app.dayclose import item_code
    from app.outputs.pos_csv import PRICELIST_HEADER, pricelist_csv

    assert item_code("Small Onion") == "small-onion"
    assert item_code("Onion") == "onion"
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato(), draft_onion()])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        payload = pricelist_csv(conn, shop)
    finally:
        conn.close()
    assert payload[:3] == b"\xef\xbb\xbf"
    text = payload.decode("utf-8-sig")
    assert text.splitlines()[0].split(",") == PRICELIST_HEADER
    assert PRICELIST_HEADER == ["item_code", "item_name",
                                "item_name_local", "unit", "per_amount",
                                "price", "sold_out"]
    assert "தக்காளி" in text
    resp = client.get(f"/e/{token}/exports/pricelist.csv")
    assert resp.status_code == 200
    assert resp.content[:3] == b"\xef\xbb\xbf"


def test_exports_have_range_picker_on_both_pages(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    for url in (f"/e/{token}/close", f"/e/{token}/bills"):
        html = client.get(url).text
        assert "sales.xlsx" in html
        assert "pos.csv" in html
        assert "pricelist.csv" in html
        assert "Last 7 days" in html
        assert "This month" in html or "this month" in html.lower()
