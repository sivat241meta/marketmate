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

# Task 127: v13 homepage section order.
SECTIONS = ("hero", "fresh", "cats", "shops", "lowest", "how", "app",
            "markets")


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
    # Task 127: v13 drops the sliding nav-pill for a grow-from-left
    # underline; the sticky bar slides in via an .on class.
    v13 = (CSS_DIR / "v13.css").read_text()
    assert ".nav a::after" in v13
    assert ".stickybar.on" in v13.replace(" ", "")
    assert 'toggle("on"' in HOME_JS.read_text()


def test_header_animation_css_and_reduced_motion():
    # Task 127: grow-from-left nav underline, sliding sticky bar,
    # hero bob + card pops — all off under reduced motion.
    v13 = (CSS_DIR / "v13.css").read_text()
    assert ".nav a::after" in v13  # grow-from-left underline
    assert ".stickybar" in v13 and "translateY(-110%)" in v13
    assert "@keyframes bob13" in v13
    assert "@keyframes pop13" in v13
    assert "prefers-reduced-motion" in v13
    motion = (CSS_DIR / "motion.css").read_text()
    assert "prefers-reduced-motion: reduce" in motion


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
    # Openers live in the header / page (the Filters opener
    # lives on /market, which also carries the count badge).
    assert "data-loc-open" in html
    assert "data-search-open" in html
    market = client.get("/market").text
    assert "data-filter-open" in market
    assert "data-filter-count" in market
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
    # Task 124: the voice button reveals the voice+text composer posting
    # to the same /market/voice action as the Find-a-shop voice panel.
    assert "data-voice-toggle" in pop  # voice button
    assert 'aria-controls="search-voice"' in pop
    assert 'id="search-voice"' in pop
    assert "data-composer" in pop
    assert 'action="/market/voice"' in pop
    assert 'data-text-field="q"' in pop
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
    # Task 127: v13 fresh/categories/shops/lowest scrollers with
    # real links, carousel arrows and honest badges.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    fresh = _section(html, "fresh", "cats")
    assert t("v13.fresh_t") in fresh
    assert "/market?q=tomato" in fresh
    assert "data-carousel" in fresh and "data-prev" in fresh
    cats = _section(html, "cats", "shops")
    assert t("v13.cats_t") in cats
    assert "/market?cat=" in cats
    shops = _section(html, "shops", "lowest")
    assert "Kannan Veg" in shops
    assert 'class="shop-photo"' in shops
    lowest = _section(html, "lowest", "how")
    assert t("v13.lowest_t") in lowest
    # ADD on every item tile links into the shop page row.
    assert 'class="add" href="/s/kannan-veg"' in lowest
    markets = _section(html, "markets")
    assert t("v13.markets_t") in markets
    assert "link-grid" in markets


def test_sell_meta_install_bands_and_footer(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    # Task 127: the sell bands moved to /sellers; the homepage
    # keeps the Meta model cards, the QR app band and the footer.
    assert 'id="sell"' not in html
    how = _section(html, "how", "app")
    for model in ("muse-voice-transcribe-1.0", "muse-spark-1.3",
                  "sam-3.1"):
        assert model in how, model
    assert 'href="/how"' in how
    app = _section(html, "app", "markets")
    assert 'src="/app-qr.png"' in app
    assert "App Store" not in app
    footer = html.split('class="foot"')[1]
    for key in ("v13.col_market", "v13.col_sell", "v13.col_help",
                "v13.col_avail", "v13.col_lang"):
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
    assert html.count('class="pic"') == 2
    assert html.count('class="add-pill" data-add') == 2
    # Task 127: tomato matches a v13 cut-out, so the row shows the
    # transparent cut-out instead of its own photo.
    assert 'src="/static/img/v13/tomato.webp"' in html
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
    # Task 125: one search — the pill is always visible (it opens the
    # search pop-up) and the classic second form is gone.
    assert "mkt-pill" in html
    assert 'class="hp-search"' not in html
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
