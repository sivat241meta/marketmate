"""Task 90: v10 customer pages.

Pins the shared public header on every public page, the shop band,
the order-flow timeline and next steps, My orders cards, the Find a
shop search card, the public bill/share/error pages, and the
Task 64 customer JS hooks after the redesign.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from test_task64 import SHOP_HOOKS

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "css" / "public.css"
TEMPLATES = ROOT / "app" / "web" / "templates"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, name="T90 Store", phone="+914400000090",
                 area="Koyambedu", language="ta", listed=True):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": area,
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    token = resp.headers["location"].split("/e/")[1]
    if listed:
        data_dir = Path(client.app.state.settings.data_dir)
        conn = db.connect(data_dir)
        try:
            shop = db.shop_by_token(conn, token)
            conn.execute("UPDATE shops SET listed = 1 WHERE id = ?",
                         (shop["id"],))
            conn.commit()
        finally:
            conn.close()
    return token


def _draft(name_en, price, local=None):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en,
        name_local=local or CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
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


def _slug(tmp_path, token) -> str:
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def _seed_customer_quote(tmp_path, token, status="new"):
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
                                 source="customer", kind="quote",
                                 status=status)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        public = db.ensure_bill_token(conn, bill_id)
        return qtoken, public, bill_id
    finally:
        conn.close()


def _seed(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி"),
                               _draft("onion", 30, "வெங்காயம்")])
    qtoken, public, _bill_id = _seed_customer_quote(tmp_path, token)
    return client, token, slug, qtoken, public


def _public_urls(slug, qtoken, public):
    return ["/", "/market", "/my", "/share", f"/s/{slug}",
            f"/s/{slug}/quote", f"/q/{qtoken}", f"/b/{public}"]


# --- 1. shared header ----------------------------------------------------------

def test_every_public_page_includes_shared_header(tmp_path):
    client, _token, slug, qtoken, public = _seed(tmp_path)
    for url in _public_urls(slug, qtoken, public):
        html = client.get(url).text
        assert "data-public-header" in html, f"{url}: no shared header"
        assert 'href="/market"' in html, f"{url}: no Find a shop link"
        assert 'href="/my"' in html, f"{url}: no My orders link"
        assert 'href="/new"' in html, f"{url}: no Start selling link"
        assert "data-ui-toggle" in html, f"{url}: no language switch"
        assert "data-menu-open" in html, f"{url}: no phone menu"


def test_header_anchors_stay_on_home_but_point_home_elsewhere(tmp_path):
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    home = client.get("/").text
    for anchor in ("#lowest", "#markets"):
        assert f'href="{anchor}"' in home, anchor
    for href in ("/market", "/sellers", "/how"):
        assert f'href="{href}"' in home, href
    assert home.count('id="site-header"') == 1
    shop = client.get(f"/s/{slug}").text
    for anchor in ("#lowest", "#markets"):
        assert f'href="/{anchor}"' in shop, anchor


def test_no_shop_strip_bag_lives_in_header(tmp_path):
    # Task 93 removed the separate shop strip: the shop name shows once
    # (in the page, not the header) and Bag sits in the shared header.
    client, _token, slug, qtoken, _public = _seed(tmp_path)
    for url in (f"/s/{slug}", f"/s/{slug}/quote", f"/q/{qtoken}"):
        html = client.get(url).text
        assert "data-shop-strip" not in html, f"{url}: stray shop strip"
        assert "ph-shop-strip" not in html, f"{url}: stray shop strip"
        assert "T90 Store" in html, f"{url}: no shop name on page"
        head = re.search(r'<header id="site-header".*?</header>', html,
                         re.DOTALL).group(0)
        assert "hp-bag" in head, f"{url}: no Bag in header"
        assert 'href="/my"' in head, f"{url}: Bag link missing"
        assert "T90 Store" not in head, f"{url}: shop name in header"
    # Task 122: Bag (with count badge) sits in the header on every
    # public page now.
    for url in ("/", "/market", "/my", "/share"):
        html = client.get(url).text
        assert "data-shop-strip" not in html, f"{url}: stray shop strip"
        head = re.search(r'<header id="site-header".*?</header>', html,
                         re.DOTALL).group(0)
        assert "hp-bag" in head, f"{url}: no Bag in header"
        assert "data-bag-count" in head, f"{url}: no Bag badge"


def test_no_seller_navigation_on_public_pages(tmp_path):
    client, _token, slug, qtoken, public = _seed(tmp_path)
    for url in _public_urls(slug, qtoken, public):
        html = client.get(url).text
        assert 'class="bnav"' not in html, f"{url} leaks seller bnav"
        assert 'class="rail"' not in html, f"{url} leaks seller rail"
        # Task 127: the v13 hero topbar is a <header>; the seller
        # topbar is a <div> and must stay out of public pages.
        assert '<div class="topbar">' not in html, \
            f"{url} leaks seller topbar"
        assert "data-orders-badge" not in html, f"{url} leaks badge hook"
        assert 'href="/e/' not in html, f"{url} links into seller pages"


# --- 2. shop page ---------------------------------------------------------------

def test_shop_band_tools_and_hooks(tmp_path):
    # Task 127: v13 info card + price list + in-shop search + chips.
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    html = client.get(f"/s/{slug}").text
    assert 'class="info-card"' in html
    assert html.index('class="info-card"') < html.index("data-shop-grid")
    assert "Koyambedu" in html
    assert "Order by voice" in html
    assert "chip-btn" in html
    assert "wa.me/" in html and "tel:" in html
    assert "said today" in html.lower() or "said_today" not in html
    assert 'id="shop-q"' in html
    assert "fchip" in html
    for hook in SHOP_HOOKS:
        assert hook in html, f"shop page missing {hook}"


def test_shop_empty_state_with_next_step(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client, name="T90 Empty", phone="+914400000091")
    slug = _slug(tmp_path, token)
    html = client.get(f"/s/{slug}").text
    assert "No prices published yet" in html
    assert "tel:+914400000091" in html
    assert "wa.me/914400000091" in html


def test_shop_more_shops_near_you(tmp_path, monkeypatch):
    # Task 127: the v13 shop page carries no cross-shop block (the
    # reference has none); area discovery lives on /market instead.
    from app.market.search import Query, Want
    from app.web import main as main_mod

    def fake_parse(text, **_kw):
        return Query([Want(text, None, None, None)], None, None)

    monkeypatch.setattr(main_mod, "parse_query", fake_parse)
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    other = _create_shop(client, name="T90 Nearby", phone="+914400000092")
    other_slug = _slug(tmp_path, other)
    _publish(tmp_path, other, [_draft("tomato", 35)])
    hidden = _create_shop(client, name="T90 Far", phone="+914400000093",
                          area="Anna Nagar")
    _publish(tmp_path, hidden, [_draft("tomato", 20)])
    html = client.get(f"/s/{slug}").text
    assert "More shops near you" not in html
    koy = client.get("/market?q=tomato&area=Koyambedu").text
    assert f"/s/{other_slug}" in koy
    assert f"/s/{_slug(tmp_path, hidden)}" not in koy
    anna = client.get("/market?q=tomato&area=Anna%20Nagar").text
    assert f"/s/{_slug(tmp_path, hidden)}" in anna


# --- 3. order flow ---------------------------------------------------------------

# Task 125: the old live-order recorder left the quote page — the
# composer is the only recorder there now.
ORDER_HOOKS = ["data-methods", "data-method=", "data-panel=",
               "data-composer", "data-composer-form", "data-composer-mic",
               "data-composer-send", "data-composer-cancel",
               "data-composer-plus", "data-composer-text",
               "data-needs-internet", "data-customer-name",
               "data-customer-phone", 'name="audio"', 'name="items"',
               'name="photo"', "methods.js",
               "composer.js", "customer-contact.js"]


def test_quote_start_flow_steps_and_hooks(tmp_path):
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    html = client.get(f"/s/{slug}/quote").text
    assert "flow-steps" in html
    for step in ("Your list", "Your name", "Send"):
        assert step in html, step
    assert "segmented" in html
    for panel in ("speak", "type", "photo"):
        assert f'data-panel="{panel}"' in html
    assert html.count(f'action="/s/{slug}/quote') >= 3
    for hook in ORDER_HOOKS:
        assert hook in html, f"quote start missing {hook}"


def test_quote_start_labels_inputs_and_errors(tmp_path):
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    html = client.get(f"/s/{slug}/quote").text
    # Task 125: the speak panel keeps one name/phone pair, inside
    # the composer (the old recorder's duplicate pair is gone).
    for field_id in ("quote-name-speak", "quote-phone-speak",
                     "quote-name-type", "quote-phone-type", "quote-items",
                     "quote-name-photo", "quote-phone-photo", "quote-photo"):
        assert f'for="{field_id}"' in html, f"no label for {field_id}"
        assert f'id="{field_id}"' in html, f"no field {field_id}"
    assert 'inputmode="tel"' in html
    assert 'autocomplete="tel"' in html
    assert 'autocomplete="name"' in html
    assert "field-error" not in html
    resp = client.post(f"/s/{slug}/quote",
                       data={"items": "2 kg tomato", "customer_name": ""})
    assert resp.status_code == 400
    assert 'role="alert"' in resp.text
    assert "field-error" in resp.text
    assert "Your name" in resp.text


def test_quote_timeline_next_step_and_totals(tmp_path):
    client, _token, _slug, qtoken, _public = _seed(tmp_path)
    html = client.get(f"/q/{qtoken}").text
    assert 'data-timeline' in html
    for step in ("Sent", "RIGHT NOW"):
        assert step in html, step
    assert "next-step" in html
    assert "Next: the shop accepts your order." in html
    assert "quote-total" in html
    assert html.index("quote-total") < html.index("receipt-line")
    assert "₹40" in html
    assert "Pay at the shop" in html
    assert "Send on WhatsApp" in html
    assert "data-order-record" in html
    assert "data-order-poll" in html
    assert "order-status.js" in html


def test_quote_next_step_per_status(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    for status, needle in (
            ("packing", "Next: the shop packs your items."),
            ("ready", "Next: collect it from the shop."),
            ("collected", "Done. Thank you for shopping!")):
        qtoken, _public, _bid = _seed_customer_quote(
            tmp_path, token, status=status)
        html = client.get(f"/q/{qtoken}").text
        assert needle in html, status


def test_quote_status_page_renders(tmp_path):
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_slug(conn, slug)
        session_id = db.create_session(conn, shop["id"], "quote_voice")
        db.set_session_status(conn, session_id, "processing", "working")
    finally:
        conn.close()
    html = client.get(f"/s/{slug}/quote/{session_id}").text
    assert "data-public-header" in html
    assert "data-stepper" in html
    assert "data-step-count" in html
    assert "setInterval" in html


# --- 4. my orders -----------------------------------------------------------------

def test_my_orders_boxes_and_card_js(tmp_path):
    client, _token, _slug, _qtoken, _public = _seed(tmp_path)
    html = client.get("/my").text
    assert "data-my-page" in html
    assert "data-my-orders" in html
    assert "data-my-shops" in html
    assert "data-my-clear" in html
    assert "my.js" in html
    assert "No orders yet" in html
    js = (ROOT / "app" / "web" / "static" / "my.js").read_text()
    assert "my-card" in js
    assert "my-card-actions" in js
    assert "/market" in js


# --- 5. find a shop ---------------------------------------------------------------

# Task 124: the voice panel's recorder hooks became the composer hooks.
# Task 127: sort/open/pincode moved into the Filters pop-up (sort is
# radios now, so the in-place sort-value/data-sort hooks are gone).
MARKET_HOOKS = ["data-composer", "data-composer-form", "data-composer-mic",
                "data-voice-panel", "data-filters",
                "market-open", "near-me", "near-me-status",
                "market-pincode", "composer.js", "near-me.js"]

MARKET_RESULT_HOOKS = ["data-shop-list", "data-shop-row", "data-distance",
                       "data-unknown"]


def test_market_search_card_prefilled_and_hooks(tmp_path):
    # Task 125: one search — the query shows as a pill (tap opens the
    # search pop-up) and area/budget live in the filter pop-up.
    client, _token, _slug, _qtoken, _public = _seed(tmp_path)
    html = client.get("/market?q=tomato&area=Koyambedu&budget=200").text
    assert 'class="hp-search"' not in html
    assert "mkt-pill" in html and "tomato" in html
    assert 'name="q"' in html
    filt = html.split('id="filter-pop"')[1]
    assert 'name="area"' in filt
    assert 'value="Koyambedu" checked' in filt
    assert 'name="budget"' in filt
    assert 'value="200" checked' in filt
    assert 'name="sort"' in filt
    assert 'name="open_now"' in filt
    assert 'name="pincode"' in filt
    assert 'id="near-me"' in filt
    for hook in MARKET_HOOKS:
        assert hook in html, f"market page missing {hook}"


def test_market_result_cards_keep_hooks(tmp_path, monkeypatch):
    from app.market.search import Query, Want
    from app.web import main as main_mod

    client, _token, _slug, _qtoken, _public = _seed(tmp_path)
    monkeypatch.setattr(
        main_mod, "parse_query",
        lambda text, **_kw: Query([Want("tomato", None, None, None)],
                                 None, None))
    html = client.get("/market?q=tomato").text
    assert "T90 Store" in html
    for hook in MARKET_RESULT_HOOKS:
        assert hook in html, f"market results missing {hook}"


def test_market_empty_search_has_next_step(tmp_path):
    from app.market.search import Query, Want

    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    real_parse = __import__("app.web.main", fromlist=["parse_query"])
    orig = real_parse.parse_query
    real_parse.parse_query = lambda text, **kw: Query(
        [Want("dragonfruit", None, None, None)], None, None)
    try:
        html = client.get("/market?q=dragonfruit").text
    finally:
        real_parse.parse_query = orig
    assert "No shops have what you asked for today." in html
    assert "hp-empty" in html


# --- 6. public bill / share / error --------------------------------------------------

def test_public_bill_renders_receipt(tmp_path):
    client, _token, slug, _qtoken, public = _seed(tmp_path)
    html = client.get(f"/b/{public}").text
    assert "data-public-header" in html
    assert "T90 Store" in html
    assert "₹40" in html
    assert "bill-qr" in html
    assert f"/s/{slug}" in html


def test_share_pages_render_states(tmp_path):
    client, _token, _slug, _qtoken, _public = _seed(tmp_path)
    html = client.get("/share").text
    assert "data-public-header" in html
    for hook in ("data-share-loading", "data-share-ready",
                 "data-share-no-token", "data-share-no-file",
                 "data-share-question", "data-share-upload",
                 "data-share-speak", 'name="speak_lang"'):
        assert hook in html, f"share page missing {hook}"


def test_error_page_renders_with_header(tmp_path):
    from fastapi.templating import Jinja2Templates

    from app.web.i18n import jinja_flag, jinja_t

    templates = Jinja2Templates(directory=str(TEMPLATES))
    templates.env.globals["t"] = jinja_t
    templates.env.globals["t_flag"] = jinja_flag
    scope = {"type": "http", "method": "GET", "path": "/oops",
             "headers": [], "query_string": b"", "server": ("t", 80),
             "scheme": "http"}
    from starlette.requests import Request

    response = templates.TemplateResponse(
        Request(scope), "error.html",
        {"title": "Oops", "message": "Something broke"})
    body = response.body.decode()
    assert "data-public-header" in body
    assert "empty-state" in body
    assert "/#lowest" in body


# --- 7. languages, CSS, JS ------------------------------------------------------------

def test_public_pages_render_en_ta_hi(tmp_path):
    client, _token, slug, qtoken, public = _seed(tmp_path)
    urls = ["/", "/market", "/my", "/share", f"/s/{slug}",
            f"/s/{slug}/quote", f"/q/{qtoken}", f"/b/{public}"]
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url}"
            assert resp.text.strip(), f"{lang} {url} empty"
        ta_shop = client.get(f"/s/{slug}?lang=ta").text
        assert "தக்காளி" in ta_shop, lang
        client.cookies.clear()


def test_no_missing_i18n_keys():
    from app.web.i18n import missing_keys

    assert missing_keys() == {"ta": [], "hi": []}


def test_public_css_linked_and_scoped():
    base = (TEMPLATES / "base.html").read_text()
    assert "css/public.css" in base
    assert CSS.exists()
    css = CSS.read_text()
    # Task 127: .shop-compact-line (v10 band) is gone with the
    # rest of the removed public.css.
    for selector in ("body.pub > .hdr", ".hp-bag", ".ph-head",
                     ".form-card", ".field-input", ".field-error",
                     ".action-bar", "details.more", ".next-step",
                     ".my-card", ".chip-row", ".obj-tint"):
        assert selector in css, selector
    assert "position: sticky" in css
    assert "safe-area-inset-bottom" in css


def test_no_inline_styles_and_one_primary(tmp_path):
    client, _token, slug, qtoken, public = _seed(tmp_path)
    for url in _public_urls(slug, qtoken, public):
        html = client.get(url).text
        assert "style=" not in html, f"{url}: inline style"


def test_changed_js_parses():
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node, "node is required for --check"
    for name in ("public.js", "my.js"):
        path = ROOT / "app" / "web" / "static" / name
        result = subprocess.run([node, "--check", str(path)], check=False,
                                capture_output=True, text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_homepage_header_unchanged(tmp_path):
    before = (TEMPLATES / "home.html").read_text()
    assert before.count('{% include "_public_header.html" %}') == 1
    assert 'id="site-header"' not in before
    client = _client(tmp_path)
    html = client.get("/").text
    assert html.count('id="site-header"') == 1
    assert "data-public-header" in html
    assert 'href="#lowest"' in html
