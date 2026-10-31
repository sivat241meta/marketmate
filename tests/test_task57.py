"""Task 57 polish: bars clear the bottom nav, language check, variety names,
first-run card, localised dates. Failing-tests-first."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"

TA_DAYS = ("திங்கள்", "செவ்வாய்", "புதன்", "வியாழன்", "வெள்ளி", "சனி",
           "ஞாயிறு")
TA_MONTHS = ("ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்",
             "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்",
             "டிசம்பர்")
HI_DAYS = ("सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार",
           "रविवार")
HI_MONTHS = ("जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई",
             "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, language="ta"):
    resp = client.post("/new", data={
        "name": "Polish Store", "phone": "+914400000057",
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


def draft(name_en, name_local, price, variety=None, flags=()):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety, price_lines=[pl(price)],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        flags=list(flags), confirmed=True)


def seed_published(tmp_path, token, drafts, kind="video"):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        if kind in ("video", "live", "board"):
            db.ensure_session_base(conn, session_id)
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def seed_bill(tmp_path, token, lines, total, day="2026-10-27", kind="bill",
              status="billed"):
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
                                 source="seller", kind=kind, status=status)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        y, m, d = (int(p) for p in day.split("-"))
        local = datetime(y, m, d, 9, 30, tzinfo=IST)
        conn.execute("UPDATE quotes SET created_at = ? WHERE id = ?",
                     (local.astimezone(UTC).isoformat(), bill_id))
        conn.commit()
        return bill_id
    finally:
        conn.close()


def seed_review_session(tmp_path, token, drafts, kind="video"):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        db.save_drafts(conn, session_id, list(drafts))
        db.set_session_status(conn, session_id, "review",
                              f"{len(drafts)} items need review")
        return session_id
    finally:
        conn.close()


def seed_langcheck(tmp_path, token):
    from app.pipeline.scripts import dominant_script

    text = "ಟೊಮೇಟೊ ಬೆಲೆ ನಲವತ್ತು"
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        session_dir = data_dir / "sessions" / str(session_id)
        (session_dir / "frames").mkdir(parents=True, exist_ok=True)
        (session_dir / "audio.wav").write_bytes(b"fake-wav")
        (session_dir / "frames" / "f_1000.jpg").write_bytes(b"fake-jpg")
        (session_dir / "transcript.json").write_text(json.dumps({
            "text": text, "duration_ms": 9000,
            "turns": [{"id": 1, "start_ms": 0, "end_ms": 9000,
                       "text": text}]}))
        db.set_session_status(conn, session_id, "processing", "test")
        db.set_stage(conn, session_id, "language_check",
                     detail=dominant_script(text))
        return session_id
    finally:
        conn.close()


# --- 1. one CSS variable for the bottom nav height ---------------------------

def test_css_bnav_variable_shared_by_bnav_and_lifted_bars():
    css = CSS.read_text()
    assert "--bnav-h" in css
    assert "calc(68px" not in css  # old hard-coded lift is gone
    bnav_block = css.split(".bnav {", 1)[1].split("}", 1)[0]
    assert "var(--bnav-h)" in bnav_block
    assert "body:has(.bnav) .float" in css
    assert "body:has(.bnav) .sticky-bar" in css
    lift_start = css.index("body:has(.bnav)")
    lift_block = css[lift_start:css.index("}", lift_start)]
    assert "var(--bnav-h)" in lift_block
    assert "8px" in lift_block


# --- 2. language check: empty default, disabled Continue, guide look --------

def test_language_check_empty_default_and_disabled_continue(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_langcheck(tmp_path, token)
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert '<option value="">' in html
    # Empty default comes first, so Arabic is no longer pre-selected.
    assert html.index('<option value="">') < html.index('value="ar"')
    go = html.index('id="langcheck-go"')
    button_open = html.rindex("<button", 0, go)
    button_tag = html[button_open:html.index(">", go) + 1]
    assert "disabled" in button_tag
    assert "One quick check" in html
    assert "<h1" in html and "big" in html.split("<h1", 1)[1][:40]


def test_language_chips_at_least_46px():
    css = CSS.read_text()
    assert "min-height" in css
    # button.chip keeps the 48px tap target (>= 46px).
    assert "--tap: 48px" in css or "--tap:48px" in css


# --- 3. variety said once in Tamil --------------------------------------------

def test_variety_once_helper():
    from app.pipeline.names import display_name_local

    assert display_name_local("பூவன் பழம்", "poovan") == "பூவன் பழம்"
    assert (display_name_local("வாழைப்பழம்", "poovan")
            == "வாழைப்பழம் (பூவன்)")
    assert display_name_local("வாழைப்பழம்", None) == "வாழைப்பழம்"


def test_bill_page_repeats_no_variety(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token,
                   [draft("banana", "பூவன் பழம்", 60, variety="poovan")])
    bill_id = seed_bill(
        tmp_path, token,
        [("banana", "பூவன் பழம்", "poovan", "1", "kg", "60", "60.00")],
        "60.00")
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "பூவன் பழம் (பூவன்)" not in html
    assert "பூவன் பழம்" in html


# --- 4. POS CSV + Excel keep the variety --------------------------------------

def test_pos_csv_variety_code_and_name(tmp_path):
    from app.outputs.pos_csv import pos_csv

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token,
                   [draft("banana", "பூவன் பழம்", 60, variety="poovan")])
    seed_bill(tmp_path, token,
              [("banana", "பூவன் பழம்", "poovan", "1", "kg", "60",
                "60.00")],
              "60.00", day="2026-10-27")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        payload = pos_csv(conn, shop, "2026-10-27", "2026-10-27")
    finally:
        conn.close()
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert rows[0]["item_code"] == "banana-poovan"
    assert rows[0]["item_name"] == "Banana (Poovan)"
    assert rows[0]["item_name_local"] == "பூவன் பழம்"


def test_pricelist_csv_variety_code_and_name(tmp_path):
    from app.outputs.pos_csv import pricelist_csv

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token,
                   [draft("banana", "பூவன் பழம்", 60, variety="poovan")])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        payload = pricelist_csv(conn, shop)
    finally:
        conn.close()
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert rows[0]["item_code"] == "banana-poovan"
    assert rows[0]["item_name"] == "Banana (Poovan)"
    assert rows[0]["item_name_local"] == "பூவன் பழம்"


def test_excel_lines_and_items_keep_variety(tmp_path):
    import openpyxl

    from app.outputs.excel import sales_workbook

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token,
                   [draft("banana", "பூவன் பழம்", 60, variety="poovan")])
    seed_bill(tmp_path, token,
              [("banana", "பூவன் பழம்", "poovan", "1", "kg", "60",
                "60.00")],
              "60.00", day="2026-10-27")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        data = sales_workbook(conn, shop, "2026-10-27", "2026-10-27")
    finally:
        conn.close()
    book = openpyxl.load_workbook(io.BytesIO(data))
    line_names = [r[2].value for r in
                  book["Lines"].iter_rows(min_row=2)]
    assert "Banana (Poovan)" in line_names
    item_names = [r[0].value for r in
                  book["Items"].iter_rows(min_row=2)]
    assert "Banana (Poovan)" in item_names


# --- 5. localised date kickers -------------------------------------------------

def test_tamil_seller_home_kicker(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    client.cookies.set("ui_lang", "ta")
    html = client.get(f"/e/{token}").text
    today = date.today()
    assert TA_DAYS[today.weekday()] in html
    assert TA_MONTHS[today.month - 1] in html
    assert today.strftime("%A") not in html


def test_hindi_seller_home_kicker(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    client.cookies.set("ui_lang", "hi")
    html = client.get(f"/e/{token}").text
    today = date.today()
    assert HI_DAYS[today.weekday()] in html
    assert HI_MONTHS[today.month - 1] in html


def test_day_close_kicker_localised(tmp_path):
    assert date(2026, 10, 29).strftime("%A") == "Thursday"
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    client.cookies.set("ui_lang", "ta")
    html = client.get(f"/e/{token}/close?date=2026-10-29").text
    assert "வியாழன்" in html
    assert "அக்டோபர்" in html
    client.cookies.set("ui_lang", "hi")
    html = client.get(f"/e/{token}/close?date=2026-10-29").text
    assert "गुरुवार" in html
    assert "अक्टूबर" in html


# --- 6. first-run Get started card ---------------------------------------------

def test_first_run_card_shows_until_published(tmp_path):
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    html = client.get(f"/e/{token}").text
    assert "Get started" in html
    assert "Save your link" in html
    assert "Say today" in html or "today&#39;s prices" in html.lower()
    assert "Share your shop" in html
    # Band of zeros stays hidden until the first bill.
    assert "This week in numbers" not in html
    client.cookies.set("ui_lang", "ta")
    assert t_for("ta")("gs.title") in client.get(f"/e/{token}").text
    client.cookies.set("ui_lang", "en")
    seed_published(tmp_path, token, [draft("tomato", "தக்காளி", 40)])
    html = client.get(f"/e/{token}").text
    assert "Get started" not in html
    seed_bill(tmp_path, token,
              [("tomato", "தக்காளி", None, "2", "kg", "40", "80.00")],
              "80.00")
    assert "This week in numbers" in client.get(f"/e/{token}").text


# --- 7. source-aware customer notice -------------------------------------------

def _shop_notice(tmp_path, token, lang="en"):
    client = make_client(tmp_path)
    slug = slug_of(tmp_path, token)
    url = f"/s/{slug}" + (f"?lang={lang}" if lang != "en" else "")
    return client.get(url).text


def test_customer_notice_names_the_source(tmp_path):
    client = make_client(tmp_path)
    cases = [("video", "in today&#39;s video"),
             ("live", "live prices"),
             ("board", "board photo"),
             ("voice_update", "voice note")]
    for kind, phrase in cases:
        token = token_of(create_shop(client))
        seed_published(tmp_path, token, [draft("tomato", "தக்காளி", 40)],
                       kind=kind)
        html = _shop_notice(tmp_path, token)
        assert phrase in html.lower() or phrase in html, (kind, html)


def test_customer_notice_tamil_and_mixed(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft("tomato", "தக்காளி", 40)],
                   kind="video")
    html = _shop_notice(tmp_path, token, lang="ta")
    assert "இன்றைய வீடியோவில்" in html
    # A board photo on top of a video version mixes the sources.
    seed_published(tmp_path, token, [draft("onion", "வெங்காயம்", 30)],
                   kind="board")
    html = _shop_notice(tmp_path, token)
    assert "today&#39;s recording" in html.lower()


# --- 8. capitalised flag questions ----------------------------------------------

def test_flag_text_capitalised_en_unchanged_ta_hi():
    from app.web.i18n import flag_text

    flag = Flag(field="price", code="SOUND_ALIKE",
                message="did you say 50 or 80?",
                options=["50", "80"], blocking=True)
    assert flag_text(flag, "en") == "Did you say 50 or 80?"
    assert flag_text(flag, "ta") == "50ஆ 80ஆ சொன்னீங்க?"
    assert flag_text(flag, "hi") == "आपने 50 बोला या 80?"


def test_check_page_flag_capitalised(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(
        tmp_path, token,
        [draft("tomato", "தக்காளி", 50, flags=[Flag(
            field="price", code="SOUND_ALIKE",
            message="did you say 50 or 80?", options=["50", "80"],
            blocking=True)])])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Did you say 50 or 80?" in html


# --- 9. bill public URL wraps ----------------------------------------------------

def test_bill_public_url_wraps():
    css = CSS.read_text()
    assert ".shop-link" in css
    start = css.index(".shop-link")
    assert "overflow-wrap" in css[start:start + 400]
    assert "anywhere" in css[start:start + 400]


# --- 10. home credit + lost link --------------------------------------------------

def test_home_credit_and_lost_link(tmp_path):
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = client.get("/").text
    # Task 127: the v13 footer credits the Meta AI models.
    assert t_for("en")("v13.built_models") in html
    # Task 127: the shared footer links the lost-link help, but the
    # full section lives on /sellers only.
    assert 'id="lost-link"' not in html
    html = client.get("/sellers").text
    assert "Lost your link?" in html
    assert 'id="lost-link"' in html
    client.cookies.set("ui_lang", "ta")
    html = client.get("/").text
    assert t_for("ta")("v13.built_models") in html
    html = client.get("/sellers").text
    assert t_for("ta")("home.lost_title") in html
    client.cookies.set("ui_lang", "hi")
    html = client.get("/").text
    assert t_for("hi")("v13.built_models") in html
    html = client.get("/sellers").text
    assert t_for("hi")("home.lost_title") in html


# --- every touched page renders in en, ta and hi ---------------------------------

def _seed_everything(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token,
                   [draft("banana", "பூவன் பழம்", 60, variety="poovan")])
    bill_id = seed_bill(
        tmp_path, token,
        [("banana", "பூவன் பழம்", "poovan", "1", "kg", "60", "60.00")],
        "60.00")
    session_id = seed_review_session(
        tmp_path, token, [draft("tomato", "தக்காளி", 50)])
    lang_id = seed_langcheck(tmp_path, token)
    slug = slug_of(tmp_path, token)
    return client, token, slug, bill_id, session_id, lang_id


def test_touched_pages_render_en_ta_hi(tmp_path):
    client, token, slug, bill_id, session_id, lang_id = _seed_everything(
        tmp_path)
    urls = [f"/e/{token}", f"/e/{token}/s/{session_id}",
            f"/e/{token}/s/{lang_id}", f"/e/{token}/bills/{bill_id}",
            f"/e/{token}/close?date=2026-10-27", f"/s/{slug}", "/"]
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 200, (lang, url, resp.status_code)


def test_new_shop_home_renders_en_ta_hi(tmp_path):
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        resp = client.get(f"/e/{token}")
        assert resp.status_code == 200, lang
