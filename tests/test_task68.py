"""Task 68: v9 polish after the owner's review.

Full-width seller workspace, Today header, collapsible groups, shared
rename dialog, short rail labels, orders board statuses, breadcrumbs,
single phone bars, products-first phone shop, letter-tile varieties
and Tamil name repair.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof, Transcript


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
TEMPLATES = ROOT / "app" / "web" / "templates"


def _client(tmp_path, lang="en") -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    return client


def _create_shop(client, name="T68 Stall", phone="+914400000068",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en="banana", price=80, local="வாழைப்பழம்", variety="poovan",
           qty=None, qty_unit=None, flags=None):
    return DraftItem(
        name_spoken=name_en, name_local=local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg",
                               "kilo eighty")],
        qty=qty, qty_unit=qty_unit,
        proof=Proof(quote=f"{name_en} kilo {price}", turn_ids=[1],
                    start_ms=0, end_ms=1000),
        flags=flags or [], confirmed=True)


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


def _slug(tmp_path, token) -> str:
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def _seed_order(tmp_path, token, status="new", name="Priya", kind="quote",
                source="customer"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(lines=[QuoteLine(
            name_en="tomato", name_local="தக்காளி", qty=Decimal(1),
            unit="kg", unit_price=Decimal(40), per_amount=Decimal(1),
            line_total=Decimal(40), status="priced")],
            total=Decimal(40), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source=source, kind=kind, status=status,
                                 customer_name=name)
        return db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()


def _start_review_session(tmp_path, token, kind, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review",
                              f"{len(drafts)} items need review")
        return session_id
    finally:
        conn.close()


def _section(html: str, section_id: str) -> str:
    start = html.find(f'id="{section_id}"')
    assert start != -1, f"missing section {section_id}"
    ends = [len(html)]
    for other in ("step-morning", "step-day", "step-evening",
                  "todays-list", "more"):
        if other != section_id:
            at = html.find(f'id="{other}"', start + 1)
            if at != -1:
                ends.append(at)
    return html[start:min(ends)]


def _clusters(text: str) -> list[str]:
    out: list[str] = []
    for char in text:
        if unicodedata.category(char).startswith("M") and out:
            out[-1] += char
        else:
            out.append(char)
    return out


# --- 1. Today header + full-width workspace ---------------------------------


def test_today_header_is_workspace_style(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி", None)])
    html = client.get(f"/e/{token}").text
    assert '<h1 class="today-title">Today</h1>' in html
    assert "Good morning" in html or "Good afternoon" in html \
        or "Good evening" in html
    assert "sold today" in html
    assert "Live · 1 price" in html
    assert '<h1 class="big">' not in html.split('id="step-morning"')[0]


def test_today_header_when_not_live(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    assert '<h1 class="today-title">Today</h1>' in html
    assert "Not live yet" in html


def test_seller_content_fills_width_right_of_rail():
    css = CSS.read_text()
    block = re.search(
        r"@media \(min-width: 1000px\) \{\s*"
        r"body:has\(\.rail\) \.content \{([^}]*)\}", css)
    assert block, "no full-width seller content rule at >=1000px"
    body = block.group(1)
    assert "max-width: 1440px" in body
    assert "margin: 0" in body
    assert "padding: 24px" in body
    assert re.search(r"\.today-title \{\s*font-size: 26px", css)
    assert re.search(
        r"@media \(max-width: 999\.98px\) \{\s*"
        r"\.today-title \{ font-size: 22px", css)


# --- 2. Today groups: one header, SVG chevron, collapse ----------------------


def test_today_groups_have_one_header_each(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி", None)])
    html = client.get(f"/e/{token}").text
    assert html.count('class="gh"') == 4
    assert html.count('data-grp="') == 4
    assert "▾" not in html
    assert 'class="icon chev"' in html
    morning = _section(html, "step-morning")
    assert 'class="kick"' not in morning
    evening = _section(html, "step-evening")
    assert 'class="kick"' not in evening
    assert "MORNING" in morning and "EVENING" in evening


def test_group_collapse_remembers_per_group(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    assert "mm_grp_" in html
    assert "aria-expanded" in html
    assert "is-collapsed" in html
    css = CSS.read_text()
    assert ".grp.is-collapsed > :not(.gh)" in css
    assert ".grp.is-collapsed .gh .chev" in css


# --- 3. rename dialog + Today's list -----------------------------------------


def test_rename_opener_is_icon_button_with_modal_dialog(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி", None)])
    html = client.get(f"/e/{token}").text
    assert "rename-dialog.js" in html
    assert html.count('class="pen-icon"') == 2, \
        "Today's list row + side panel row each need one icon opener"
    assert 'aria-label="Rename"' in html
    assert "data-rename-sheet" in html
    # No-JS fallback: the form still posts to the existing route.
    assert 'method="post"' in html
    assert f"/e/{token}/item/" in html and '/name"' in html
    assert 'name="name_local"' in html
    assert 'name="name_en"' in html
    assert 'name="variety"' in html


def test_rename_dialog_css_is_centred_or_bottom_sheet():
    css = CSS.read_text()
    assert ".rdlg-wrap" in css and "position: fixed" in css
    assert ".rdlg-backdrop" in css
    assert re.search(r"\.pen-icon \{[^}]*width: 32px", css)
    sheet = re.search(
        r"@media \(max-width: 600px\) \{\s*"
        r"\.rdlg-wrap \{([^}]*)\}", css)
    assert sheet and "align-items: flex-end" in sheet.group(1)


def test_check_page_uses_same_rename_dialog(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _start_review_session(
        tmp_path, token, "video", [_draft(), _draft("tomato", 20,
                                                   "தக்காளி", None)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "rename-dialog.js" in html
    assert html.count("data-rename-open") == 2
    assert html.count("data-rename-form") == 2
    assert 'aria-label="Rename"' in html
    assert "data-rename-save" in html
    assert "data-rename-cancel" in html


def test_todays_list_row_structure(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft()])
    html = client.get(f"/e/{token}").text
    assert "list-thumb letter" in html
    assert "banana · poovan · 1 kg" in html
    assert "mini-main" in html
    css = CSS.read_text()
    assert ".list-row .list-thumb { width: 44px" in css
    assert ".mini-main { flex: 1; min-width: 0" in css
    assert "#todays-list > summary { justify-content: flex-start" in css


def test_stock_not_counted_line(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft(), _draft("tomato", 40,
                                                "தக்காளி", None)])
    html = client.get(f"/e/{token}").text
    assert "Stock not counted" in html
    assert "in stock" not in html
    assert "Not counted:" not in html


def test_left_out_names_deduped_with_variety(tmp_path):
    from app.outputs.value import stock_left_out_display

    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [
        _draft("tomato", 40, "தக்காளி", None, qty=Decimal(5),
               qty_unit="kg"),
        _draft(), _draft(),
        _draft("banana", 60, "வாழைப்பழம்", "yelakki"),
    ])
    html = client.get(f"/e/{token}").text
    assert "in stock" in html
    assert html.count("Banana (Poovan)") == 1
    assert html.count("Banana (Yelakki)") == 1
    assert stock_left_out_display([]) == []


# --- 4. rail labels ----------------------------------------------------------


def test_rail_is_80px_with_whole_word_labels():
    css = CSS.read_text()
    assert "width: 80px" in css
    assert "margin-left: 80px" in css
    labels = re.search(
        r"\.rail \.ic span:not\(\.nbadge\) \{([^}]*)\}", css)
    assert labels, "no rail label rule"
    body = labels.group(1)
    assert "font-size: 10px" in body
    assert "word-break: keep-all" in body
    assert "overflow-wrap: normal" in body


def test_rail_labels_short_in_ta_hi(tmp_path):
    from app.web.i18n import STRINGS

    for lang in ("ta", "hi"):
        for key in ("rail.today", "rail.prices", "rail.orders",
                    "rail.bills", "rail.credit", "rail.close",
                    "rail.more"):
            label = STRINGS[lang][key]
            assert "\u200b" not in label, f"{lang} {key}: zwsp trick"
            assert len(_clusters(label)) <= 8, \
                f"{lang} {key}={label!r} too long"
    assert STRINGS["ta"]["rail.prices"] == "விலை"
    assert STRINGS["hi"]["rail.prices"] == "दाम"
    client = _client(tmp_path, lang="ta")
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    rail = re.search(r'<nav class="rail".*?</nav>', html, re.DOTALL)
    assert rail and "விலை" in rail.group(0)
    assert "விலைகள்" not in rail.group(0)


# --- 5. orders board uses the list's orders ----------------------------------


def test_board_column_mapping():
    from app.web.bills import board_column_for

    assert board_column_for({"source": "customer",
                             "status": "new"}) == "waiting"
    assert board_column_for({"source": "customer",
                             "status": "packing"}) == "packing"
    assert board_column_for({"source": "customer",
                             "status": "ready"}) == "ready"
    assert board_column_for({"source": "customer",
                             "status": "collected"}) == "collected"
    assert board_column_for({"source": "customer",
                             "status": "billed"}) == "waiting"
    assert board_column_for({"source": "customer",
                             "status": "paid"}) == "collected"
    assert board_column_for({"source": "customer",
                             "status": "cancelled"}) is None
    assert board_column_for({"source": "customer",
                             "status": "credit"}) is None
    assert board_column_for({"source": "seller",
                             "status": "ready"}) is None
    assert board_column_for({"source": "seller",
                             "status": "billed"}) is None


def test_board_shows_every_customer_order_status(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி", None)])
    new_id = _seed_order(tmp_path, token, "new", "Priya")
    packing_id = _seed_order(tmp_path, token, "packing", "Ravi")
    ready_id = _seed_order(tmp_path, token, "ready", "Meena")
    collected_id = _seed_order(tmp_path, token, "collected", "Kala")
    billed_id = _seed_order(tmp_path, token, "billed", "Anbu",
                            kind="bill")
    paid_id = _seed_order(tmp_path, token, "paid", "Divya", kind="bill")
    cancelled_id = _seed_order(tmp_path, token, "cancelled", "Gone")
    walkin_id = _seed_order(tmp_path, token, "billed", "Walk",
                            kind="bill", source="seller")
    html = client.get(f"/e/{token}/bills?range=today&status=all").text
    chunks = html.split('<section class="colb"')[1:]
    assert len(chunks) == 4
    counts = [chunk.count('class="ocard"') for chunk in chunks]
    assert counts == [2, 1, 1, 2], counts
    assert f"Order #{new_id}" in chunks[0]
    assert f"Order #{billed_id}" in chunks[0]
    assert f"Order #{packing_id}" in chunks[1]
    assert f"Order #{ready_id}" in chunks[2]
    assert f"Order #{collected_id}" in chunks[3]
    assert f"Order #{paid_id}" in chunks[3]
    board = html.split('<div class="board">')[1]
    assert f"/e/{token}/bills/{cancelled_id}" not in board
    assert f"/e/{token}/bills/{walkin_id}" not in board


def test_board_exact_case_bill_ready_customer(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி", None)])
    order_id = _seed_order(tmp_path, token, "ready", "Meena",
                           kind="bill", source="customer")
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT kind, source, status FROM quotes"
                           " WHERE id = ?", (order_id,)).fetchone()
        assert tuple(row) == ("bill", "customer", "ready")
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills?range=today&status=all").text
    assert f"Order #{order_id}" in html
    chunks = html.split('<section class="colb"')[1:]
    assert len(chunks) == 4
    assert chunks[2].count('class="ocard"') == 1
    assert f"Order #{order_id}" in chunks[2]


# --- 6. breadcrumbs ----------------------------------------------------------


def _seed_crumb_shop(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி",
                                      variety=None)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id, [_draft()])
        db.set_session_status(conn, session_id, "review", "1 item")
        proc_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, proc_id, "processing", "working")
        lang_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, lang_id, "processing", "test")
        db.set_stage(conn, lang_id, "language_check", detail="other")
        pur_id = db.create_session(conn, shop["id"], "purchase")
        db.set_session_status(conn, pur_id, "review", "1 item")
        bill_sid = db.create_session(conn, shop["id"], "bill_voice")
        db.set_session_status(conn, bill_sid, "processing", "working")
        check_id = db.save_photo_check(
            conn, shop_id=shop["id"], image_path="x.jpg",
            report_json={}, cost=0.0)
    finally:
        conn.close()
    bill_id = _seed_order(tmp_path, token, "billed", "Walk",
                          kind="bill", source="seller")
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "98765 43210"})
    assert resp.status_code in (302, 303), resp.text
    match = re.search(rf"/e/{re.escape(token)}/credit/([^\"]+)",
                      client.get(f"/e/{token}/credit").text)
    assert match, "no credit customer link"
    return client, token, {
        "session": session_id, "proc": proc_id, "lang": lang_id,
        "bill": bill_id, "pur": pur_id, "bill_sid": bill_sid,
        "check": check_id, "credit_key": match.group(1),
    }


def test_every_seller_page_names_its_crumb(tmp_path):
    client, token, ids = _seed_crumb_shop(tmp_path)
    urls = [
        f"/e/{token}", f"/e/{token}/live",
        f"/e/{token}/s/{ids['session']}", f"/e/{token}/s/{ids['proc']}",
        f"/e/{token}/s/{ids['lang']}",
        f"/e/{token}/s/{ids['session']}/live",
        f"/e/{token}/bills/new", f"/e/{token}/bills",
        f"/e/{token}/bills/{ids['bill']}",
        f"/e/{token}/bills?range=today&status=waiting",
        f"/e/{token}/bills/new/{ids['bill_sid']}",
        f"/e/{token}/close", f"/e/{token}/credit",
        f"/e/{token}/credit/{ids['credit_key']}",
        f"/e/{token}/settings", f"/e/{token}/purchases",
        f"/e/{token}/purchases/{ids['pur']}", f"/e/{token}/update",
        f"/e/{token}/photos", f"/e/{token}/photos/{ids['check']}",
    ]
    for url in urls:
        html = client.get(url).text
        match = re.search(
            r'<div class="crumb">.*?<b>(.*?)</b>', html, re.DOTALL)
        assert match, f"{url}: no breadcrumb"
        assert match.group(1).strip(), f"{url}: empty page name"


# --- 7. phone seller top: one bar --------------------------------------------


def test_phone_seller_top_is_one_bar(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    assert 'class="wordmark"' in html
    assert "data-sound-compact" in html
    assert 'class="iconbtn"' in html
    css = CSS.read_text()
    assert "body.is-seller .hdr { flex-wrap: nowrap" in css
    assert "body.is-seller .hdr .wordmark { display: none" in css
    assert ".hdr .iconbtn" in css


# --- 8. phone shop: products first --------------------------------------------


def test_phone_shop_orders_products_first(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி", None)])
    html = client.get(f"/s/{slug}").text
    assert 'class="is-shop"' in html or "is-shop" in html
    # Task 127: no hero2 band — the compact info card precedes the
    # grid in DOM order, so phones get prices without reordering.
    assert 'class="hero2"' not in html
    assert html.index('class="info-card"') < html.index("data-shop-grid")
    assert html.index("data-shop-grid") < html.index("data-cart-bar")


# --- 9. letter tiles carry the variety ----------------------------------------


def test_tile_variety_helper():
    from app.web.i18n import tile_variety

    assert tile_variety(None) == ""
    assert tile_variety("") == ""
    assert tile_variety("poovan") == "பூவன்"
    assert tile_variety("yelakki") == "ஏலக்கி"
    assert tile_variety("bengaluru") == "Bengaluru"


def test_two_banana_varieties_have_distinct_tiles(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [
        _draft("banana", 80, "வாழைப்பழம்", "poovan"),
        _draft("banana", 60, "வாழைப்பழம்", "yelakki"),
    ])
    shop_html = client.get(f"/s/{slug}").text
    # Task 127: the shop page shows item photos, so the two varieties
    # are told apart by their variety tags, not letter tiles.
    assert "poovan" in shop_html and "yelakki" in shop_html
    assert shop_html.count("VARIETY:") == 2
    home = client.get(f"/e/{token}").text
    assert '<span class="til-v">பூவன்</span>' in home
    assert '<span class="til-v">ஏலக்கி</span>' in home
    tap = client.get(f"/e/{token}/bills/new").text
    assert '<span class="til-v">பூவன்</span>' in tap


# --- 10. Tamil name repair ----------------------------------------------------


def test_repair_local_name_helper():
    from app.pipeline.names import CANONICAL_NAMES, repair_local_name

    assert CANONICAL_NAMES["broad beans"] == "அவரைக்காய்"
    assert repair_local_name("broad beans", "அவரககய") == "அவரைக்காய்"
    assert repair_local_name("broad beans", "அவரைக்காய்") == "அவரைக்காய்"
    assert repair_local_name("broad beans", "seller special") == \
        "seller special"
    assert repair_local_name("other", "அவரககய") == "அவரககய"
    assert repair_local_name("broad beans", None) is None


def test_pipeline_repairs_markless_draft_name():
    from app.pipeline.extract import parse_extract_json

    data = {"items": [{
        "name_en": "broad beans", "name_local": "அவரககய",
        "name_spoken": "avarai", "quote": "avarai kilo fifty",
        "turn_ids": [], "prices": []}]}
    items = parse_extract_json(
        data, Transcript(text="", duration_ms=0, turns=[]),
        language="ta")
    assert len(items) == 1
    assert items[0].name_en == "broad beans"
    assert items[0].name_local == "அவரைக்காய்"
    # Other languages keep what was said.
    items_hi = parse_extract_json(
        data, Transcript(text="", duration_ms=0, turns=[]),
        language="hi")
    assert items_hi[0].name_local == "அவரககய"


def test_migration_repairs_existing_rows_but_not_seller_names(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="ta")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        broken = _draft("broad beans", 50, "அவரககய", None)
        kept = _draft("broad beans", 55, "அவரககய", "karpooravalli")
        version_id = db.approve(conn, session_id, [broken, kept])
        db.set_published(conn, version_id, True)
        items = db.version_items(conn, version_id)
        assert [item.name_local for item in items] == [
            "அவரககய", "அவரககய"]
        # The second row carries a seller-chosen name: never touch it.
        db.save_chosen_name(conn, shop["id"], "broad beans",
                            "karpooravalli", "அவரககய", "broad beans")
        db.log_name_change(conn, shop["id"], items[1].id,
                           ("old", "broad beans", None),
                           ("அவரககய", "broad beans", "karpooravalli"))
    finally:
        conn.close()
    repaired = db.connect(tmp_path / "data")
    try:
        again = db.version_items(repaired, version_id)
        assert again[0].name_local == "அவரைக்காய்"
        assert again[1].name_local == "அவரககய"
    finally:
        repaired.close()
    # A later connect changes nothing further.
    third_conn = db.connect(tmp_path / "data")
    try:
        third = db.version_items(third_conn, version_id)
        assert [item.name_local for item in third] == [
            "அவரைக்காய்", "அவரககய"]
    finally:
        third_conn.close()


def test_migration_skips_non_tamil_shops(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="hi", phone="+914400000069",
                         name="T68 Hindi")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(
            conn, session_id, [_draft("broad beans", 50, "அவரககய",
                                      None)])
    finally:
        conn.close()
    fixed = db.connect(tmp_path / "data")
    try:
        items = db.version_items(fixed, version_id)
        assert items[0].name_local == "அவரககய"
    finally:
        fixed.close()


# --- i18n parity + JS checks --------------------------------------------------


def test_no_missing_i18n_keys():
    from app.web.i18n import missing_keys

    assert missing_keys() == {"ta": [], "hi": []}


def test_changed_js_passes_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    for name in ("rename-dialog.js", "review.js", "live.js"):
        proc = subprocess.run(
            [node, "--check", f"app/web/static/{name}"], cwd=ROOT,
            check=False, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"{name}: {proc.stderr}"


def test_rename_dialog_js_behaviour():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/rename_dialog.test.mjs"], cwd=ROOT,
        check=False, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
