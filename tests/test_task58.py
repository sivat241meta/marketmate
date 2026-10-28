"""Task 58: fixed bottom nav on short pages, unknown names never show as
'other', unpaid bills export with payment_mode "unpaid". Failing-tests-first."""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"

MADE_UP_TA = "கற்பனைக்காய்"


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, language="ta"):
    resp = client.post("/new", data={
        "name": "Fix Store", "phone": "+914400000058",
        "area": "Koyambedu", "language": language, "currency": "INR",
        "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"]


def token_of(location):
    return location.split("/e/")[1]


def slug_of(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def pl(price, per_amount=1, unit="kg", said=""):
    return PriceLine(Decimal(price), Decimal(per_amount), unit, said)


def draft(name_en, name_local, price, variety=None):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety, price_lines=[pl(price)],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def seed_published(tmp_path, token, drafts, kind="video"):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        if kind in ("video", "live", "board"):
            db.ensure_session_base(conn, session_id)
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
        return session_id, version_id
    finally:
        conn.close()


def seed_bill(tmp_path, token, lines, total, day="2026-10-27",
              status="billed", mode=None):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote_lines = [QuoteLine(
            name_en=name_en, name_local=name_local, qty=Decimal(qty),
            unit=unit, unit_price=Decimal(unit_price),
            per_amount=Decimal(1), line_total=Decimal(line_total),
            status="priced", variety=variety)
            for name_en, name_local, variety, qty, unit, unit_price,
            line_total in lines]
        quote = Quote(lines=quote_lines, total=Decimal(total),
                      priced_count=len(quote_lines), unpriced_count=0,
                      prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status=status)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        y, m, d = (int(p) for p in day.split("-"))
        local = datetime(y, m, d, 9, 30, tzinfo=IST)
        conn.execute(
            "UPDATE quotes SET created_at = ?, payment_mode = ? WHERE id = ?",
            (local.astimezone(UTC).isoformat(), mode, bill_id))
        conn.commit()
        return bill_id
    finally:
        conn.close()


# --- 1. bottom nav fixed on short pages --------------------------------------

def test_bnav_fixed_with_body_padding_on_phones():
    css = CSS.read_text()
    phones_start = css.index("@media (max-width: 899.98px)")
    phones = css[phones_start:]
    assert "position: fixed" in phones
    fixed_at = phones.index("position: fixed")
    window = phones[max(0, fixed_at - 300):fixed_at + 200]
    assert ".bnav" in window
    assert "left: 0" in window and "right: 0" in window
    assert "bottom: 0" in window
    pad_at = phones.index("padding-bottom: var(--bnav-h)")
    pad_window = phones[max(0, pad_at - 300):pad_at]
    assert "body:has(.bnav)" in pad_window
    # Task 57 lift still clears the nav by at least 8px.
    assert "calc(var(--bnav-h) + 8px)" in phones


def test_approved_session_page_carries_bnav(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id, _ = seed_published(
        tmp_path, token, [draft("tomato", "தக்காளி", 40)])
    resp = client.get(f"/e/{token}/s/{session_id}")
    assert resp.status_code == 200
    assert 'class="bnav"' in resp.text


# --- 2. unknown spoken names --------------------------------------------------

def test_resolve_krishnagiri_inside_longer_name():
    from app.pipeline.names import resolve_name

    assert resolve_name("வரி krishnagiri வரி") == ("brinjal", "krishnagiri")
    assert resolve_name("vari Krishnagiri vari") == ("brinjal", "krishnagiri")


def test_extract_krishnagiri_clip_keeps_latin_only():
    from app.models import Transcript
    from app.pipeline.extract import parse_extract_json

    empty = Transcript(text="", duration_ms=0, turns=[])
    (item,) = parse_extract_json(
        {"items": [{
            "name_spoken": "வரி krishnagiri வரி",
            "name_en": "வரி krishnagiri வரி",
            "name_local": "",
            "variety": "வரி krishnagiri வரி",
            "prices": [{"said": "அறுபது ரூபா", "price": 60,
                        "per_amount": 1, "unit": "kg"}],
            "quote": "வரி krishnagiri வரி அறுபது ரூபா",
            "turn_ids": [],
        }]},
        empty,
        language="ta",
    )
    assert item.name_en == "brinjal"
    assert item.variety == "krishnagiri"
    assert item.name_en.isascii()
    assert (item.variety or "").isascii()


def test_unknown_tamil_word_stays_in_name_local():
    from app.models import Transcript
    from app.pipeline.extract import parse_extract_json
    from app.pipeline.names import resolve_name

    assert resolve_name(MADE_UP_TA)[0] == "other"
    empty = Transcript(text="", duration_ms=0, turns=[])
    (item,) = parse_extract_json(
        {"items": [{
            "name_spoken": MADE_UP_TA,
            "name_en": MADE_UP_TA,
            "name_local": "",
            "variety": MADE_UP_TA,
            "prices": [{"said": "அறுபது ரூபா", "price": 60,
                        "per_amount": 1, "unit": "kg"}],
            "quote": f"{MADE_UP_TA} அறுபது ரூபா",
            "turn_ids": [],
        }]},
        empty,
        language="ta",
    )
    assert item.name_en == "other"
    assert MADE_UP_TA in item.name_local
    assert item.name_en.isascii()
    assert (item.variety or "") == "" or item.variety.isascii()


def _visible_other(html: str) -> bool:
    return re.search(r">other<", html, re.IGNORECASE) is not None


def test_unknown_name_never_shows_other(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft("other", MADE_UP_TA, 60)])
    slug = slug_of(tmp_path, token)
    html = client.get(f"/s/{slug}").text
    assert MADE_UP_TA in html
    assert not _visible_other(html)
    html = client.get(f"/e/{token}/bills/new").text
    assert not _visible_other(html)


def test_board_and_tags_hide_other(tmp_path):
    from datetime import datetime as _dt

    from app.outputs.pdf import price_board_pdf, price_tags_pdf
    from tests.test_outputs import demo_shop_row, item, pypdf_text
    from tests.test_outputs import pl as out_pl

    goods = [item(name_en="other", name_local=MADE_UP_TA,
                  lines=[out_pl(60, 1, "kg")])]
    at = _dt(2026, 10, 28, 9, 0, tzinfo=IST)
    url = "http://127.0.0.1:8000/s/demo-stall"
    for pdf in (price_board_pdf(demo_shop_row(), goods, at, url),
                price_tags_pdf(demo_shop_row(), goods, at, url)):
        text = pypdf_text(pdf)
        # Tags may line-break a long Tamil word; compare without breaks.
        assert MADE_UP_TA in re.sub(r"\s+", "", text)
        assert re.search(r"\bother\b", text, re.IGNORECASE) is None


# --- 3. unpaid bills export with "unpaid" -------------------------------------

def test_pos_csv_unpaid_mode_kept(tmp_path):
    from app.outputs.pos_csv import pos_csv

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft("tomato", "தக்காளி", 40)])
    seed_bill(tmp_path, token,
              [("tomato", "தக்காளி", None, "2", "kg", "40", "80.00")],
              "80.00", day="2026-10-27", status="billed", mode=None)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        payload = pos_csv(conn, shop, "2026-10-27", "2026-10-27")
    finally:
        conn.close()
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["payment_mode"] == "unpaid"


def test_excel_bills_unpaid_mode_kept(tmp_path):
    import openpyxl

    from app.outputs.excel import sales_workbook

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft("tomato", "தக்காளி", 40)])
    seed_bill(tmp_path, token,
              [("tomato", "தக்காளி", None, "2", "kg", "40", "80.00")],
              "80.00", day="2026-10-27", status="billed", mode=None)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        data = sales_workbook(conn, shop, "2026-10-27", "2026-10-27")
    finally:
        conn.close()
    book = openpyxl.load_workbook(io.BytesIO(data))
    modes = [r[4].value for r in book["Bills"].iter_rows(min_row=2)]
    assert modes == ["unpaid"]
