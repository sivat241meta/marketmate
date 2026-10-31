"""Task 86: homepage polish (rhythm, market cards, plurals, shop line, slots, overlay)."""

from __future__ import annotations

import html as htmlmod
import re
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
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"


def _home_css():
    return APP_CSS.read_text().split("/* Task 84 homepage */")[1]


def _v13_css():
    return V13_CSS.read_text()


def _rule(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\}",
                      css, re.DOTALL)
    assert match, selector
    return match.group(1)


# --- 1. section rhythm --------------------------------------------------------


def test_section_rhythm_css():
    # Task 127: v13 section rhythm — 64px gaps, 40px on phones,
    # shared 24px/800 section headings with top-right arrows.
    css = _v13_css()
    flat = css.replace(" ", "")
    assert "body.v13.sec{padding-top:64px}" in flat
    phone = css.split("@media (max-width:700px)", 1)[1].split("@media")[0]
    assert ".sec" in phone and "padding-top:40px" in phone.replace(" ", "")
    head = _rule(css, "body.v13 .sec-head h3")
    assert "font-size:24px" in head.replace(" ", "")
    assert "font-weight:800" in head.replace(" ", "")


def test_sections_share_heading_block(tmp_path):
    # Task 127: every v13 scroller section shares the sec-head
    # block (title + top-right arrows).
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    t = t_for("en")
    html = _home(client, "en")
    for section, nxt, title in (
            ("fresh", "cats", "v13.fresh_t"),
            ("cats", "shops", "v13.cats_t"),
            ("shops", "lowest", "v13.shops_t_all"),
            ("lowest", "how", "v13.lowest_t")):
        body = _section(html, section, nxt)
        assert "sec-head" in body, section
        assert t(title) in htmlmod.unescape(body), section
        assert 'class="arrows"' in body, section


# --- 2. explore-by-market cards -----------------------------------------------


def test_markets_link_grid_and_all_areas_chip(tmp_path):
    # Task 127: the homepage markets section is a bordered link
    # grid (one link per market with prices); area picking lives
    # on /market quick chips with All areas selected by default.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    t = t_for("en")
    html = htmlmod.unescape(_home(client, "en"))
    markets = _section(html, "markets")
    assert "link-grid" in markets
    assert t("v13.fresh_in", market="Koyambedu") in markets
    assert t("v13.fresh_in", market="Anna Nagar") in markets
    chips = client.get("/market").text
    all_chip = re.search(r'<a class="chip( on)?" href="/market[^"]*"'
                         r" data-open-all>", chips)
    assert all_chip and all_chip.group(1) == " on"
    css = _v13_css()
    assert "repeat(4,1fr)" in _rule(
        css, "body.v13 .link-grid").replace(" ", "")


def test_selected_area_keeps_accent_border(tmp_path):
    # Task 127: the picked market chip stays teal-selected.
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(client.get("/market?area=Koyambedu").text)
    chips = re.findall(r'<a class="chip( on)?" href="[^"]*"'
                       r" data-open-(?:all|area)>", html)
    assert chips, "no area chips"
    koy = re.search(r'<a class="chip( on)?" href="/market\?[^"]*'
                    r"area=Koyambedu", html)
    assert koy and koy.group(1) == " on"
    css = _v13_css()
    on = _rule(css, "body.v13 .chip.on").replace(" ", "")
    assert "background:var(--teal-soft)" in on
    assert "border-color:var(--teal)" in on


# --- 3. plurals ---------------------------------------------------------------


def test_plural_forms_zero_one_two():
    from app.web.i18n import t_for

    expected = {
        "en": (("shop", "shops"), ("price", "prices"),
               ("order", "orders")),
        "ta": (("கடை", "கடைகள்"), ("விலை", "விலைகள்"),
               ("ஆர்டர்", "ஆர்டர்கள்")),
        "hi": (("दुकान", "दुकानें"), ("कीमत", "कीमतें"),
               ("ऑर्डर", "ऑर्डर")),
    }
    for lang, (shop, price, order) in expected.items():
        t = t_for(lang)
        for key, (one, other) in (("hp.shop", shop), ("hp.price", price),
                                  ("hp.order", order)):
            assert t(key, count=0) == other, (lang, key, 0)
            assert t(key, count=1) == one, (lang, key, 1)
            assert t(key, count=2) == other, (lang, key, 2)


def test_rendered_counts_use_plurals(tmp_path):
    # Task 127: the v13 shop cards pluralize "N prices today".
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        html = htmlmod.unescape(_home(client, lang))
        shops = _section(html, "shops", "lowest")
        assert t("hp.prices_today", n=1) in shops, lang  # Anna Fresh
        assert t("hp.prices_today", n=4) in shops, lang  # Kannan Veg
    assert "1 shops" not in htmlmod.unescape(_home(client, "en"))
    assert "1 prices" not in htmlmod.unescape(_home(client, "en"))


# --- 4. product card shop line -------------------------------------------------


def test_shop_line_splits_name_and_area(tmp_path):
    # Task 127: the v13 photo card keeps the shop name on the photo
    # and the area in its own meta row below.
    seed_market(tmp_path)
    seed_shop(tmp_path, "Malar மலர் Veg", "Koyambedu", [
        draft("carrot", "கேரட்", "50")])
    client = make_client(tmp_path)
    html = _home(client, "en")
    shops = _section(html, "shops", "lowest")
    assert "shop-line" not in shops
    assert '<b class="shop-name">Malar மலர் Veg</b>' in shops
    assert '<b class="shop-name">Kannan Veg</b>' in shops
    metas = re.findall(r'<span class="shop-meta">(.*?)</span>', shops,
                       re.DOTALL)
    assert metas, "no shop-meta rows"
    assert any("Koyambedu" in meta for meta in metas)


def test_shop_name_clamp_css():
    # Task 127: card body text wraps (Tamil/Hindi never cut); only
    # the photo-overlay shop name ellipsizes.
    css = _v13_css()
    assert "overflow-wrap:break-word" in css.replace(" ", "")
    name = _rule(css, "body.v13 .shop-name").replace(" ", "")
    assert "text-overflow:ellipsis" in name
    assert "white-space:nowrap" in name


# --- 5. empty-slot cards -------------------------------------------------------


def test_single_shop_renders_without_filler(tmp_path):
    # Task 127: v13 scrollers show real shops only — no filler slot.
    seed_shop(tmp_path, "Solo Veg", "Koyambedu", [
        draft("tomato", "தக்காளி", "40")])
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = htmlmod.unescape(_home(client, lang))
        shops = _section(html, "shops", "lowest")
        assert shops.count('class="shop"') == 1, lang
        assert "hp-slot" not in shops, lang
        lowest = _section(html, "lowest", "how")
        assert "hp-slot" not in lowest, lang


def test_full_grids_and_empty_states_have_no_slot(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    assert "hp-slot" not in _section(html, "lowest", "how")
    shops = _section(html, "shops", "lowest")
    assert 'class="shop"' in shops
    assert "hp-slot" not in shops
    client2 = make_client(tmp_path)
    html = _home(client2, "en", "?area=Nowhere")
    assert "hp-slot" not in _section(html, "lowest", "how")
    assert "hp-slot" not in _section(html, "shops", "lowest")


def test_scroller_css_scrolls_x():
    # Task 127: v13 rows scroll horizontally with snap + no bar.
    css = _v13_css()
    slot = _rule(css, "body.v13 .scroller").replace(" ", "")
    assert "overflow-x:auto" in slot
    assert "scroll-snap-type:xmandatory" in slot
    assert "scrollbar-width:none" in slot


# --- 6. hero overlay -----------------------------------------------------------


def test_hero_gradient_band():
    # Task 127: the v13 hero is a teal→blue gradient band with a
    # white headline (no photo overlay anymore).
    css = _v13_css()
    flat = css.replace(" ", "")
    assert "--hero:linear-gradient(118deg,#0B6F67" in flat
    assert "background:var(--hero)" in _rule(
        css, "body.v13 .hero").replace(" ", "")
    head = _rule(css, "body.v13 .hero h1").replace(" ", "")
    assert "color:#fff" in head
    assert "font-weight:800" in head
