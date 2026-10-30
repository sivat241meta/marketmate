"""Task 125: v12 polish + composer follow-ups.

1. Laptop header: nav labels never wrap, location ellipsizes, nav
   icons hide below ~1360px, sellers/how move into More below ~1180px.
2. Phone header: one row (mark, location, search, bag, menu).
3. Homepage promo banner carousel + slim count line.
4. Top-shops carousel borrows nearby shops when the area has < 4.
5. Shop-card avatar no longer covers the price line.
6. Sell band: no strike-through underline.
7. Search pop-up popular chips use item photos before letters.
8. Shop page selected quantity chips stay legible (white on teal).
9. Find-a-shop: one search (pill + filters + tabs, old form gone).
10. Composer: old recorder gone, Cancel left / Send right of wave.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from test_task84 import _home, draft, make_client, seed_market, seed_shop

from app.web.i18n import missing_keys, t_for

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
HOME_CSS = ROOT / "app" / "web" / "static" / "css" / "home.css"
PUBLIC_CSS = ROOT / "app" / "web" / "static" / "css" / "public.css"
HOME_JS = ROOT / "app" / "web" / "static" / "home.js"
MOTION_JS = ROOT / "app" / "web" / "static" / "motion.js"
POPUPS_JS = ROOT / "app" / "web" / "static" / "popups.js"
PUBLIC_JS = ROOT / "app" / "web" / "static" / "public.js"
COMPOSER_HTML = ROOT / "app" / "web" / "templates" / "_composer.html"


def _header(html):
    return re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)


def _luminance(code):
    rgb = [int(code[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def channel(value):
        return (value / 12.92 if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4)

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(fore, back):
    lighter = max(_luminance(fore), _luminance(back))
    darker = min(_luminance(fore), _luminance(back))
    return (lighter + 0.05) / (darker + 0.05)


def _media_block(css, query, occurrence=1):
    parts = css.split(query)
    assert len(parts) > occurrence, query
    return parts[occurrence].split("@media", 1)[0]


# --- 1. laptop header -------------------------------------------------------


def test_nav_labels_nowrap_and_location_ellipsis_css():
    css = APP_CSS.read_text()
    # Above the Task 84 marker (which forbids nowrap below it).
    base = css.split("/* Task 84 homepage */")[0]
    assert ".hp-nav a > span" in base
    assert "white-space: nowrap" in base.split(
        ".hp-nav a > span")[1].split("}")[0]
    assert ".loc-txt" in base
    loc = re.search(r"\.loc-txt \{\s*display: block;([^}]*)\}", css)
    assert loc, ".loc-txt ellipsis rule"
    assert "text-overflow: ellipsis" in loc.group(1)
    assert "overflow: hidden" in loc.group(1)
    btn = css.split(".loc-btn {")[1].split("}")[0]
    assert "max-width" in btn


def test_nav_icons_hide_below_1360_and_more_below_1180():
    css = APP_CSS.read_text()
    small = _media_block(css, "@media (max-width: 1360px)")
    assert ".hp-nav > a > .obj" in small
    assert "display: none" in small
    more = _media_block(css, "@media (max-width: 1180px)")
    assert ".hp-nav a.nav-extra" in more
    assert "display: none" in more
    assert ".hp-nav .nav-more" in more
    assert "display: block" in more
    # The dropdown animates like the rest of the nav.
    menu = css.split(".nav-more-menu {")[1].split("}")[0]
    assert "transition" in menu
    assert "transform" in menu


def test_header_more_dropdown_markup_and_pill(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    head = _header(html)
    assert "data-nav-more-btn" in head
    assert 'aria-expanded="false"' in head
    assert t_for("en")("nav.more") in head
    assert head.count("data-nav-more-link") == 2
    assert head.count("nav-pill") == 1
    js = MOTION_JS.read_text()
    assert "data-nav-more-btn" in js
    assert "slidePill" in js
    assert "nav-pill" in js
    popups = POPUPS_JS.read_text()
    assert "data-nav-more-btn" in popups
    assert "aria-expanded" in popups


# --- 2. one-row phone header -------------------------------------------------


def test_phone_header_one_row_markup_and_css(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    head = _header(html)
    assert "brand-mark-sm" in head
    assert "brand-logo" in head
    order = ["class=\"logo\"", "loc-btn", "hp-search-btn", "hp-bag",
             "hp-menu-btn"]
    positions = [head.index(needle) for needle in order]
    assert positions == sorted(positions)
    css = APP_CSS.read_text()
    phone = _media_block(css, "@media (max-width: 430px)", occurrence=2)
    assert ".hp-header .brand-logo" in phone
    assert ".hp-header .brand-mark-sm" in phone
    assert "display: none" in phone
    assert "display: block" in phone
    assert "flex-wrap: nowrap" in phone
    assert "flex-wrap: wrap" not in phone
    assert ".hp-header .hp-bag" in phone
    assert "min-height: 44px" in phone
    pub = PUBLIC_CSS.read_text()
    pub_phone = _media_block(pub, "@media (max-width: 420px)")
    assert "flex-wrap: nowrap" in pub_phone
    assert "flex-wrap: wrap" not in pub_phone


# --- 3. promo banner + slim counts -------------------------------------------


def _promo(html):
    return html.split('id="promo"')[1].split('id="mind"')[0]


def test_banner_slides_links_and_photos(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    assert html.index('id="promo"') < html.index('id="mind"')
    promo = _promo(html)
    assert promo.count("promo-slide") >= 3
    t = t_for("en")
    assert t("v12.banner_prices_near") in promo
    assert t("v12.banner_voice") in promo
    assert t("v12.banner_sell") in promo
    assert 'href="/market"' in promo
    assert 'href="/new"' in promo
    assert "data-search-open" in promo
    assert "data-search-voice" in promo
    for photo in ("street-market-800.jpg", "customer-phone-800.jpg",
                  "seller-phone-800.jpg"):
        assert photo in promo, photo
        assert (ROOT / "app" / "web" / "static" / "landing"
                / photo).exists()
    assert "data-prev" in promo and "data-next" in promo
    assert "data-dots" in promo
    assert "data-carousel" in promo


def test_banner_area_slide_names_area(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en", "?area=Koyambedu")
    promo = _promo(html)
    assert t_for("en")("v12.banner_prices", area="Koyambedu") in promo
    assert 'href="/market?area=Koyambedu"' in promo


def test_banner_autoadvance_js_and_reduced_motion():
    src = HOME_JS.read_text()
    assert "initBanner" in src
    assert "data-banner" in src
    assert "setInterval" in src and "5000" in src
    for event in ("mouseenter", "mouseleave", "focusin", "focusout"):
        assert event in src, event
    assert "prefers-reduced-motion" in src
    css = HOME_CSS.read_text()
    assert ".promo-1" in css and "linear-gradient" in css
    assert ".promo-2" in css and ".promo-3" in css
    reduced = css.split("prefers-reduced-motion: reduce", 1)[1]
    assert "promo-track" in reduced
    # White slide text passes 4.5:1 on every gradient stop.
    stops = re.findall(r"\.promo-[123]\s*\{[^}]*?\}", css)
    assert len(stops) == 3
    for stop in stops:
        for code in re.findall(r"#[0-9a-fA-F]{6}", stop):
            assert _contrast("#FFFFFF", code) >= 4.5, code


def test_count_slim_line_keeps_numbers(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    assert "hp-count-line" in html
    assert "hp-counter" not in html
    assert 'data-count="3"' in html
    assert 'data-count="7"' in html
    assert 'data-count="2"' in html
    css = HOME_CSS.read_text()
    assert ".hp-count-line > span + span::before" in css
    assert 'content: "·"' in css


def test_banner_and_counts_all_langs(tmp_path):
    assert missing_keys() == {"ta": [], "hi": []}
    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        t = t_for(lang)
        promo = _promo(html)
        for key in ("v12.banner_prices_near", "v12.banner_voice",
                    "v12.banner_sell"):
            assert t(key) in promo, (lang, key)


# --- 4. top-shops fallback ----------------------------------------------------


def _seed_sparse(tmp_path):
    seed_shop(tmp_path, "Koyam Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "40")],
              lat=13.070, lng=80.290)
    seed_shop(tmp_path, "Near Fresh", "Nearville",
              [draft("onion", "வெங்காயம்", "35")],
              lat=13.071, lng=80.291)
    seed_shop(tmp_path, "Far Fresh", "Farville",
              [draft("potato", "உருளை", "30")],
              lat=13.500, lng=80.000)


def _top(html):
    return html.split('id="top-shops"')[1].split('id="shops"')[0]


def test_top_shops_borrow_nearby_when_sparse(tmp_path):
    _seed_sparse(tmp_path)
    html = _home(make_client(tmp_path), "en", "?area=Koyambedu")
    top = _top(html)
    t = t_for("en")
    assert t("v12.top_t_near", area="Koyambedu") in top
    assert top.count('class="shop-cover"') == 3
    for name in ("Koyam Veg", "Near Fresh", "Far Fresh"):
        assert name in top, name
    # Area shops first, then closest borrowed shop first.
    assert top.index("Koyam Veg") < top.index("Near Fresh")
    assert top.index("Near Fresh") < top.index("Far Fresh")
    # The grid below stays scoped to the picked area.
    grid = html.split('id="shops"')[1].split('id="best-prices"')[0]
    assert "Koyam Veg" in grid
    assert "Near Fresh" not in grid


def test_top_shops_plain_heading_when_full(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    top = _top(html)
    assert "and nearby markets" not in top
    assert t_for("en")("v12.top_t_all") in top


def test_top_shops_hidden_when_empty(tmp_path):
    _seed_sparse(tmp_path)
    client = make_client(tmp_path)
    html = client.get("/?area=Nowhere").text
    assert 'class="top-row"' not in html
    bare = _home(make_client(tmp_path / "fresh"), "en")
    assert 'class="top-row"' not in bare


# --- 5 + 6. avatar + sell band -------------------------------------------------


def test_shop_avatar_below_photo():
    css = HOME_CSS.read_text()
    rule = css.split(".shop-ava {")[1].split("}")[0]
    margin = re.search(r"margin:\s*([^;]+);", rule)
    assert margin, rule
    assert "-" not in margin.group(1), margin.group(1)
    top = re.search(r"([-\d.]+)px", margin.group(1))
    assert top and float(top.group(1)) >= 0


def test_sell_band_has_no_strike_through(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    sell = html.split('id="sell"')[1].split('id="meta"')[0]
    assert "hlshine" not in sell
    t = t_for("en")
    assert t("v12.sell_t") in sell
    assert t("v12.sell_d") in sell


# --- 7. popular photos ----------------------------------------------------------


def _seed_photo_items(tmp_path):
    names = ["tomato", "potato", "peas", "onion", "greens", "garlic",
             "drumstick", "cauliflower", "carrot", "cabbage", "banana",
             "apple"]
    seed_shop(tmp_path, "Photo Veg", "Koyambedu",
              [draft(name, name, "10",
                     photo=f"data/photos/{name}_orig.jpg")
               for name in names])


def test_popular_chips_use_item_photos(tmp_path):
    _seed_photo_items(tmp_path)
    html = _home(make_client(tmp_path), "en")
    pop = html.split('id="search-pop"')[1].split('id="filter-pop"')[0]
    grid = pop.split("mm-pop-grid")[1]
    assert grid.count("<img") == 6
    assert "nophoto" not in grid
    for name in ("cabbage", "cauliflower", "drumstick"):
        assert f"/m/{name}_orig.jpg" in grid, name


def test_popular_chip_letter_fallback_without_photo(tmp_path):
    seed_shop(tmp_path, "Plain Veg", "Koyambedu",
              [draft("greens", "கீரை", "20")])
    html = _home(make_client(tmp_path), "en")
    pop = html.split('id="search-pop"')[1].split('id="filter-pop"')[0]
    assert "nophoto" in pop


# --- 8. selected chip contrast ---------------------------------------------------


def test_selected_chip_white_on_teal():
    css = PUBLIC_CSS.read_text()
    rule = css.split("body.pub .shop-rows .card .sz.on {")[1].split(
        "}")[0]
    assert "background: #0f766e" in rule
    assert "color: #fff" in rule
    assert _contrast("#FFFFFF", "#0F766E") >= 4.5


def test_shop_page_renders_selected_chip(tmp_path):
    slug, _token = seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "40")])
    html = make_client(tmp_path).get(f"/s/{slug}").text
    assert 'class="sz on"' in html


# --- 9. one search on Find-a-shop -------------------------------------------------


def test_market_has_no_second_search_form(tmp_path):
    seed_market(tmp_path)
    html = make_client(tmp_path).get("/market").text
    assert 'class="hp-search"' not in html
    assert 'id="search"' not in html
    assert "hp-tab" not in html
    assert 'id="market-q"' not in html
    assert 'id="market-area"' not in html
    assert 'id="market-budget"' not in html
    # The query pill is always there and opens the search pop-up.
    assert "mkt-pill" in html
    assert "data-search-open" in html
    # Filters live in the filter pop-up.
    filt = html.split('id="filter-pop"')[1]
    for field in ('name="area"', 'name="budget"', 'name="open_now"',
                  'name="sort"'):
        assert field in filt, field


def test_market_tabs_and_area_chips_after_search(tmp_path, monkeypatch):
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
    html = client.get("/market", params={"q": "tomato"}).text
    assert "mkt-pill" in html and "tomato" in html
    assert html.count("data-mtab=") == 3
    assert "data-filter-open" in html
    assert "filter-row" in html  # area quick filters stay
    assert 'id="market-voice"' in html
    assert "data-composer" in html


# --- 10. one mic + composer button order --------------------------------------------


def _seller_client(tmp_path):
    from fastapi.testclient import TestClient

    from app import db
    from app.config import load_settings
    from app.web.main import create_app

    data = tmp_path / "data"
    conn = db.connect(data)
    try:
        _sid, _slug, token = db.create_shop(
            conn, name="T125 Store", phone="+914400001251",
            area="Koyambedu", language="ta", currency="INR",
            shop_type="vegetable", listed=True)
    finally:
        conn.close()
    return TestClient(create_app(load_settings(
        {"MODEL_API_KEY": "k", "DATA_DIR": str(data)})),
        follow_redirects=False), token


def test_quote_page_has_one_recorder(tmp_path):
    slug, _token = seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "40")])
    html = make_client(tmp_path).get(f"/s/{slug}/quote").text
    for gone in ("data-live-order", "live-order.js", "mic-btn",
                 "quote-name-voice", "quote-phone-voice"):
        assert gone not in html, gone
    assert "data-composer" in html
    assert "quote-name-speak" in html


def test_bills_page_has_one_recorder(tmp_path):
    client, token = _seller_client(tmp_path)
    html = client.get(f"/e/{token}/bills/new").text
    for gone in ("data-live-order", "live-order.js", "mic-btn"):
        assert gone not in html, gone
    assert "data-composer" in html
    assert "composer.js" in html


def test_composer_cancel_left_send_right_of_wave():
    html = COMPOSER_HTML.read_text()
    assert (html.index("data-composer-cancel")
            < html.index("data-composer-wave")
            < html.index("data-composer-send"))
    cancel = next(line for line in html.splitlines()
                  if "data-composer-cancel" in line)
    assert "hidden" in cancel


def test_touched_js_syntax():
    node = shutil.which("node")
    assert node, "node is required for --check"
    for path in (HOME_JS, MOTION_JS, POPUPS_JS, PUBLIC_JS):
        result = subprocess.run([node, "--check", str(path)],
                                check=False, capture_output=True,
                                text=True)
        assert result.returncode == 0, (path.name, result.stderr)
