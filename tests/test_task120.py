"""Task 120: sample-shop wording, full-width shop grid, compact voice panel.

1. Sample shops are never described as "said by the seller today":
   thin top strip, homepage counters, /market rows, shop-page note,
   and the voice badge on sample cards (en/ta/hi).
2. Shop page grid uses the full content width while the bag is empty
   and shares it with the order column only once the bag has lines.
3. /market shows the Order-by-voice panel only when the voice tab is
   selected or there is no query.
"""

from __future__ import annotations

import html as htmlmod
import re
from pathlib import Path

from test_task84 import _home, make_client, seed_market

from app import db
from app.web.i18n import t_for
from scripts import seed_samples

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA = ROOT / "scripts" / "sample_data"
PUBLIC_CSS = ROOT / "app" / "web" / "static" / "css" / "public.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
PUBLIC_JS = ROOT / "app" / "web" / "static" / "public.js"
SHOP_HTML = ROOT / "app" / "web" / "templates" / "shop.html"

# (ui lang, sample slug in that shop language)
SAMPLE_PAGES = (
    ("en", "green-basket"),
    ("ta", "selvi-vegetable-stall"),
    ("hi", "gupta-sabzi-wale"),
)


def seed(data_dir):
    return seed_samples.seed(Path(data_dir), SAMPLE_DATA,
                             "http://localhost:8000")


def _shop_url(slug, lang):
    return f"/s/{slug}" + ("" if lang == "en" else f"?lang={lang}")


# --- 1a. thin top strip: "Sample prices · <area>", never "said today" ---


def test_thin_strip_sample_wording_all_langs(tmp_path):
    seed(tmp_path / "data")
    client = make_client(tmp_path)
    for lang, slug in SAMPLE_PAGES:
        html = client.get(_shop_url(slug, lang)).text
        t = t_for(lang)
        assert t("ann.said_sample").split("{area}")[0].strip() in html, lang
        said = t("ann.said_today").split("{time}")[0].strip()
        assert said not in html, (lang, said)


def test_thin_strip_sample_wording_on_quote_page(tmp_path):
    seed(tmp_path / "data")
    client = make_client(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop = conn.execute(
            "SELECT * FROM shops WHERE slug = 'green-basket'").fetchone()
        version_id = db.latest_version(conn, shop["id"],
                                       published_only=True)
        name = db.version_items(conn, version_id)[0].name_en
    finally:
        conn.close()
    resp = client.post(
        "/s/green-basket/quote",
        json={"lines": [{"name_en": name, "variety": "",
                         "qty": 1, "unit": "kg"}],
              "customer_name": "Test", "customer_phone": ""})
    assert resp.status_code == 200, resp.text
    html = client.get(resp.json()["url"]).text
    assert "Sample prices ·" in html
    assert "said by the seller today" not in html


def test_thin_strip_real_shop_keeps_said_today(tmp_path):
    seed(tmp_path / "data")
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = client.get("/s/kannan-veg").text
    assert "Prices said by the seller today" in html


# --- 1b. homepage counters exclude sample prices ---


def _hero(client, lang="en"):
    # Task 122: counters live in their own strip after the header.
    return _home(client, lang)


def test_counters_count_only_real_prices_with_sample_note(tmp_path):
    # Task 127: the hero pill shows the real total (7 real + 53
    # sample prices); sample cards carry their own SAMPLE labels.
    from app.web.i18n import t_for as _t

    seed(tmp_path / "data")
    seed_market(tmp_path)
    hero = _hero(make_client(tmp_path))
    assert "data-count" not in hero
    assert "60 PRICES TODAY" in hero
    assert _t("en")("hp.demo") in hero
    assert _t("en")("hp.said_sample") in hero


def test_counters_all_sample_label_prices_listed(tmp_path):
    # Task 127: all-sample data still counts honestly, and every
    # card says SAMPLE.
    from app.web.i18n import t_for as _t

    seed(tmp_path / "data")
    hero = _hero(make_client(tmp_path))
    assert "53 PRICES TODAY" in hero
    assert _t("en")("hp.demo") in hero
    assert _t("en")("hp.said_sample") in hero
    assert 'id="empty-all"' not in _home(make_client(tmp_path), "en")


def test_counter_totals_split_real_and_sample(tmp_path):
    from app.web.home_data import home_data

    seed(tmp_path / "data")
    seed_market(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        totals = home_data(conn)["totals"]
    finally:
        conn.close()
    assert totals["n_shops"] == 3
    assert totals["m_prices"] == 7
    assert totals["n_sample_shops"] == 5
    assert totals["m_sample_prices"] == 53


# --- 1c. /market rows: "Sample prices", not "Updated Sample prices" ---


def test_market_rows_sample_wording_all_langs(tmp_path, monkeypatch):
    from decimal import Decimal

    from app.market.search import Query, Want

    seed(tmp_path / "data")
    client = make_client(tmp_path)
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        html = client.get("/market?q=tomato").text
        t = t_for(lang)
        assert t("hp.said_sample") in html, lang
        assert "Updated " + t("hp.said_sample") not in html, lang


def test_market_rows_real_shop_keeps_updated(tmp_path, monkeypatch):
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
    assert "Updated " in html


# --- 1d. shop-page note: one clean sentence, no bracket ---


def test_shop_note_single_sentence_all_langs(tmp_path):
    seed(tmp_path / "data")
    client = make_client(tmp_path)
    for lang, slug in SAMPLE_PAGES:
        html = htmlmod.unescape(client.get(_shop_url(slug, lang)).text)
        t = t_for(lang)
        assert t("shop.notice_sample") + "." in html, lang
        assert "(" + t("spoken_and_checked") not in html, lang


def test_shop_note_real_shop_keeps_bracket(tmp_path):
    seed_market(tmp_path)
    html = make_client(tmp_path).get("/s/kannan-veg").text
    assert "(spoken and checked " in html


# --- 1e. sample card badge ---


def test_sample_card_badge_all_langs(tmp_path):
    from app.web.i18n import t_for as _t

    seed(tmp_path / "data")
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        assert _t(lang)("hp.said_sample") in html, lang
        assert _t(lang)("hp.demo") in html, lang


def test_sample_card_badge_replaces_voice_line(tmp_path):
    # Task 127: sample cards say SAMPLE + "Sample prices"; the
    # seeded samples pass the proof check, so the voice badge shows
    # too (ribbon + badge, like the reference).
    seed(tmp_path / "data")
    html = _home(make_client(tmp_path), "en")
    assert "Sample shop" in html
    assert "Sample prices" in html
    assert "✓ Voice-checked" in html


def test_real_card_keeps_voice_badge(tmp_path):
    seed_market(tmp_path)
    html = htmlmod.unescape(_home(make_client(tmp_path), "en"))
    assert "✓ Voice-checked" in html


# --- 2. shop page grid: full width while the bag is empty ---


def test_grid_css_full_width_when_bag_empty():
    # Task 127: v13 rows run full width; the fixed bag bar slides up
    # only when the bag has lines (bar.hidden toggles in-page).
    css = SHOP13_CSS.read_text()
    flat = css.replace(" ", "")
    assert ".menu-wrap{width:min(800px,100%-32px)" in flat
    assert "position:fixed" in flat.split(".bag-bar{")[1].split("}")[0]
    src = SHOP_HTML.read_text()
    assert "bar.hidden = count === 0" in src
    assert "data-cart-bar" in src and "data-cart-sheet" in src


def test_grid_phone_columns_unchanged():
    css = APP_CSS.read_text()
    assert (".grid-products { display: grid; "
            "grid-template-columns: repeat(3, 1fr);") in css
    assert (".grid-products { grid-template-columns: repeat(2, 1fr); }"
            in css)


# --- 3. voice panel only on the voice tab / no query ---


def _panel_tag(html):
    match = re.search(r"<section[^>]*data-voice-panel[^>]*>", html)
    assert match, "voice panel missing"
    return match.group(0)


def test_voice_panel_visible_without_query(tmp_path):
    seed_market(tmp_path)
    html = make_client(tmp_path).get("/market").text
    assert "hidden" not in _panel_tag(html)
    # Task 124: the panel's recorder became the voice+text composer.
    for hook in ("market-voice", "data-composer", "data-composer-form",
                 "data-composer-mic", "data-composer-text",
                 'action="/market/voice"'):
        assert hook in html, hook


def test_voice_panel_hidden_after_typed_search(tmp_path, monkeypatch):
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
    assert "hidden" in _panel_tag(html)
    # Hooks stay in the DOM; results follow the search card directly.
    for hook in ("market-voice", "data-composer", "data-composer-form",
                 "data-composer-mic", "data-composer-text",
                 'action="/market/voice"'):
        assert hook in html, hook
    assert html.index("mkt-pill") < html.index("data-voice-panel")


def test_voice_panel_js_toggles_on_tabs():
    # Task 125: the old search card (and its voice tab toggle) is
    # gone; the mic toggle lives in the search pop-up instead.
    src = PUBLIC_JS.read_text()
    assert "hp-tab-voice" not in src
    assert "hp-mic" not in src
    assert "initMarketTabs" in src
    popups = (ROOT / "app" / "web" / "static" / "popups.js").read_text()
    assert "data-voice-toggle" in popups
    assert "search-voice" in popups


def test_sample_strings_exist_in_all_langs():
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        for key in ("ann.said_sample", "hp.said_sample",
                    "shop.notice_sample", "order.sample_notice",
                    "hp.demo", "hp.prices_listed", "hp.samples_note",
                    "hp.voice_badge_sample"):
            assert t(key) != key, (lang, key)
    assert t_for("en")("hp.samples_note", n=1, count=1) == "+ 1 sample shop"
    assert t_for("en")("hp.samples_note", n=5, count=5) == "+ 5 sample shops"
