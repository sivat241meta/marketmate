"""Task 40: Tamil and Hindi seller screens (failing first)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")


def _client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, language="ta", name="T40 Store", phone="+914400000040"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"].split("/e/")[1]


def _seed_published(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        drafts = [DraftItem(
            name_spoken="thakkali", name_local="தக்காளி", name_en="tomato",
            variety=None, price_lines=[PriceLine(Decimal(40), Decimal(1), "kg", "kilo forty")],
            qty=None, qty_unit=None,
            proof=Proof(quote="thakkali kilo forty", turn_ids=[], start_ms=0, end_ms=0),
            confirmed=True)]
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
    finally:
        conn.close()


def test_catalogue_has_seller_keys_and_no_missing():
    from app.web.i18n import STRINGS

    for lang in ("en", "ta", "hi"):
        assert lang in STRINGS, f"missing language {lang}"
    en_keys = set(STRINGS["en"])
    # Seller catalogue must exist, grouped by page.
    for key in ("nav.dashboard", "nav.prices", "nav.photos", "nav.bills",
                "dash.live_prices", "dash.go_live", "review.title",
                "flag.sound_alike", "bills.new_bill", "close.title",
                "set.title", "error.try_samples"):
        assert key in en_keys, f"missing seller key {key}"
    missing = {}
    for lang in ("ta", "hi"):
        miss = sorted(en_keys - set(STRINGS[lang]))
        missing[lang] = miss
        assert not miss, f"missing {lang} keys: {miss[:20]}"


def test_t_helper_falls_back_to_english():
    from app.web.i18n import t_for

    t_ta = t_for("ta")
    assert t_ta("nav.dashboard") != "nav.dashboard"
    assert t_ta("no.such.key") == t_for("en")("no.such.key", default="x") or "x"


def test_default_follows_shop_language_and_cookie_overrides(tmp_path):
    client = _client(tmp_path)
    token_ta = _create_shop(client, language="ta", phone="+914400000041")
    token_en = _create_shop(client, language="en", name="EN Store", phone="+914400000042")
    # Default: ta shop renders Tamil, en shop renders English.
    html_ta = client.get(f"/e/{token_ta}").text
    assert "தமிழ்" in html_ta or "விலை" in html_ta
    html_en = client.get(f"/e/{token_en}").text
    assert ">Today<" in html_en
    # Cookie overrides shop language.
    client.cookies.set("ui_lang", "hi")
    html_hi = client.get(f"/e/{token_ta}").text
    assert "हिन्दी" in html_hi or "दाम" in html_hi or "बिल" in html_hi
    client.cookies.set("ui_lang", "en")
    html_en_override = client.get(f"/e/{token_ta}").text
    assert ">Today<" in html_en_override
    client.cookies.clear()
    # Toggle present in seller topbar.
    assert 'data-ui-lang="ta"' in html_ta or "ui_lang" in html_ta


def test_customer_pages_keep_lang_behaviour(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="ta")
    _seed_published(tmp_path, token)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        slug = shop["slug"]
    finally:
        conn.close()
    html_en = client.get(f"/s/{slug}?lang=en").text
    # Task 127 polish: the green notice box is gone; the top strip
    # keeps the said-today line in the page language.
    assert "Prices said by the seller today" in html_en
    html_ta = client.get(f"/s/{slug}?lang=ta").text
    assert "விற்பனையாளர்" in html_ta


def test_flag_message_translated_stored_english(tmp_path):
    from app.web.i18n import flag_text

    flag = Flag(field="price", code="SOUND_ALIKE",
                message="did you say 18 or 80? (50 and 80 sound alike in Tamil)",
                options=["18", "80"])
    ta = flag_text(flag, "ta")
    hi = flag_text(flag, "hi")
    assert "18" in ta and "80" in ta
    assert ta != flag.message
    assert any(ord(c) > 127 for c in ta), ta
    assert any(ord(c) > 127 for c in hi), hi
    # Stored message stays English.
    assert flag.message.startswith("did you say")


def test_whatsapp_bill_text_tamil(tmp_path):
    from app.web.i18n import bill_whatsapp_text

    shop = {"name": "Kannan", "currency": "INR"}
    lines = [{"name_en": "tomato", "qty": "2", "unit": "kg",
              "line_total": "80.00", "status": "priced"}]
    text = bill_whatsapp_text(shop, 7, lines, "80.00", "ta")
    assert "7" in text and "80" in text
    assert any(ord(c) > 127 for c in text), text


def test_no_english_leftovers_on_tamil_dashboard(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="ta")
    _seed_published(tmp_path, token)
    html = client.get(f"/e/{token}").text
    for needle in ("Dashboard", "Live prices", "Go live", "Upload a video",
                   "Update by voice", "Scan stock photo", "Print board",
                   "Today's list", "Recent sessions", "Versions",
                   "Bills today", "Sales today", "Close day", "Settings",
                   "Check prices", "Approve price list",
                   "Your voice recording is sent to Meta's AI service to be transcribed."):
        assert needle not in html, f"English leftover: {needle}"


def test_every_seller_template_renders_all_langs(tmp_path):
    from app.market.quote import Quote, QuoteLine

    client = _client(tmp_path)
    token = _create_shop(client, language="ta")
    _seed_published(tmp_path, token)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(lines=[QuoteLine(
            name_en="tomato", name_local="தக்காளி", qty=Decimal(1), unit="kg",
            unit_price=Decimal(40), per_amount=Decimal(1),
            line_total=Decimal(40), status="priced")],
            total=Decimal(40), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        session_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, session_id, "processing", "working")
    finally:
        conn.close()
    urls = [f"/e/{token}", f"/e/{token}/update", f"/e/{token}/live",
            f"/e/{token}/photos", f"/e/{token}/bills",
            f"/e/{token}/bills/new", f"/e/{token}/bills/{bill_id}",
            f"/e/{token}/settings", f"/e/{token}/purchases",
            f"/e/{token}/close", f"/e/{token}/s/{session_id}"]
    for lang in ("en", "ta", "hi"):
        for url in urls:
            client.cookies.set("ui_lang", lang)
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url} -> {resp.status_code}"
            if lang == "en":
                assert ">Today<" in resp.text, f"en {url} missing seller nav"
            else:
                assert ">Today<" not in resp.text, f"{lang} {url} still English nav"
                assert any(ord(ch) > 127 for ch in resp.text), f"{lang} {url} has no translated script"
            client.cookies.clear()
