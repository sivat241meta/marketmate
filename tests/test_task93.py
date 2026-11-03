"""Task 93: products first on the phone shop page again.

Pins the post-v10 browser fixes: no separate shop strip (Bag lives in
the shared header on shop pages), a compact shop band on phones, one
language switch per public page (in the header), tinted mostly-white
object icons, and the shared public header on /new.
"""

from __future__ import annotations

import json
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
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def _create_shop(client, name="T93 Store", phone="+914400000093",
                 area="Anna Nagar", language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": area,
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


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


def _always_open(tmp_path, token):
    hours = json.dumps({"closed": [], "slots": {
        str(d): [["00:00", "00:00"]] for d in range(7)}})
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET hours_json = ? WHERE id = ?",
                     (hours, shop["id"]))
        conn.commit()
    finally:
        conn.close()


def _seed_customer_quote(tmp_path, token):
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
                                 status="new")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        public = db.ensure_bill_token(conn, bill_id)
        return qtoken, public
    finally:
        conn.close()


def _seed(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _always_open(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40, "தக்காளி"),
                               _draft("onion", 30, "வெங்காயம்")])
    qtoken, public = _seed_customer_quote(tmp_path, token)
    return client, token, slug, qtoken, public


def _header(html: str) -> str:
    return re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)


def _ann(html: str) -> str:
    start = html.index('class="ann"')
    return html[start:html.index("</div>", start)]


# --- 1. products first on the phone shop page (extends Task 68) -------------


def test_phone_shop_section_order_and_compact_band(tmp_path):
    # Task 127: v13 shop page — crumbs, title, info card, price
    # list, in-shop search, filter chips, open accordions with rows.
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    html = client.get(f"/s/{slug}").text
    assert "data-shop-strip" not in html
    assert "ph-shop-strip" not in html
    order = ['class="ann"', 'id="site-header"', 'class="crumbs"',
             'class="shop-title"', 'class="info-card"',
             'id="price-list"', 'menu-search', 'data-shop-grid']
    positions = [html.index(needle) for needle in order]
    assert positions == sorted(positions), order
    # In-shop search moved into a sheet; the input keeps its hooks.
    assert 'id="shopsearch-pop"' in html
    assert 'id="shop-q"' in html and "data-shop-search" in html
    assert "data-shopsearch-open" in html
    # Info card: one h1 + area + open state + contact chips.
    assert html.count("<h1") == 1
    assert "T93 Store" in html
    info = re.search(r'class="info-card".*?</section>', html,
                     re.DOTALL).group(0)
    info_text = re.sub(r"<[^>]+>", "", info)
    assert "Anna Nagar" in info_text
    assert "Open now" in info_text
    assert "Share" in html
    assert "Order by voice" in html
    # Shop name: in the page, never in the shared header.
    assert "T93 Store" not in _header(html)
    # Rows follow the tools in the same DOM order phones show.
    assert html.count("data-card") >= 2
    for hook in SHOP_HOOKS:
        assert hook in html, f"shop page missing {hook}"


def test_compact_band_css_is_phone_only():
    # Task 127: v13 shop rows shrink on phones (118px tiles) and the
    # info-card actions wrap full-width.
    css = (ROOT / "app" / "web" / "static" / "css" / "shop13.css").read_text()
    assert "@media(max-width:700px)" in css.replace(" ", "")
    block = css.split("@media (max-width:700px)", 1)[1]
    assert ".row-pic" in block and "118px" in block
    assert ".info-foot" in block and "wrap" in block
    assert ".shop-title" in block and "font-size:23px" in block.replace(
        " ", "")


def test_bag_in_header_only_on_shop_pages(tmp_path):
    # Task 122: Bag (with count badge) sits in the header on every
    # public page now, not just shop pages.
    client, _token, slug, qtoken, _public = _seed(tmp_path)
    for url in (f"/s/{slug}", f"/s/{slug}/quote", f"/q/{qtoken}",
                "/", "/market", "/my", "/share", "/new"):
        head = _header(client.get(url).text)
        assert "hp-bag" in head, f"{url}: no Bag in header"
        assert 'href="/my"' in head, f"{url}: Bag link missing"
        assert "data-bag-count" in head, f"{url}: no Bag badge"


# --- 2. one language switch per page, in the header ---------------------------


def test_top_strip_has_no_language_switch_on_public_pages(tmp_path):
    client, _token, slug, qtoken, public = _seed(tmp_path)
    urls = ["/", "/new", "/market", "/my", "/share", f"/s/{slug}",
            f"/s/{slug}/quote", f"/q/{qtoken}", f"/b/{public}"]
    for url in urls:
        html = client.get(url).text
        ann = _ann(html)
        assert "data-ui-toggle" not in ann, f"{url}: switch in top strip"
        assert 'class="lang' not in ann, f"{url}: lang in top strip"
        assert html.count('class="lang"') == 1, f"{url}: switch count"
        if url == "/":
            # Task 127: on the homepage the switch sits on the hero
            # topbar; the sticky white header has none until scroll.
            hero = re.search(r'<header class="topbar".*?</header>', html,
                             re.DOTALL).group(0)
            assert "data-ui-toggle" in hero, f"{url}: no hero switch"
        else:
            assert "data-ui-toggle" in _header(html), \
                f"{url}: no header switch"


def test_seller_top_strip_keeps_its_switch(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    assert "data-ui-toggle" in _ann(html)


def test_shop_header_switch_keeps_content_links(tmp_path):
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    head = _header(client.get(f"/s/{slug}").text)
    assert "?lang=ta" in head and "?lang=en" in head
    assert client.get(f"/s/{slug}?lang=ta").text.count("தக்காளி") >= 1


# --- 3. white object icons on tinted squares ---------------------------------


def test_whatsapp_icon_sits_on_green_soft(tmp_path):
    # Task 127: v13 shop contact actions are text chips; the tinted
    # object-icon macro and CSS stay for the pages that use them.
    client, _token, slug, _qtoken, _public = _seed(tmp_path)
    html = client.get(f"/s/{slug}").text
    assert 'class="chip-btn" href="https://wa.me/' in html
    css = CSS.read_text()
    assert ".obj-tint" in css
    assert ".obj-tint.tint-green { background: var(--green-soft); }" in css
    ui_macro = (TEMPLATES / "_ui.html").read_text()
    assert "tint=None" in ui_macro


# --- 4. shared header on setup pages ------------------------------------------


def test_new_shop_uses_shared_public_header(tmp_path):
    client = _client(tmp_path)
    html = client.get("/new").text
    assert '<body class="pub v13">' in html
    assert "data-public-header" in html
    head = _header(html)
    assert 'href="/market"' in head
    assert 'href="/sellers"' in head
    assert 'href="/my"' in head
    assert "hp-bag" in head
    assert 'href="/new"' in html  # Start selling lives in the menu
    for hook in ("data-newshop", "data-steps", "data-step-dot",
                 "data-step-count", "data-pane", "data-next", "data-back"):
        assert hook in html, f"/new missing {hook}"


# --- 5. languages, JS hooks ----------------------------------------------------


def test_public_pages_render_en_ta_hi(tmp_path):
    client, _token, slug, qtoken, public = _seed(tmp_path)
    urls = ["/", "/new", "/market", "/my", "/share", f"/s/{slug}",
            f"/s/{slug}/quote", f"/q/{qtoken}", f"/b/{public}"]
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url}"
            assert resp.text.strip(), f"{lang} {url} empty"
        client.cookies.clear()


def test_no_missing_i18n_keys():
    from app.web.i18n import missing_keys

    assert missing_keys() == {"ta": [], "hi": []}
