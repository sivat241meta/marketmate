"""Task 50: seller pages in the Fresh Green design (failing first).

Seller home, live prices, check prices, new bill, get paid, bills list,
day close, tags, settings and purchases follow docs/ui/fresh-green.html
(S.seller / S.live / S.bill / S.pay / S.close). Honesty rules stay: every
figure comes from existing data; nothing is invented.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client, name="T50 Store", phone="+914400000050"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, per_amount=1, unit="kg", local=None,
           flags=None):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en,
        name_local=local or CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
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


def _seed_bill(tmp_path, token, status="billed", kind="bill",
               source="seller", total="80.00", lines=None,
               phone="+919876543210"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=lines or [QuoteLine(
                name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
                unit="kg", unit_price=Decimal(40), per_amount=Decimal(1),
                line_total=Decimal(80), status="priced")],
            total=Decimal(total), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source=source, kind=kind, status=status)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        if phone:
            db.set_bill_phone(conn, bill_id, phone)
        return bill_id
    finally:
        conn.close()


def _two_price_draft():
    return _draft("carrot", 50, flags=[Flag(
        field="price", code="TWO_PRICES",
        message="Did you say ₹50 or ₹80?",
        options=["50", "80"], blocking=True)])


# --- 1. seller home ---------------------------------------------------------


def test_seller_home_fresh_green(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, name="T50 Lakshmi")
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="80.00")
    _seed_bill(tmp_path, token, status="new", kind="quote",
               source="customer", total="60.00")
    session_id = _start_review_session(tmp_path, token, "live",
                                       [_two_price_draft()])
    html = client.get(f"/e/{token}").text
    assert 'class="kick"' in html
    assert 'class="big"' in html or "<h1" in html
    assert "sold today" in html
    assert "₹80" in html or "₹80.00" in html
    assert "Good morning" in html or "Good afternoon" in html \
        or "Good evening" in html
    # Task 61: three step cards follow the seller's day.
    assert 'id="step-morning"' in html
    assert 'id="step-day"' in html
    assert 'id="step-evening"' in html
    assert "Say today" in html  # header CTA to live
    assert f'href="/e/{token}/live"' in html
    assert "New bill" in html
    # Gold-soft tap notice with a check link.
    assert "one tap" in html
    assert f"/e/{token}/s/{session_id}" in html
    assert "Check now" in html
    # New orders with the existing status route.
    assert "New orders" in html
    assert "Start packing" in html
    assert "/order-status" in html
    # Week band with real figures only (under More).
    assert "This week in numbers" in html
    assert "gcards" in html or "gc " in html or 'class="gc"' in html
    # Everything else lives under More, once each.
    more = html.split('id="more"')[1]
    for label in ("Settings", "Helpers", "Purchases", "Board photo",
                  "Price tags", "CSV", "Excel (.xlsx)",
                  "Send my link to my WhatsApp"):
        assert label in more, label
    # Install + recovery cards kept, small; old shop-name card gone.
    assert "Install app" in html
    assert "class=\"shopcard\"" not in html


def test_seller_home_hides_margin_without_costs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="80.00")
    html = client.get(f"/e/{token}").text
    assert "This week in numbers" in html
    band = html.split("This week in numbers", 1)[1].split("</div>", 8)
    assert "margin" not in "".join(band).lower()


def test_seller_home_margin_with_costs(tmp_path):
    from app import purchases as pur

    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="80.00")
    conn = db.connect(tmp_path / "data")
    try:
        from app.dayclose import shop_today

        shop = db.shop_by_token(conn, token)
        pur.add_purchase(conn, shop["id"], shop_today(shop),
                         "tomato", Decimal(20), "kg", Decimal(600),
                         source="typed")
    finally:
        conn.close()
    html = client.get(f"/e/{token}").text
    assert "This week in numbers" in html
    assert "margin" in html.lower()


# --- 2. every seller page renders in en/ta/hi -------------------------------


def _seed_all(tmp_path, token):
    from app.market.quote import Quote, QuoteLine

    _publish(tmp_path, token, [_draft("tomato", 40)])
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
                                 source="seller", kind="bill",
                                 status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        session_id = db.create_session(conn, shop["id"], "live")
        db.save_drafts(conn, session_id,
                       [_two_price_draft(), _draft("onion", 30)])
        db.set_session_status(conn, session_id, "review", "2 items")
    finally:
        conn.close()
    return bill_id, session_id


def test_every_seller_page_renders_all_langs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    bill_id, session_id = _seed_all(tmp_path, token)
    urls = [f"/e/{token}", f"/e/{token}/live",
            f"/e/{token}/s/{session_id}", f"/e/{token}/bills",
            f"/e/{token}/bills/new", f"/e/{token}/bills/{bill_id}",
            f"/e/{token}/close", f"/e/{token}/settings",
            f"/e/{token}/purchases"]
    for lang in ("en", "ta", "hi"):
        for url in urls:
            client.cookies.set("ui_lang", lang)
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url} -> {resp.status_code}"
            assert "style=" not in resp.text, f"{lang} {url} inline style"
            if lang != "en":
                assert any(ord(c) > 127 for c in resp.text), \
                    f"{lang} {url} has no translated script"
        client.cookies.set("ui_lang", "en")


# --- 3. JS hooks still present ----------------------------------------------

# Hooks collected from the JS each page loads (live.js, review.js,
# methods.js, live-order.js, tap-chips.js, offline-bills.js, quote.js).

LIVE_HOOKS = ["data-live", "data-token", "data-worklet", "data-live-video",
              "data-live-canvas", "data-live-mic", "data-live-hint",
              "data-live-badge", "data-live-ready", "data-live-timer",
              "data-live-last", "data-live-partial", "data-live-error",
              "data-live-finish", "data-live-elapsed", "data-live-offline",
              "data-live-cards", "data-live-empty", "data-live-fallback",
              "live-columns", "live.js"]

REVIEW_HOOKS = ["review-form", "data-approve-url", "data-msg-ready",
                "data-msg-need-one", "data-msg-need-many",
                "data-msg-counts", "data-msg-counts-aria",
                "data-msg-play-confirm", "data-msg-approve-failed",
                "data-review-counts", "data-review-bar",
                "data-card-toggle", "data-card=", "opt-btn",
                "data-target-field", "data-card-confirm",
                "data-confirm-wrap", "data-edit-note", "proof-data",
                "data-item=", "data-field=", 'class="line"',
                "line-remove", "data-carried", "data-carried-clear",
                "approve-btn", "approve-error", "data-approve-count",
                "review.js"]

BILLS_NEW_HOOKS = ["data-methods", "data-method=", "data-panel=",
                   "data-tap-form", "data-token", "data-version",
                   "data-zero", "data-line", "data-rate", "data-per",
                   "data-stepper", "data-step=", "name=\"qty_",
                   "name=\"name_en_", "name=\"unit_", "name=\"amount_",
                   "data-amount-label", "data-chips", "data-chip=",
                   "data-keypad", "data-keypad-display", "data-keypad-unit",
                   "data-keypad-cancel", "data-keypad-ok", "data-key=",
                   "data-live-order", "data-ws-url", "data-live-order-mic",
                   "data-live-order-hint", "data-live-order-last",
                   "data-live-order-partial", "data-live-order-error",
                   "data-live-order-lines", "data-live-order-list",
                   "data-live-order-total", "data-live-order-done",
                   "rec-start", "rec-stop", "rec-status",
                   "data-offline-banner", "data-offline-text",
                   "data-needs-internet", "data-needs-internet-hint",
                   "methods.js", "live-order.js", "tap-chips.js",
                   "offline-bills.js", "quote.js", "recorder.js"]

BILL_HOOKS = ["data-receipt", "data-line", "data-rate", "data-per",
              "data-stepper", "data-step=", "name=\"qty_",
              "name=\"name_en_", "name=\"unit_", "name=\"amount_",
              "data-amount-label", "data-chips", "data-chip=",
              "data-keypad", "data-keypad-display", "data-keypad-unit",
              "data-keypad-cancel", "data-keypad-ok", "data-key=",
              "data-amount", "data-total", "data-cash", "data-cash-gave",
              "data-cash-chip", "data-cash-keys", "data-cash-back",
              "cash-gave", "receipt-card", "receipt-total", "bill-actions",
              "tap-chips.js", "quote.js"]


def test_js_hooks_present_on_seller_pages(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    bill_id, session_id = _seed_all(tmp_path, token)
    pages = [(f"/e/{token}/live", LIVE_HOOKS),
             (f"/e/{token}/s/{session_id}", REVIEW_HOOKS),
             (f"/e/{token}/bills/new", BILLS_NEW_HOOKS),
             (f"/e/{token}/bills/{bill_id}", BILL_HOOKS)]
    for url, hooks in pages:
        html = client.get(url).text
        for hook in hooks:
            assert hook in html, f"{url} missing {hook}"


def test_hooks_match_what_js_queries():
    """Every data-*/id/class hook asserted above is really queried by JS."""
    js = {}
    for name in ("live", "review", "methods", "live-order", "tap-chips",
                 "offline-bills", "quote", "recorder"):
        js[name] = (ROOT / f"app/web/static/{name}.js").read_text()
    # bill.html carries its own cash-helper script inline.
    js["bill-inline"] = (ROOT / "app/web/templates/bill.html").read_text()
    def _camel(key):
        if not key.startswith("data-"):
            return key
        parts = key[5:].split("-")
        return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])

    checks = {"live": LIVE_HOOKS, "review": REVIEW_HOOKS,
              "bills_new": BILLS_NEW_HOOKS, "bill": BILL_HOOKS}
    pooled = "\n".join(js.values())
    for page, hooks in checks.items():
        for hook in hooks:
            if hook.endswith(".js"):
                continue
            key = hook.rstrip("=")
            if key.startswith('class="') and key.endswith('"'):
                key = "." + key[len('class="'):-1]
            elif key.startswith('name="'):
                key = key[len('name="'):]
            assert key in pooled or _camel(key) in pooled, \
                f"{page} hook {hook} not queried by any JS"


# --- 4. live page -----------------------------------------------------------


def test_live_page_fresh_green(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/live").text
    assert "Live prices" in html
    assert 'class="kick"' in html
    assert "cam" in html  # camera card with live caption
    assert "Heard so far" in html
    assert "Tap to stop and check" in html
    assert "Ready" in html
    assert "Finishing – checking every price…" in html
    # Heard rows render as .heard rows (mint check / gold ask).
    live_js = (ROOT / "app/web/static/live.js").read_text()
    assert '"heard' in live_js or "'heard" in live_js or "heard" in live_js


# --- 5. review page ---------------------------------------------------------


def test_review_page_fresh_green_needs_first(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 30),
                               _draft("potato", 40)])
    session_id = _start_review_session(tmp_path, token, "live",
                                       [_two_price_draft()])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert 'data-card="0"' in html
    assert 'class="question"' in html
    assert "Two prices for the same amount" in html
    assert "₹50" in html and "₹80" in html
    assert "opt-btn" in html
    assert "Approve" in html or "approve" in html
    assert 'class="carried-box"' in html
    assert "Also on your list" in html
    # Compact fine list + sticky approve bar.
    assert "sticky-bar" in html


def test_review_approve_with_carried_still_passes(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 30),
                               _draft("potato", 40)])
    session_id = _start_review_session(tmp_path, token, "live",
                                       [_draft("tomato", 99)])
    client.get(f"/e/{token}/s/{session_id}")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        base_id = db.latest_version(conn, shop["id"], published_only=True)
        base_items = db.version_items(conn, base_id)
        carried_ids = [i.id for i in base_items
                       if i.name_en != "tomato"]
        drafts = db.load_drafts(conn, session_id)
        raw_items = [json.loads(db._draft_to_json(d)) for d in drafts]
    finally:
        conn.close()
    body = {"items": raw_items,
            "confirmed": list(range(len(raw_items))),
            "carried": carried_ids}
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text


# --- 6. new bill ------------------------------------------------------------


def test_bills_new_fresh_green(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40),
                               _draft("banana", 60, unit="dozen")])
    html = client.get(f"/e/{token}/bills/new").text
    assert 'class="kick"' in html
    assert "Tap, speak or weigh" in html
    for tab in ("Tap", "Speak", "Type", "Photo"):
        assert tab in html, tab
    assert 'class="card' in html  # product card grid
    assert "quick-chips" in html or "data-chips" in html
    assert "Bill ·" in html or "float" in html
    assert "Make bill" in html
    assert "will sync when you" in html  # offline banner text kept


def test_tap_billing_creates_right_bill(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40),
                               _draft("coconut", 15, unit="piece")])
    resp = client.post(f"/e/{token}/bills/new",
                       data={"name_en_0": "tomato", "qty_0": "2",
                             "unit_0": "kg",
                             "name_en_1": "coconut", "qty_1": "1",
                             "unit_1": "piece"})
    assert resp.status_code in (302, 303), resp.text
    html = client.get(resp.headers["location"]).text
    assert "₹80" in html and "₹15" in html and "₹95" in html


# --- 7. bill + payment ------------------------------------------------------


def test_bill_page_fresh_green(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET upi_id=? WHERE id=?",
                     ("shop@okbank", shop["id"]))
        conn.commit()
    finally:
        conn.close()
    bill_id = _seed_bill(tmp_path, token, total="80.00")
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert f"Bill #{bill_id}" in html
    assert "to collect" in html
    assert "upi" in html.lower()
    assert "GPay" in html and "PhonePe" in html
    assert "Give back" in html
    assert "Paid by cash" in html or "Paid" in html
    assert "Send bill" in html or "WhatsApp" in html


def test_paid_lock_still_works(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    bill_id = _seed_bill(tmp_path, token, total="40.00")
    assert client.post(f"/e/{token}/bills/{bill_id}/paid",
                       data={"mode": "cash"}).status_code in (302, 303)
    import html as html_lib

    msg = "This bill is paid. Tap 'Change bill' to reopen it."
    resp = client.post(
        f"/e/{token}/bills/{bill_id}/lines",
        data={"name_en_0": "tomato", "qty_0": "1", "unit_0": "kg"})
    assert msg in html_lib.unescape(resp.text)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Change bill" in html
    assert "data-stepper" not in html
    assert "/remove" not in html


# --- 8. bills list ----------------------------------------------------------


def test_bills_list_fresh_green(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="billed", total="80.00")
    _seed_bill(tmp_path, token, status="new", kind="quote",
               source="customer", total="60.00")
    html = client.get(f"/e/{token}/bills").text
    assert 'class="kick"' in html
    assert "rcpt" in html
    for chip in ("All", "New", "Packing", "Ready", "Unpaid", "Paid"):
        assert chip in html, chip


# --- 9. day close -----------------------------------------------------------


def test_close_page_fresh_green(tmp_path):
    from app import purchases as pur

    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="80.00")
    conn = db.connect(tmp_path / "data")
    try:
        from app.dayclose import shop_today

        shop = db.shop_by_token(conn, token)
        pur.add_purchase(conn, shop["id"], shop_today(shop),
                         "tomato", Decimal(20), "kg", Decimal(600),
                         source="typed")
    finally:
        conn.close()
    html = client.get(f"/e/{token}/close").text
    assert "sold." in html
    assert "Today in numbers" in html
    assert "close-table" in html
    assert "wastage_" in html
    for label in ("Excel", "CSV (works with any billing software)",
                  "PDF", "WhatsApp"):
        assert label in html, label
    assert "wa.me/" in html


def test_day_close_numbers_unchanged(tmp_path):
    from app import purchases as pur
    from app.dayclose import day_tiles, shop_today

    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="80.00")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        day = shop_today(shop)
        pur.add_purchase(conn, shop["id"], day,
                         "tomato", Decimal(20), "kg", Decimal(600),
                         source="typed")
        tiles = day_tiles(conn, shop, day)
    finally:
        conn.close()
    html = client.get(f"/e/{token}/close?date={day}").text
    from app.outputs.money import format_money

    assert format_money(tiles["sales"], "INR") in html
    assert format_money(tiles["cash"], "INR") in html
    assert str(tiles["bills_count"]) in html
    assert format_money(tiles["margin"], "INR") in html


def test_close_margin_unknown_shows_dash(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, status="paid", total="80.00")
    html = client.get(f"/e/{token}/close").text
    assert "—" in html


# --- 10. tags, settings, purchases ------------------------------------------


def test_tags_settings_purchases_fresh_green(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    resp = client.get(f"/e/{token}/tags.pdf")
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
    src = (ROOT / "app/web/templates/tags.html").read_text()
    assert "173F2A" in src or "forest" in src.lower()
    assert "F5C451" in src or "gold" in src.lower()
    settings = client.get(f"/e/{token}/settings").text
    assert "rcpt" in settings
    assert 'name="upi_id"' in settings
    assert 'name="name"' in settings
    purchases = client.get(f"/e/{token}/purchases").text
    assert "rcpt" in purchases
    assert 'name="item"' in purchases
    assert 'name="quantity"' in purchases


def test_touch_targets_and_wrap_css():
    css = (ROOT / "app/web/static/app.css").read_text()
    assert "44px" in css
    assert "overflow-wrap" in css
    # Seller components exist.
    for cls in (".kick", ".band", ".gc", ".rcpt", ".upi", ".cam",
                ".heard", ".float", ".change", ".stopb"):
        assert cls in css, cls
