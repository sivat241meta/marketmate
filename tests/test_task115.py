"""Task 115: rich public site (v11) — photo-led cards, animated hero,
area photos, motion system, rich footer. Updated by Task 122 (v12):
Swiggy-style marketplace sections (mind, top-shops, grid, best
prices, markets), sellers/how pages, pop-ups instead of search boxes.
"""

from __future__ import annotations

import html as htmlmod
import re
import shutil
import subprocess
from pathlib import Path

from test_task84 import (
    _home,
    _section,
    draft,
    make_client,
    seed_market,
    seed_shop,
)

ROOT = Path(__file__).resolve().parent.parent
HOME_JS = ROOT / "app" / "web" / "static" / "home.js"
MOTION_JS = ROOT / "app" / "web" / "static" / "motion.js"
MOTION_CSS = ROOT / "app" / "web" / "static" / "css" / "motion.css"
HOME_CSS = ROOT / "app" / "web" / "static" / "css" / "home.css"
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
BASE_HTML = ROOT / "app" / "web" / "templates" / "base.html"

# Task 127: v13 homepage section order.
SECTIONS = ("hero", "fresh", "cats", "shops", "lowest", "how", "app",
            "markets")


def _seeded(tmp_path):
    seed_market(tmp_path)
    return make_client(tmp_path)


# --- 1. every section id in en/ta/hi when data exists -------------------------


def test_v11_sections_all_langs(tmp_path):
    client = _seeded(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        positions = []
        for section in SECTIONS:
            needle = f'id="{section}"'
            assert needle in html, (lang, section)
            positions.append(html.index(needle))
        assert positions == sorted(positions), (lang, "section order")


def test_empty_sections_hide_with_one_combined_state(tmp_path):
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    # Task 127: v13 data sections hide; one combined empty box shows.
    for section in ("fresh", "cats", "shops", "lowest", "markets"):
        tag = re.search(rf'<section[^>]*id="{section}"[^>]*>', html).group(0)
        assert "hidden" in tag, section
    # ...but only ONE visible empty box on the whole page.
    assert 'id="empty-all"' in html
    assert html.count("hp-empty") == 1
    assert t("hp.picks_empty_t") in html
    assert 'class="shop"' not in html
    assert 'class="deal"' not in html


# --- 2. motion system files ----------------------------------------------------


def test_motion_files_exist_linked_and_small(tmp_path):
    assert MOTION_JS.is_file()
    assert MOTION_CSS.is_file()
    assert HOME_CSS.is_file()
    assert MOTION_JS.stat().st_size <= 6 * 1024, MOTION_JS.stat().st_size
    base = BASE_HTML.read_text()
    assert "css/motion.css" in base
    assert "css/home.css" in base
    assert "motion.js" in base
    html = _home(make_client(tmp_path), "en")
    assert re.search(r"/static/motion\.js\?v=[0-9a-f]{10}", html)
    assert re.search(r"/static/css/motion\.css\?v=[0-9a-f]{10}", html)
    assert re.search(r"/static/css/home\.css\?v=[0-9a-f]{10}", html)
    # Seller pages get the subtle parts too (motion linked in base).
    seller_client = make_client(tmp_path)
    first = seller_client.get("/try")
    assert first.status_code in (302, 303)
    assert "motion.js" in seller_client.get(
        first.headers["location"]).text


def test_motion_css_keyframes_and_reduced_motion():
    css = MOTION_CSS.read_text()
    for name in ("rise", "fin", "lbin", "ddin", "tabshine", "panelshine",
                 "newpulse", "hlshine", "uldraw", "hw", "twinkle", "bob",
                 "bellping", "kenburns", "sheetup", "pop"):
        assert f"@keyframes {name}" in css, name
    assert "prefers-reduced-motion: reduce" in css
    reduced = css.split("prefers-reduced-motion: reduce", 1)[1]
    assert "animation: none" in reduced
    assert "transition: none" in reduced
    # Dialog/sheet entrances are pure CSS (run when [hidden] flips off).
    assert ".hp-modal:not([hidden]) .hp-modal-card" in css
    assert ".sheet-wrap:not([hidden]) .sheet" in css


def test_motion_js_reveal_countup_no_network():
    src = MOTION_JS.read_text()
    assert "IntersectionObserver" in src
    assert "data-reveal" in src
    assert "data-count" in src
    assert "prefers-reduced-motion" in src
    assert "fetch(" not in src
    assert "XMLHttpRequest" not in src
    assert "sendBeacon" not in src
    assert re.search(r"\b(lat|lng|latitude|longitude)\b", src) is None


def test_js_files_pass_node_check():
    node = shutil.which("node")
    assert node is not None, "node required"
    for path in (HOME_JS, MOTION_JS):
        proc = subprocess.run([node, "--check", str(path)], check=False,
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, (path.name, proc.stderr)


def test_home_js_local_only_additions():
    src = HOME_JS.read_text()
    assert "data-carousel" in src
    assert "data-heart" in src
    assert "mm_last_q" in src
    assert "fetch(" not in src
    assert "XMLHttpRequest" not in src
    assert "navigator.sendBeacon" not in src


# --- 3. hero: counters, rotator, curve -----------------------------------------


def test_hero_counters_rotator_and_curve(tmp_path):
    # Task 127: the counter strip is gone; the hero service card
    # shows the real prices-today count (7 in the seed market).
    client = _seeded(tmp_path)
    html = _home(client, "en")
    assert "data-count" not in html
    assert "data-words" not in html
    assert "7 PRICES TODAY" in html
    assert "Shops" in html and "Markets" in html
    # Zero prices: the honest zero, still no counters.
    bare = _home(make_client(tmp_path / "fresh"), "en")
    assert "data-count" not in bare
    assert "0 PRICES TODAY" in bare


# --- 4. pick cards: photo, price, badges, heart, actions -----------------------


def test_pick_cards_rich_markup(tmp_path):
    # Task 127: v13 "Today's lowest prices" tiles — photo, name,
    # unit + shop, price, ADD link to the shop page.
    client = _seeded(tmp_path)
    html = _home(client, "en")
    picks = _section(html, "lowest", "how")
    assert picks.count('class="deal"') == 6  # one tile per item
    assert 'loading="lazy"' in picks
    assert "₹40" in htmlmod.unescape(picks)
    # Tomato is sold twice: lowest keeps the cheaper tile only.
    assert "₹43" not in htmlmod.unescape(picks)
    assert ">Add<" in picks
    assert "/s/" in picks


def test_pick_cards_tamil_renders(tmp_path):
    from app.web.i18n import t_for

    client = _seeded(tmp_path)
    html = _home(client, "ta")
    picks = _section(html, "lowest", "how")
    assert t_for("ta")("v13.lowest_t") in picks
    assert "சேர்" in picks  # Add
    assert "தக்காளி" in html


# --- 5. categories -------------------------------------------------------------


def test_category_tiles(tmp_path):
    # Task 127: v13 grey category tiles with clustered item photos;
    # tapping one browses the category.
    client = _seeded(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        cats = _section(html, "cats", "shops")
        tiles = re.findall(r'<a class="cat"[^>]*href="([^"]+)"', cats)
        assert 1 <= len(tiles) <= 12, (lang, len(tiles))
        for href in tiles:
            assert href.startswith("/market?cat="), (lang, href)
    cats = _section(_home(client, "en"), "cats", "shops")
    assert "<img" in cats  # real photos where today's lists have them


# --- 6. shop cards: cover, avatar, voice badge ---------------------------------


def test_shop_cards_cover_and_badges(tmp_path):
    from app.web.i18n import t_for

    client = _seeded(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    shops = _section(html, "shops", "lowest")
    # Task 127: v13 photo cards — cover, name on the photo, meta,
    # deal bar, voice bar, said line.
    assert shops.count('class="shop"') == 3
    assert "seller's voice" in shops
    t = t_for("en")
    assert t("hp.prices_today", n=4) in shops  # Kannan Veg
    assert t("v13.order_voice_lang") in shops
    assert "shop-name" in shops
    assert "bar-deal" in shops  # cheapest items
    assert "landing/" not in shops


# --- 7. basket: sample line + best shop + coverage -----------------------------


def test_basket_section(tmp_path, monkeypatch):
    # Task 122: the homepage basket moved to Find a shop, where basket
    # plan cards carry coverage badges.
    from decimal import Decimal

    from app.market.search import Query, Want

    client = _seeded(tmp_path)
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None),
             Want("banana", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")
    html = htmlmod.unescape(client.get("/market?q=tomato+banana").text)
    assert "cov-badge" in html
    assert "100% of your list" in html
    assert "Kannan Veg" in html
    assert 'href="/s/kannan-veg"' in html
    # Tamil + Hindi render their own strings.
    client.cookies.set("ui_lang", "ta")
    assert "உங்கள் பட்டியல் 100%" in client.get("/market?q=x").text
    client.cookies.set("ui_lang", "hi")
    assert "आपकी सूची 100%" in client.get("/market?q=x").text
    client.cookies.clear()


# --- 8. sellers phone, meta flow, install --------------------------------------


def test_sellers_meta_install(tmp_path):
    client = _seeded(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    sellers = htmlmod.unescape(client.get("/sellers").text)
    assert "Did you say ₹40 or ₹14?" in sellers
    assert "₹40 ✓ confirmed in your voice" in sellers
    assert 'href="/try"' in sellers
    assert "sell-phone" in sellers
    # Task 127: v13 "How the prices get here" cards + dark app band.
    meta = _section(html, "how", "app")
    assert meta.count("meta-card") == 4
    assert "muse-voice-transcribe-1.0" in meta
    assert "muse-spark-1.3" in meta
    assert "sam-3.1" in meta
    install = _section(html, "app", "markets")
    assert "Add to Home Screen" in install
    assert "app-store" not in install.lower()
    assert "App Store" not in install
    assert "/app-qr.png" in install


# --- 9. rich footer ------------------------------------------------------------


def test_footer_columns_link_existing_routes(tmp_path):
    from app.web.i18n import t_for

    client = _seeded(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    # Task 127: the shared v13 footer on every public page.
    footer = html.split('class="foot"')[1]
    assert footer.count('class="foot-col"') == 4
    t = t_for("en")
    for key in ("v13.col_market", "v13.col_sell", "v13.col_help",
                "v13.col_avail", "v13.col_lang"):
        assert t(key) in footer, key
    hrefs = re.findall(r'href="([^"]+)"', footer)
    assert hrefs, "footer has no links"
    for href in hrefs:
        if href.startswith("https://"):
            assert href.startswith(
                ("https://github.com/sivat241meta/marketmate",
                 "https://wa.me/")), href
            continue
        path = href.split("#")[0].split("?")[0] or "/"
        resp = client.get(path)
        assert resp.status_code != 404, href
    t = t_for("en")
    assert t("land.photos_credit") in footer
    assert t("land.icons_credit") in footer
    assert t("land.honest") in footer
    # Task 127: footer language switch + exactly one header switch.
    assert 'class="foot-lang"' in footer
    assert footer.count('data-ui-lang="en"') == 1
    assert footer.count('data-ui-lang="ta"') == 1
    assert footer.count('data-ui-lang="hi"') == 1
    assert html.count('class="lang"') == 1


def _luminance(code: str) -> float:
    rgb = [int(code[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def channel(value: float) -> float:
        return (value / 12.92 if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4)

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(fore: str, back: str) -> float:
    light, dark = sorted([_luminance(fore), _luminance(back)],
                         reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_new_colour_pairs_pass_contrast():
    # Task 127: v13 token pairs — teal/soft-blue on white and tile,
    # white on the dark app band and teal fills.
    css = V13_CSS.read_text().lower()
    assert "#0f766e" in css  # teal
    assert "#0b2a33" in css  # dark app band
    assert "#e8f4fd" in css  # soft blue
    pairs = [
        ("teal on white", "#0F766E", "#FFFFFF"),
        ("blue on white", "#0369A1", "#FFFFFF"),
        ("ink on tile", "#0B2A33", "#EEF3F5"),
        ("white on teal", "#FFFFFF", "#0F766E"),
        ("white on dark", "#FFFFFF", "#0B2A33"),
        ("blue on soft blue", "#0369A1", "#E8F4FD"),
        ("white on blue", "#FFFFFF", "#0369A1"),
    ]
    for name, fore, back in pairs:
        assert _contrast(fore, back) >= 4.5, (name, fore, back)


# --- 10. small-phone + image rules ---------------------------------------------


def test_home_css_small_phone_rules():
    # Task 127: v13 phone rules — wrapping headlines, in-container
    # scrollers, 44px targets, compact sticky bar.
    css = V13_CSS.read_text()
    assert "min-width:0" in css.replace(" ", "")
    assert "overflow-wrap" in css
    assert "@media(max-width:380px)" in css.replace(" ", "")
    assert "scroll-snap-type" in css  # scrollers snap in-container
    assert "44px" in css  # tap targets: nav, buttons, menu, icons
    phone = css.split("@media (max-width:700px)", 1)[1]
    phone = phone.split("@media", 1)[0]
    assert ".stickybar .topbar-in" in phone
    assert ".loc-mini" in phone
    # Tamil/Hindi titles wrap instead of cutting.
    assert "overflow-wrap:break-word" in css.replace(" ", "")


def test_homepage_images_sized_and_lazy(tmp_path):
    # Task 127: content photos are sized + lazy; the decorative hero
    # cut-outs are width-sized + eager (absolute, never shifting).
    client = _seeded(tmp_path)
    html = _home(client, "en")
    imgs = re.findall(r"<img\b[^>]*>", html)
    assert len(imgs) > 5, "expected enriched imagery"
    for tag in imgs:
        if "/static/brand/" in tag:
            continue  # SVG logo: intrinsic ratio, height-only is shift-free
        assert 'width="' in tag, tag
        if re.search(r'class="(float|hero-float|a\d|aa\d)\b', tag):
            continue  # decorative cut-out, sized by width
        assert 'height="' in tag, tag
        if 'loading="eager"' in tag:
            continue  # above-the-fold hero imagery
        assert 'loading="lazy"' in tag, tag


# --- 11. market + shop pages ---------------------------------------------------


def test_market_cards_keep_hooks_with_coverage(tmp_path, monkeypatch):
    from decimal import Decimal

    from app.market.search import Query, Want

    seed_market(tmp_path)
    client = make_client(tmp_path)
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")
    html = client.get("/market?q=tomato").text
    for hook in ("data-shop-list", "data-shop-row", "data-distance",
                 "data-unknown", "data-plan"):
        assert hook in html, hook
    assert "cov-badge" in html  # coverage badge on the plan card
    assert "res-ava" in html  # avatar in the same card language


def test_shop_hero_cover_and_contact_conditionals(tmp_path):
    from app import db

    slug, _token = seed_shop(tmp_path, "Cover Store", "Koyambedu", [
        draft("tomato", "தக்காளி", "40",
              photo="data/photos/tom_cut.jpg"),
        draft("onion", "வெங்காயம்", "35",
              photo="data/photos/oni_orig.jpg"),
    ])
    client = make_client(tmp_path)
    html = client.get(f"/s/{slug}").text
    # Task 127: v13 info card with the cover photo on the right.
    assert 'class="info-cover"' in html
    assert 'src="/m/tom_cut.jpg"' in html or "/static/img/v13/" in html
    assert "wa.me/" in html and "tel:" in html
    assert 'class="added"' not in html  # pop is JS-added, not static
    assert 'classList.add("added")' in html
    # Without a phone, WhatsApp/Call disappear (share + quote stay).
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE shops SET phone = '' WHERE slug = ?",
                     (slug,))
        conn.commit()
    finally:
        conn.close()
    bare = make_client(tmp_path).get(f"/s/{slug}").text
    assert "wa.me/" in bare  # share link keeps its wa.me/?text= form
    assert "tel:" not in bare
    assert "/market" in bare  # fallback: find another shop


def test_no_forbidden_files_touched():
    # Task 127: the guard pins task 115's own commit, not the working
    # tree — later tasks (116, 127, …) legitimately own these files.
    names = subprocess.run(
        ["git", "show", "--name-only", "--format=", "0f8127b"],
        cwd=ROOT, check=False, capture_output=True, text=True,
        timeout=30).stdout
    changed = [line.strip().split(" -> ")[-1]
               for line in names.splitlines() if line.strip()]
    # Task 116 owns these; Task 115 must not touch them.
    for path in changed:
        assert path not in ("app/db.py",
                            "app/web/home_data.py",
                            "app/web/templates/settings.html"), path
        assert not path.startswith("scripts/"), path
        assert not path.startswith("data/"), path
