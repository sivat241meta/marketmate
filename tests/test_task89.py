"""Task 89: v10 shared form components and easy seller setup forms.

Pins the _ui.html form macros, forms.css, and the rebuilt seller-setup
forms (new shop, settings, new bill, credit payment, purchases, photos,
voice update, language check, rename dialog).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.web.i18n import t_for

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "web" / "templates"
FORMS_CSS = ROOT / "app" / "web" / "static" / "css" / "forms.css"


def _env():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.globals["t"] = t_for("en")
    return env


def _macro(name: str, *args, **kwargs) -> str:
    tpl = _env().from_string(
        "{% import '_ui.html' as ui %}{{ ui." + name + "(*args, **kwargs) }}")
    return tpl.render(args=args, kwargs=kwargs)


def _call_macro(name: str, body: str, *args, **kwargs) -> str:
    tpl = _env().from_string(
        "{% import '_ui.html' as ui %}{% call ui." + name
        + "(*args, **kwargs) %}" + body + "{% endcall %}")
    return tpl.render(args=args, kwargs=kwargs)


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client, **over) -> str:
    data = {"name": "T89 Store", "phone": "+914400000089",
            "area": "Koyambedu", "language": "ta", "currency": "INR",
            "type": "vegetable"}
    data.update(over)
    resp = client.post("/new", data=data)
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en="tomato", price=40):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en,
        name_local=CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        flags=[], confirmed=True)


def _publish(tmp_path, token, drafts) -> None:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
    finally:
        conn.close()


def _seed_bill(tmp_path, token, total="40.00"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(lines=[QuoteLine(
            name_en="tomato", name_local="தக்காளி", qty=Decimal(1),
            unit="kg", unit_price=Decimal(total), per_amount=Decimal(1),
            line_total=Decimal(total), status="priced")],
            total=Decimal(total), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill",
                                 status="billed")
        return db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()


def _seed_credit_customer(client, tmp_path, token):
    bill_id = _seed_bill(tmp_path, token)
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "98765 43210"})
    assert resp.status_code in (302, 303), resp.text
    return "9876543210"


def _seed_purchase_review(tmp_path, token):
    from app.pipeline.purchase import write_purchase_meta

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "purchase")
        db.set_session_status(conn, session_id, "review", "1 item")
    finally:
        conn.close()
    write_purchase_meta(tmp_path / "data", session_id, {
        "transcript": "onion 50 kilo 1200",
        "drafts": [{
            "name_spoken": "onion", "name_local": "வெங்காயம்",
            "name_en": "onion", "qty": "50", "unit": "kg",
            "total_cost": "1200",
            "proof": {"quote": "onion 50 kilo 1200", "turn_ids": [1],
                      "start_ms": 0, "end_ms": 1000},
            "flags": []}],
    })
    return session_id


def _seed_review_session(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id, [_draft()])
        db.set_session_status(conn, session_id, "review", "1 item")
        return session_id
    finally:
        conn.close()


def _seed_langcheck(tmp_path, token):
    import json

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


# --- 1. shared macros ---------------------------------------------------------

def test_field_macro_structure():
    html = _macro("field", "Shop name", "name", value="K",
                  hint="Shown on the board.", required=True,
                  inputmode="text", autocomplete="organization",
                  attrs={"id": "shop-name", "maxlength": "60"})
    assert '<div class="field">' in html
    label_at = html.index('class="field-label"')
    input_at = html.index('class="field-input"')
    hint_at = html.index('class="field-hint"')
    assert label_at < input_at < hint_at, "label above, hint below"
    assert 'for="shop-name"' in html and 'id="shop-name"' in html
    assert 'name="name"' in html and 'value="K"' in html
    assert "required" in html and '<span class="req"' in html
    assert 'autocomplete="organization"' in html
    assert 'maxlength="60"' in html
    assert "field-error" not in html


def test_field_macro_types_and_error():
    html = _macro("field", "Phone", "phone", type="tel", inputmode="tel",
                  autocomplete="tel", error="bad number",
                  attrs={"id": "shop-phone"})
    assert 'type="tel"' in html
    assert 'inputmode="tel"' in html
    assert 'aria-invalid="true"' in html
    assert '<p class="field-error"' in html
    assert "bad number" in html


def test_select_and_textarea_macros():
    html = _call_macro("select_field", '<option value="ta">x</option>',
                       "Language", "language", hint="Speak it.",
                       required=True, attrs={"id": "set-language"})
    assert html.index('class="field-label"') < html.index("<select")
    assert 'name="language"' in html and "required" in html
    assert '<option value="ta">x</option>' in html
    assert "Speak it." in html
    html = _macro("textarea_field", "Note", "note", value="hi", rows=4,
                  attrs={"id": "note"})
    assert "<textarea" in html and 'rows="4"' in html and ">hi<" in html


def test_form_card_action_bar_toast_more_macros():
    html = _call_macro("form_card", "<p>body</p>", "Title", "Sub")
    assert html.startswith("<section") and 'class="form-card"' in html
    assert "Title" in html and "Sub" in html and "<p>body</p>" in html
    html = _call_macro("action_bar", "<button>Go</button>")
    assert html == '<div class="action-bar"><button>Go</button></div>'
    html = _macro("toast", "Saved")
    assert 'class="toast"' in html and 'role="status"' in html
    assert "Saved" in html
    html = _call_macro("more", "<p>rare</p>", "More options")
    assert '<details class="more">' in html
    assert "<summary>More options</summary>" in html
    assert "<p>rare</p>" in html


def test_error_summary_macro():
    html = _macro("error_summary", "bad phone")
    assert 'class="error-summary"' in html
    assert 'role="alert"' in html
    assert "There is a problem" in html
    assert "<li>bad phone</li>" in html
    html = _macro("error_summary", ["one", "two"])
    assert "<li>one</li>" in html and "<li>two</li>" in html


# --- 2. static wiring ---------------------------------------------------------

def test_forms_css_linked_after_app_css(tmp_path):
    html = _client(tmp_path).get("/new").text
    app_at = html.index("app.css")
    forms_at = html.index("css/forms.css")
    assert app_at < forms_at, "forms.css must load after app.css"
    assert FORMS_CSS.is_file()
    css = FORMS_CSS.read_text()
    for selector in (".field-label", ".field-input", ".field-hint",
                     ".field-error", ".form-card", ".action-bar",
                     ".toast", ".more", ".error-summary", ".v10-title"):
        assert selector in css, selector
    assert "var(--bnav-h)" in css, "action bar needs the bnav lift"
    assert "[data-stepper]" in css, "steppers need 48px targets"


def test_forms_css_served_with_version(tmp_path):
    html = _client(tmp_path).get("/new").text
    match = re.search(r"/static/css/forms\.css\?v=([0-9a-f]{10})", html)
    assert match, "forms.css needs a cache-busting ?v= query"
    resp = _client(tmp_path).get("/static/css/forms.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


# --- 3. new shop --------------------------------------------------------------

NEW_FIELDS = ['name="name"', 'name="phone"', 'name="area"',
              'name="language"', 'name="currency"', 'name="type"',
              'name="upi_id"', 'name="listed"']


def test_new_shop_three_steps_and_same_field_names(tmp_path):
    html = _client(tmp_path).get("/new").text
    assert html.count('data-pane="') == 3, "3 steps on one page"
    assert html.count("data-step-dot=") == 3, "step indicator"
    assert "Step 1 of 3" in html
    assert "data-next" in html and "data-back" in html
    assert "Create my shop" in html
    for field in NEW_FIELDS:
        assert field in html, field
    assert 'value="0" name="listed"' in html or 'name="listed" value="0"' \
        in html or 'type="hidden" name="listed"' in html
    assert 'id="shop-language"' in html and 'id="shop-currency"' in html
    assert html.index("field-label") < html.index("field-input")


def test_new_shop_failed_submit_shows_error_summary(tmp_path):
    client = _client(tmp_path)
    base = {"name": "S", "phone": "+914400000000", "area": "A",
            "language": "ta", "currency": "INR", "type": "vegetable"}
    bad = client.post("/new", data={**base, "phone": "abc"})
    assert bad.status_code == 422
    assert "error-summary" in bad.text
    assert "field-error" in bad.text
    assert bad.text.count('data-pane="') == 3
    empty = client.post("/new", data={})
    assert empty.status_code == 422
    assert "error-summary" in empty.text


def test_new_shop_saves_upi_and_listed(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/new", data={
        "name": "S", "phone": "+914400000000", "area": "A",
        "language": "ta", "currency": "INR", "type": "vegetable",
        "upi_id": "shop@okbank", "listed": "0"})
    assert resp.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        shop = conn.execute("SELECT * FROM shops").fetchone()
        assert shop["upi_id"] == "shop@okbank"
        assert shop["listed"] == 0
    finally:
        conn.close()
    bad_upi = client.post("/new", data={
        "name": "S", "phone": "+914400000000", "area": "A",
        "language": "ta", "currency": "INR", "type": "vegetable",
        "upi_id": "not-a-upi"})
    assert bad_upi.status_code == 422
    assert "error-summary" in bad_upi.text


# --- 4. settings --------------------------------------------------------------

def test_settings_sections_hours_editor_and_single_save(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/settings").text
    for title in ("Shop profile", "Payments (UPI)", "Opening hours",
                  "Shop location (optional)", "Find a shop", "Language"):
        assert title in html, title
    assert html.count("data-day-row=") == 7
    for name in ("closed_0", "open_0_1", "close_0_1", "open_0_2",
                 "close_0_2", "closed_6", "open_6_2", "close_6_2"):
        assert f'name="{name}"' in html, name
    assert "Same every day" in html
    assert "data-same-everyday" in html
    assert "More options" in html
    assert "Round bills to the nearest rupee" in html
    assert html.count("btn btn-primary") == 1, "one primary Save"
    assert "action-bar" in html
    assert 'id="use-location"' in html and 'id="copy-seller"' in html
    assert "stored rounded to about 100 m" in html


def test_settings_hours_post_saves_same_fields(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    resp = client.post(f"/e/{token}/settings", data={
        "name": "T89 Store", "area": "Koyambedu",
        "phone": "+914400000089", "language": "ta", "currency": "INR",
        "type": "vegetable", "open_0_1": "09:00", "close_0_1": "13:00",
        "open_0_2": "16:00", "close_0_2": "21:00", "closed_6": "1"})
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].endswith("/settings?saved=1")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        assert '"09:00"' in (shop["hours_json"] or "")
        assert "6" in (shop["hours_json"] or "")
    finally:
        conn.close()
    saved = client.get(f"/e/{token}/settings?saved=1").text
    assert 'class="toast"' in saved and "Saved" in saved


def test_settings_failed_submit_shows_error_summary(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    base = {"name": "T89 Store", "area": "Koyambedu",
            "phone": "+914400000089", "language": "ta",
            "currency": "INR", "type": "vegetable"}
    bad = client.post(f"/e/{token}/settings",
                      data={**base, "phone": "abc"})
    assert bad.status_code == 400
    assert "error-summary" in bad.text
    assert "field-error" in bad.text


# --- 5. new bill --------------------------------------------------------------

def test_bills_new_picker_total_and_type_card(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    fresh = client.get(f"/e/{token}/bills/new").text
    assert "error-summary" not in fresh
    assert f"/e/{token}/live" in fresh, "no-list empty state needs a next step"
    _publish(tmp_path, token, [_draft()])
    html = client.get(f"/e/{token}/bills/new").text
    assert "data-tap-form" in html
    assert "data-stepper" in html
    bar = re.search(r'<div class="float tap-bar[^"]*">.*?</button>\s*</div>',
                    html, re.DOTALL).group(0)
    assert "action-bar" in bar
    assert "data-tap-summary" in bar, "running total in the sticky bar"
    assert "Make bill" in bar
    assert 'name="items"' in html
    assert "data-composer-text" in html, "type tab is the composer text mode"
    assert "data-composer" in html and "composer.js" in html


# --- 6. credit ----------------------------------------------------------------

def test_credit_pay_form_error_and_saved(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    key = _seed_credit_customer(client, tmp_path, token)
    url = f"/e/{token}/credit/{key}"
    html = client.get(url).text
    assert 'id="credit-amount"' in html and 'name="amount"' in html
    assert 'id="credit-mode"' in html and 'name="mode"' in html
    assert "wa.me" in html, "reminder action kept"
    assert "Record payment" in html
    over = client.post(url + "/pay", data={"amount": "999",
                                           "mode": "cash"})
    assert over.status_code == 400
    assert "error-summary" in over.text
    assert "field-error" in over.text
    ok = client.post(url + "/pay", data={"amount": "10", "mode": "upi"})
    assert ok.status_code in (302, 303)
    assert ok.headers["location"].endswith("?saved=1")
    saved = client.get(url + "?saved=1").text
    assert 'class="toast"' in saved


# --- 7. purchases -------------------------------------------------------------

def test_purchases_forms_error_and_saved(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/purchases").text
    for name in ('name="audio"', 'name="item"', 'name="quantity"',
                 'name="unit"', 'name="total_paid"'):
        assert name in html, name
    assert "data-composer" in html and "composer.js" in html
    assert 'href="#record"' in html, "empty state needs a next step"
    bad = client.post(f"/e/{token}/purchases/add", data={
        "item": "tomato", "quantity": "ten", "unit": "kg",
        "total_paid": "200"})
    assert bad.status_code == 400
    assert "error-summary" in bad.text
    assert "field-error" in bad.text
    ok = client.post(f"/e/{token}/purchases/add", data={
        "item": "tomato", "quantity": "10", "unit": "kg",
        "total_paid": "200"})
    assert ok.status_code in (302, 303)
    assert ok.headers["location"].endswith("/purchases?saved=1")
    assert 'class="toast"' in client.get(
        f"/e/{token}/purchases?saved=1").text


def test_purchase_review_confirm_bar(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _seed_purchase_review(tmp_path, token)
    html = client.get(f"/e/{token}/purchases/{session_id}").text
    assert "Confirm purchases" in html
    assert 'name="confirmed"' in html or "sticky-bar" in html
    assert "sticky-bar action-bar" in html


# --- 8. photos / update / language check --------------------------------------

def test_photos_upload_forms(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/photos").text
    assert 'id="photo-camera"' in html
    assert 'id="photo-gallery"' in html
    assert html.count('name="photo"') == 2
    assert "Scan this photo" in html
    assert "action-bar" in html
    assert 'href="#scan"' in html, "empty state needs a next step"


def test_update_record_form_keeps_hooks(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/update").text
    for hook in ("data-composer", "data-composer-form", "data-composer-mic",
                 "data-composer-send", "data-composer-cancel",
                 "data-composer-plus", "composer.js", "board-photo",
                 'name="audio"', 'name="photo"', 'id="board"'):
        assert hook in html, hook
    assert "form-card" in html


def test_language_check_forms(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _seed_langcheck(tmp_path, token)
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert 'name="speak_lang"' in html
    assert 'id="langcheck-more"' in html
    assert 'id="langcheck-go"' in html
    assert "form-card" in html and "action-bar" in html


# --- 9. rename dialog ---------------------------------------------------------

def test_rename_dialog_keeps_names_and_hooks(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft()])
    seller = client.get(f"/e/{token}").text
    assert "data-rename-sheet" in seller
    assert "data-rename-form" in seller
    for name in ('name="name_local"', 'name="name_en"',
                 'name="variety"'):
        assert name in seller, name
    assert "field-label" in seller, "labels above the rename inputs"
    session_id = _seed_review_session(tmp_path, token)
    review = client.get(f"/e/{token}/s/{session_id}").text
    assert "data-rename-form" in review
    assert "data-rename-save" in review
    for name in ('name="name_local"', 'name="name_en"',
                 'name="variety"'):
        assert name in review, name


# --- 10. every owned page renders in en/ta/hi ---------------------------------

def _owned_urls(client, tmp_path, token):
    key = _seed_credit_customer(client, tmp_path, token)
    purchase_id = _seed_purchase_review(tmp_path, token)
    lang_id = _seed_langcheck(tmp_path, token)
    _publish(tmp_path, token, [_draft()])
    return [
        ("/new", "data-newshop"),
        (f"/e/{token}/settings", "data-day-row"),
        (f"/e/{token}/settings?saved=1", 'class="toast"'),
        (f"/e/{token}/bills/new", "data-tap-form"),
        (f"/e/{token}/credit/{key}", "credit-amount"),
        (f"/e/{token}/purchases", "data-composer"),
        (f"/e/{token}/purchases?saved=1", 'class="toast"'),
        (f"/e/{token}/purchases/{purchase_id}", "sticky-bar"),
        (f"/e/{token}/photos", "photo-camera"),
        (f"/e/{token}/update", "data-composer"),
        (f"/e/{token}/s/{lang_id}", "langcheck-go"),
    ]


def test_owned_pages_render_all_langs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    urls = _owned_urls(client, tmp_path, token)
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url, marker in urls:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url} -> " \
                f"{resp.status_code}"
            assert marker in resp.text, f"{lang} {url} missing {marker}"


def test_tamil_text_kept_on_owned_pages(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    client.cookies.set("ui_lang", "ta")
    html = client.get(f"/e/{token}/settings").text
    assert "திறந்திருக்கும் நேரம்" in html
    html = client.get("/new").text
    assert "உங்கள் கடையைத் திறங்கள்" in html
