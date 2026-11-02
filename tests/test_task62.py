"""Task 62: CREDIT (udhaar / "write it down"). Failing-tests-first."""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

IST = ZoneInfo("Asia/Kolkata")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, name="Credit Store", phone="+914400000062",
                language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, local=None):
    return DraftItem(
        name_spoken=name_en, name_local=local or name_en, name_en=name_en,
        variety=None, price_lines=[PriceLine(Decimal(price), Decimal(1),
                                             "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def publish(tmp_path, token, drafts=None):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(
            conn, session_id, list(drafts or [_draft("tomato", 40)]))
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def seed_bill(tmp_path, token, *, status="billed", total="36.00",
              name=None, phone=None, day=None, hour=10):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=[QuoteLine(
                name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
                unit="kg", unit_price=Decimal(18), per_amount=Decimal(1),
                line_total=Decimal(total), status="priced")],
            total=Decimal(total), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status=status,
                                 customer_name=name, customer_phone=phone)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        if status == "paid":
            db.mark_bill_paid(conn, bill_id, "cash")
        if day is not None:
            y, m, d = (int(p) for p in day.split("-"))
            when = datetime(y, m, d, hour, 0, tzinfo=IST)
            conn.execute("UPDATE quotes SET created_at = ? WHERE id = ?",
                         (when.astimezone(UTC).isoformat(), bill_id))
            conn.commit()
        db.ensure_bill_token(conn, bill_id)
        return bill_id
    finally:
        conn.close()


def _today_ist():
    return datetime.now(IST).date().isoformat()


def _conn(tmp_path):
    return db.connect(tmp_path / "data")


# --- 1. a credit bill needs a name and phone ---


def test_credit_bill_needs_name_and_phone(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    bill_id = seed_bill(tmp_path, token, total="50.00")
    # Bill page offers pay later next to cash/UPI.
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Paid by cash" in html
    assert "Paid by UPI" in html
    assert "Pay later" in html
    # Missing name -> refused.
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "", "customer_phone": "9876543210"})
    assert resp.status_code == 400, resp.text
    # Missing phone -> refused.
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": ""})
    assert resp.status_code == 400, resp.text
    # Bad phone -> refused.
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "123"})
    assert resp.status_code == 400, resp.text
    conn = _conn(tmp_path)
    try:
        assert db.get_quote_by_id(conn, bill_id)["status"] == "billed"
    finally:
        conn.close()
    # Good name + phone (with spaces) -> credit, phone normalised.
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "98765 43210"})
    assert resp.status_code in (302, 303), resp.text
    conn = _conn(tmp_path)
    try:
        row = db.get_quote_by_id(conn, bill_id)
        assert row["status"] == "credit"
        assert (row["payment_mode"] or "").lower() == "credit"
        assert row["customer_phone"] == "9876543210"
        assert row["customer_name"] == "Priya"
    finally:
        conn.close()
    # Locked like a paid bill: edits refused, Change bill offered.
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Change bill" in html
    resp = client.post(f"/e/{token}/bills/{bill_id}/lines", data={
        "name_en_0": "tomato", "qty_0": "5", "unit_0": "kg",
        "amount_0": "", "variety_0": ""})
    assert "Change bill" in resp.text


def test_credit_prefills_from_order_contact(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    bill_id = seed_bill(tmp_path, token, total="50.00", name="Kani",
                        phone="9876543211")
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Kani" in html
    assert "9876543211" in html


# --- 2. balance after two credit bills and one partial payment ---


def test_balance_two_bills_partial_payment(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    b1 = seed_bill(tmp_path, token, total="100.00")
    b2 = seed_bill(tmp_path, token, total="50.00")
    for bill_id in (b1, b2):
        resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
            "customer_name": "Priya", "customer_phone": "9876543210"})
        assert resp.status_code in (302, 303), resp.text
    # Partial payment of 60 on a 150 balance.
    resp = client.post(f"/e/{token}/credit/9876543210/pay", data={
        "amount": "60", "mode": "cash"})
    assert resp.status_code in (302, 303), resp.text
    html = client.get(f"/e/{token}/credit").text
    assert "₹90" in html
    assert "1 customer" in html or "1 customers" in html
    detail = client.get(f"/e/{token}/credit/9876543210").text
    assert "₹90" in html or "₹90" in detail
    assert "₹60" in detail
    assert "/b/" in detail
    # Stored rows: two credit bills minus one payment.
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        rows = conn.execute(
            "SELECT * FROM credit_payments WHERE shop_id = ?",
            (shop["id"],)).fetchall()
        assert len(rows) == 1
        assert Decimal(str(rows[0]["amount"])) == Decimal(60)
        assert rows[0]["mode"] == "cash"
    finally:
        conn.close()


# --- 3. overpayment refused ---


def test_overpayment_refused(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    bill_id = seed_bill(tmp_path, token, total="40.00")
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Velu", "customer_phone": "9876543220"})
    assert resp.status_code in (302, 303), resp.text
    resp = client.post(f"/e/{token}/credit/9876543220/pay", data={
        "amount": "50", "mode": "cash"})
    assert resp.status_code == 400, resp.text
    resp = client.post(f"/e/{token}/credit/9876543220/pay", data={
        "amount": "0", "mode": "cash"})
    assert resp.status_code == 400, resp.text
    html = client.get(f"/e/{token}/credit/9876543220").text
    assert "₹40" in html


# --- 4. reminder link text and amount ---


def test_reminder_link_text_and_amount(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client, name="Credit Store", language="en")
    publish(tmp_path, token)
    # Shop has a UPI id so the reminder names it.
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        db.update_shop_settings(
            conn, shop["id"], name=shop["name"], area=shop["area"],
            phone=shop["phone"], language=shop["language"],
            currency="INR", shop_type=shop["type"], upi_id="store@upi",
            upi_payee=None, round_bills=True)
    finally:
        conn.close()
    b1 = seed_bill(tmp_path, token, total="100.00")
    resp = client.post(f"/e/{token}/bills/{b1}/credit", data={
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text
    html = client.get(f"/e/{token}/credit/9876543210").text
    match = re.search(r"https://wa\.me/(\d+)\?text=([^\"]+)", html)
    assert match, html
    assert match.group(1) == "919876543210"
    text = unquote(match.group(2))
    assert "Credit Store" in text
    assert "₹100" in text
    assert "1 bill" in text
    assert "store@upi" in text
    assert "/s/" in text
    # A Tamil shop reminds in Tamil.
    ta_client = make_client(tmp_path)
    ta_token = create_shop(ta_client, name="Ta Store", language="ta")
    publish(tmp_path, ta_token)
    ta_bill = seed_bill(tmp_path, ta_token, total="60.00")
    resp = ta_client.post(f"/e/{ta_token}/bills/{ta_bill}/credit", data={
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text
    ta_html = ta_client.get(f"/e/{ta_token}/credit/9876543210").text
    ta_match = re.search(r"https://wa\.me/\d+\?text=([^\"]+)", ta_html)
    assert ta_match, ta_html
    assert "பாக்கி" in unquote(ta_match.group(1))


# --- 5. day close numbers in a mixed day ---


def test_day_close_mixed_cash_upi_credit(tmp_path):
    from app.dayclose import day_tiles

    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    day = _today_ist()
    # Cash paid 100, UPI paid 50, credit given 80.
    cash_id = seed_bill(tmp_path, token, total="100.00", day=day, hour=9)
    upi_id = seed_bill(tmp_path, token, total="50.00", day=day, hour=10)
    cred_id = seed_bill(tmp_path, token, total="80.00", day=day, hour=11)
    conn = _conn(tmp_path)
    try:
        db.mark_bill_paid(conn, cash_id, "cash")
        db.mark_bill_paid(conn, upi_id, "upi")
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/bills/{cred_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text
    # Collect 30 cash + 20 UPI against the 80 credit.
    for amount, mode in (("30", "cash"), ("20", "upi")):
        resp = client.post(f"/e/{token}/credit/9876543210/pay", data={
            "amount": amount, "mode": mode})
        assert resp.status_code in (302, 303), resp.text
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        tiles = day_tiles(conn, shop, day)
    finally:
        conn.close()
    assert tiles["sales"] == Decimal("230.00")
    assert tiles["cash"] == Decimal("130.00")
    assert tiles["upi"] == Decimal("70.00")
    assert tiles["credit_given"] == Decimal("80.00")
    assert tiles["credit_collected"] == Decimal("50.00")
    html = client.get(f"/e/{token}/close?date={day}").text
    assert "Given on credit today" in html
    assert "Credit collected today" in html
    assert "₹80" in html
    assert "₹50" in html


# --- 6. Excel/CSV rows ---


def test_excel_csv_credit_rows(tmp_path):
    import openpyxl

    from app.outputs.excel import sales_workbook
    from app.outputs.pos_csv import pos_csv

    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    day = _today_ist()
    cred_id = seed_bill(tmp_path, token, total="80.00", day=day, hour=11)
    resp = client.post(f"/e/{token}/bills/{cred_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text
    resp = client.post(f"/e/{token}/credit/9876543210/pay", data={
        "amount": "30", "mode": "cash"})
    assert resp.status_code in (302, 303), resp.text
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        data = sales_workbook(conn, shop, day, day)
        payload = pos_csv(conn, shop, day, day)
    finally:
        conn.close()
    book = openpyxl.load_workbook(io.BytesIO(data))
    bills_rows = list(book["Bills"].iter_rows(min_row=2, values_only=True))
    modes = [row[4] for row in bills_rows]
    statuses = [row[8] for row in bills_rows]
    assert "credit" in modes
    assert "credit_payment" in statuses
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert any(r["payment_mode"] == "credit" for r in rows)
    assert any(r.get("item_code") == "credit_payment"
               or r.get("payment_mode") == "credit_payment"
               for r in rows)


# --- 7. helper without the credit permission gets 403 ---


def test_helper_without_credit_permission_403(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    bill_id = seed_bill(tmp_path, token, total="40.00")
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        _hid, helper_token = db.create_helper(conn, shop["id"], "Giri")
        helper_id = _hid
    finally:
        conn.close()
    helper = make_client(tmp_path)
    helper.cookies.set("ui_lang", "en")
    # Bills still work for helpers.
    assert helper.get(f"/e/{helper_token}/bills").status_code == 200
    # Credit does not.
    assert helper.get(f"/e/{helper_token}/credit").status_code == 403
    resp = helper.post(f"/e/{helper_token}/bills/{bill_id}/credit",
                       data={"customer_name": "A",
                             "customer_phone": "9876543210"})
    assert resp.status_code == 403
    # Owner grants the credit permission; helper can proceed.
    resp = client.post(
        f"/e/{token}/settings/helpers/{helper_id}/credit",
        data={"can_credit": "1"})
    assert resp.status_code in (200, 302, 303), resp.text
    assert helper.get(f"/e/{helper_token}/credit").status_code == 200


# --- 8. pages render in en/ta/hi ---


def test_pages_render_en_ta_hi(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    bill_id = seed_bill(tmp_path, token, total="40.00")
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in (f"/e/{token}/bills/{bill_id}",
                    f"/e/{token}/credit",
                    f"/e/{token}/credit/9876543210",
                    f"/e/{token}/close?date={_today_ist()}"):
            resp = client.get(url)
            assert resp.status_code == 200, (lang, url)
            assert "style=" not in resp.text, (lang, url)
        home = client.get(f"/e/{token}").text
        assert resp.status_code == 200
        if lang == "ta":
            assert "கடன்" in home or "கடன்" in client.get(
                f"/e/{token}/credit").text
        if lang == "hi":
            assert "उधार" in home or "उधार" in client.get(
                f"/e/{token}/credit").text
    client.cookies.set("ui_lang", "en")


def test_seller_home_shows_credit_to_collect(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    bill_id = seed_bill(tmp_path, token, total="40.00")
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text
    html = client.get(f"/e/{token}").text
    assert "Credit to collect" in html
    assert f"/e/{token}/credit" in html
