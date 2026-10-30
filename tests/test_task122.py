"""Task 122: design v12 — Swiggy-style marketplace in teal green +
soft blue, with pop-ups instead of search boxes and an animated
header.

Pins: theme tokens + text contrast pairs; the header (5 links,
search + location buttons, one sliding indicator); the three
pop-ups (dialog roles, close buttons); homepage section ids;
the /sellers and /how pages in en/ta/hi; shop-page item rows
(photo + ADD + data hooks); and the honesty rule (no invented
ratings, reviews or delivery times anywhere).
"""

from __future__ import annotations

import html as htmlmod
import re
from pathlib import Path

from test_task84 import _home, _section, draft, make_client, seed_market, seed_shop

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
CSS_DIR = ROOT / "app" / "web" / "static" / "css"
TEMPLATES = ROOT / "app" / "web" / "templates"
HOME_JS = ROOT / "app" / "web" / "static" / "home.js"
MOTION_JS = ROOT / "app" / "web" / "static" / "motion.js"
POPUPS_JS = ROOT / "app" / "web" / "static" / "popups.js"
LOCATE_JS = ROOT / "app" / "web" / "static" / "locate.js"
PUBLIC_JS = ROOT / "app" / "web" / "static" / "public.js"

SECTIONS = ("mind", "top-shops", "shops", "best-prices", "markets",
            "sell", "meta", "install", "footer")


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


# --- 1. theme tokens + contrast pairs ----------------------------------------


def test_theme_tokens_in_root_and_every_css():
    root = CSS.read_text()
    for token, value in (
            ("--accent", "#0F766E"), ("--accent-ink", "#115E59"),
            ("--accent-soft", "#E6FAF6"),
            ("--accent-bright", "#14B8A6"), ("--blue", "#0369A1"),
            ("--blue-soft", "#E8F4FD"), ("--sky", "#38BDF8"),
            ("--ink", "#102A33"), ("--muted", "#56707A"),
            ("--line", "#E2EAEE"), ("--bg", "#F3F8FA")):
        assert re.search(rf"{re.escape(token)}\s*:\s*{re.escape(value)}",
                         root, re.IGNORECASE), token
    squashed = root.replace(" ", "")
    assert "linear-gradient(135deg,#0F766E,#0EA5A450%,#38BDF8)" in squashed
    for path in sorted(CSS_DIR.glob("*.css")):
        text = path.read_text()
        for token, value in (("--accent", "#0F766E"),
                             ("--accent-ink", "#115E59"),
                             ("--accent-soft", "#E6FAF6"),
                             ("--blue", "#0369A1"),
                             ("--blue-soft", "#E8F4FD")):
            assert re.search(
                rf"{re.escape(token)}\s*:\s*{re.escape(value)}", text,
                re.IGNORECASE), (path.name, token)


def test_theme_text_pairs_pass_contrast():
    pairs = [
        ("white on accent", "#FFFFFF", "#0F766E", 5.5),
        ("white on accent-ink", "#FFFFFF", "#115E59", 7.6),
        ("accent on accent-soft", "#0F766E", "#E6FAF6", 5.0),
        ("white on blue", "#FFFFFF", "#0369A1", 5.9),
        ("blue on blue-soft", "#0369A1", "#E8F4FD", 5.3),
        ("muted on white", "#56707A", "#FFFFFF", 4.5),
        ("muted on bg", "#56707A", "#F3F8FA", 4.5),
        ("ink on white", "#102A33", "#FFFFFF", 4.5),
        ("mint on dark", "#5EEAD4", "#0B2A33", 4.5),
        ("sky on dark", "#7DD3FC", "#0B2A33", 4.5),
        ("white on dark", "#FFFFFF", "#0B2A33", 4.5),
        ("price green stays", "#FFFFFF", "#0F7F3F", 4.5),
    ]
    for name, fore, back, floor in pairs:
        ratio = _contrast(fore, back)
        assert ratio >= 4.5, (name, fore, back, ratio)
        assert ratio >= floor - 0.15, (name, fore, back, ratio)


# --- 2. header ----------------------------------------------------------------


def _header(html):
    return re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)


def test_header_has_five_links_search_and_location(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    head = _header(html)
    t = t_for("en")
    for key in ("hp.nav_find", "hp.nav_picks", "hp.nav_areas",
                "hp.nav_sellers", "hp.nav_how"):
        assert t(key) in head, key
    assert head.count("data-nav") >= 5
    assert "data-loc-open" in head  # location button
    assert "data-search-open" in head  # search icon button
    assert 'href="/my"' in head  # My orders + Bag
    assert "data-bag-count" in head
    assert "data-menu-open" in head
    # One shared sliding indicator, moved with transform by motion.js.
    assert head.count("nav-pill") == 1
    assert "nav-pill" in MOTION_JS.read_text()
    assert "compact" in MOTION_JS.read_text()


def test_header_animation_css_and_reduced_motion():
    css = CSS.read_text()
    assert ".hp-nav a::after" in css  # centre-grow underline
    assert ".nav-pill" in css  # one shared indicator, moved by JS
    assert ".hp-header.compact" in css  # 60px on scroll down
    assert "min-height: 72px" in css
    motion = (CSS_DIR / "motion.css").read_text()
    assert "prefers-reduced-motion: reduce" in motion
    assert "@keyframes drawerleft" in motion
    assert "@keyframes popin" in motion
    assert "@keyframes sheetlink" in motion


# --- 3. pop-ups ----------------------------------------------------------------


def test_three_popups_are_dialogs_with_close_buttons(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    bounds = (("loc-drawer", "search-pop"), ("search-pop", "filter-pop"),
              ("filter-pop", "popups.js"))
    for pop_id, next_id in bounds:
        pop = html.split(f'id="{pop_id}"')[1].split(next_id)[0]
        assert 'role="dialog"' in pop, pop_id
        assert 'aria-modal="true"' in pop, pop_id
        assert "data-close" in pop, pop_id
    # Openers live in the header / page.
    assert "data-loc-open" in html
    assert "data-search-open" in html
    assert "data-filter-open" in html
    assert "data-filter-count" in html
    # One shared dialog manager: trap, Esc, scroll lock.
    src = POPUPS_JS.read_text()
    assert "aria-modal" in src or "role" in src
    assert "Escape" in src
    assert "mm-locked" in src
    assert "Tab" in src


def test_search_popup_has_voice_recent_and_popular(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    pop = html.split('id="search-pop"')[1].split('id="filter-pop"')[0]
    t = t_for("en")
    assert 'name="q"' in pop
    assert t("v12.search_ph") in pop
    assert 'href="/market#rec-start"' in pop  # voice button
    assert t("v12.recent") in html and "data-recent" in pop
    assert t("v12.popular") in html
    assert "pop-circle" in pop
    assert "data-live" in pop  # live results as you type
    assert "/market/suggest.json" in pop


def test_suggest_endpoint_returns_items_shops_areas(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    resp = client.get("/market/suggest.json",
                      params={"q": "tomato", "area": "Koyambedu"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"], body
    first = body["items"][0]
    assert "Kannan" in first["shop"] or "Malar" in first["shop"]
    assert "slug" in first and "price" in first
    resp = client.get("/market/suggest.json", params={"q": "kannan"})
    assert any("Kannan" in shop["name"]
               for shop in resp.json()["shops"])
    resp = client.get("/market/suggest.json", params={"q": ""})
    body = resp.json()
    assert body["areas"] and body["popular"]
    assert "Koyambedu" in {area["name"] for area in body["areas"]}
    # Never any coordinates in the response: no lat/lng keys at all.
    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for entry in node:
                yield from keys(entry)

    for key in keys(body):
        assert key.lower() not in ("lat", "lng", "latitude", "longitude",
                                   "coords", "coordinates"), key


# --- 4. homepage --------------------------------------------------------------


def test_homepage_section_ids_all_langs(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        positions = []
        for section in SECTIONS:
            needle = f'id="{section}"'
            assert needle in html, (lang, section)
            positions.append(html.index(needle))
        assert positions == sorted(positions), (lang, "section order")


def test_mind_row_top_shops_and_best_prices(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    mind = _section(html, "mind", "top-shops")
    assert t("v12.mind_t") in mind
    assert "mind-circle" in mind
    assert "/market?q=tomato" in mind
    assert "data-carousel" in mind and "data-prev" in mind
    assert "data-dots" in mind  # progress dots
    top = _section(html, "top-shops", "shops")
    assert "Top shops" in top
    assert top.count('class="shop-cover"') == 3
    assert "cover-line" in top  # overlay line over the gradient
    assert "data-dots" in top
    best = _section(html, "best-prices", "markets")
    assert t("v12.best_t") in best
    assert "pick-add" in best  # ADD on every item card
    assert best.count('class="pick-card"') == 6  # one card per item
    markets = _section(html, "markets", "sell")
    assert t("v12.markets_t") in markets
    assert t("v12.pop_items") in markets
    assert 'class="area-tile' in markets


def test_sell_meta_install_bands_and_footer(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    sell = _section(html, "sell", "meta")
    assert t("v12.sell_t") in sell and t("v12.sell_d") in sell
    assert 'href="/new"' in sell and 'href="/try"' in sell
    meta = _section(html, "meta", "install")
    for model in ("muse-voice-transcribe-1.0", "muse-spark-1.3",
                  "sam-3.1", "meta-models/muse-spark-open-1026"):
        assert model in meta, model
    assert 'href="/how"' in meta
    install = _section(html, "install", "footer")
    assert "Add to home screen" in install
    assert "App Store" not in install
    footer = _section(html, "footer")
    for key in ("v12.col_market", "v12.col_sell", "v12.col_help",
                "v12.col_areas"):
        assert t(key) in footer, key
    assert t("land.honest") in footer


# --- 5. sellers + how pages ----------------------------------------------------


def test_sellers_and_how_render_all_langs(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        t = t_for(lang)
        sellers = htmlmod.unescape(client.get("/sellers").text)
        assert t("v12.sellers_t") in sellers, lang
        assert t("land.hero_a") in sellers, lang  # hero moved here
        assert t("land.value_t") in sellers, lang
        assert t("land.who_t") in sellers, lang
        assert t("land.day_t") in sellers, lang
        assert t("home.lost_title") in sellers, lang
        assert "data-public-header" in sellers, lang
        how = htmlmod.unescape(client.get("/how").text)
        assert t("v12.how_t") in how, lang
        assert t("land.how_t") in how, lang
        assert t("land.cust_t") in how, lang
        assert 'action="/find"' in how, lang
        assert "data-public-header" in how, lang
        client.cookies.clear()


# --- 6. shop page rows ----------------------------------------------------------


def test_shop_page_item_rows_have_photo_add_and_hooks(tmp_path):
    slug, _token = seed_shop(tmp_path, "Row Store", "Koyambedu", [
        draft("tomato", "தக்காளி", "40",
              photo="data/photos/tom_cut.jpg"),
        draft("onion", "வெங்காயம்", "35"),
    ])
    html = make_client(tmp_path).get(f"/s/{slug}").text
    assert html.count("<article") == 2
    assert html.count('class="ph') == 2
    assert html.count("data-add>") == 2
    assert 'src="/m/tom_cut.jpg"' in html
    assert "data-step" in html and "data-sizes" in html
    assert "cat-acc" in html  # category accordion, open by default
    assert "data-cart-bar" in html and "data-cart-view" in html
    assert "data-shopsearch-open" in html  # in-shop search sheet
    assert 'id="shopsearch-pop"' in html
    assert 'id="shop-q"' in html
    for hook in ("data-shop-grid", "data-price", "data-per",
                 "data-name-en", "data-customer-name",
                 "data-customer-phone"):
        assert hook in html, hook


def test_shop_rows_show_voice_link_only_when_clip_exists(tmp_path):
    import json as jsonmod

    from app import db

    slug, _token = seed_shop(tmp_path, "Clip Store", "Koyambedu", [
        draft("tomato", "தக்காளி", "40")])
    html = make_client(tmp_path).get(f"/s/{slug}").text
    assert "voice-link" not in html  # no clip file on disk
    # A clip file inside the data dir gets a voice link + route.
    data_dir = tmp_path / "data"
    clip = data_dir / "voice" / "clip.m4a"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"fake-audio")
    conn = db.connect(data_dir)
    try:
        shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                            (slug,)).fetchone()
        version_id = db.latest_version(conn, shop["id"],
                                       published_only=True)
        item = next(it for it in db.version_items(conn, version_id)
                    if it.name_en == "tomato")
        conn.execute(
            "UPDATE items SET proof = ? WHERE id = ?",
            (jsonmod.dumps({
                "quote": item.proof.quote, "turn_ids": [],
                "start_ms": 0, "end_ms": 0, "frame": None,
                "audio_clip": str(clip), "number_check": None,
                "source": None}), item.id))
        conn.commit()
        item_id = item.id
    finally:
        conn.close()
    html = make_client(tmp_path).get(f"/s/{slug}").text
    assert "voice-link" in html
    resp = make_client(tmp_path).get(f"/s/{slug}/voice/{item_id}")
    assert resp.status_code == 200
    assert client_missing_404(tmp_path, slug)


def client_missing_404(tmp_path, slug):
    return make_client(tmp_path).get(
        f"/s/{slug}/voice/999999").status_code == 404


# --- 7. market page -------------------------------------------------------------


def test_market_page_pill_tabs_and_filter_popup(tmp_path, monkeypatch):
    from decimal import Decimal

    from app.market.search import Query, Want

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = client.get("/market").text
    assert "mkt-pill" not in html  # no query, no pill
    assert 'class="hp-search"' in html  # classic form kept
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")
    html = client.get("/market", params={"q": "tomato"}).text
    assert "mkt-pill" in html  # query shown as a pill
    assert "data-search-open" in html
    assert "data-mtab" in html
    for key in ("v12.tab_basket", "v12.tab_shops", "v12.tab_items"):
        from app.web.i18n import t_for
        assert t_for("en")(key) in html, key
    assert "data-filter-open" in html
    assert 'id="filter-pop"' in html


def test_market_category_browse_and_items_sort(tmp_path, monkeypatch):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = client.get("/market", params={"cat": "fruit"}).text
    assert "banana" in html.lower()
    assert "Anna Fresh" in html or "Kannan Veg" in html
    # Items sort keeps basket + groups working.
    html = client.get("/market", params={"cat": "veg",
                                         "sort": "items"}).text
    assert "tomato" in html.lower() or "Tomato" in html


# --- 8. honesty: no invented ratings/reviews/times ------------------------------


def test_no_ratings_reviews_or_delivery_times_anywhere():
    static = ROOT / "app" / "web" / "static"
    files = [CSS, *sorted(CSS_DIR.glob("*.css")),
             *sorted(TEMPLATES.glob("*.html")),
             *sorted(static.glob("*.js"))]
    for path in files:
        lowered = path.read_text().lower()
        assert "rating" not in lowered, path.name
        assert "★" not in lowered, path.name
        assert "mins" not in lowered, path.name
        assert "reviews" not in lowered, path.name
