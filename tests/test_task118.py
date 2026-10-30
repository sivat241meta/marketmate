"""Task 118: v11 polish — phone header, install-band contrast, one
footer, uncropped cut-outs, Meta cards, sparkles, hero credit,
area-tile pin fallback.

Keeps every Task 84/86/115 hook (routes, ids, data-* attrs, i18n
keys); new behaviour is asserted here, not by changing old tests.
"""

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
from test_task115 import _contrast

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
HOME_CSS = ROOT / "app" / "web" / "static" / "css" / "home.css"
HOME_HTML = ROOT / "app" / "web" / "templates" / "home.html"

OPEN_SENTENCE = ("the same text steps can run on Meta's open-weight "
                 "Muse Spark Open via Baseten when a key is set.")


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


# --- 1. phone header: sell pill on one line, badge hidden <=430px ---


def test_sell_pill_never_wraps_or_breaks_words():
    base = APP_CSS.read_text().split("/* Task 84 homepage */")[0]
    rule = _rule(base, ".hp-sell,\n.hp-sell .free-badge")
    assert "white-space: nowrap" in rule
    small = base.split("@media (max-width: 430px)", 1)[1]
    small = small.split("@media", 1)[0]
    assert ".hp-sell .free-badge" in small
    assert "display: none" in small
    # Task 125: one row — the header never wraps; the location
    # button ellipsizes so logo + pill + menu fit 320px.
    assert "flex-wrap: nowrap" in small
    assert "flex-wrap: wrap" not in small
    assert ".home-mkt .hp-sell" in small


def test_sell_links_in_menu_and_sell_band(tmp_path):
    # Task 122: the header sell pill moved to the phone menu; the
    # sell band keeps a big Start selling CTA.
    client = make_client(tmp_path)
    html = _home(client, "en")
    menu = html.split('id="mobile-nav"')[1]
    assert 'href="/new"' in menu
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    assert "For sellers" in head
    sell = _section(html, "sell", "meta")
    assert 'href="/new"' in sell
    assert 'class="pill cta"' in sell


# --- 2. install band: white text on the navy gradient ---


def test_install_band_text_contrast_from_css():
    css = HOME_CSS.read_text()
    band = _rule(css, ".install-band")
    assert "color: #fff;" in band
    backs = re.findall(r"#[0-9a-fA-F]{6}", band)
    assert backs, "gradient background missing"
    fore = re.search(r"\.install-band h2\s*\{([^}]*)\}", css).group(1)
    assert "#fff" in fore.lower().replace(" ", "")
    for back in backs:
        assert _contrast("#FFFFFF", back) >= 4.5, back
    icon = _rule(css, ".install-ic")
    assert "#fff" in icon.lower().replace(" ", "")


# --- 3. one footer on rich-footer pages ---


def test_home_has_only_the_rich_footer(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = htmlmod.unescape(_home(client, lang))
        t = t_for(lang)
        assert html.count("<footer") == 1, lang
        assert 'class="land-footer rich"' in html, lang
        assert t("top.footer") not in html, lang
        assert t("land.honest") in html, lang  # honesty line kept


def test_other_pages_keep_the_base_footer(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    client.cookies.set("ui_lang", "en")
    html = htmlmod.unescape(client.get("/market").text)
    assert 'class="land-footer rich"' not in html
    assert t_for("en")("top.footer") in html


# --- 4. cut-outs contained + padded; only covers use cover ---


def test_cutout_css_contain_and_pad():
    css = HOME_CSS.read_text()
    for selector in (".home-mkt .pick-photo img",
                     ".shop-cover img",
                     ".hero-cover img",
                     "body.pub .card .ph img"):
        rule = _rule(css, selector)
        assert "object-fit: contain" in rule, selector
        assert "padding" in rule, selector
    # Real photos may still use cover.
    for selector in (".shop-cover img.cov", ".hero-cover img.cov",
                     ".tile-photo img"):
        assert "object-fit: cover" in _rule(css, selector), selector
    assert "object-fit: cover" in _rule(APP_CSS.read_text(),
                                        ".hp-band-img")


def test_cover_branches_keep_cover_class():
    assert 'class="cov"' in HOME_HTML.read_text()
    shop = (ROOT / "app" / "web" / "templates" / "shop.html").read_text()
    assert 'class="cov"' in shop


def test_pick_collage_and_tile_photos_render_unpadded_hooks(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    picks = _section(html, "best-prices", "markets")
    assert "data-cutout" in picks  # cut-out hook kept
    shops = _section(html, "shops", "best-prices")
    assert 'src="/m/tom_cut.jpg"' in shops  # collage hook kept


def test_market_results_carry_no_product_photos(tmp_path, monkeypatch):
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
    assert "results-grid" in html
    groups = html.split("results-grid", 1)[1]
    assert "data-cutout" not in groups
    assert 'src="/m/' not in groups  # avatar icons only, no product photos


def test_shop_tiles_render_photos_unpadded_hooks(tmp_path):
    slug, _token = seed_shop(tmp_path, "Cut Store", "Koyambedu", [
        draft("tomato", "தக்காளி", "40",
              photo="data/photos/tom_cut.jpg"),
        draft("onion", "வெங்காயம்", "35",
              photo="data/photos/oni_orig.jpg"),
    ])
    html = make_client(tmp_path).get(f"/s/{slug}").text
    assert html.count('class="ph"') == 2
    assert 'src="/m/tom_cut.jpg"' in html
    assert 'src="/m/oni_orig.jpg"' in html
    assert "data-cutout" in html


# --- 5. Built with Meta cards ---


def test_open_weights_card_label_and_sentence(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    expected = {"en": ("Open-weights option", OPEN_SENTENCE),
                "ta": ("ஓப்பன்-வெயிட் விருப்பம்", None),
                "hi": ("ओपन-वेट विकल्प", None)}
    for lang, (label, sentence) in expected.items():
        html = htmlmod.unescape(_home(client, lang))
        meta = _section(html, "meta", "lost-link")
        assert label in meta, lang
        if sentence is not None:
            assert sentence in meta
    en = htmlmod.unescape(_home(client, "en"))
    meta = _section(en, "meta", "lost-link")
    assert "Double-checks" not in meta


def test_each_card_shows_its_id_once_mono_only(tmp_path):
    seed_market(tmp_path)
    html = htmlmod.unescape(_home(make_client(tmp_path), "en"))
    meta = _section(html, "meta", "lost-link")
    cards = re.findall(r'<article class="meta-card".*?</article>', meta,
                       re.DOTALL)
    assert len(cards) == 4
    for card in cards:
        code = re.search(r"<code>(.*?)</code>", card).group(1)
        ids = [part.strip() for part in code.split("+")]
        body = re.sub(r"<code>.*?</code>", "", card)
        body = re.sub(r"<[^>]+>", " ", body)
        for model_id in ids:
            assert meta.count(model_id) >= 1, model_id
            assert model_id not in body, model_id


# --- 6. seller sparkles stay in the margins ---


def test_sparkles_behind_copy_in_margins():
    css = HOME_CSS.read_text()
    assert "pointer-events: none" in _rule(css, ".sell-stars")
    assert "z-index: 0" in _rule(css, ".sell-stars")
    assert "z-index: 1" in _rule(css, ".sell-wrap")
    first = _rule(css, ".sell-stars span:nth-child(1)")
    assert "left: 10px" in first and "bottom:" in first
    second = _rule(css, ".sell-stars span:nth-child(2)")
    assert "right:" in second and "top:" in second
    third = _rule(css, ".sell-stars span:nth-child(3)")
    assert "right:" in third and "bottom:" in third
    src = (ROOT / "app" / "web" / "templates" / "sellers.html"
           ).read_text()
    assert '<div class="sell-stars" aria-hidden="true">' in src


# --- 7. hero credit fully visible on phones ---


def test_hero_credit_moves_above_card_on_phones():
    css = HOME_CSS.read_text()
    phone = css.split("@media (max-width: 600px)", 1)[1]
    credit = _rule(phone.split("@media", 1)[0], ".hp-credit")
    assert "left:" in credit
    assert "right: auto" in credit
    bottom = int(re.search(r"bottom:\s*(\d+)px", credit).group(1))
    assert bottom >= 72  # clears the overlapping search card


# --- 8. area tiles: pin fallback until a real photo exists ---


def test_area_tiles_use_pin_without_real_photo(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    areas = _section(html, "markets", "sell")
    assert "data-cutout" not in areas
    assert "tile-photo" not in areas  # seed tiles only have cut-outs
    assert areas.count("tile-ic") >= 3  # all-areas + 2 tiles
    assert "pin.svg" in areas
    assert "Koyambedu" in areas and "Anna Nagar" in areas
    chooser = _section(html, "loc-drawer", "search-pop")
    assert "data-cutout" not in chooser
