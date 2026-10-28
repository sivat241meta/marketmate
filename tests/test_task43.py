"""Task 43: partial sessions keep the rest, visible QR, paid locked, per-unit rate."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

QUOTE = "t43 secret quote"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client, name="T43 Stall", phone="+914400000043"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, per_amount=1, unit="kg", local=None, variety=None):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en, name_local=local or CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None, qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def _publish(tmp_path, token, drafts) -> int:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def _start_review_session(tmp_path, token, kind, drafts):
    """Create a session with drafts already in review; returns session_id."""
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review", f"{len(drafts)} items need review")
        return session_id
    finally:
        conn.close()


def _approve_payload(tmp_path, session_id, confirmed_all=True, carried=None):
    conn = db.connect(tmp_path / "data")
    try:
        drafts = db.load_drafts(conn, session_id)
        raw_items = [json.loads(db._draft_to_json(d)) for d in drafts]
    finally:
        conn.close()
    body = {"items": raw_items,
            "confirmed": list(range(len(raw_items))) if confirmed_all else []}
    if carried is not None:
        body["carried"] = carried
    return body


# --- 1. partial sessions keep the rest ------------------------------------


def test_second_live_session_keeps_rest_of_list(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    names = ["tomato", "onion", "potato", "banana", "coconut", "carrot",
             "beans", "brinjal"]
    _publish(tmp_path, token, [_draft(n, 10 + i) for i, n in enumerate(names)])
    # Second live session updates 2 of the 8.
    session_id = _start_review_session(
        tmp_path, token, "live",
        [_draft("tomato", 99), _draft("onion", 88)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Also on your list (not in this session)" in html
    # 6 carried items, all checked by default.
    assert html.count("data-carried") >= 6
    assert "Remove all of these" in html
    # Approve keeping all carried (default checked).
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        base_id = db.latest_version(conn, shop["id"], published_only=True)
        base_items = db.version_items(conn, base_id)
        # carried = base minus tomato/onion
        carried_ids = [it.id for it in base_items
                       if it.name_en not in ("tomato", "onion")]
        assert len(carried_ids) == 6
    finally:
        conn.close()
    body = _approve_payload(tmp_path, session_id, carried=carried_ids)
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        new_id = db.latest_version(conn, shop["id"])
        items = db.version_items(conn, new_id)
        assert len(items) == 8, [i.name_en for i in items]
        by_name = {i.name_en: i for i in items}
        assert by_name["tomato"].price_lines[0].price == Decimal(99)
        assert by_name["onion"].price_lines[0].price == Decimal(88)
    finally:
        conn.close()


def test_unchecked_carried_item_dropped(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 30),
                               _draft("potato", 40)])
    session_id = _start_review_session(
        tmp_path, token, "live", [_draft("tomato", 99)])
    client.get(f"/e/{token}/s/{session_id}")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        base_id = db.latest_version(conn, shop["id"], published_only=True)
        base_items = db.version_items(conn, base_id)
        onion_id = next(i.id for i in base_items if i.name_en == "onion")
        potato_id = next(i.id for i in base_items if i.name_en == "potato")
    finally:
        conn.close()
    # Uncheck onion, keep potato.
    body = _approve_payload(tmp_path, session_id, carried=[potato_id])
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        items = db.version_items(conn, db.latest_version(conn, shop["id"]))
        names = sorted(i.name_en for i in items)
        assert names == ["potato", "tomato"], names
        assert onion_id not in [i.id for i in items]
    finally:
        conn.close()


def test_board_session_replaces_only_onion(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 30),
                               _draft("potato", 40)])
    from app.models import Flag

    board_draft = _draft("onion", 35)
    board_draft.proof.source = "board_photo"
    board_draft.flags = [Flag(field="price", code="BOARD_CONFIRM",
                              message="read from your board – tap to confirm",
                              options=["35"], blocking=True)]
    session_id = _start_review_session(tmp_path, token, "board", [board_draft])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Also on your list (not in this session)" in html
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        base_items = db.version_items(
            conn, db.latest_version(conn, shop["id"], published_only=True))
        carried_ids = [i.id for i in base_items if i.name_en != "onion"]
    finally:
        conn.close()
    body = _approve_payload(tmp_path, session_id, carried=carried_ids)
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        items = db.version_items(conn, db.latest_version(conn, shop["id"]))
        assert len(items) == 3
        by_name = {i.name_en: i for i in items}
        assert by_name["onion"].price_lines[0].price == Decimal(35)
        assert by_name["tomato"].price_lines[0].price == Decimal(20)
        assert by_name["potato"].price_lines[0].price == Decimal(40)
    finally:
        conn.close()


def test_first_session_behaves_as_before(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _start_review_session(
        tmp_path, token, "video", [_draft("tomato", 20)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Also on your list" not in html
    body = _approve_payload(tmp_path, session_id)
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        items = db.version_items(conn, db.latest_version(conn, shop["id"]))
        assert [i.name_en for i in items] == ["tomato"]
    finally:
        conn.close()


# --- 2. QR codes visible ---------------------------------------------------


def test_qr_svg_uses_path_not_rect():
    from app.outputs.qr import qr_svg

    svg = qr_svg("https://example.com/b/abc123")
    assert "<?xml" not in svg
    assert "svg:rect" not in svg
    assert "<svg" in svg and "viewBox=" in svg
    assert "<path d=" in svg


def test_bill_page_qr_has_viewbox_path(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET upi_id=? WHERE id=?",
                     ("shop@okbank", shop["id"]))
        conn.commit()
        from app.market.quote import WantedLine, build_quote
        quote = build_quote(conn, shop["id"],
                            [WantedLine("tomato", Decimal(1), "kg", "text")])
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "svg:rect" not in html
    assert "viewBox=" in html
    assert "<path d=" in html


def test_settings_qr_no_rect(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/settings").text
    assert "svg:rect" not in html
    assert "viewBox=" in html


def test_qr_pdfs_still_render(tmp_path):
    from app.outputs.link_card import link_card_pdf
    from app.outputs.pdf import price_board_pdf, price_tags_pdf

    shop = {"name": "S", "slug": "s", "area": "A", "phone": "1",
            "currency": "INR"}
    from app.models import Item
    items = [Item(id=1, version_id=1, name_local="தக்காளி", name_en="tomato",
                  variety=None, qty=None, qty_unit=None, photo=None,
                  sold_out=False, price_lines=[PriceLine(Decimal(20), Decimal(1), "kg")],
                  proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0))]
    at = datetime(2026, 10, 28, 9, 0)
    for pdf in (price_board_pdf(shop, items, at, "http://x/s/s"),
                price_tags_pdf(shop, items, at, "http://x/s/s"),
                link_card_pdf(shop, "http://x/e/tok")):
        assert pdf[:5] == b"%PDF-"


# --- 3. paid bills locked --------------------------------------------------


def _seed_bill(tmp_path, token, lines=None):
    from app.market.quote import WantedLine, build_quote
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        wanted = lines or [WantedLine("tomato", Decimal(2), "kg", "text"),
                           WantedLine("onion", Decimal(2), "kg", "text")]
        quote = build_quote(conn, shop["id"], wanted)
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status="billed")
        return db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()


def test_edit_paid_rejected(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 29)])
    bill_id = _seed_bill(tmp_path, token)
    assert client.post(f"/e/{token}/bills/{bill_id}/paid",
                       data={"mode": "cash"}).status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        before = db.get_quote_by_id(conn, bill_id)["total"]
    finally:
        conn.close()
    import html as html_lib
    msg = "This bill is paid. Tap 'Change bill' to reopen it."
    # lines
    r1 = client.post(f"/e/{token}/bills/{bill_id}/lines",
                     data={"name_en_0": "tomato", "qty_0": "1", "unit_0": "kg",
                           "name_en_1": "onion", "qty_1": "2", "unit_1": "kg"})
    assert msg in html_lib.unescape(r1.text), r1.text[:2000]
    # add
    r2 = client.post(f"/e/{token}/bills/{bill_id}/add",
                     data={"name_en": "tomato", "qty": "1", "unit": "kg"})
    assert msg in html_lib.unescape(r2.text)
    # remove
    r3 = client.post(f"/e/{token}/bills/{bill_id}/remove", data={"index": "0"})
    assert msg in html_lib.unescape(r3.text)
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, bill_id)
        assert row["total"] == before
        assert row["status"] == "paid"
    finally:
        conn.close()
    # read-only receipt view: no steppers/chips/remove on paid page
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Change bill" in html
    assert "data-stepper" not in html
    assert "data-chips" not in html
    assert "/remove" not in html


def test_reopen_then_edit_works(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 29)])
    bill_id = _seed_bill(tmp_path, token)
    client.post(f"/e/{token}/bills/{bill_id}/paid", data={"mode": "cash"})
    resp = client.post(f"/e/{token}/bills/{bill_id}/reopen")
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, bill_id)
        assert row["status"] == "billed"
        assert (row["payment_mode"] or "") == ""
        assert (row["paid_at"] or "") == ""
    finally:
        conn.close()
    # edit now works
    r2 = client.post(f"/e/{token}/bills/{bill_id}/remove", data={"index": "0"})
    assert r2.status_code in (302, 303), r2.text


def test_day_close_reflects_reopened(tmp_path):
    from app.dayclose import day_tiles, shop_today
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    bill_id = _seed_bill(tmp_path, token,
                         [__import__("app.market.quote", fromlist=["WantedLine"]).WantedLine(
                             "tomato", Decimal(1), "kg", "text")])
    client.post(f"/e/{token}/bills/{bill_id}/paid", data={"mode": "cash"})
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = shop_today(shop, datetime.now(UTC))
        t1 = day_tiles(conn, shop, day)
        assert t1["cash"] > 0 and t1["unpaid"] == Decimal("0.00")
    finally:
        conn.close()
    client.post(f"/e/{token}/bills/{bill_id}/reopen")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = shop_today(shop, datetime.now(UTC))
        t2 = day_tiles(conn, shop, day)
        assert t2["cash"] == Decimal("0.00")
        assert t2["unpaid"] > 0
    finally:
        conn.close()


# --- 4. per-unit POS rate --------------------------------------------------


def test_pos_csv_per_unit_rate(tmp_path):
    from app.outputs.pos_csv import pos_csv
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 18, "0.5", "kg"),
                               _draft("coriander", 10, 1, "bunch")])
    from app.market.quote import WantedLine, build_quote
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = build_quote(conn, shop["id"],
                            [WantedLine("tomato", Decimal(1), "kg", "text"),
                             WantedLine("coriander", Decimal(1), "bunch", "text")])
        db.create_quote(conn, shop_id=shop["id"], quote=quote,
                        source="seller", kind="bill", status="billed")
        from app.dayclose import shop_today
        day = shop_today(shop, datetime.now(UTC))
        payload = pos_csv(conn, shop, day, day)
    finally:
        conn.close()
    import csv
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    by_name = {r["item_name"]: r for r in rows}
    assert by_name["tomato"]["rate"] in ("36", "36.00")
    assert by_name["tomato"]["amount"] in ("36", "36.00")
    assert by_name["coriander"]["rate"] in ("10", "10.00")
    assert by_name["coriander"]["amount"] in ("10", "10.00")


def test_excel_per_unit_rate(tmp_path):
    from app.outputs.excel import sales_workbook
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 18, "0.5", "kg")])
    from app.market.quote import WantedLine, build_quote
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = build_quote(conn, shop["id"],
                            [WantedLine("tomato", Decimal(1), "kg", "text")])
        db.create_quote(conn, shop_id=shop["id"], quote=quote,
                        source="seller", kind="bill", status="billed")
        from app.dayclose import shop_today
        day = shop_today(shop, datetime.now(UTC))
        data = sales_workbook(conn, shop, day, day)
    finally:
        conn.close()
    import openpyxl
    book = openpyxl.load_workbook(io.BytesIO(data))
    rows = list(book["Lines"].iter_rows(min_row=2, values_only=True))
    assert rows, "expected a Lines row"
    # Bill no, Date, Item EN, Item local, Qty, Unit, Rate, Amount
    assert rows[0][6] == 36 or rows[0][6] == 36.0
    assert rows[0][7] == 36 or rows[0][7] == 36.0


def test_exports_doc_says_per_one_unit():
    text = Path("docs/exports.md").read_text()
    assert "rate is per one unit" in text.lower()


# --- 5. bill PDF + tags ----------------------------------------------------


def test_bill_pdf_round_off_and_paid(tmp_path):
    from pypdf import PdfReader
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    from app.market.quote import Quote, QuoteLine
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET round_bills=1 WHERE id=?", (shop["id"],))
        conn.commit()
        q = Quote(lines=[QuoteLine("tomato", "தக்காளி", Decimal(1), "kg",
                                  Decimal("77.50"), Decimal(1),
                                  Decimal("77.50"), "priced")],
                  total=Decimal("77.50"), priced_count=1, unpriced_count=0,
                  prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=q,
                                 source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        db.mark_bill_paid(conn, bill_id, "cash")
    finally:
        conn.close()
    pdf = client.get(f"/e/{token}/bills/{bill_id}/pdf")
    assert pdf.status_code == 200
    text = "\n".join(p.extract_text() or ""
                     for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Round off +0.50" in text
    assert "Paid" in text and "Cash" in text


def test_tags_template_reserves_qr_and_wraps():
    src = Path("app/web/templates/tags.html").read_text()
    assert "padding-right" in src
    # Long Tamil names must wrap instead of running under the QR.
    assert "overflow-wrap" in src or "word-break" in src
    # Both title lines reserve the QR width.
    assert src.count("padding-right") >= 2


# --- 6. tap layout + close table -------------------------------------------


def test_new_bill_tap_layout_structure(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("coriander", 10, 1, "bunch")])
    html = client.get(f"/e/{token}/bills/new").text
    # photo thumb | name+rate left flex1 | stepper right, chips below aligned
    assert "tap-line" in html or "tap-main" in html
    css = Path("app/web/static/app.css").read_text()
    assert ".tap-line" in css or ".tap-main" in css
    assert "flex: 1" in css or "flex:1" in css


def test_close_table_css():
    css = Path("app/web/static/app.css").read_text()
    assert ".close-table" in css
    block = css.split(".close-table", 1)[1][:2000]
    assert "width" in block and "100%" in block
    assert "padding" in block


# --- 7. Tamil notice -------------------------------------------------------


def test_notice_keys_exist():
    from app.web.i18n import STRINGS
    for lang in ("en", "ta", "hi"):
        assert "notice.voice" in STRINGS[lang], f"missing notice.voice in {lang}"
    assert "Meta" in STRINGS["en"]["notice.voice"]
    assert any(ord(c) > 127 for c in STRINGS["ta"]["notice.voice"])
    assert any(ord(c) > 127 for c in STRINGS["hi"]["notice.voice"])


def test_tamil_dashboard_no_voice_english(tmp_path):
    client = _client(tmp_path)
    client.cookies.clear()
    resp = client.post("/new", data={
        "name": "T43 Tamil", "phone": "+914400000044", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    token = resp.headers["location"].split("/e/")[1]
    html = client.get(f"/e/{token}").text
    assert "Your voice recording is sent to Meta's AI service to be transcribed." not in html
