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


def _home_css():
    return APP_CSS.read_text().split("/* Task 84 homepage */")[1]


def _rule(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\}",
                      css, re.DOTALL)
    assert match, selector
    return match.group(1)


# --- 1. section rhythm --------------------------------------------------------


def test_section_rhythm_css():
    css = _home_css()
    assert ".home-mkt .content > section + section" in css
    assert "margin-top: 64px" in css
    phone = [block for block in
             re.split(r"@media\s*\(max-width:\s*600px\)", css)[1:]]
    joined = "\n".join(block.split("@media")[0] for block in phone)
    assert ".home-mkt .content > section + section" in joined
    assert "margin-top: 40px" in joined
    head = _rule(css, ".hp-sec-head")
    assert "margin-bottom: 16px" in head
    assert "flex-start" in head  # "… →" link sits on the title line
    assert "font-size: 26px" in _rule(css, ".hp-sec-head h2")
    assert "font-weight: 800" in _rule(css, ".hp-sec-head h2")


def test_sections_share_heading_block(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    t = t_for("en")
    html = _home(client, "en")
    for section, nxt, title, sub in (
            ("picks", "areas", "hp.picks_t", "hp.picks_sub"),
            ("areas", "shops", "hp.areas_t", "hp.areas_sub"),
            ("shops", "value", "hp.shops_t", "hp.shops_sub")):
        body = _section(html, section, nxt)
        assert 'class="hp-sec-head"' in body, section
        assert t(title) in htmlmod.unescape(body), section
        assert t(sub) in htmlmod.unescape(body), section
    picks = _section(html, "picks", "areas")
    assert t("hp.compare") in htmlmod.unescape(picks)


# --- 2. explore-by-market cards -----------------------------------------------


def test_all_areas_is_a_normal_card(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    areas = _section(html, "areas", "shops")
    t = t_for("en")
    assert "hp-reset" not in areas
    tiles = re.findall(r'<a class="area-tile( on)?" href="([^"]*)">(.*?)</a>',
                       areas, re.DOTALL)
    assert len(tiles) == 3, len(tiles)  # All areas + 2 markets
    all_cls, all_href, all_body = tiles[0]
    assert all_cls == " on"  # nothing picked: All areas is selected
    assert all_href == "/"
    assert t("hp.all_areas") in all_body
    assert "tile-ic" in all_body
    assert t("hp.area_counts", n=3, m=7) in all_body
    css = _home_css()
    grid = _rule(css, ".hp-area-grid")
    assert "repeat(auto-fill, minmax(200px, 1fr))" in grid


def test_selected_area_keeps_accent_border(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en", "?area=Koyambedu"))
    areas = _section(html, "areas", "shops")
    tiles = re.findall(r'<a class="area-tile( on)?" href="([^"]*)">(.*?)</a>',
                       areas, re.DOTALL)
    by_href = {href: (cls, body) for cls, href, body in tiles}
    assert by_href["/"][0] == ""  # All areas not selected now
    koy = [cls for cls, href, body in tiles if "Koyambedu" in body]
    assert koy == [" on"]
    css = _home_css()
    assert "border-color: var(--accent)" in _rule(css, ".area-tile.on")


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
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        html = htmlmod.unescape(_home(client, lang))
        areas = _section(html, "areas", "shops")
        assert t("hp.area_counts", n=1, m=1) in areas, lang
        assert t("hp.area_counts", n=2, m=6) in areas, lang
        shops = _section(html, "shops", "value")
        assert t("hp.prices_today", n=1) in shops, lang  # Anna Fresh
        assert t("hp.prices_today", n=4) in shops, lang  # Kannan Veg
    assert "1 shops" not in htmlmod.unescape(_home(client, "en"))
    assert "1 prices" not in htmlmod.unescape(_home(client, "en"))


# --- 4. product card shop line -------------------------------------------------


def test_shop_line_splits_name_and_area(tmp_path):
    seed_market(tmp_path)
    seed_shop(tmp_path, "Malar மலர் Veg", "Koyambedu", [
        draft("carrot", "கேரட்", "50")])
    client = make_client(tmp_path)
    html = _home(client, "en")
    picks = _section(html, "picks", "areas")
    assert "shop-line" not in picks
    names = re.findall(r'<p class="shop-name" lang="(\w+)">(.*?)</p>',
                       picks)
    assert names, "no shop-name lines"
    langs = {text: lang for lang, text in names}
    assert langs.get("Malar மலர் Veg") == "ta"
    assert langs.get("Kannan Veg") == "en"
    areas = re.findall(r'<p class="muted shop-area" lang="\w+">(.*?)</p>',
                       picks, re.DOTALL)
    assert areas, "no shop-area lines"
    assert "Koyambedu" in areas[0]


def test_shop_name_clamp_css():
    css = _home_css()
    assert "white-space: nowrap" not in css  # Tamil/Hindi never cut
    name = _rule(css, ".pick-card .shop-name")
    assert "-webkit-line-clamp: 1" in name
    assert "line-clamp: 1" in name
    assert "-webkit-line-clamp: 2" in css
    assert ".pick-card .shop-name:lang(ta)" in css
    assert ".pick-card .shop-name:lang(hi)" in css
    assert "margin-top: auto" in css  # actions pinned: even card heights
    assert "flex: 1" in _rule(css, ".pick-body,\n.shop-body")


# --- 5. empty-slot cards -------------------------------------------------------


def test_single_shop_gets_dashed_slot(tmp_path):
    from app.web.i18n import t_for

    seed_shop(tmp_path, "Solo Veg", "Koyambedu", [
        draft("tomato", "தக்காளி", "40")])
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        html = htmlmod.unescape(_home(client, lang))
        shops = _section(html, "shops", "value")
        assert shops.count('class="shop-card"') == 1, lang
        assert shops.count('class="shop-card hp-slot"') == 1, lang
        assert t("hp.slot_t") in shops, lang
        assert t("hp.start_selling") in shops, lang
        assert 'class="shop-card hp-slot" href="/new"' in shops, lang
        picks = _section(html, "picks", "areas")
        assert picks.count('class="pick-card hp-slot"') == 1, lang


def test_full_grids_and_empty_states_have_no_slot(tmp_path):
    seed_market(tmp_path)  # 7 picks, 3 shops
    client = make_client(tmp_path)
    html = _home(client, "en")
    assert "hp-slot" not in _section(html, "picks", "areas")
    shops = _section(html, "shops", "value")
    assert shops.count('class="shop-card hp-slot"') == 1
    client2 = make_client(tmp_path)
    html = _home(client2, "en", "?area=Nowhere")
    assert "hp-slot" not in _section(html, "picks", "areas")
    assert "hp-slot" not in _section(html, "shops", "value")


def test_slot_css_is_dashed():
    css = _home_css()
    slot = _rule(css, ".hp-slot")
    assert "dashed" in slot


# --- 6. hero overlay -----------------------------------------------------------


def test_hero_overlay_strengthened():
    css = _home_css()
    shade = _rule(css, ".hp-band-shade")
    assert "radial-gradient" in shade
    alphas = [float(a) for a in
              re.findall(r"rgba\(17,\s*17,\s*28,\s*([\d.]+)\)", shade)]
    assert alphas, "no overlay alpha values"
    assert max(alphas) >= 0.6, alphas
    assert "#fff" in _rule(css, ".hp-headline")
    assert "#fff" in _rule(css, ".hp-sub")
