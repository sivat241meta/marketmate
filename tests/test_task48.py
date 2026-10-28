"""Task 48: Meta Blue design system, fonts and app shell (failing first)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "app" / "web" / "static" / "fonts"
CSS = ROOT / "app" / "web" / "static" / "app.css"
SOURCES = FONTS_DIR / "SOURCES.md"
OFL = FONTS_DIR / "OFL.txt"

EXPECTED_FONTS = {
    "Outfit-Variable.ttf": (
        "Outfit",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/outfit/Outfit%5Bwght%5D.ttf",
    ),
    "BalooThambi2-Variable.ttf": (
        "Baloo Thambi 2",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/baloothambi2/BalooThambi2%5Bwght%5D.ttf",
    ),
}

# Fresh Market palette + derived tones grepped from the old app.css. None may
# remain (annotation/box colours and pure white are not part of the palette).
OLD_HEXES = [
    "14532d", "0e3b20", "f59e0b", "c77c06", "fbf7ef", "1c1917", "78716c",
    "efe8d8", "15803d", "dcfce7", "b45309", "fff7e6", "b3261e", "fdecea",
    "d6cfbd", "6b6459", "eef4ee", "f5f0e6", "e8f0e4", "e7dcc5", "4ade80",
    "fde68a", "a8a29e", "ef4444",
]


def _client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, language="ta", name="T48 Store", phone="+914400000048"):
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
        return shop["slug"]
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


# --- 1. fonts ---

def test_meta_fonts_exist_magic_and_sources():
    assert SOURCES.is_file(), "SOURCES.md missing"
    sources_text = SOURCES.read_text()
    ofl_text = OFL.read_text() if OFL.is_file() else ""
    for filename, (family, url) in sorted(EXPECTED_FONTS.items()):
        path = FONTS_DIR / filename
        assert path.is_file(), f"missing {filename}"
        data = path.read_bytes()
        assert data[:4] == b"\x00\x01\x00\x00", f"{filename} bad magic"
        assert 20 * 1024 <= len(data) <= 2 * 1024 * 1024, f"{filename} size {len(data)}"
        assert filename in sources_text, f"{filename} not in SOURCES.md"
        assert hashlib.sha256(data).hexdigest() in sources_text, f"{filename} sha256 missing"
        assert url in sources_text, f"{filename} url not in SOURCES.md"
        assert family.split()[0] in ofl_text, f"{family} not noted in OFL.txt"


# --- 2. tokens ---

def test_css_meta_blue_tokens():
    css = CSS.read_text()
    assert re.search(r"--brand\s*:\s*#0866ff", css, re.IGNORECASE)
    for token, value in (
        ("--bg", "#F0F2F5"), ("--surface2", "#E4E6EB"), ("--line", "#DADDE1"),
        ("--ink", "#1C2B33"), ("--muted", "#65676B"), ("--ok", "#1E7E34"),
        ("--ok-bg", "#E6F4EA"),
    ):
        assert re.search(rf"{re.escape(token)}\s*:\s*{value}", css, re.IGNORECASE), token
    assert re.search(r"--surface\s*:\s*#fff", css, re.IGNORECASE)
    for stop in ("#0050C8", "#0064E0", "#0866FF"):
        assert stop.lower() in css.lower(), f"hero stop {stop} missing"
    assert "#E7F0FF" in css or "#e7f0ff" in css.lower()


def test_css_has_no_old_palette_hexes():
    css = CSS.read_text().lower()
    for old in OLD_HEXES:
        assert f"#{old}" not in css, f"old palette hex #{old} still in app.css"


def test_css_typography_and_tap_targets():
    css = CSS.read_text()
    assert "Outfit" in css and "Baloo Thambi 2" in css
    for family in ("Outfit", "Baloo Thambi 2"):
        blocks = [b for b in re.findall(r"@font-face\s*\{[^}]+\}", css, re.DOTALL) if family in b]
        assert blocks, f"no @font-face for {family}"
        assert any("unicode-range" in b for b in blocks), f"no unicode-range for {family}"
        assert any("font-display" in b and "swap" in b for b in blocks), f"no swap for {family}"
    assert re.search(r"font-size\s*:\s*15px", css), "base size 15px missing"
    for match in re.finditer(r"font-size\s*:\s*([\d.]+)(px|rem)", css):
        value, unit = float(match.group(1)), match.group(2)
        px = value if unit == "px" else value * 16
        assert px >= 13 - 1e-9, f"font-size {match.group(0)} below 13px minimum"
    assert re.search(r"--tap\s*:\s*48px", css), "--tap must be 48px"
    assert re.search(r"\.btn\s*\{[^}]*min-height", css), ".btn needs min-height"


def test_css_components_and_patterns():
    css = CSS.read_text()
    assert re.search(r"\.card[^{]*\{[^}]*border-radius\s*:\s*20px", css)
    assert re.search(r"\.chip\.is-active\s*\{[^}]*var\(--brand\)", css), "selected chip must be blue"
    assert re.search(r"input,\s*select,\s*textarea\s*\{[^}]*border-radius\s*:\s*14px", css), \
        "inputs need radius 14"
    assert re.search(r"\.pill-check\s*\{[^}]*#E7F0FF", css, re.IGNORECASE), \
        "needs-you pill must use the blue tint"
    assert re.search(r"\.btn-secondary\s*\{[^}]*var\(--surface2\)", css), \
        "secondary button must be grey"
    assert re.search(r"\.btn-green\s*\{[^}]*var\(--ok\)", css), "paid button must be green"
    for pattern in (".hero", ".search", ".cartbar", ".tabbar", ".golive", ".scale",
                    ".standee", ".sheet", ".ring", ".tl", ".story", ".stk", ".pc"):
        assert re.search(rf"^{re.escape(pattern)}[\s.{{:,]", css, re.MULTILINE), \
            f"missing pattern {pattern}"


# --- 4. app shell ---

def _tabbar(html):
    match = re.search(r'<nav class="tabbar".*?</nav>', html, re.DOTALL)
    assert match, "no seller tabbar rendered"
    return match.group(0)


def test_seller_tabbar_links_and_active(tmp_path):
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
        bar = _tabbar(html)
        for href in (f"/e/{token}", f"/e/{token}/bills",
                     f"/e/{token}/live", orders_href, f"/e/{token}/close"):
            assert f'href="{href}"' in bar, f"{url}: tabbar missing {href}"
        links = re.findall(r'<a class="([^"]*)" href="([^"]+)"', bar)
        assert len(links) == 5, f"{url}: tabbar should have 5 links, got {len(links)}"
        active = [href for cls, href in links if "on" in cls.split()]
        assert active == [active_href.replace("&amp;", "&").replace("&", "&amp;")], \
            f"{url}: active tab {active} != {[active_href]}"


def test_staff_tabbar_hides_forbidden_links(tmp_path):
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
    assert html and "tabbar" in html
    bar = _tabbar(html)
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
    from app.market.quote import Quote, QuoteLine

    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _seed_published(tmp_path, token)
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
    finally:
        conn.close()
    for url in ("/", "/new", "/market", f"/s/{slug}", f"/s/{slug}/quote",
                f"/q/{qtoken}", f"/b/{public}"):
        html = client.get(url).text
        assert "tabbar" not in html, f"{url} leaks seller tabbar"
        assert "seller-hero" not in html, f"{url} leaks seller hero"
        assert "side-link" not in html, f"{url} leaks seller sidebar"


def test_seller_hero_sidebar_and_more(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client, name="T48 Hero Store")
    slug = _seed_published(tmp_path, token)
    html = client.get(f"/e/{token}").text
    assert "seller-hero" in html
    assert "T48 Hero Store" in html and "Koyambedu" in html
    assert 'data-ui-lang="ta"' in html and 'data-ui-lang="hi"' in html
    assert f'href="/e/{token}#more"' in html
    assert 'id="more"' in html
    for href in (f"/e/{token}/update", f"/e/{token}/live", f"/e/{token}/photos",
                 f"/e/{token}/bills", f"/e/{token}/purchases", f"/e/{token}/close",
                 f"/s/{slug}", f"/e/{token}/settings"):
        assert f'href="{href}"' in html, f"sidebar missing {href}"
    assert "topbar" in html


def test_every_template_renders_all_langs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _seed_published(tmp_path, token)
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
                "dash.tile_settings"):
        for lang in ("en", "ta", "hi"):
            assert key in STRINGS[lang], f"{key} missing in {lang}"
        assert STRINGS["ta"][key] != STRINGS["en"][key], f"{key} ta == en"
        assert STRINGS["hi"][key] != STRINGS["en"][key], f"{key} hi == en"
    client = _client(tmp_path)
    token = _create_shop(client)
    client.cookies.set("ui_lang", "ta")
    html = client.get(f"/e/{token}").text
    for needle in (">Home<", ">Bills<", ">Live<", ">Orders<", ">Day<", ">More<"):
        assert needle not in html, f"Tamil shell leaks English {needle}"


def test_manifest_and_theme_color(tmp_path):
    client = _client(tmp_path)
    body = client.get("/manifest.webmanifest").json()
    assert body["theme_color"] == "#0866FF"
    assert body["background_color"] == "#F0F2F5"
    html = client.get("/").text
    assert 'name="theme-color"' in html and "#0866FF" in html
