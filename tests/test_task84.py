"""Task 84: marketplace homepage + shop header and Today heading fixes.

Homepage ("/"): top strip, header, hero with search card, banner, today's
top picks, explore-by-market, recent shops, how/sellers/customers/meta,
footer, and an area chooser modal. All cards use listed shops with a
published list; unlisted shops never appear.
"""

from __future__ import annotations

import html as htmlmod
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent
HOME_JS = ROOT / "app" / "web" / "static" / "home.js"
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"

# Task 127: v13 homepage sections in order (marketing stays on
# /sellers and /how; "empty-all" only renders with no shop data).
SECTIONS = ("hero", "fresh", "cats", "shops", "lowest", "how", "app",
            "markets")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def _proof(name):
    return Proof(quote=f"said {name}", turn_ids=[1], start_ms=0,
                 end_ms=500, audio_clip="/tmp/clip.m4a")


def draft(name_en, name_local, price, photo=None, variety=None):
    lines = [] if price is None else [
        PriceLine(Decimal(price), Decimal(1), "kg", f"{price} said")]
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety, price_lines=lines, qty=None, qty_unit=None,
        proof=_proof(name_en), confirmed=True, photo=photo)


def seed_shop(tmp_path, name, area, items, listed=True, publish=True,
              days_ago=0, lat=None, lng=None, is_demo=False,
              phone="+914400000001"):
    data = tmp_path / "data"
    conn = db.connect(data)
    try:
        shop_id, slug, token = db.create_shop(
            conn, name=name, phone=phone, area=area, language="ta",
            currency="INR", shop_type="vegetable", listed=listed,
            is_demo=is_demo)
        if days_ago or lat is not None:
            created = (datetime.now(UTC)
                       - timedelta(days=days_ago)).isoformat()
            conn.execute(
                "UPDATE shops SET created_at = ?, lat = ?, lng = ?"
                " WHERE id = ?", (created, lat, lng, shop_id))
            conn.commit()
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, list(items))
        db.set_published(conn, version_id, publish)
    finally:
        conn.close()
    return slug, token


def seed_market(tmp_path):
    """Two listed Koyambedu shops + one listed Anna Nagar shop."""
    seed_shop(tmp_path, "Kannan Veg", "Koyambedu", [
        draft("tomato", "தக்காளி", "40",
              photo="data/photos/tom_cut.jpg"),
        draft("onion", "வெங்காயம்", "35",
              photo="data/photos/oni_orig.jpg"),
        draft("banana", "வாழைப்பழம்", "60"),
        draft("potato", "உருளை", "30"),
    ], lat=13.070, lng=80.290)
    seed_shop(tmp_path, "Malar Greens", "Koyambedu", [
        draft("tomato", "தக்காளி", "42",
              photo="data/photos/tom2_cut.jpg", variety="nattu"),
        draft("greens", "கீரை", "20"),
    ], lat=13.072, lng=80.292)
    seed_shop(tmp_path, "Anna Fresh", "Anna Nagar", [
        draft("mango", "மாம்பழம்", "120",
              photo="data/photos/man_cut.jpg"),
    ], lat=13.090, lng=80.210)


def _home(client, lang="en", query=""):
    client.cookies.set("ui_lang", lang)
    # Task 171: in-site navigation (same-host Referer) reads today's
    # home page at /; the cookie alone now gets the entry page.
    resp = client.get(f"/{query}",
                      headers={"referer": "http://testserver/market"})
    assert resp.status_code == 200, lang
    return resp.text


def _section(html, section_id, next_id=None):
    start = html.index(f'id="{section_id}"')
    if next_id is None:
        return html[start:]
    try:
        end = html.index(f'id="{next_id}"', start)
    except ValueError:
        end = len(html)
    return html[start:end]


# --- 1. every section id in en/ta/hi, in order -------------------------------


def test_homepage_sections_in_order_all_langs(tmp_path):
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


# --- 2. search form posts to the existing market route ------------------------


def test_search_form_targets_market_with_right_params(tmp_path):
    # Task 122: the hero search card became the search pop-up; area /
    # budget / sort live in the filter pop-up. Both submit GET /market.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    pop = html.split('id="search-pop"')[1].split('id="filter-pop"')[0]
    assert 'method="get" action="/market"' in pop
    assert 'name="q"' in pop
    assert 'placeholder=' in pop
    t = t_for("en")
    assert t("v12.search_ph") in pop
    assert t("v12.recent") in html and t("v12.popular") in html
    # Task 124: voice search is the embedded voice+text composer posting
    # to /market/voice (same action as the voice panel on /market).
    assert "data-voice-toggle" in pop
    assert 'id="search-voice"' in pop
    assert "data-composer" in pop
    assert 'action="/market/voice"' in pop
    filt = html.split('id="filter-pop"')[1]
    assert 'method="get" action="/market"' in filt
    assert 'name="sort"' in filt and 'name="area"' in filt
    assert 'name="budget"' in filt and 'name="open_now"' in filt
    assert 'name="cat"' in filt
    assert "Koyambedu" in filt and "Anna Nagar" in filt
    for value in ('value=""', 'value="100"', 'value="200"',
                  'value="500"', 'value="1000"'):
        assert value in filt, value
    for value in ('value="total"', 'value="distance"', 'value="items"'):
        assert value in filt, value


def test_market_accepts_budget_param(tmp_path, monkeypatch):
    from app.market.search import Query, Want
    from app.web import main as main_mod

    seed_market(tmp_path)
    client = make_client(tmp_path)
    monkeypatch.setattr(
        main_mod, "parse_query",
        lambda text, **_kw: Query(
            wants=[Want("tomato", None, None, None)], budget=None,
            area=None))
    html = client.get("/market?q=tomato&budget=200").text
    assert "Budget" in html
    assert "₹200" in html
    # An invalid budget never breaks the search.
    resp = client.get("/market?q=tomato&budget=lots")
    assert resp.status_code == 200
    assert "Budget" not in resp.text


# --- 3. only listed shops with published prices -------------------------------


def test_unlisted_shop_never_appears(tmp_path):
    seed_market(tmp_path)
    seed_shop(tmp_path, "Hidden Store", "Koyambedu", [
        draft("papaya", "பப்பாளி", "25")], listed=False)
    seed_shop(tmp_path, "Silent Shop", "Koyambedu", [
        draft("papaya", "பப்பாளி", "25")], publish=False)
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        assert "Hidden Store" not in html, lang
        assert "Silent Shop" not in html, lang
        # Task 127 polish: the Fruits tile art is a fixed cluster
        # (papaya/apple/guava cut-outs), so the hidden item is
        # matched as content — never the asset filename.
        assert "/market?q=papaya" not in html.lower(), lang
        assert ">papaya<" not in html.lower(), lang
    html = _home(client, "en")
    assert "Kannan Veg" in html
    assert "Malar Greens" in html


def test_stale_list_excluded_from_today(tmp_path):
    seed_market(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        conn.execute("UPDATE versions SET created_at = ?", (old,))
        conn.commit()
    finally:
        conn.close()
    client = make_client(tmp_path)
    html = _home(client, "en")
    lowest = _section(html, "lowest", "how")
    assert "Kannan Veg" not in lowest
    assert "Anna Fresh" not in lowest


def test_demo_shop_labelled_on_cards(tmp_path):
    seed_market(tmp_path)
    seed_shop(tmp_path, "Demo Veg", "Koyambedu", [
        draft("carrot", "கேரட்", "50")], is_demo=True)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    from app.web.i18n import t_for

    assert t_for("en")("hp.demo") in html


# --- 4. counts, popular chips, cheapest items ----------------------------------


def test_markets_cover_every_area_once(tmp_path):
    # Task 127: the v13 markets grid links every market with shops
    # (no counts on the links anymore).
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    areas = _section(html, "markets")
    t = t_for("en")
    assert t("v13.fresh_in", market="Koyambedu") in areas
    assert t("v13.fresh_in", market="Anna Nagar") in areas
    assert areas.count("Fresh prices in") == 2


def test_popular_chips_use_real_item_names(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    markets = _section(html, "markets", "sell")
    assert "/market?q=tomato" in markets
    chips = re.findall(r"/market\?q=[a-z]+", markets)
    assert 1 <= len(chips) <= 6, chips
    # Every chip names a real live item.
    for chip in chips:
        name = chip.split("=", 1)[1]
        assert name in ("tomato", "onion", "banana", "potato",
                        "greens", "mango"), name


def test_recent_shops_show_cheapest_three(tmp_path):
    # Task 127: the v13 photo card's teal bar names the two
    # cheapest prices plus a "+N" remainder.
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    shops = _section(html, "shops", "lowest")
    assert "Kannan Veg" in shops
    kannan = shops.split("Kannan Veg", 1)[1].split('class="shop"', 1)[0]
    bar = re.search(r'class="bar-deal".*', kannan, re.DOTALL).group(0)
    for name in ("potato", "onion"):
        assert name in bar.lower(), name
    assert "+2" in bar  # tomato + banana beyond the first two
    assert "Banana" not in shops  # 4th cheapest item stays out


def test_lowest_photos_prefer_cutouts(tmp_path):
    # Task 164: the seller's own photo comes first in the lowest
    # tiles; the v13 cut-out is only the fallback with no own photo.
    items = [draft(f"item{i}", f"பொருள்{i}", str(10 + i),
                   photo=(f"data/photos/it{i}_cut.jpg" if i == 9 else None))
             for i in range(10)]
    items.append(draft("tomato", "தக்காளி", "40",
                       photo="data/photos/tom_orig.jpg"))
    items.append(draft("onion", "வெங்காயம்", "35"))
    seed_shop(tmp_path, "Big Veg", "Koyambedu", items)
    client = make_client(tmp_path)
    html = _home(client, "en")
    lowest = _section(html, "lowest", "how")
    assert "/m/tom_orig.jpg" in lowest
    assert "/static/img/v13/tomato.webp" not in lowest
    assert "/m/it9_cut.jpg" in lowest
    assert "/static/img/v13/onion.webp" in lowest


# --- 5. ?area= filters by area name --------------------------------------------


def test_area_param_filters_homepage(tmp_path):
    # Task 127: the v13 shops row borrows other areas' shops under
    # an "and nearby markets" heading; fresh/lowest stay scoped.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en", "?area=Anna+Nagar"))
    assert "Anna Nagar" in html
    assert "Anna Fresh" in html
    shops = _section(html, "shops", "lowest")
    assert "and nearby markets" in shops
    assert "Kannan Veg" in shops
    lowest = _section(html, "lowest", "how")
    assert "tomato" not in lowest.lower()
    assert "mango" in lowest.lower()
    # Unknown areas show honest empty states, not other areas' shops.
    html = htmlmod.unescape(_home(client, "en", "?area=Nowhere"))
    empty = _section(html, "empty-all")
    assert "Anna Fresh" not in empty
    assert t_for("en")("hp.picks_empty_t") in empty


# --- 6. empty states with no data ----------------------------------------------


def test_empty_homepage_has_honest_empty_states(tmp_path):
    # Task 127: empty sections hide; one combined empty state with
    # a Start-selling link renders instead.
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    assert t("hp.picks_empty_t") in _section(html, "empty-all")
    assert 'href="/new"' in _section(html, "empty-all")
    assert 'class="pick-card"' not in html
    assert 'class="shop-card"' not in html
    assert 'class="shop"' not in _section(html, "shops", "lowest")


# --- 7. no stock photos inside product or shop cards ----------------------------


def test_no_landing_photos_in_product_or_shop_cards(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    for section, nxt in (("fresh", "cats"), ("cats", "shops"),
                         ("shops", "lowest"), ("lowest", "how")):
        body = _section(html, section, nxt)
        assert "landing/" not in body, section
        assert "Unsplash" not in body, section


# --- 8. strip, header, hero, banner, meta ---------------------------------------


def test_strip_and_header(tmp_path):
    # Task 127: the header sits on the hero (white logo, five white
    # nav links, EN switch, app + selling buttons, menu on phones);
    # the white sticky bar slides in after the hero.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en", "?area=Koyambedu"))
    t = t_for("en")
    hero = re.search(r'<header class="topbar".*?</header>', html,
                     re.DOTALL).group(0)
    for href in ("/market", "#lowest", "#markets", "/sellers", "/how"):
        assert f'href="{href}"' in hero, href
    assert "data-ui-toggle" in hero
    assert "data-menu-open" in hero
    assert 'href="#app"' in hero
    assert 'href="/new"' in hero
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    assert "data-loc-open" in head
    assert "Koyambedu" in head
    assert "data-search-open" in head
    assert 'href="/my"' in head
    assert "data-bag-count" in head
    assert "data-menu-open" in head
    html = htmlmod.unescape(_home(client, "en"))
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    assert t("hp.all_areas") in head


def test_hero_headline_names_area_or_default(tmp_path):
    # Task 122: no hero; the location button names the picked area,
    # and the sellers hero lives on /sellers.
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    t = t_for("en")
    html = htmlmod.unescape(_home(client, "en"))
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    assert t("hp.all_areas") in head
    html = htmlmod.unescape(_home(client, "en", "?area=Koyambedu"))
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    assert "Koyambedu" in head
    sellers = htmlmod.unescape(client.get("/sellers").text)
    assert t("land.hero_a") in sellers


def test_banner_and_meta_mention(tmp_path):
    # Task 127: long marketing lives on /sellers and /how, not the
    # homepage; the homepage keeps the Meta model cards instead.
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    assert 'id="sell"' not in html
    assert 'id="meta"' not in html
    sellers = htmlmod.unescape(client.get("/sellers").text)
    assert t("v12.sell_t") in sellers
    assert 'href="/new"' in sellers
    assert 'href="/try"' in sellers
    how = htmlmod.unescape(client.get("/how").text)
    assert t("land.how_t") in how


# --- 9. area chooser: modal + privacy-safe JS ----------------------------------


def test_area_chooser_modal_and_tiles(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    assert 'id="loc-drawer"' in html
    modal = html.split('id="loc-drawer"')[1].split('id="search-pop"')[0]
    assert 'role="dialog"' in modal and 'aria-modal="true"' in modal
    assert "data-close" in modal
    assert t("hp.chooser_t") in modal
    assert t("hp.chooser_d") in modal
    assert t("hp.detect") in modal
    assert "Koyambedu" in modal and "Anna Nagar" in modal
    assert "2 shops" in modal
    assert "data-area-lat" in modal and "data-area-lng" in modal
    assert "popups.js" in html and "locate.js" in html


def test_chooser_js_carries_no_coordinates():
    src = HOME_JS.read_text()
    assert "fetch(" not in src
    assert "XMLHttpRequest" not in src
    assert "navigator.sendBeacon" not in src
    assert "haversine" in src.lower()


def test_node_chooser_helper():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/home_chooser.test.mjs"], cwd=ROOT, check=False,
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- 10. fix A: customer shop header on phones ----------------------------------


def test_shop_header_two_row_structure(tmp_path):
    seed_shop(tmp_path, "Sri Murugan Pazhamudhir Nilayam Fresh Vegetables",
              "Koyambedu", [draft("tomato", "தக்காளி", "40")])
    client = make_client(tmp_path)
    html = client.get("/s/sri-murugan-pazhamudhir-nilayam-fresh-vegetables").text
    assert htmlmod.unescape(html).count(
        "Sri Murugan Pazhamudhir Nilayam Fresh Vegetables") >= 1
    head = re.search(r'<header class="hdr".*?</header>', html,
                     re.DOTALL).group(0)
    assert 'class="shop-id"' in head
    assert 'class="shop-name"' in head


def test_shop_header_css_two_rows_under_600px():
    # Task 127: the v13 inner header stays ONE row on phones — logo
    # mark, flexing location button, icons, menu (EN in the menu).
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    phone = css.split("@media (max-width:700px)", 1)[1].split("@media")[0]
    assert ".stickybar .top-actions .lang" in phone
    assert "display:none" in phone.replace(" ", "")
    assert ".loc-mini" in phone and "min-width:0" in phone.replace(" ", "")
    narrow = css.split("@media (max-width:430px)", 1)[1]
    assert ".stickybar .brand-word" in narrow


# --- 11. fix B: one header style on Seller Today ---------------------------------


def test_today_day_group_has_no_kick_line(tmp_path):
    _slug, token = seed_shop(
        tmp_path, "Day Shop", "Koyambedu",
        [draft("tomato", "தக்காளி", "40")])
    client = make_client(tmp_path)
    html = client.get(f"/e/{token}").text
    day = html.split('id="step-day"')[1].split('id="step-evening"')[0]
    assert 'class="kick"' not in day
    assert "step-num" not in day
    assert "t61.step2_kick" not in day
    # Both sub-groups keep the collapsible ▾ group header.
    assert day.count("data-grp-toggle") == 2
    assert 'data-grp="orders"' in day
    assert 'data-grp="bills"' in day


# --- 12. i18n: every new string translated ---------------------------------------


def test_new_strings_translated_all_langs():
    from app.web.i18n import _ENGLISH, _HINDI, _TAMIL, missing_keys

    assert missing_keys() == {"ta": [], "hi": []}
    keys = [key for key in _ENGLISH if key.startswith("hp.")]
    assert len(keys) > 40, len(keys)
    for key in keys:
        assert key in _TAMIL, key
        assert key in _HINDI, key


def test_tamil_homepage_renders_translated_strings(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "ta"))
    t = t_for("ta")
    assert t("hp.search") in html
    assert t("v13.fresh_t") in html
    assert t("v13.cats_t") in html
    assert t("v13.lowest_t") in html
    assert t("v13.markets_t") in html
    # Tamil text must wrap, never overflow the screen.
    css = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    assert "overflow-wrap" in css
