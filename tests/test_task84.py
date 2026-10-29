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

ROOT = Path(__file__).resolve().parent.parent
HOME_JS = ROOT / "app" / "web" / "static" / "home.js"
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"

SECTIONS = ("strip", "hero", "search", "banner", "picks", "areas",
            "shops", "how", "sellers", "customers", "meta", "footer")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)),
                      follow_redirects=False)


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
    resp = client.get(f"/{query}")
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
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    form = _section(html, "search", "banner")
    assert form.startswith('id="search" class="hp-search"')
    assert 'method="get" action="/market"' in form
    assert 'name="q"' in form
    assert 'name="area"' in form
    assert 'name="budget"' in form
    assert "Koyambedu" in form and "Anna Nagar" in form
    for value in ('value=""', 'value="100"', 'value="200"',
                  'value="500"', 'value="1000"'):
        assert value in form, value
    t = t_for("en")
    for key in ("hp.tab_all", "hp.tab_veg", "hp.tab_fruit",
                "hp.tab_greens", "hp.tab_voice"):
        assert t(key) in form, key
    assert t("hp.search") in form
    # "Order by voice" opens the existing voice search on /market.
    assert 'href="/market#rec-start"' in form
    # Category tabs only prefill: placeholder data, no filter params.
    assert "data-ph=" in form
    assert "data-filter=" not in form


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
        assert "papaya" not in html.lower(), lang
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
    picks = _section(html, "picks", "areas")
    assert "Kannan Veg" not in picks
    assert "Anna Fresh" not in picks


def test_demo_shop_labelled_on_cards(tmp_path):
    seed_market(tmp_path)
    seed_shop(tmp_path, "Demo Veg", "Koyambedu", [
        draft("carrot", "கேரட்", "50")], is_demo=True)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    from app.web.i18n import t_for

    assert t_for("en")("hp.demo") in html


# --- 4. counts, popular chips, cheapest items ----------------------------------


def test_area_counts_are_correct(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    areas = _section(html, "areas", "shops")
    t = t_for("en")
    # Koyambedu: 2 shops, 6 priced items. Anna Nagar: 1 shop, 1 item.
    assert t("hp.area_counts", n=2, m=6) in areas
    assert t("hp.area_counts", n=1, m=1) in areas


def test_popular_chips_use_real_item_names(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    hero = _section(html, "hero", "banner")
    assert "/market?q=tomato" in hero
    chips = re.findall(r"/market\?q=[a-z]+", hero)
    assert 1 <= len(chips) <= 6, chips
    # Every chip names a real live item.
    for chip in chips:
        name = chip.split("=", 1)[1]
        assert name in ("tomato", "onion", "banana", "potato",
                        "greens", "mango"), name


def test_recent_shops_show_cheapest_three(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    shops = _section(html, "shops", "value")
    assert "Kannan Veg" in shops
    for name in ("potato", "onion", "tomato"):
        assert name in shops.lower(), name
    # Banana (₹60) is the 4th cheapest: not in the short list.
    assert "banana" not in shops.lower()


def test_picks_max_eight_cutout_first(tmp_path):
    items = [draft(f"item{i}", f"பொருள்{i}", str(10 + i),
                   photo=(f"data/photos/it{i}_cut.jpg" if i == 9 else None))
             for i in range(10)]
    seed_shop(tmp_path, "Big Veg", "Koyambedu", items)
    client = make_client(tmp_path)
    html = _home(client, "en")
    picks = _section(html, "picks", "areas")
    cards = re.findall(r'class="pick-card"', picks)
    assert len(cards) == 8, len(cards)
    assert picks.index("it9_cut.jpg") < picks.index("item0")


# --- 5. ?area= filters by area name --------------------------------------------


def test_area_param_filters_homepage(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en", "?area=Anna+Nagar"))
    assert "Anna Nagar" in html
    assert "Kannan Veg" not in html
    assert "Malar Greens" not in html
    assert "Anna Fresh" in html
    picks = _section(html, "picks", "areas")
    assert "tomato" not in picks.lower()
    assert "mango" in picks.lower()
    # Unknown areas show honest empty states, not other areas' shops.
    html = htmlmod.unescape(_home(client, "en", "?area=Nowhere"))
    picks = _section(html, "picks", "areas")
    assert "Anna Fresh" not in picks
    assert t_for("en")("hp.picks_empty_t") in picks


# --- 6. empty states with no data ----------------------------------------------


def test_empty_homepage_has_honest_empty_states(tmp_path):
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    assert t("hp.picks_empty_t") in _section(html, "picks", "areas")
    assert t("hp.shops_empty_t") in _section(html, "shops", "value")
    assert t("hp.areas_empty_t") in _section(html, "areas", "shops")
    assert 'href="/new"' in _section(html, "picks", "areas")
    assert 'class="pick-card"' not in html
    assert 'class="shop-card"' not in html


# --- 7. no stock photos inside product or shop cards ----------------------------


def test_no_landing_photos_in_product_or_shop_cards(tmp_path):
    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = _home(client, "en")
    for section, nxt in (("picks", "areas"), ("shops", "value"),
                         ("areas", "shops")):
        body = _section(html, section, nxt)
        assert "landing/" not in body, section
        assert "Unsplash" not in body, section


# --- 8. strip, header, hero, banner, meta ---------------------------------------


def test_strip_and_header(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en", "?area=Koyambedu"))
    t = t_for("en")
    strip = _section(html, "strip", "hero")
    assert "Koyambedu" in strip
    assert t("hp.strip_today") in strip
    assert "data-chooser-open" in strip
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    for href in ("/market", "#picks", "#areas", "#sellers", "#how"):
        assert f'href="{href}"' in head, href
    assert 'href="/new"' in head
    assert t("hp.free") in head
    assert 'href="/my"' in head
    assert "data-ui-toggle" in head
    assert "data-menu-open" in head


def test_hero_headline_names_area_or_default(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    t = t_for("en")
    html = htmlmod.unescape(_home(client, "en"))
    hero = _section(html, "hero", "banner")
    assert t("hp.hero_a") in hero
    assert t("hp.hero_default") in hero
    assert "curve" in hero  # soft purple curve under the place name
    html = htmlmod.unescape(_home(client, "en", "?area=Koyambedu"))
    assert "Koyambedu" in _section(html, "hero", "banner")
    assert t("hp.hero_sub") in _section(html, "hero", "banner")


def test_banner_and_meta_mention(tmp_path):
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    banner = _section(html, "banner", "picks")
    assert t("hp.banner_t1") in banner
    assert t("hp.banner_t2") in banner
    assert t("hp.banner_d") in banner
    assert 'href="/new"' in banner
    meta = _section(html, "meta", "footer")
    assert "/e/<token>/ai" in meta


# --- 9. area chooser: modal + privacy-safe JS ----------------------------------


def test_area_chooser_modal_and_tiles(tmp_path):
    from app.web.i18n import t_for

    seed_market(tmp_path)
    client = make_client(tmp_path)
    html = htmlmod.unescape(_home(client, "en"))
    t = t_for("en")
    assert 'id="area-chooser"' in html
    modal = html.split('id="area-chooser"')[1]
    assert t("hp.chooser_t") in modal
    assert t("hp.chooser_d") in modal
    assert t("hp.detect") in modal
    assert t("hp.skip") in modal
    assert "Koyambedu" in modal and "Anna Nagar" in modal
    assert t("hp.area_counts", n=2, m=6) in modal
    assert "data-area-lat" in modal and "data-area-lng" in modal
    assert "home.js" in html


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
    css = APP_CSS.read_text()
    blocks = [block for block in
              re.split(r"@media\s*\(max-width:\s*600px\)", css)[1:]]
    assert blocks, "missing <=600px media query"
    joined = "\n".join(block.split("@media")[0] for block in blocks)
    assert ".hdr .shop-id" in joined
    assert "flex-basis: 100%" in joined
    assert "order:" in joined
    assert ".hdr .shop-name" in joined
    assert "overflow-wrap: break-word" in joined


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
    assert t("hp.picks_t") in html
    assert t("hp.areas_t") in html
    assert t("hp.shops_t") in html
    # Tamil text must wrap, never be cut: no nowrap on homepage text.
    css = APP_CSS.read_text()
    home_css = css.split("/* Task 84 homepage */")[1]
    assert "overflow-wrap" in home_css
    assert "white-space: nowrap" not in home_css
