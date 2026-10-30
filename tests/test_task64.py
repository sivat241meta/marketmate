"""Task 64: v9 look (workspace for sellers, fresh product grid for customers).

Pins the v9 tokens, their contrast, the seller desktop shell + phone nav,
the product tile, the orders board, the no-network search filter, the JS
hooks on the key pages, and rendering of every page in en/ta/hi.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
TEMPLATES = ROOT / "app" / "web" / "templates"
BASE = TEMPLATES / "base.html"

# Task 105: v11 re-themed the app to the Meta blue accent; the v9 purple
# tokens were renamed to --accent/* with new values and Meta neutrals.
# Task 122: v12 re-themed to teal green + soft blue with new values.
V9_TOKENS = {
    "--ink": "#102A33", "--ink2": "#3C4048", "--muted": "#56707A",
    "--line": "#E2EAEE", "--soft": "#F0F2F5", "--bg": "#F3F8FA",
    "--surface": "#FFFFFF", "--chrome": "#0B2A33",
    "--chrome-2": "#123A44", "--chrome-line": "#1E4A55",
    "--chrome-txt": "#C8CCD3", "--chrome-on": "#134E4A",
    "--chrome-accent": "#5EEAD4",
    "--accent": "#0F766E", "--accent-ink": "#115E59",
    "--accent-soft": "#E6FAF6", "--green": "#0F7F3F",
    "--green-soft": "#E8F7EE", "--amber": "#8A5208",
    "--amber-soft": "#FFF5E3", "--red": "#C4363B",
    "--red-soft": "#FDECEC", "--blue": "#0369A1",
    "--blue-soft": "#E8F4FD", "--todo": "#5F6672",
    "--todo-soft": "#F0F1F3",
}
# Task 122: the v11 Meta-blue hexes must be gone from app.css and every
# template, like the older palettes before them.
# (--avatar-1 #1F5FBF is the one v11 blue the v12 palette keeps.)
V11_HEXES = ("0866FF", "0064E0", "0081FB", "00B2FF", "E7F0FF", "1E1F21",
             "2C2D31", "3A3B40", "1B2B44", "4D9BFF", "F7F8FA", "E4E6EB",
             "65676B", "1C2B33", "EAF2FF")

OLD_HEXES = ("173F2A", "4F9A2E", "3E7D22", "178A4C", "F5C451",
             "FFF4D6", "EEF6EE", "7B5CFA", "5B3FE0", "F1EEFF",
             "17171C", "12924A", "FF4FA0", "3A86FF", "121216",
             "2A2A33")
OLD_TOKENS = ("--forest", "--leaf", "--gold", "--violet", "--cta",
              "--mint", "--danger", "--brand", "--hero",
              "--purple", "--purple-ink", "--purple-soft")
# Task 105: the v9 purple hexes must be gone from CSS/templates/JS.
PURPLE_HEXES = ("7B68EE", "5F55EE", "F0EEFD", "38335A")


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, name="T64 Store", phone="+914400000064",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, local=None, flags=None):
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
    from app.models import Flag

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


def _slug(tmp_path, token) -> str:
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def _seed_bill_and_session(tmp_path, token):
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
                                 source="seller", kind="bill",
                                 status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id,
                       [_two_price_draft(), _draft("onion", 30)])
        db.set_session_status(conn, session_id, "review", "2 items")
        return bill_id, session_id
    finally:
        conn.close()


def _seed_order(tmp_path, token, status="new", name="Priya"):
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
                                 status=status,
                                 customer_name=name)
        return db.get_quote_by_token(conn, qtoken)["id"]
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


# --- 1. tokens: v9 in, old colours out --------------------------------------


def test_v9_tokens_exist_and_old_colours_gone():
    css = CSS.read_text()
    for token, value in V9_TOKENS.items():
        assert re.search(rf"{re.escape(token)}\s*:\s*{re.escape(value)}",
                         css, re.IGNORECASE), token
    squashed = css.replace(" ", "")
    assert "linear-gradient(135deg,#0F766E,#0EA5A450%,#38BDF8)" in squashed
    for gone in OLD_TOKENS:
        assert gone not in css, f"{gone} still in app.css"
    for path in [CSS, *sorted(TEMPLATES.glob("*.html"))]:
        lowered = path.read_text().lower()
        for stop in OLD_HEXES + V11_HEXES:
            assert f"#{stop.lower()}" not in lowered, \
                f"{path.name}: old #{stop}"
        if path.suffix == ".html":
            for word in ("forest", "leaf", "gold", "violet", "purple"):
                assert word not in lowered, f"{path.name}: {word} leftover"
    # Task 105: no v9 purple hex or token name in any CSS, template or JS.
    static = ROOT / "app" / "web" / "static"
    themed = [CSS, *sorted((static / "css").glob("*.css")),
              *sorted(TEMPLATES.glob("*.html")),
              *sorted(static.glob("*.js"))]
    for path in themed:
        lowered = path.read_text().lower()
        for stop in PURPLE_HEXES:
            assert f"#{stop.lower()}" not in lowered, \
                f"{path.name}: purple #{stop}"
        assert "--purple" not in lowered, f"{path.name}: --purple leftover"


# --- 2. contrast ------------------------------------------------------------

def _luminance(hexcode: str) -> float:
    rgb = [int(hexcode[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def channel(value: float) -> float:
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(fore: str, back: str) -> float:
    light, dark = sorted([_luminance(fore), _luminance(back)],
                         reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_text_background_pairs_pass_contrast():
    # Task 122: teal + soft-blue pairs (every text pair >= 4.5:1).
    pairs = [
        ("white on accent", "#FFFFFF", "#0F766E"),
        ("white on accent-ink", "#FFFFFF", "#115E59"),
        ("accent-ink on white", "#115E59", "#FFFFFF"),
        ("accent on accent-soft", "#0F766E", "#E6FAF6"),
        ("accent-ink on accent-soft", "#115E59", "#E6FAF6"),
        ("white on blue", "#FFFFFF", "#0369A1"),
        ("blue on blue-soft", "#0369A1", "#E8F4FD"),
        ("muted on white", "#56707A", "#FFFFFF"),
        ("muted on bg", "#56707A", "#F3F8FA"),
        ("muted on soft", "#56707A", "#F0F2F5"),
        ("chip new", "#0F766E", "#E6FAF6"),
        ("chip packing", "#8A5208", "#FFF5E3"),
        ("chip ready", "#0F7F3F", "#E8F7EE"),
        ("chip collected", "#56707A", "#F0F2F5"),
        ("chip unpaid", "#C4363B", "#FDECEC"),
        ("chip live", "#0F7F3F", "#E8F7EE"),
        ("chip needs-you", "#8A5208", "#FFF5E3"),
        ("chip to-do", "#5F6672", "#F0F1F3"),
        ("chrome text on chrome", "#C8CCD3", "#0B2A33"),
        ("white on chrome-on", "#FFFFFF", "#134E4A"),
        ("chrome accent on chrome", "#5EEAD4", "#0B2A33"),
        ("sky on chrome", "#7DD3FC", "#0B2A33"),
        ("white on price green", "#FFFFFF", "#0F7F3F"),
        ("white on avatar 0", "#FFFFFF", "#C2337A"),
        ("white on avatar 1", "#FFFFFF", "#1F5FBF"),
        ("white on avatar 2", "#FFFFFF", "#0F7F3F"),
        ("white on avatar 3", "#FFFFFF", "#0F766E"),
        ("white on avatar 4", "#FFFFFF", "#8A5208"),
    ]
    for name, fore, back in pairs:
        assert _contrast(fore, back) >= 4.5, f"{name} below 4.5"


# --- 3. seller desktop shell --------------------------------------------------

SELLER_TABS = [
    ("/e/{t}", "/e/{t}"),
    ("/e/{t}/live", "/e/{t}/live"),
    ("/e/{t}/bills?range=today&status=waiting", "/e/{t}/bills"),
    ("/e/{t}/bills", "/e/{t}/bills"),
    ("/e/{t}/credit", "/e/{t}/credit"),
    ("/e/{t}/close", "/e/{t}/close"),
]


def test_seller_desktop_shell(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    for url, _active in SELLER_TABS:
        html = client.get(url.format(t=token)).text
        assert 'class="topbar"' in html, f"{url}: no dark top bar"
        assert "data-shell-search" in html, f"{url}: no shell search"
        assert "Search items, orders, customers" in html, \
            f"{url}: search placeholder"
        assert 'class="seg"' in html, f"{url}: no language switch"
        assert "Say today" in html, f"{url}: no prices button"
        assert 'class="rail"' in html, f"{url}: no icon rail"
        for label in ("Today", "Prices", "Orders", "Bills", "Credit",
                      "Close", "More"):
            assert label in html, f"{url}: rail missing {label}"
        assert "data-orders-badge" in html, f"{url}: no orders badge"
    # The right rail item is active on each page.
    cases = [(f"/e/{token}", f'href="/e/{token}"'),
             (f"/e/{token}/live", f'href="/e/{token}/live"'),
             (f"/e/{token}/bills", f'href="/e/{token}/bills"'),
             (f"/e/{token}/credit", f'href="/e/{token}/credit"'),
             (f"/e/{token}/close", f'href="/e/{token}/close"')]
    for url, href in cases:
        html = client.get(url).text
        rail = re.search(r'<nav class="rail".*?</nav>', html,
                         re.DOTALL).group(0)
        assert re.search(rf'<a class="ic on" {href}', rail), \
            f"{url}: rail active item wrong"


def test_helper_sees_only_allowed_links(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        _, helper = db.create_helper(conn, shop["id"], "Muthu")
    finally:
        conn.close()
    html = client.get(f"/e/{helper}").text
    assert 'class="rail"' in html
    rail = re.search(r'<nav class="rail".*?</nav>', html,
                     re.DOTALL).group(0)
    assert f"/e/{helper}/live" not in rail
    assert f"/e/{helper}/close" not in rail
    assert f"/e/{helper}/live" not in html
    assert f"/e/{helper}/close" not in html
    assert f"/e/{helper}/settings" not in html
    assert f"/e/{helper}/photos" not in html
    assert f"/e/{helper}/purchases" not in html


def test_phone_bottom_nav_has_five_links(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    bar = re.search(r'<nav class="bnav".*?</nav>', html,
                    re.DOTALL).group(0)
    links = re.findall(r"<a ", bar)
    assert len(links) == 5, f"bnav should have 5 links, got {len(links)}"
    assert 'class="mic' in bar, "centre mic button missing"
    assert "data-orders-badge" in bar


def test_customer_pages_have_no_seller_nav(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    qtoken, public = _seed_customer_quote(tmp_path, token)
    for url in ("/", "/new", "/market", f"/s/{slug}",
                f"/s/{slug}/quote", f"/q/{qtoken}", f"/b/{public}",
                "/my", "/share"):
        html = client.get(url).text
        assert 'class="bnav"' not in html, f"{url} leaks seller bnav"
        assert 'class="rail"' not in html, f"{url} leaks seller rail"
        assert 'class="topbar"' not in html, f"{url} leaks seller topbar"
        assert "data-orders-badge" not in html, f"{url} leaks badge hook"


# --- 4. product tile ----------------------------------------------------------

def test_product_tile_structure(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    html = client.get(f"/s/{slug}").text
    card = re.search(r'<article class="card".*?</article>', html,
                     re.DOTALL).group(0)
    assert '<div class="pw">' in card, "tile needs a photo wrapper"
    assert 'class="add"' in card, "ADD must sit on the photo"
    assert card.index('class="pw"') < card.index('class="add"'), \
        "ADD must be inside the photo wrapper"
    assert 'class="step"' in card, "ADD needs its stepper"
    assert '<span class="pp">' in card, "tile needs the price label"
    assert "₹40" in card
    assert "தக்காளி" in card


def test_new_bill_tiles(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    html = client.get(f"/e/{token}/bills/new").text
    assert '<div class="pw">' in html
    assert '<span class="pp">' in html
    assert "data-search-row" in html


# --- 5. orders board ------------------------------------------------------------

def test_board_view_counts_and_next_steps(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_order(tmp_path, token, "new", "Priya")
    _seed_order(tmp_path, token, "new", "Arun")
    _seed_order(tmp_path, token, "packing", "Ravi")
    _seed_order(tmp_path, token, "ready", "Meena")
    _seed_order(tmp_path, token, "collected", "Kala")
    html = client.get(f"/e/{token}/bills?range=today&status=all").text
    assert "data-view-btn" in html, "List | Board switch missing"
    assert "List" in html and "Board" in html
    assert "mm_bills_view" in html, "view switch must remember"
    assert '<div class="board">' in html, "no board rendered"
    chunks = html.split('<section class="colb"')[1:]
    assert len(chunks) == 4, f"board needs 4 columns, got {len(chunks)}"
    for chunk, chip, count in zip(
            chunks, ("c-new", "c-pack", "c-ready", "c-done"),
            (2, 1, 1, 1)):
        assert f'<span class="chip {chip}">' in chunk
        assert chunk.count('class="ocard"') == count, \
            f"{chip} should hold {count} cards"
    # Next-step buttons post to the existing order-status route.
    posts = re.findall(
        r'<form class="inline-form" method="post" '
        rf'action="/e/{re.escape(token)}/bills/(\d+)/order-status">\s*'
        r'<input type="hidden" name="status" value="(\w+)">',
        html)
    assert len(posts) == 4, f"expected 4 next-step forms, got {len(posts)}"
    assert ("packing" in [s for _, s in posts]
            and "ready" in [s for _, s in posts]
            and "collected" in [s for _, s in posts])


# --- 6. search filter sends nothing -------------------------------------------

def test_search_filter_script_sends_nothing(tmp_path):
    base = BASE.read_text()
    blocks = re.findall(r"<script>(.*?)</script>", base, re.DOTALL)
    scripts = [b for b in blocks if "data-search-row" in b]
    assert scripts, "no shell search script found"
    for script in scripts:
        assert "fetch" not in script, "shell search must not fetch"
        assert "XMLHttpRequest" not in script
        assert "[data-search-row]" in script
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    _seed_order(tmp_path, token, "new", "Priya")
    for url in (f"/e/{token}", f"/e/{token}/bills",
                f"/e/{token}/bills/new"):
        html = client.get(url).text
        assert "data-search-row" in html, f"{url}: rows need the hook"


# --- 7. JS hooks still present --------------------------------------------------
# Hooks collected from the JS each page loads (same approach as Task 50).

LIVE_HOOKS = ["data-live", "data-live-mic", "data-live-finish",
              "data-live-cards", "data-live-error", "live.js"]
REVIEW_HOOKS = ["review-form", "data-approve-url", "data-review-counts",
                "data-review-bar", "data-card-toggle", "data-card=",
                "opt-btn", "data-target-field", "data-card-confirm",
                "data-confirm-wrap", "data-edit-note", "proof-data",
                "approve-btn", "approve-error", "data-approve-count",
                "review.js"]
BILLS_NEW_HOOKS = ["data-methods", "data-tap-form", "data-line",
                   "data-rate", "data-per", "data-stepper", "data-keypad",
                   "data-live-order", "data-offline-banner", "methods.js",
                   "live-order.js", "tap-chips.js", "offline-bills.js",
                   "quote.js", "recorder.js"]
BILL_HOOKS = ["data-receipt", "data-amount", "data-total", "data-cash",
              "data-cash-gave", "data-cash-back", "cash-gave",
              "receipt-card", "receipt-total", "bill-actions",
              "tap-chips.js", "quote.js"]
SHOP_HOOKS = ["data-shop-grid", "data-shop-search", "data-card",
              "data-add", "data-step", "data-step-qty", "data-inc",
              "data-dec", "data-sizes", "data-cart-bar", "data-cart-label",
              "data-cart-summary", "data-cart-lines", "data-cart-total",
              "data-cart-sheet", "data-cart-submit", "data-cart-view",
              "data-customer-name", "data-customer-phone", "my.js"]


def test_js_hooks_present_on_key_pages(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id, session_id = _seed_bill_and_session(tmp_path, token)
    pages = [(f"/e/{token}/live", LIVE_HOOKS),
             (f"/e/{token}/s/{session_id}", REVIEW_HOOKS),
             (f"/e/{token}/bills/new", BILLS_NEW_HOOKS),
             (f"/e/{token}/bills/{bill_id}", BILL_HOOKS),
             (f"/s/{slug}", SHOP_HOOKS)]
    for url, hooks in pages:
        html = client.get(url).text
        for hook in hooks:
            assert hook in html, f"{url} missing {hook}"


def test_hooks_match_what_js_queries():
    pooled = ""
    for name in ("live", "review", "methods", "live-order", "tap-chips",
                 "offline-bills", "quote", "recorder", "my"):
        pooled += (ROOT / f"app/web/static/{name}.js").read_text()
    pooled += (ROOT / "app/web/templates/bill.html").read_text()
    pooled += (ROOT / "app/web/templates/shop.html").read_text()

    def queried(key: str) -> bool:
        if key.endswith(".js"):
            return True
        if key.startswith("data-"):
            bare = key[5:].rstrip("=")
            camel = bare.split("-")[0] + "".join(
                p[:1].upper() + p[1:] for p in bare.split("-")[1:])
            return (key in pooled or camel in pooled
                    or f'"{key}"' in pooled or f"'{key}'" in pooled
                    or f"[{key}]" in pooled or f"[{key}=" in pooled)
        return (key in pooled or f'"{key}"' in pooled
                or f"'{key}'" in pooled or f".{key}" in pooled
                or f"#{key}" in pooled)

    for hooks in (LIVE_HOOKS, REVIEW_HOOKS, BILLS_NEW_HOOKS, BILL_HOOKS,
                  SHOP_HOOKS):
        for hook in hooks:
            assert queried(hook), f"{hook} is not queried by any JS"


# --- 8. every page renders in en, ta and hi -------------------------------------

def _seed_render_shop(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி"),
                               _draft("onion", 30, local="வெங்காயம்")])
    bill_id, session_id = _seed_bill_and_session(tmp_path, token)
    qtoken, public = _seed_customer_quote(tmp_path, token)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        proc_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, proc_id, "processing", "working")
        lang_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, lang_id, "processing", "test")
        db.set_stage(conn, lang_id, "language_check", detail="other")
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit", data={
        "customer_name": "Priya", "customer_phone": "98765 43210"})
    assert resp.status_code in (302, 303), resp.text
    credit_html = client.get(f"/e/{token}/credit").text
    match = re.search(rf"/e/{re.escape(token)}/credit/([^\"]+)",
                      credit_html)
    assert match, "no credit customer link"
    return client, token, slug, {
        "bill": bill_id, "session": session_id, "proc": proc_id,
        "lang": lang_id, "qtoken": qtoken, "public": public,
        "credit_key": match.group(1),
    }


def _render_urls(token, slug, ids):
    t = token
    return [
        "/", "/new", "/market", "/my", "/share", f"/s/{slug}",
        f"/s/{slug}/quote", f"/q/{ids['qtoken']}", f"/b/{ids['public']}",
        f"/e/{t}", f"/e/{t}/live", f"/e/{t}/s/{ids['session']}",
        f"/e/{t}/s/{ids['proc']}", f"/e/{t}/s/{ids['lang']}",
        f"/e/{t}/s/{ids['session']}/live", f"/e/{t}/bills/new",
        f"/e/{t}/bills", f"/e/{t}/bills/{ids['bill']}",
        f"/e/{t}/bills?range=today&status=waiting", f"/e/{t}/close",
        f"/e/{t}/credit", f"/e/{t}/credit/{ids['credit_key']}",
        f"/e/{t}/settings", f"/e/{t}/purchases", f"/e/{t}/update",
        f"/e/{t}/photos",
    ]


def test_every_page_renders_all_langs(tmp_path):
    client, token, slug, ids = _seed_render_shop(tmp_path)
    urls = _render_urls(token, slug, ids)
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 200, \
                f"{lang} {url} -> {resp.status_code}"


def test_pdfs_render(tmp_path):
    client, token, _slug, ids = _seed_render_shop(tmp_path)[:4]
    t = token
    version_conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(version_conn, t)
        version_id = db.latest_version(version_conn, shop["id"],
                                       published_only=True)
    finally:
        version_conn.close()
    for url in (f"/e/{t}/bills/{ids['bill']}/pdf",
                f"/e/{t}/v/{version_id}/board.pdf",
                f"/e/{t}/tags.pdf", f"/e/{t}/close.pdf",
                f"/q/{ids['qtoken']}/pdf", f"/e/{t}/link-card.pdf"):
        resp = client.get(url)
        assert resp.status_code == 200, f"{url} -> {resp.status_code}"
        assert resp.content[:5] == b"%PDF-", f"{url} is not a PDF"


def test_error_page_renders_all_langs(tmp_path):
    from fastapi.templating import Jinja2Templates
    from starlette.requests import Request

    from app.web.i18n import jinja_flag, jinja_t

    templates = Jinja2Templates(
        directory=str(ROOT / "app" / "web" / "templates"))
    templates.env.globals["t"] = jinja_t
    templates.env.globals["t_flag"] = jinja_flag
    for lang in ("en", "ta", "hi"):
        scope = {"type": "http", "method": "GET", "path": "/",
                 "headers": [(b"cookie",
                              f"ui_lang={lang}".encode())],
                 "query_string": b"", "server": ("test", 80),
                 "scheme": "http"}
        response = templates.TemplateResponse(
            Request(scope), "error.html",
            {"title": "Oops", "message": "Something broke"})
        assert response.status_code == 200
        assert "MarketMate" in response.body.decode()
