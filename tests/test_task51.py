"""Task 51: Fresh Green design system, fonts and app shell (failing first).

Replaces the Task 48 Meta Blue look with the approved style guide in
docs/ui/fresh-green.html: Plus Jakarta Sans, forest/leaf/gold tokens and
the white sticky header + forest announcement bar + bottom nav shell.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import IST
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "app" / "web" / "static" / "fonts"
CSS = ROOT / "app" / "web" / "static" / "app.css"
TEMPLATES = ROOT / "app" / "web" / "templates"
SOURCES = FONTS_DIR / "SOURCES.md"
OFL = FONTS_DIR / "OFL.txt"

JAKARTA_FILE = "PlusJakartaSans-Variable.ttf"
JAKARTA_URL = ("https://raw.githubusercontent.com/google/fonts/main/ofl/"
               "plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf")

REMOVED_FONTS = ("Outfit-Variable.ttf", "BalooThambi2-Variable.ttf")

# Task 105: v11 IS the Meta Blue theme now, so the v9 purple leftovers
# are the ones that may not remain in app.css or any template.
PURPLE_HEXES = ("7b68ee", "5f55ee", "f0eefd", "38335a")
BLUE_WORDS = ("Outfit", "Baloo")


def _client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def _create_shop(client, language="ta", name="T51 Store", phone="+914400000051"):
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
        return shop["slug"], version_id
    finally:
        conn.close()


def _seed_review_session(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, session_id, "review", "waiting")
        return session_id
    finally:
        conn.close()


def _seed_bill_and_session(tmp_path, token):
    from app.market.quote import Quote, QuoteLine

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
        return bill_id, session_id
    finally:
        conn.close()


def _seed_customer_quote(tmp_path, token):
    from app.market.quote import Quote, QuoteLine

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
                                 source="customer", kind="quote", status="new")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        public = db.ensure_bill_token(conn, bill_id)
        return qtoken, public
    finally:
        conn.close()


def _prices_hhmm(tmp_path, version_id):
    conn = db.connect(tmp_path / "data")
    try:
        when = db.version_time(conn, version_id)
    finally:
        conn.close()
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(IST).strftime("%H:%M")


# --- 1. fonts ---

def test_jakarta_font_exists_magic_and_sources():
    path = FONTS_DIR / JAKARTA_FILE
    assert path.is_file(), f"missing {JAKARTA_FILE}"
    data = path.read_bytes()
    assert data[:4] == b"\x00\x01\x00\x00", f"{JAKARTA_FILE} bad magic"
    assert 20 * 1024 <= len(data) <= 2 * 1024 * 1024, f"{JAKARTA_FILE} size {len(data)}"
    sources_text = SOURCES.read_text()
    assert JAKARTA_FILE in sources_text
    assert hashlib.sha256(data).hexdigest() in sources_text
    assert JAKARTA_URL in sources_text
    assert "Plus Jakarta Sans" in OFL.read_text()


def test_meta_blue_fonts_gone_and_unreferenced():
    for filename in REMOVED_FONTS:
        assert not (FONTS_DIR / filename).exists(), f"{filename} still on disk"
    haystacks = [CSS.read_text(), SOURCES.read_text(), OFL.read_text()]
    haystacks += [p.read_text() for p in sorted(TEMPLATES.glob("*.html"))]
    haystacks += [p.read_text() for p in sorted((ROOT / "app" / "web" / "static").glob("*.js"))]
    for text in haystacks:
        for word in BLUE_WORDS:
            assert word not in text, f"{word} still referenced"


# --- 2. tokens ---

def test_css_fresh_green_tokens():
    # Task 64 re-themed the app to v9 (workspace x fresh grid); the Fresh
    # Green tokens were replaced. Task 105 re-themed v11 to Meta blue.
    # Task 122 re-themed v12 to teal green + soft blue.
    # This test now pins the v12 tokens.
    css = CSS.read_text()
    for token, value in (
        ("--ink", "#102A33"), ("--ink2", "#3C4048"),
        ("--muted", "#56707A"), ("--line", "#E2EAEE"),
        ("--soft", "#F0F2F5"), ("--bg", "#F3F8FA"),
        ("--surface", "#FFFFFF"),
        ("--chrome", "#0B2A33"), ("--chrome-2", "#123A44"),
        ("--chrome-line", "#1E4A55"), ("--chrome-txt", "#C8CCD3"),
        ("--chrome-on", "#134E4A"), ("--chrome-accent", "#5EEAD4"),
        ("--accent", "#0F766E"), ("--accent-ink", "#115E59"),
        ("--accent-soft", "#E6FAF6"), ("--accent-bright", "#14B8A6"),
        ("--green", "#0F7F3F"), ("--green-soft", "#E8F7EE"),
        ("--amber", "#8A5208"), ("--amber-soft", "#FFF5E3"),
        ("--red", "#C4363B"), ("--red-soft", "#FDECEC"),
        ("--blue", "#0369A1"), ("--blue-soft", "#E8F4FD"),
        ("--sky", "#38BDF8"),
        ("--avatar-0", "#C2337A"), ("--avatar-1", "#1F5FBF"),
        ("--avatar-2", "#0F7F3F"), ("--avatar-3", "#0F766E"),
        ("--avatar-4", "#8A5208"),
        ("--r-card", "14px"), ("--r-pill", "999px"),
    ):
        assert re.search(rf"{re.escape(token)}\s*:\s*{re.escape(value)}",
                         css, re.IGNORECASE), token
    assert "41,45,52" in css.replace(" ", ""), "ink-tinted shadow missing"
    for gone in ("--forest", "--leaf", "--cta", "--gold", "--mint",
                 "--gold-soft", "--leaf-ink", "--forest-2", "--danger",
                 "--violet", "--brand", "--hero",
                 "--purple", "--purple-ink", "--purple-soft"):
        assert gone not in css, f"{gone} still in app.css"


def test_css_has_no_purple():
    css = CSS.read_text()
    lowered = css.lower()
    for stop in PURPLE_HEXES:
        assert f"#{stop}" not in lowered, f"purple #{stop} still in app.css"
    for word in BLUE_WORDS:
        assert word not in css, f"{word} still in app.css"
    assert "--brand" not in css, "--brand token still in app.css"
    assert "--hero" not in css, "--hero token still in app.css"
    assert "--purple" not in css, "--purple token still in app.css"


def test_css_typography_and_tap_targets():
    css = CSS.read_text()
    # Task 76: Inter replaced Plus Jakarta Sans as the Latin UI font
    # (the Jakarta file stays for the logo generator, but CSS no longer
    # references it).
    assert "Plus Jakarta Sans" not in css
    assert "PlusJakartaSans" not in css
    blocks = [b for b in re.findall(r"@font-face\s*\{[^}]+\}", css, re.DOTALL)
              if '"Inter"' in b]
    assert blocks, "no @font-face for Inter"
    assert any("unicode-range" in b for b in blocks)
    assert any("font-display" in b and "swap" in b for b in blocks)
    assert "Noto Sans Tamil" in css, "Tamil must keep Noto Sans Tamil"
    assert re.search(r"font-size\s*:\s*15px", css), "base size 15px missing"
    # No px floor: the approved guide uses smaller micro-labels (kickers,
    # badges); tap targets stay at 48px.
    assert re.search(r"--tap\s*:\s*48px", css), "--tap must be 48px"
    assert re.search(r"\.btn\s*\{[^}]*min-height", css), ".btn needs min-height"


def test_css_guide_components():
    css = CSS.read_text()
    # pill buttons: dark / cta / ghost, at least 46px tall (Task 64: gold
    # was removed; the compact topbar cta at 38px is laptop-only).
    for kind in ("dark", "cta", "ghost"):
        matches = re.findall(rf"\.pill\.{kind}\s*\{{[^}}]*\}}", css)
        assert matches, f"missing .pill.{kind}"
        heights = [float(m.group(1)) for m in
                   (re.search(r"min-height\s*:\s*([\d.]+)px", block)
                    for block in matches) if m]
        assert heights and max(heights) >= 46, \
            f".pill.{kind} must be at least 46px tall"
    # kicker, headline, trio, notice, search, chips
    assert re.search(r"\.kick\s*\{", css), "missing .kick"
    assert re.search(r"\.kick::before\s*\{", css), "kicker needs the leading line"
    assert re.search(r"h1\.big\s+em\s*\{", css), "missing h1.big em"
    assert re.search(r"\.trio\s*\{", css), "missing .trio"
    assert re.search(r"\.notice\s*\{[^}]*var\(--accent-soft\)", css), \
        ".notice must be accent-soft"
    assert re.search(r"\.search\s*\{", css), "missing .search"
    assert re.search(r"(?<!tabs )\.chip\.on\s*\{[^}]*var\(--ink\)", css) or \
        re.search(r"\.chip\.is-active\s*\{[^}]*var\(--ink\)", css), \
        "selected chip must be ink"
    # product card, float bar, band, timeline, receipt, standee, live
    for pattern in (r"\.card\s+\.ph\s*\{", r"\.float\s*\{", r"\.band\s*\{",
                    r"\.gc\s*\{", r"\.tline\s*\{", r"\.rcpt\s*\{", r"\.upi\s*\{",
                    r"\.change\s*\{", r"\.cam\s*\{", r"\.heard\s*\{"):
        assert re.search(pattern, css), f"missing {pattern}"
    # shell
    for pattern in (r"\.ann\s*\{", r"\.hdr\s*\{", r"\.bnav\s*\{", r"\.lang\s*\{"):
        assert re.search(pattern, css), f"missing {pattern}"
    # needs-a-tap is amber-soft, never blue (Task 64: was gold-soft)
    assert re.search(r"pill-check[^}]*(--amber-soft|#FFF5E3)",
                     css, re.IGNORECASE), "needs-you pill must use amber-soft"
    assert re.search(r"\.heard\.need\s*\{[^}]*(--amber-soft|--need-bg|#FFF5E3)",
                     css, re.IGNORECASE), ".heard.need must use amber-soft"


def test_templates_have_no_purple():
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text()
        lowered = text.lower()
        for stop in PURPLE_HEXES:
            assert f"#{stop}" not in lowered, f"{path.name}: purple #{stop}"
        assert "--purple" not in lowered, f"{path.name}: --purple leftover"
        for word in BLUE_WORDS:
            assert word not in text, f"{path.name}: {word} leftover"


# --- 4. app shell ---

def _seller_urls(token):
    return [f"/e/{token}", f"/e/{token}/update", f"/e/{token}/live",
            f"/e/{token}/photos", f"/e/{token}/bills",
            f"/e/{token}/bills/new", f"/e/{token}/settings",
            f"/e/{token}/purchases", f"/e/{token}/close"]


def test_every_page_has_one_hdr_and_one_toggle(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, _version_id = _seed_published(tmp_path, token)
    bill_id, session_id = _seed_bill_and_session(tmp_path, token)
    qtoken, public = _seed_customer_quote(tmp_path, token)
    urls = _seller_urls(token) + [f"/e/{token}/bills/{bill_id}",
                                  f"/e/{token}/s/{session_id}",
                                  "/", "/new", "/market", f"/s/{slug}",
                                  f"/s/{slug}/quote", f"/q/{qtoken}",
                                  f"/b/{public}"]
    for url in urls:
        # Task 171: same-host Referer so / reads the home page.
        html = client.get(
            url, headers={"referer": "http://testserver/market"}).text
        assert html.count('class="hdr"') == 1, f"{url}: hdr count"
        assert html.count('class="lang"') == 1, f"{url}: toggle count"
        assert "data-ui-toggle" in html, f"{url}: toggle missing hook"
        assert 'class="ann"' in html, f"{url}: missing announcement bar"


def test_seller_announcement_uses_real_data(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _slug, version_id = _seed_published(tmp_path, token)
    _seed_review_session(tmp_path, token)
    html = client.get(f"/e/{token}").text
    expected = _prices_hhmm(tmp_path, version_id)
    assert "Shop is open" in html
    assert f"last prices {expected}" in html
    assert "1 list to check" in html


def test_customer_announcement_uses_real_data(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, version_id = _seed_published(tmp_path, token)
    html = client.get(f"/s/{slug}").text
    expected = _prices_hhmm(tmp_path, version_id)
    assert f"Prices said by the seller today, {expected}" in html
    assert "Koyambedu" in html


def _bnav(html):
    match = re.search(r'<nav class="bnav".*?</nav>', html, re.DOTALL)
    assert match, "no seller bnav rendered"
    return match.group(0)


def test_seller_bnav_links_and_active(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _seed_published(tmp_path, token)
    orders_href = f"/e/{token}/bills?range=today&amp;status=waiting"
    cases = [
        (f"/e/{token}", f"/e/{token}"),
        (f"/e/{token}/bills", f"/e/{token}/bills"),
        (f"/e/{token}/live", f"/e/{token}/live"),
        (orders_href.replace("&amp;", "&"), orders_href),
        (f"/e/{token}/close", f"/e/{token}/close"),
    ]
    for url, active_href in cases:
        html = client.get(url).text
        bar = _bnav(html)
        for href in (f"/e/{token}", f"/e/{token}/bills",
                     f"/e/{token}/live", orders_href, f"/e/{token}/close"):
            assert f'href="{href}"' in bar, f"{url}: bnav missing {href}"
        links = re.findall(r'<a class="([^"]*)" href="([^"]+)"', bar)
        assert len(links) == 5, f"{url}: bnav should have 5 links, got {len(links)}"
        active = [href for cls, href in links if "on" in cls.split()]
        assert active == [active_href.replace("&amp;", "&").replace("&", "&amp;")], \
            f"{url}: active tab {active} != {[active_href]}"


def test_seller_desktop_nav_and_cta(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client, name="T51 Hero Store")
    _seed_published(tmp_path, token)
    html = client.get(f"/e/{token}").text
    match = re.search(r'<nav class="nav".*?</nav>', html, re.DOTALL)
    assert match, "no seller desktop nav rendered"
    nav = match.group(0)
    orders_href = f"/e/{token}/bills?range=today&amp;status=waiting"
    # Task 61: Today, Orders (badge), Bills, Close day, More (Task 64).
    for href in (f"/e/{token}", orders_href, f"/e/{token}/bills",
                 f"/e/{token}/close", f"/e/{token}#more"):
        assert f'href="{href}"' in nav, f"desktop nav missing {href}"
    assert f'href="/e/{token}/live"' not in nav
    assert nav.index(orders_href) < nav.index(f"/e/{token}/bills\">")
    for label in ("Today", "Bills", "Close day", "More"):
        assert f">{label}</a>" in nav, f"desktop nav missing {label}"
    assert ">Orders</a>" in nav
    assert "data-orders-badge" in nav
    assert "Say today&#39;s prices" in html or "Say today's prices" in html
    assert f'href="/e/{token}/live"' in html
    assert f'href="/e/{token}/settings"' in html
    assert 'id="more"' in html


def test_staff_bnav_hides_forbidden_links(tmp_path):
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
    assert html and "bnav" in html
    bar = _bnav(html)
    assert f'href="/e/{helper}"' in bar
    assert f'href="/e/{helper}/bills"' in bar
    assert f"/e/{helper}/live" not in bar
    assert f"/e/{helper}/close" not in bar
    assert f"/e/{helper}/live" not in html
    assert f"/e/{helper}/close" not in html
    assert f"/e/{helper}/settings" not in html
    assert f"/e/{helper}/photos" not in html
    assert f"/e/{helper}/purchases" not in html


def test_customer_pages_have_no_seller_nav(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, _version_id = _seed_published(tmp_path, token)
    qtoken, public = _seed_customer_quote(tmp_path, token)
    for url in ("/", "/new", "/market", f"/s/{slug}", f"/s/{slug}/quote",
                f"/q/{qtoken}", f"/b/{public}"):
        # Task 171: same-host Referer so / reads the home page.
        html = client.get(
            url, headers={"referer": "http://testserver/market"}).text
        assert 'class="bnav"' not in html, f"{url} leaks seller bnav"
        assert "seller-hero" not in html, f"{url} leaks seller hero"
        assert "side-link" not in html, f"{url} leaks seller sidebar"
        assert "tabbar" not in html, f"{url} leaks seller tabbar"
        # Task 127: .topbar is the v13 public header now; the seller
        # topbar is pinned by its shell search instead.
        assert "shell-q" not in html, f"{url} leaks seller topbar"
        assert 'class="hdr"' in html, f"{url} missing hdr"


def test_every_template_renders_all_langs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, _version_id = _seed_published(tmp_path, token)
    bill_id, session_id = _seed_bill_and_session(tmp_path, token)
    seller_urls = [f"/e/{token}", f"/e/{token}/update", f"/e/{token}/live",
                   f"/e/{token}/photos", f"/e/{token}/bills",
                   f"/e/{token}/bills/new", f"/e/{token}/bills/{bill_id}",
                   f"/e/{token}/settings", f"/e/{token}/purchases",
                   f"/e/{token}/close", f"/e/{token}/s/{session_id}"]
    customer_urls = ["/", "/new", "/market", f"/s/{slug}", f"/s/{slug}/quote"]
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in seller_urls + customer_urls:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url} -> {resp.status_code}"
        client.cookies.clear()


def test_shell_strings_translated(tmp_path):
    from app.web.i18n import STRINGS

    for key in ("nav.home", "nav.live", "nav.orders", "nav.day", "nav.more",
                "dash.tile_settings", "ann.shop_open", "ann.last_prices",
                "ann.need_tap", "ann.no_prices", "ann.said_today",
                "ann.said_notime", "ann.public", "shell.say_prices",
                "shell.order_voice", "shell.todays_prices", "shell.find_shop",
                "shell.bag"):
        for lang in ("en", "ta", "hi"):
            assert key in STRINGS[lang], f"{key} missing in {lang}"
        assert STRINGS["ta"][key] != STRINGS["en"][key], f"{key} ta == en"
        assert STRINGS["hi"][key] != STRINGS["en"][key], f"{key} hi == en"
    client = _client(tmp_path)
    token = _create_shop(client)
    client.cookies.set("ui_lang", "ta")
    html = client.get(f"/e/{token}").text
    for needle in (">Home<", ">Bills<", ">Live<", ">Orders<", ">Day<", ">More<",
                   "Shop is open", "Say today's prices"):
        assert needle not in html, f"Tamil shell leaks English {needle}"


def test_manifest_and_theme_color(tmp_path):
    client = _client(tmp_path)
    body = client.get("/manifest.webmanifest").json()
    assert body["theme_color"] == "#0F766E"
    assert body["background_color"] == "#F3F8FA"
    html = client.get("/").text
    assert 'name="theme-color"' in html and "#0F766E" in html
