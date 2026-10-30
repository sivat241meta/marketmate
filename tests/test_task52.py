"""Task 52: fixes from the owner-side browser review (failing first).

Covers the MUST fixes (Add sets quantity, bottom bars above the seller
nav, cart JSON limits, wrapping order rows) and the SHOULD fixes (merged
seller home, order labels, currency, language pill, card layout, grapheme
tiles, stat alignment, plurals, check-page look, shop spacing/float/cart
lines, nav active state, market Stop, grid gap).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
TAP_CHIPS = ROOT / "app" / "web" / "static" / "tap-chips.js"
QUOTE_JS = ROOT / "app" / "web" / "static" / "quote.js"
SHOP_HTML = ROOT / "app" / "web" / "templates" / "shop.html"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client, name="T52 Store", phone="+914400000052",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
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


def _slug(tmp_path, token) -> str:
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def _seed_bill(tmp_path, token, status="billed", kind="bill",
               source="seller", total="135.00", lines=None,
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


def _seed_customer_order(tmp_path, token, status="new", phone="+919111111111"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=[QuoteLine(
                name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
                unit="kg", unit_price=Decimal(40), per_amount=Decimal(1),
                line_total=Decimal(80), status="priced")],
            total=Decimal("80.00"), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="customer", kind="quote",
                                 status=status)
        order_id = db.get_quote_by_token(conn, qtoken)["id"]
        if phone:
            db.set_bill_phone(conn, order_id, phone)
        return order_id, qtoken
    finally:
        conn.close()


def _start_review_session(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review",
                              f"{len(drafts)} items need review")
        return session_id
    finally:
        conn.close()


def _two_price_draft():
    return _draft("carrot", 50, flags=[Flag(
        field="price", code="TWO_PRICES",
        message="Did you say ₹50 or ₹80?",
        options=["50", "80"], blocking=True)])


# --- 1. Add sets the first quantity -----------------------------------------


def test_tap_add_node_sets_first_quantity():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/tap_add.test.mjs"], cwd=ROOT, check=False,
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_new_bill_has_add_stepper_hooks(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40),
                               _draft("coconut", 15, unit="piece")])
    html = client.get(f"/e/{token}/bills/new").text
    for needle in ("data-tap-form", "data-line", "data-add", "data-stepper",
                   'name="qty_0"', 'name="unit_0"', "data-chips",
                   "data-tap-total", "data-tap-count", "data-tap-summary",
                   "data-count-one", "data-count-many"):
        assert needle in html, needle


def test_tap_bill_posts_quantities_from_same_fields(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    resp = client.post(
        f"/e/{token}/bills/new",
        data={"name_en_0": "tomato", "qty_0": "1", "unit_0": "kg",
              "amount_0": ""})
    assert resp.status_code in (302, 303), resp.text
    html = client.get(resp.headers["location"]).text
    assert "₹40" in html


# --- 2. bottom bars above the seller nav ------------------------------------


def test_bottom_bars_lifted_above_bnav():
    css = CSS.read_text()
    assert "body:has(.bnav)" in css
    assert "safe-area-inset-bottom" in css
    assert re.search(r"body:has\(\.bnav\)[^{]*\{[^}]*z-index:\s*([0-9]+)",
                     css), "lifted bars need a z-index"
    lifted = max(int(v) for v in re.findall(
        r"body:has\(\.bnav\)[^{]*\{[^}]*?z-index:\s*([0-9]+)", css))
    bnav = int(re.search(r"\.bnav\s*\{[^}]*?z-index:\s*([0-9]+)",
                         css).group(1))
    assert lifted > bnav, f"bars z {lifted} must beat bnav z {bnav}"
    assert "max-width" in css, "lift must be phones-only"


@pytest.mark.parametrize("path_kind", ["new", "bill", "check"])
def test_action_bar_pages_render_bnav_hook(tmp_path, path_kind):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    if path_kind == "new":
        html = client.get(f"/e/{token}/bills/new").text
        assert "float tap-bar" in html
    elif path_kind == "bill":
        bill_id = _seed_bill(tmp_path, token)
        html = client.get(f"/e/{token}/bills/{bill_id}").text
        assert "sticky-bar bill-bar" in html
    else:
        session_id = _start_review_session(
            tmp_path, token, [_two_price_draft()])
        html = client.get(f"/e/{token}/s/{session_id}").text
        assert "sticky-bar" in html
    assert 'class="bnav"' in html


# --- 3. cart JSON limits ----------------------------------------------------


_CART_IPS = iter(range(1, 200))


def _post_cart(client, slug, payload):
    ip = f"10.9.9.{next(_CART_IPS)}"
    body = dict(payload)
    body.setdefault("customer_name", "Test")
    return client.post(f"/s/{slug}/quote", json=body,
                       headers={"x-forwarded-for": ip})


def test_cart_rejects_bad_quantities(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    for bad in ("NaN", "Infinity", "-Infinity", "1e12", "0", "-2", "101"):
        resp = _post_cart(client, slug, {"lines": [
            {"name_en": "tomato", "qty": bad, "unit": "kg"}]})
        assert resp.status_code == 400, (bad, resp.text)
        assert "error" in resp.json(), (bad, resp.text)


def test_cart_rejects_too_many_lines_and_long_fields(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    many = [{"name_en": "tomato", "qty": 1, "unit": "kg"}] * 51
    resp = _post_cart(client, slug, {"lines": many})
    assert resp.status_code == 400
    assert "error" in resp.json()
    resp = _post_cart(client, slug, {"lines": [
        {"name_en": "x" * 81, "qty": 1, "unit": "kg"}]})
    assert resp.status_code == 400
    resp = _post_cart(client, slug, {"lines": [
        {"name_en": "tomato", "qty": 1, "unit": "u" * 21}]})
    assert resp.status_code == 400


def test_cart_accepts_boundary_quantities(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    resp = _post_cart(client, slug, {"lines": [
        {"name_en": "tomato", "qty": "0.5", "unit": "kg"},
        {"name_en": "tomato", "qty": 100, "unit": "kg"}]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"].startswith("/q/")


def test_cart_rate_limited_to_429(tmp_path, monkeypatch):
    from app.web.main import create_app

    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)
    app.state.limiter._per_ip = 1
    app.state.limiter._global = 100000
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    body = {"lines": [{"name_en": "tomato", "qty": 1, "unit": "kg"}],
            "customer_name": "Test"}
    first = client.post(f"/s/{slug}/quote", json=body)
    assert first.status_code == 200, first.text
    second = client.post(f"/s/{slug}/quote", json=body)
    assert second.status_code == 429
    assert "error" in second.json()


def test_shop_page_shows_cart_error(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/s/{slug}").text
    assert "data-cart-error" in html
    js = SHOP_HTML.read_text()
    assert "data.error" in js or 'data["error"]' in js


def test_update_quote_lines_rejects_infinite_and_huge(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _, qtoken = _seed_customer_order(tmp_path, token)
    conn = db.connect(tmp_path / "data")
    try:
        with pytest.raises(ValueError):
            db.update_quote_lines(conn, qtoken, [
                {"name_en": "tomato", "qty": "Infinity", "unit": "kg"}])
        with pytest.raises(ValueError):
            db.update_quote_lines(conn, qtoken, [
                {"name_en": "tomato", "qty": "101", "unit": "kg"}])
    finally:
        conn.close()


# --- 4. order rows wrap ------------------------------------------------------


def test_order_rows_wrap():
    css = CSS.read_text()
    for selector in (".order-top", ".order-bottom"):
        assert re.search(rf"{re.escape(selector)}[^{{]*\{{[^}}]*"
                         r"flex-wrap:\s*wrap", css), selector
    assert "min-width: 0" in css or "min-width:0" in css


# --- 5. merged seller home ---------------------------------------------------


def test_seller_home_has_single_quick_links_grid(tmp_path):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft("tomato", 40)])
    # Say-prices step: yesterday's list is live, nothing said today (Task 61).
    conn = db.connect(tmp_path / "data")
    try:
        noon = datetime.now(ZoneInfo("Asia/Kolkata")).replace(
            hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        conn.execute("UPDATE versions SET created_at = ? WHERE id = ?",
                     (noon.astimezone(UTC).isoformat(), version_id))
        conn.commit()
    finally:
        conn.close()
    html = client.get(f"/e/{token}").text
    assert "Say today&#39;s prices" in html or "Say today's prices" in html
    # Task 61: quick-link rows are gone; More holds each target once.
    assert "quick-links" not in html
    assert 'id="more"' in html
    more = html.split('id="more"')[1]
    for href in (f"/e/{token}/settings", f"/e/{token}/settings#helpers",
                 f"/e/{token}/purchases", f"/e/{token}/update#board",
                 f"/e/{token}/tags.pdf",
                 f"/e/{token}/v/{version_id}/export.csv",
                 f"/e/{token}/exports/sales.xlsx?range=today"):
        assert more.count(f'href="{href}"') == 1, href
    # Old tile grid and raw file input are gone.
    assert "tile-grid" not in html and 'class="tiles ' not in html
    assert 'id="clip"' in html and 'name="video"' in html
    assert "file-hidden" in html
    assert "data-upload-name" in html


# --- 6. order labels ---------------------------------------------------------


def test_customer_orders_labelled_with_status(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    order_id, _ = _seed_customer_order(tmp_path, token)
    home = client.get(f"/e/{token}").text
    assert f"Order #{order_id}" in home
    assert "+919111111111" in home
    bills = client.get(f"/e/{token}/bills").text
    assert f"Order #{order_id}" in bills
    assert ">New<" in bills
    assert "Quotes waiting" not in home
    assert "Quotes waiting" not in bills
    assert "New orders" in bills


def test_walk_in_bills_keep_walk_in(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_bill(tmp_path, token, phone=None)
    bills = client.get(f"/e/{token}/bills").text
    assert "Walk-in" in bills


# --- 7. rupee on the bill headline -------------------------------------------


def test_bill_headline_has_rupee(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id = _seed_bill(tmp_path, token, total="135.00")
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "₹135 to collect." in html


# --- 8. live language pill ---------------------------------------------------


def test_live_pill_shows_language_name_and_timer(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="ta")
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}/live").text
    assert "தமிழ் · " in html
    timer_tag = next(line for line in html.splitlines()
                     if "data-live-timer" in line)
    assert "0:00" in timer_tag
    assert "hidden" not in timer_tag


# --- 9 + 10. card names and grapheme tiles -----------------------------------


def test_first_grapheme_helper():
    from app.web.i18n import first_grapheme

    assert first_grapheme("பூண்டு") == "பூ"
    assert first_grapheme("கொத்தமல்லி") == "கொ"
    assert first_grapheme("onion") == "O"
    assert first_grapheme("") == ""


def test_new_bill_cards_use_local_names_and_tiles(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("garlic", 30, local="பூண்டு"),
                               _draft("coriander", 10, local="கொத்தமல்லி",
                                      unit="bunch")])
    html = client.get(f"/e/{token}/bills/new").text
    assert ">கொத்தமல்லி<" in html
    assert ">பூ<" in html
    assert ">கொ<" in html
    assert "<small>Garlic</small>" in html


def test_shop_tiles_use_graphemes(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("garlic", 30, local="பூண்டு")])
    html = client.get(f"/s/{slug}").text
    assert ">பூ<" in html


# --- 11. stat alignment ------------------------------------------------------


def test_stat_cards_left_aligned():
    css = CSS.read_text()
    assert re.search(r"\.stat-grid\s+\.stat[^{]*\{[^}]*text-align:\s*left",
                     css)


# --- 12. item plurals --------------------------------------------------------


def test_receipt_count_plural(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}/bills/new").text
    assert "0 items" in html
    js = QUOTE_JS.read_text()
    assert "data-count-one" in js and "data-count-many" in js
    shop_js = SHOP_HTML.read_text()
    assert "1 items" not in shop_js
    assert "item" in shop_js


# --- 13. check page look -----------------------------------------------------


def test_check_page_headline_counts(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    session_id = _start_review_session(
        tmp_path, token, [_two_price_draft(), _draft("tomato", 40)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Check prices" in html
    assert "1 price needs one tap." in html
    assert "Two prices for the same amount" in html
    assert "₹50" in html and "₹80" in html
    for needle in ("data-card", "opt-btn", "data-target-field",
                   "data-card-confirm", "data-msg-need-one",
                   "data-approve-url"):
        assert needle in html, needle


def test_check_page_all_right_headline(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    session_id = _start_review_session(tmp_path, token,
                                       [_draft("tomato", 40)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "All prices look right." in html


# --- 14 + 15. shop spacing and float bar -------------------------------------


def test_shop_hero_prices_spacing():
    css = CSS.read_text()
    assert re.search(r"\.hero2\s*\+\s*\.kick\s*\{[^}]*margin-top", css)


def test_shop_float_bar_visible_every_width():
    css = CSS.read_text()
    desktop = css.split("@media (min-width: 900px)", 1)[1]
    assert ".float.shop-float" not in desktop or \
        "display: none" not in desktop.split(".float.shop-float")[1][:80]
    assert "560px" in css


# --- 16. order page nav ------------------------------------------------------


def test_order_page_has_no_active_nav(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _, qtoken = _seed_customer_order(tmp_path, token)
    html = client.get(f"/q/{qtoken}").text
    nav = re.search(r'<nav class="nav".*?</nav>', html, re.DOTALL).group(0)
    assert " on" not in nav and '"on"' not in nav


# --- 17. market Stop hidden --------------------------------------------------


def test_market_stop_hidden_until_recording(tmp_path):
    # Task 124: Stop became the composer's Cancel, still hidden until
    # a recording is underway.
    client = _client(tmp_path)
    html = client.get("/market").text
    stop_tag = next(line for line in html.splitlines()
                    if "data-composer-cancel" in line)
    assert "hidden" in stop_tag
    composer = (ROOT / "app" / "web" / "static" / "composer.js").read_text()
    assert "cancel.hidden = !recording" in composer


# --- 18. cart lines ----------------------------------------------------------


def test_cart_lines_show_qty_and_total():
    js = SHOP_HTML.read_text()
    assert "${entry.qty} ${entry.unit} · ${fmt(line)}" in js
    assert "× ${fmt(entry.rate)}" not in js
    assert "${fmt(entry.price)} / ${entry.per} ${entry.unit}" in js


# --- 19. product grid gap ----------------------------------------------------


def test_product_grid_row_gap():
    css = CSS.read_text()
    assert re.search(r"\.grid-products\s+\.card\s*\{[^}]*margin:\s*0", css)


# --- every touched page renders in en, ta, hi --------------------------------


def _seed_everything(tmp_path, token):
    _publish(tmp_path, token, [_draft("tomato", 40),
                               _draft("garlic", 30, local="பூண்டு")])
    bill_id = _seed_bill(tmp_path, token)
    session_id = _start_review_session(
        tmp_path, token, [_two_price_draft()])
    _, qtoken = _seed_customer_order(tmp_path, token)
    return bill_id, session_id, qtoken


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_touched_pages_render_all_langs(tmp_path, lang):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    bill_id, session_id, qtoken = _seed_everything(tmp_path, token)
    client.cookies.set("ui_lang", lang)
    seller_paths = [f"/e/{token}", f"/e/{token}/bills/new",
                    f"/e/{token}/bills/{bill_id}",
                    f"/e/{token}/s/{session_id}", f"/e/{token}/bills",
                    f"/e/{token}/live"]
    for path in seller_paths:
        resp = client.get(path)
        assert resp.status_code == 200, (lang, path, resp.status_code)
    customer_paths = [f"/s/{slug}?lang={lang}" if lang != "en"
                      else f"/s/{slug}",
                      f"/q/{qtoken}?lang={lang}" if lang != "en"
                      else f"/q/{qtoken}",
                      "/market"]
    for path in customer_paths:
        resp = client.get(path)
        assert resp.status_code == 200, (lang, path, resp.status_code)


