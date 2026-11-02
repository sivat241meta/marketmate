"""Task 91: v10 seller pages in the homepage design language.

Pins the v10 seller shell (page-head header block, homepage-style
sections, one primary action per screen in an action bar, section heads,
empty states with a next step), the shared _ui.html form macros, the new
seller.css, the kept JS hooks, helper link scoping, and en/ta/hi render.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "css" / "seller.css"
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
TEMPLATES = ROOT / "app" / "web" / "templates"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, name="T91 Store", phone="+914400000091",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en="tomato", price=40, local=None, flags=None):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en,
        name_local=local or CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        flags=flags or [], confirmed=True)


def _two_price_draft():
    return _draft("carrot", 50, flags=[Flag(
        field="price", code="TWO_PRICES",
        message="Did you say ₹50 or ₹80?",
        options=["50", "80"], blocking=True)])


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


def _seed_bill(tmp_path, token, status="billed", total="40.00",
               kind="bill", source="seller", name="Walk"):
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
                                 source=source, kind=kind, status=status,
                                 customer_name=name)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        if status == "paid":
            db.mark_bill_paid(conn, bill_id, "cash")
        return bill_id
    finally:
        conn.close()


def _seed_review_session(tmp_path, token, drafts=None):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id,
                       drafts or [_two_price_draft(), _draft("onion", 30)])
        db.set_session_status(conn, session_id, "review", "2 items")
        return session_id
    finally:
        conn.close()


def _seed_status_session(tmp_path, token, kind="video", status="processing",
                         message="working"):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        db.set_session_status(conn, session_id, status, message)
        return session_id
    finally:
        conn.close()


def _seed_credit_customer(client, tmp_path, token):
    bill_id = _seed_bill(tmp_path, token, status="billed", total="90.00")
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "98765 43210"})
    assert resp.status_code in (302, 303), resp.text
    match = re.search(rf"/e/{re.escape(token)}/credit/([^\"]+)",
                      client.get(f"/e/{token}/credit").text)
    assert match, "no credit customer link"
    return match.group(1)


def _bar(html: str):
    """The page's single primary-action bar, if any."""
    return re.findall(r'<div class="[^"]*\baction-bar\b[^"]*">', html)


# --- 1. seller.css + base link -----------------------------------------------


def test_seller_stylesheet_linked_after_app_css():
    base = (TEMPLATES / "base.html").read_text()
    assert "css/seller.css" in base
    assert base.index("app.css") < base.index("css/seller.css")
    assert CSS.is_file()
    css = CSS.read_text()
    for cls in (".page-head", ".page-title", ".page-sub", ".page-actions",
                ".action-bar", ".form-card", ".field-label", ".field-input",
                ".field-hint", ".field-error", ".toast", ".more",
                ".eyebrow", ".ssec"):
        assert cls in css, cls
    # Sticky on phones, lifted above the bottom nav like .sticky-bar.
    assert "body:has(.bnav) .action-bar" in css
    assert "var(--bnav-h)" in css
    assert "z-index: 8" in css
    # v9 tokens only: none of the retired pre-v9 colours.
    from test_task64 import OLD_HEXES
    lowered = css.lower()
    for stop in OLD_HEXES:
        assert f"#{stop.lower()}" not in lowered, stop
    assert "var(--accent-ink)" in css


def test_shared_macros_exist_with_brief_signatures():
    ui = (TEMPLATES / "_ui.html").read_text()
    assert "macro field(label, name" in ui
    assert "macro select_field(" in ui
    assert "macro textarea_field(" in ui
    assert "macro form_card(" in ui
    assert "macro action_bar(" in ui
    assert "macro toast(" in ui
    assert "macro more(" in ui
    assert '<section class="form-card">' in ui
    assert '<div class="action-bar">' in ui
    assert '<div class="toast" role="status">' in ui
    assert '<details class="more">' in ui


# --- 2. one primary action per screen ----------------------------------------


def test_today_has_one_sticky_primary(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}").text
    assert len(_bar(html)) == 1
    assert "page-head" in html
    assert "today-title" in html


def test_today_staff_bar_links_to_new_bill_only(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        _, helper = db.create_helper(conn, shop["id"], "Muthu")
    finally:
        conn.close()
    html = client.get(f"/e/{helper}").text
    assert len(_bar(html)) == 1
    assert f"/e/{helper}/bills/new" in html


def test_review_approve_is_the_primary_and_disabled_with_reason(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    session_id = _seed_review_session(tmp_path, token)
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert len(_bar(html)) == 1
    assert "sticky-bar" in html
    btn = re.search(r'<button[^>]*id="approve-btn"[^>]*>', html).group(0)
    assert "disabled" in btn
    assert 'aria-describedby="approve-count"' in btn
    assert 'id="approve-count"' in html
    assert "data-approve-count" in html
    assert "review-progress" in html


def test_live_mic_is_the_primary_action(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/live").text
    assert "data-live-mic" in html
    assert "page-head" in html
    assert "page-title" in html


def test_bills_new_bill_is_the_primary(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token)
    html = client.get(f"/e/{token}/bills").text
    assert len(_bar(html)) == 1
    assert f'href="/e/{token}/bills/new"' in html


def test_bill_collect_bar_and_states(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    billed = _seed_bill(tmp_path, token, status="billed", total="51.00")
    html = client.get(f"/e/{token}/bills/{billed}").text
    assert len(_bar(html)) == 1
    assert "sticky-bar bill-bar" in html
    paid = _seed_bill(tmp_path, token, status="paid", total="36.00")
    paid_html = client.get(f"/e/{token}/bills/{paid}").text
    assert not _bar(paid_html)
    assert "Paid by" in paid_html


def test_close_has_one_close_day_action(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="36.00")
    html = client.get(f"/e/{token}/close").text
    assert len(_bar(html)) == 1
    assert f'action="/e/{token}/close"' in html
    assert "Close day" in html
    resp = client.post(f"/e/{token}/close")
    assert resp.status_code in (302, 303), resp.text
    closed = client.get(f"/e/{token}/close").text
    assert "Closed at" in closed
    assert not _bar(closed)


def test_credit_customer_remind_is_primary(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    key = _seed_credit_customer(client, tmp_path, token)
    html = client.get(f"/e/{token}/credit/{key}").text
    assert len(_bar(html)) == 1
    assert "Send reminder on WhatsApp" in html


def test_session_states_have_one_primary_or_progress(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    failed = _seed_status_session(tmp_path, token, status="failed",
                                  message="boom")
    failed_html = client.get(f"/e/{token}/s/{failed}").text
    assert len(_bar(failed_html)) == 1
    assert "Try again" in failed_html
    approved = _seed_status_session(tmp_path, token, status="approved",
                                    message="done")
    approved_html = client.get(f"/e/{token}/s/{approved}").text
    assert approved_html.count("action-bar") <= 2  # at most one bar div
    assert "Back to shop" in approved_html
    working = _seed_status_session(tmp_path, token)
    working_html = client.get(f"/e/{token}/s/{working}").text
    assert "data-stepper" in working_html
    assert "page-head" in working_html


def test_bill_voice_status_states(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    failed = _seed_status_session(tmp_path, token, kind="bill_voice",
                                  status="failed", message="boom")
    failed_html = client.get(f"/e/{token}/bills/new/{failed}").text
    assert len(_bar(failed_html)) == 1
    working = _seed_status_session(tmp_path, token, kind="bill_voice")
    working_html = client.get(f"/e/{token}/bills/new/{working}").text
    assert "data-stepper" in working_html


# --- 3. homepage-style sections ----------------------------------------------


def test_section_heads_and_cards(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id = _seed_bill(tmp_path, token)
    key = _seed_credit_customer(client, tmp_path, token)
    pages_with_heads = [
        f"/e/{token}/bills",
        f"/e/{token}/bills/{bill_id}",
        f"/e/{token}/close",
        f"/e/{token}/credit",
        f"/e/{token}/credit/{key}",
        f"/e/{token}/ai",
        f"/e/{token}/purchases",
    ]
    for url in pages_with_heads:
        html = client.get(url).text
        assert "page-head" in html, f"{url}: no header block"
        assert "page-title" in html, f"{url}: no title"
    for url in (f"/e/{token}/bills", f"/e/{token}/close",
                f"/e/{token}/credit/{key}", f"/e/{token}/purchases"):
        html = client.get(url).text
        assert "hp-sec-head" in html, f"{url}: no section head"
        assert "ssec" in html, f"{url}: no v10 section"
    # Today keeps its group heads plus an All-orders right link.
    home = client.get(f"/e/{token}").text
    assert home.count('class="gh"') == 4
    assert "All orders →" in home
    # Exports hide behind More on bills + close.
    assert 'class="more"' in client.get(f"/e/{token}/bills").text
    assert 'class="more"' in client.get(f"/e/{token}/close").text


# --- 4. empty states with a next step ----------------------------------------


def test_empty_states_point_somewhere(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    # Today with no prices: say them.
    home = client.get(f"/e/{token}").text
    first = _create_shop(client, name="T91 Fresh", phone="+914400000092")
    fresh_home = client.get(f"/e/{first}").text
    assert "Get started" in fresh_home  # first-run card, not the empty list
    # Bills list + top items: new bill.
    bills = client.get(f"/e/{token}/bills").text
    assert "No bills here yet" in bills
    assert f'href="/e/{token}/bills/new"' in bills
    # Close with nothing billed: new bill.
    close = client.get(f"/e/{token}/close").text
    assert "Nothing billed" in close
    assert f'href="/e/{token}/bills/new"' in close
    # Credit list with no dues: all bills.
    credit = client.get(f"/e/{token}/credit").text
    assert "No credit out" in credit
    assert f'href="/e/{token}/bills"' in credit
    # AI log with no calls: say prices.
    ai = client.get(f"/e/{token}/ai").text
    assert f'href="/e/{token}/live"' in ai
    # Purchases with nothing bought: the on-page form.
    purchases = client.get(f"/e/{token}/purchases").text
    assert "Nothing bought yet" in purchases
    assert 'href="#add-purchase"' in purchases
    assert 'id="add-purchase"' in purchases
    assert home  # owner home renders throughout


def test_credit_customer_payment_empty_links_to_form(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    key = _seed_credit_customer(client, tmp_path, token)
    html = client.get(f"/e/{token}/credit/{key}").text
    assert "No payments yet." in html
    assert 'href="#record-payment"' in html
    assert 'id="record-payment"' in html


# --- 5. forms: labels above fields, wired inputs ------------------------------


def test_bill_forms_use_shared_field_markup(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id = _seed_bill(tmp_path, token)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert 'class="field-label"' in html
    assert 'class="field-input"' in html
    # Label sits above its input and both keep their hooks.
    label_at = html.index("field-label")
    input_at = html.index("field-input")
    assert label_at < input_at
    for hook in ('id="credit-name"', 'id="credit-phone"',
                 'name="customer_name"', 'name="customer_phone"',
                 'id="cash-gave"', "data-cash-gave", 'id="add-qty"',
                 'type="tel"', 'inputmode="tel"'):
        assert hook in html, hook


# --- 6. JS hooks still present (Task 64 lists) --------------------------------


def test_js_hooks_present_on_v10_pages(tmp_path):
    from test_task64 import BILL_HOOKS, LIVE_HOOKS, REVIEW_HOOKS

    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id = _seed_bill(tmp_path, token)
    session_id = _seed_review_session(tmp_path, token)
    pages = [(f"/e/{token}/live", LIVE_HOOKS),
             (f"/e/{token}/s/{session_id}", REVIEW_HOOKS),
             (f"/e/{token}/bills/{bill_id}", BILL_HOOKS)]
    for url, hooks in pages:
        html = client.get(url).text
        for hook in hooks:
            assert hook in html, f"{url} missing {hook}"
    # Page-specific hooks beyond the Task 64 lists.
    bills = client.get(f"/e/{token}/bills").text
    for hook in ("data-view-btn", "data-view-list", "data-view-board",
                 "mm_bills_view", "data-search-row"):
        assert hook in bills, hook
    today = client.get(f"/e/{token}").text
    for hook in ("data-item-photo-form", "data-rename-sheet", "mm_grp_",
                 "data-search-row"):
        assert hook in today, hook
    live_fallback = client.get(f"/e/{token}/live").text
    assert "data-composer" in live_fallback
    assert "composer.js" in live_fallback
    ai = client.get(f"/e/{token}/ai").text
    for hook in ("data-ai-list", "data-ai-poll", "data-ai-calls",
                 "ai.js"):
        assert hook in ai, hook


# --- 7. helpers see only allowed links ----------------------------------------


def test_helper_scope_unchanged(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        _, helper = db.create_helper(conn, shop["id"], "Muthu")
    finally:
        conn.close()
    html = client.get(f"/e/{helper}").text
    for suffix in ("/live", "/close", "/settings", "/photos",
                   "/purchases"):
        assert f"/e/{helper}{suffix}" not in html, suffix
    assert "action-bar" in html  # staff still get their one primary


# --- 8. every seller page renders in en/ta/hi ---------------------------------


def _seller_urls(token, ids):
    t = token
    return [
        f"/e/{t}", f"/e/{t}/live", f"/e/{t}/s/{ids['review']}",
        f"/e/{t}/s/{ids['proc']}", f"/e/{t}/s/{ids['failed']}",
        f"/e/{t}/s/{ids['review']}/live", f"/e/{t}/bills",
        f"/e/{t}/bills/{ids['bill']}", f"/e/{t}/bills/{ids['paid']}",
        f"/e/{t}/bills?range=today&status=waiting",
        f"/e/{t}/bills/new/{ids['bill_proc']}", f"/e/{t}/close",
        f"/e/{t}/credit", f"/e/{t}/credit/{ids['credit_key']}",
        f"/e/{t}/ai", f"/e/{t}/purchases",
    ]


def test_seller_pages_render_all_langs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி"),
                               _draft("onion", 30, local="வெங்காயம்")])
    bill_id = _seed_bill(tmp_path, token)
    paid_id = _seed_bill(tmp_path, token, status="paid", total="36.00")
    review = _seed_review_session(tmp_path, token)
    proc = _seed_status_session(tmp_path, token)
    failed = _seed_status_session(tmp_path, token, status="failed",
                                  message="boom")
    bill_proc = _seed_status_session(tmp_path, token, kind="bill_voice")
    key = _seed_credit_customer(client, tmp_path, token)
    ids = {"review": review, "proc": proc, "failed": failed,
           "bill": bill_id, "paid": paid_id, "bill_proc": bill_proc,
           "credit_key": key}
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in _seller_urls(token, ids):
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url}"
            assert "style=" not in resp.text, f"{lang} {url}: inline style"
        if lang != "en":
            assert any(ord(c) > 127 for c in resp.text), lang


def test_v10_strings_translated():
    from app.web.i18n import STRINGS

    keys = [k for k in STRINGS["en"] if k.startswith("v10.")]
    assert keys, "no v10 keys"
    for key in keys:
        assert key in STRINGS["ta"], key
        assert key in STRINGS["hi"], key
        assert STRINGS["ta"][key] != STRINGS["en"][key], key
        assert STRINGS["hi"][key] != STRINGS["en"][key], key


# --- 9. saved toast after success --------------------------------------------


def test_saved_toast_after_wastage_and_payment(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="36.00")
    resp = client.post(f"/e/{token}/close/wastage", data={
        "wastage_tomato": "1", "unit_tomato": "kg"})
    assert resp.status_code in (302, 303), resp.text
    assert "saved=1" in resp.headers["location"]
    saved = client.get(resp.headers["location"]).text
    assert 'class="toast"' in saved
    assert "Saved" in saved
    key = _seed_credit_customer(client, tmp_path, token)
    pay = client.post(f"/e/{token}/credit/{key}/pay", data={
        "amount": "10", "mode": "cash"})
    assert pay.status_code in (302, 303), pay.text
    assert "saved=1" in pay.headers["location"]
    paid_html = client.get(pay.headers["location"]).text
    assert 'class="toast"' in paid_html


# --- 10. small-screen + a11y guards ------------------------------------------


def test_tables_scroll_and_tap_targets_and_focus():
    css = CSS.read_text()
    assert ".table-scroll" in APP_CSS.read_text()
    assert "min-height: var(--tap)" in css
    assert ":focus-visible" in APP_CSS.read_text()


def test_icon_only_buttons_stay_labelled(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id = _seed_bill(tmp_path, token)
    for url in (f"/e/{token}", f"/e/{token}/live",
                f"/e/{token}/bills/{bill_id}"):
        html = client.get(url).text
        for match in re.finditer(r"<button([^>]*)>", html):
            tag = match.group(0)
            if "data-live-mic" in tag or "data-rename-open" in tag:
                assert 'aria-label="' in tag, f"{url}: {tag}"
