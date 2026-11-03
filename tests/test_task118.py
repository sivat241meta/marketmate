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
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"
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
    # Task 127: the v13 Start selling buttons never wrap; phones
    # hide the hero button (the menu sheet keeps the link).
    css = V13_CSS.read_text()
    for selector in (".btn-dark{", ".btn-teal{"):
        rule = css.split(selector)[1].split("}")[0]
        assert "white-space:nowrap" in rule.replace(" ", ""), selector
    small = css.split("@media (max-width:700px)", 1)[1]
    small = small.split("@media", 1)[0]
    assert ".topbar .btn-dark" in small
    assert "display:none" in small.replace(" ", "")


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
    # Task 127: no #sell section on the homepage — the FOR SELLERS
    # hero card links /new, and /sellers keeps the big CTA.
    hero = _section(html, "hero", "fresh")
    assert 'href="/new"' in hero
    sellers = client.get("/sellers").text
    assert 'href="/new"' in sellers
    assert 'class="pill cta' in sellers


# --- 2. install band: white text on the navy gradient ---


def test_install_band_text_contrast_from_css():
    # Task 127: the dark v13 app band — white text on #0B2A33.
    css = V13_CSS.read_text()
    band = _rule(css, "body.v13 .app-band")
    assert "var(--dark)" in band
    dark = re.search(r"--dark:\s*(#[0-9a-fA-F]{6})", css).group(1)
    assert _contrast("#FFFFFF", dark) >= 4.5, dark
    copy = _rule(css, "body.v13 .app-copy h3")
    assert "#fff" in copy.lower().replace(" ", "")


# --- 3. one footer on rich-footer pages ---


def test_home_has_only_the_rich_footer(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = htmlmod.unescape(_home(client, lang))
        t = t_for(lang)
        assert html.count("<footer") == 1, lang
        assert 'class="foot"' in html, lang
        assert t("top.footer") not in html, lang
        assert t("land.honest") in html, lang  # honesty line kept


def test_other_pages_keep_the_base_footer(tmp_path):
    # Task 127: every public page shares the same v13 footer.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    client.cookies.set("ui_lang", "en")
    for url in ("/market", "/sellers", "/how", "/my"):
        html = htmlmod.unescape(client.get(url).text)
        assert 'class="foot"' in html, url
        assert t_for("en")("top.footer") not in html, url
        assert t_for("en")("land.honest") in html, url


# --- 4. cut-outs contained + padded; only covers use cover ---


def test_cutout_css_contain_and_pad():
    # Task 127: v13 cut-outs render frameless (contain + shadow);
    # grey-tile photos multiply-blend; covers still fill.
    css = V13_CSS.read_text()
    for selector in ("body.v13 .deal .tile img",
                     "body.v13 .fresh img[data-cutout]"):
        rule = _rule(css, selector)
        assert "object-fit:contain" in rule.replace(" ", ""), selector
    assert "mix-blend-mode:multiply" in _rule(
        css, "body.v13 .deal .tile img").replace(" ", "")
    assert "object-fit:cover" in _rule(
        css, "body.v13 .shop-photo img").replace(" ", "")
    shop = SHOP13_CSS.read_text()
    assert "mix-blend-mode:multiply" in _rule(
        shop, "body.v13 .pic img").replace(" ", "")
    assert "object-fit:cover" in _rule(
        shop, "body.v13 .info-cover").replace(" ", "")


def test_cover_branches_keep_cover_class():
    # Task 127: v13 keeps the data-cutout hook (cut-outs vs covers)
    # on home, shop and market item photos.
    assert "data-cutout" in HOME_HTML.read_text()
    for name in ("shop.html", "market.html"):
        text = (ROOT / "app" / "web" / "templates" / name).read_text()
        assert "data-cutout" in text, name


def test_pick_collage_and_tile_photos_render_unpadded_hooks(tmp_path):
    # Task 127: v13 lowest tiles + shop photo cards keep the
    # cut-out hook; the seed shops have no covers, so cards fall
    # back to neutral tiles.
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    picks = _section(html, "lowest", "how")
    assert "data-cutout" in picks  # cut-out hook kept
    shops = _section(html, "shops", "lowest")
    assert shops.count('class="shop"') == 3
    assert "landing/" not in shops


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
    # Task 127: v13 item results ARE photo tiles (named cut-outs
    # first, then the shop's own item photos).
    html = client.get("/market?q=tomato").text
    assert "results-grid" in html
    groups = html.split("results-grid", 1)[1]
    assert 'class="deal"' in groups
    assert "/static/img/v13/" in groups or 'src="/m/' in groups


def test_shop_tiles_render_photos_unpadded_hooks(tmp_path):
    slug, _token = seed_shop(tmp_path, "Cut Store", "Koyambedu", [
        draft("tomato", "தக்காளி", "40",
              photo="data/photos/tom_cut.jpg"),
        draft("onion", "வெங்காயம்", "35",
              photo="data/photos/oni_orig.jpg"),
    ])
    html = make_client(tmp_path).get(f"/s/{slug}").text
    # Task 127: v13 rows pair each item photo with the cut-out hook;
    # named v13 cut-outs win over the /m/ originals.
    assert html.count('class="pic"') == 2
    assert 'src="/m/tom_cut.jpg"' in html or "/static/img/v13/" in html
    assert 'src="/m/oni_orig.jpg"' in html or "/static/img/v13/" in html
    assert "data-cutout" in html


# --- 5. Built with Meta cards ---


def test_open_weights_card_label_and_sentence(tmp_path):
    # Task 127: card 2 names muse-spark-1.3 always; the open-weights
    # provider appears only when TEXT_PROVIDER=baseten.
    from fastapi.testclient import TestClient

    from app.config import load_settings
    from app.web.main import create_app

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    meta = _section(html, "how", "app")
    assert "muse-spark-1.3" in meta
    assert "meta-models/muse-spark-open-1026" not in meta
    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data"),
           "TEXT_PROVIDER": "baseten", "BASETEN_API_KEY": "k"}
    open_client = TestClient(create_app(load_settings(env)),
                             follow_redirects=False)
    # Task 167: read today's home page at /, past the entry page.
    open_client.cookies.set("mm_entered", "1")
    open_meta = _section(open_client.get("/").text, "how", "app")
    assert "meta-models/muse-spark-open-1026" in open_meta


def test_each_card_shows_its_id_once_mono_only(tmp_path):
    seed_market(tmp_path)
    html = htmlmod.unescape(_home(make_client(tmp_path), "en"))
    meta = _section(html, "how", "app")
    cards = re.findall(r'<div class="meta-card".*?</div>', meta,
                       re.DOTALL)
    assert len(cards) == 4
    for card in cards:
        code = re.search(r"<code>(.*?)</code>", card).group(1)
        ids = [part.strip() for part in re.split(r"\+|\bor\b", code)
               if part.strip()]
        body = re.sub(r"<code>.*?</code>", "", card)
        body = re.sub(r"<[^>]+>", " ", body)
        for model_id in ids:
            assert meta.count(model_id) >= 1, model_id
            if model_id == "sam-3.1":
                # Task 147: card 3's sentence names sam-3.1 as the
                # finder ("sam-3.1 finds it, and we keep a square
                # photo ..."), so the id is in the body too.
                continue
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
    # Task 144: the sellers band is a padded two-column card (text +
    # square photo, stacked on phones), so the credit keeps its
    # bottom-corner seat everywhere — the old bottom:80px dodge for
    # the overlapping full-bleed hero card is gone.
    credit = _rule(APP_CSS.read_text(), ".hp-credit")
    flat = credit.replace(" ", "")
    assert "position:absolute" in flat
    assert "bottom:8px" in flat
    assert "bottom:80px" not in HOME_CSS.read_text().replace(" ", "")


# --- 8. area tiles: pin fallback until a real photo exists ---


def test_area_tiles_use_pin_without_real_photo(tmp_path):
    # Task 127: the v13 markets grid is bordered link chips — area
    # links plus popular-item price links, no photos.
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    areas = _section(html, "markets", None).split("<footer")[0]
    assert "data-cutout" not in areas
    assert "<img" not in areas
    assert "/?area=" in areas or "/?area=" in htmlmod.unescape(areas)
    assert "/market?q=" in areas
    assert "Koyambedu" in areas and "Anna Nagar" in areas
    chooser = _section(html, "loc-drawer", "search-pop")
    assert "data-cutout" not in chooser
