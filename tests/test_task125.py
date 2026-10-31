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
    # Task 127: v13 nav links never wrap; the location mini button
    # ellipsizes instead of pushing the header wide.
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    nav = css.split("body.v13 .nav a{")[1].split("}")[0]
    assert "white-space:nowrap" in nav.replace(" ", "")
    loc = css.split("body.v13 .loc-mini b{")[1].split("}")[0]
    assert "text-overflow:ellipsis" in loc.replace(" ", "")
    assert "overflow:hidden" in loc.replace(" ", "")
    btn = css.split("body.v13 .loc-mini{")[1].split("}")[0]
    assert "max-width" in btn


def test_nav_icons_hide_below_1360_and_more_below_1180():
    # Task 127: v13 narrows in two steps — the outline button goes
    # below 1280px, the nav links collapse into the menu at 1100px.
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    narrow = _media_block(css, "@media (max-width:1280px)")
    assert ".btn-outline-w" in narrow
    assert "display:none" in narrow.replace(" ", "")
    menu = _media_block(css, "@media (max-width:1100px)")
    assert ".topbar .nav" in menu
    assert "display:none" in menu.replace(" ", "")
    assert ".menu-btn" in menu
    assert "display:grid" in menu.replace(" ", "")


def test_header_more_dropdown_markup_and_pill(tmp_path):
    # Task 127: no More dropdown — narrow screens get the menu
    # sheet with the same five links plus language + selling.
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    head = _header(html)
    assert "data-menu-open" in head
    assert 'aria-expanded="false"' in head
    sheet = html.split('id="mobile-nav"')[1].split("</nav>")[0]
    for href in ("/market", "#lowest", "#markets", "/sellers", "/how",
                 "/new"):
        assert f'href="{href}"' in sheet, href
    assert "data-ui-toggle" in sheet
    popups = POPUPS_JS.read_text()
    assert "data-menu-open" in popups
    assert "mobile-nav" in popups
    assert "aria-expanded" in popups


# --- 2. one-row phone header -------------------------------------------------


def test_phone_header_one_row_markup_and_css(tmp_path):
    # Task 127: one row — mark, flexing location, search, bag,
    # menu; the wordmark drops under 430px, EN into the menu.
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    head = _header(html)
    assert 'class="mk"' in head
    assert "brand-word" in head
    order = ["brand dark", "loc-mini", "hp-search-btn", "hp-bag",
             "hp-menu-btn"]
    positions = [head.index(needle) for needle in order]
    assert positions == sorted(positions)
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    phone = _media_block(css, "@media (max-width:700px)")
    assert ".stickybar .top-actions .lang" in phone
    assert "display:none" in phone.replace(" ", "")
    flat = phone.replace(" ", "")
    assert ".loc-mini" in phone and "flex:1" in flat
    assert "min-width:0" in flat
    narrow = _media_block(css, "@media (max-width:430px)")
    assert ".stickybar .brand-word" in narrow


# --- 3. promo banner + slim counts -------------------------------------------


def _promo(html):
    # Task 127: the promo carousel is gone; the hero service cards
    # are its replacement (find / voice / sell).
    return html.split('class="svc-row"')[1].split("</section>")[0]


def test_banner_slides_links_and_photos(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    assert 'id="promo"' not in html
    assert "promo-slide" not in html
    assert html.index('class="svc-row"') < html.index('id="fresh"')
    promo = _promo(html)
    t = t_for("en")
    assert t("v13.svc_find_t") in promo
    assert t("v13.svc_voice_t") in promo
    assert t("v13.svc_sell_t") in promo
    assert 'href="/market"' in promo
    assert 'href="/new"' in promo
    assert "data-search-open" in promo
    assert "data-search-voice" in promo
    # Decorative art is transparent cut-outs, never photo squares.
    assert "/static/img/v13/" in promo
    assert "landing/" not in promo


def test_banner_area_slide_names_area(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en", "?area=Koyambedu")
    assert "Koyambedu" in html.split('class="loc-input"')[1].split(
        "</button>")[0]
    assert 'href="/market?area=Koyambedu"' in html


def test_banner_autoadvance_js_and_reduced_motion():
    # Task 127: no auto-advancing carousel — the hero floats bob
    # via CSS, frozen under reduced motion.
    src = HOME_JS.read_text()
    assert "initBanner" not in src
    assert "setInterval" not in src
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    assert "@keyframes bob13" in css
    assert ".hero-float" in css and "animation:bob13" in css.replace(" ", "")
    assert "prefers-reduced-motion" in css
    motion = (ROOT / "app" / "web" / "static" / "css"
              / "motion.css").read_text()
    reduced = motion.split("prefers-reduced-motion", 1)[1]
    assert "animation:none" in reduced.replace(" ", "")
    # White 46px/800 display type passes the 3:1 large-text
    # floor on every gradient stop (body text keeps 4.5:1).
    hero = re.search(r"--hero:linear-gradient\(([^;]+);", css).group(1)
    stops = re.findall(r"#[0-9a-fA-F]{6}", hero)
    assert len(stops) >= 2
    for code in stops:
        assert _contrast("#FFFFFF", code) >= 3.0, code


def test_count_slim_line_keeps_numbers(tmp_path):
    # Task 127: the count line is gone; the find-a-shop card pill
    # carries the real total (7 price lines in the seed market).
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    assert "hp-count-line" not in html
    assert "hp-counter" not in html
    assert "7 PRICES TODAY" in html


def test_banner_and_counts_all_langs(tmp_path):
    assert missing_keys() == {"ta": [], "hi": []}
    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        t = t_for(lang)
        promo = _promo(html)
        for key in ("v13.svc_find_t", "v13.svc_voice_t",
                    "v13.svc_sell_t"):
            assert t(key) in promo, (lang, key)
        assert t("v13.svc_find_p", n=7) in promo, lang


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
    # Task 127: one shops row borrows nearby shops when sparse.
    return html.split('id="shops"')[1].split('id="lowest"')[0]


def test_top_shops_borrow_nearby_when_sparse(tmp_path):
    _seed_sparse(tmp_path)
    html = _home(make_client(tmp_path), "en", "?area=Koyambedu")
    top = _top(html)
    t = t_for("en")
    assert t("v13.shops_t_area", area="Koyambedu") in top
    assert top.count('class="shop-photo"') == 3
    for name in ("Koyam Veg", "Near Fresh", "Far Fresh"):
        assert name in top, name
    # Area shops first, then closest borrowed shop first.
    assert top.index("Koyam Veg") < top.index("Near Fresh")
    assert top.index("Near Fresh") < top.index("Far Fresh")


def test_top_shops_plain_heading_when_full(tmp_path):
    import html as htmlmod

    seed_market(tmp_path)
    html = htmlmod.unescape(_home(make_client(tmp_path), "en"))
    top = _top(html)
    assert "and nearby markets" not in top
    assert t_for("en")("v13.shops_t_all") in top


def test_top_shops_hidden_when_empty(tmp_path):
    _seed_sparse(tmp_path)
    client = make_client(tmp_path)
    html = client.get("/?area=Nowhere").text
    assert 'class="top-row"' not in html
    bare = _home(make_client(tmp_path / "fresh"), "en")
    assert 'class="top-row"' not in bare


# --- 5 + 6. avatar + sell band -------------------------------------------------


def test_shop_avatar_below_photo():
    # Task 127: no avatar — the shop name sits on the photo bottom
    # and can never cover the meta rows below it.
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    rule = css.split("body.v13 .shop-name{")[1].split("}")[0]
    flat = rule.replace(" ", "")
    assert "position:absolute" in flat
    assert "bottom:10px" in flat
    assert "left:12px" in flat and "right:12px" in flat


def test_sell_band_has_no_strike_through(tmp_path):
    # Task 127: the sell band left the homepage; v13 links carry
    # no underline or strike-through anywhere.
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    assert 'id="sell"' not in html
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    assert "line-through" not in css
    assert "a{color:inherit;text-decoration:none}" in css.replace(" ", "")


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
    # Task 127: selected quantity chips are teal-ink on teal-soft
    # (legible at 4.5:1, same as the old white-on-teal).
    css = (ROOT / "app" / "web" / "static" / "css"
           / "shop13.css").read_text()
    rule = css.split("body.v13 .q.on{")[1].split("}")[0]
    flat = rule.replace(" ", "")
    assert "background:var(--teal-soft)" in flat
    assert "color:var(--teal-ink)" in flat
    assert _contrast("#115E59", "#E6FAF6") >= 4.5


def test_shop_page_renders_selected_chip(tmp_path):
    slug, _token = seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "40")])
    html = make_client(tmp_path).get(f"/s/{slug}").text
    assert 'class="q sz on"' in html


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
    assert "mkt-chips" in html  # area quick filters stay
    assert "data-open-all" in html
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
