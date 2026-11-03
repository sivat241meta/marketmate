"""Task 127: design v13 — swiggy.com-style landing in teal + soft blue.

Pins the v13 tokens + Jakarta font, the homepage section order with
real-data service cards, the white sticky header hooks on inner
pages, shop-row tiles/ADD/seller's-words, the honesty strings (no
invented ratings/ETAs/discounts), the reduced-motion rule and the
PUBLIC_BASE_URL QR band.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from test_task84 import draft, make_client, seed_shop

ROOT = Path(__file__).resolve().parent.parent
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"
JAKARTA = ROOT / "app" / "web" / "static" / "fonts" / "PlusJakartaSans-Variable.ttf"


def _seed(tmp_path):
    seed_shop(tmp_path, "T127 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30"),
               draft("onion", "வெங்காயம்", "40")])
    return make_client(tmp_path)


def test_v13_tokens_and_jakarta_fontface():
    assert JAKARTA.is_file()
    css = V13_CSS.read_text()
    flat = css.replace(" ", "")
    assert "@font-face" in css
    assert '"Plus Jakarta Sans"' in css
    assert "PlusJakartaSans-Variable.ttf" in css
    assert "--teal:#0F766E" in flat
    assert "--tile:#EEF3F5" in flat
    assert "--dark:#0B2A33" in flat
    assert "--blue:#0369A1" in flat
    assert "--blue-soft:#E8F4FD" in flat


def test_homepage_section_order(tmp_path):
    html = _seed(tmp_path).get(
        "/", headers={"referer": "http://testserver/market"}).text
    marks = ['<header class="topbar">', 'class="svc-row"',
             'id="fresh"', 'id="cats"', 'id="shops"', 'id="lowest"',
             'id="how"', 'id="app"', 'id="markets"', 'class="foot"']
    pos = [html.index(mark) for mark in marks]
    assert pos == sorted(pos), marks
    # The three service cards link to /market, voice entry, /new.
    assert 'class="svc" href="/market' in html
    assert 'class="svc" href="/new"' in html
    assert "data-search-voice" in html
    # Judges must see the Meta model names on the homepage.
    assert "muse-voice-transcribe-1.0" in html
    assert "muse-spark-1.3" in html
    assert "sam-3.1" in html
    # The app band carries a real QR image.
    assert 'id="app"' in html and 'src="/app-qr.png"' in html


def test_sticky_header_on_inner_pages_keeps_hooks(tmp_path):
    client = _seed(tmp_path)
    for url in ("/market", "/s/t127-veg"):
        html = client.get(url).text
        head = re.search(r'<header id="site-header".*?</header>', html,
                         re.DOTALL).group(0)
        assert "stickybar solid" in head
        for hook in ("data-loc-open", "data-search-open",
                     "data-bag-count", "data-menu-open",
                     "data-ui-toggle"):
            assert hook in head, (url, hook)


def test_shop_row_tile_add_and_words_only_when_present(tmp_path):
    from app.models import PriceLine

    said = draft("tomato", "தக்காளி", "30")
    silent = draft("onion", "வெங்காயம்", "40")
    silent.price_lines[0] = PriceLine(Decimal(40), Decimal(1), "kg", "")
    seed_shop(tmp_path, "T127 Veg", "Koyambedu", [said, silent])
    html = make_client(tmp_path).get("/s/t127-veg").text
    assert html.count('class="pic"') == 2
    assert html.count('class="add-pill" data-add') == 2
    assert "\u201c30 said\u201d" in html
    rows = re.findall(r'<article class="row.*?</article>', html, re.DOTALL)
    assert len(rows) == 2
    assert sum("said-link" in row for row in rows) == 1


def test_no_invented_strings(tmp_path):
    client = _seed(tmp_path)
    pages = [client.get("/").text,
             client.get("/market?q=tomato").text,
             client.get("/s/t127-veg").text]
    for html in pages:
        low = html.lower()
        assert "rating" not in low
        assert "\u2605" not in html
        assert "mins" not in low
        assert "% off" not in low


def test_reduced_motion_rule_present():
    css = V13_CSS.read_text() + SHOP13_CSS.read_text()
    assert "prefers-reduced-motion" in css


def test_hero_uses_unclashed_classes(tmp_path):
    # Task 127 polish: app.css owns .hero (card) and .float (dark
    # bar), so the v13 hero uses v13-hero/hero-float instead.
    html = _seed(tmp_path).get(
        "/", headers={"referer": "http://testserver/market"}).text
    assert 'class="v13-hero"' in html
    assert "hero-float" in html
    assert 'class="float' not in html
    assert 'class="hero"' not in html
    css = V13_CSS.read_text()
    assert re.search(r"\.hero\{", css) is None
    assert re.search(r"\.float\{", css) is None


def test_voice_card_clearance_css():
    # Task 127 polish: one bubble above the mic, and the Tamil pill
    # wraps left of it instead of running underneath. Task 133 moves
    # the bubble's right edge onto the mic's (right:26px).
    css = V13_CSS.read_text()
    flat = css.replace(" ", "")
    assert ".art-voice.b1{bottom:118px;right:26px}" in flat
    assert ".svc-pill:lang(ta){max-width:160px}" in flat


def test_shop_has_no_green_notice_box(tmp_path):
    # Task 127 polish: the green "Prices set by the seller" box is
    # gone from real shop pages; the info card + top strip stay.
    html = _seed(tmp_path).get("/s/t127-veg").text
    assert "Prices set by the seller" not in html
    assert "spoken and checked" not in html
    assert 'class="info-card"' in html


def test_sample_shop_keeps_tag_and_honest_note(tmp_path):
    # Task 127 polish: sample pages keep the SAMPLE SHOP tag and the
    # blue honest-note instead of the green box.
    from scripts import seed_samples

    seed_samples.seed(tmp_path / "data",
                      ROOT / "scripts" / "sample_data",
                      "http://localhost:8000")
    html = make_client(tmp_path).get("/s/green-basket").text
    assert "Prices set by the seller" not in html
    assert "tag-sample" in html
    assert "honest-note" in html


def test_shop_row_capitalises_english_name(tmp_path):
    html = _seed(tmp_path).get("/s/t127-veg").text
    assert "<small>Tomato</small>" in html
    assert "<small>Onion</small>" in html
    assert "<small>tomato</small>" not in html


def test_market_chips_are_one_scroll_row(tmp_path):
    # Task 127 polish: area chips scroll horizontally under the
    # query pill + Filters chip instead of stacking.
    html = _seed(tmp_path).get("/market").text
    assert 'class="mkt-chips"' in html
    assert html.index("mkt-tools") < html.index("mkt-chips")
    css = V13_CSS.read_text()
    chips = re.search(r"body\.v13 \.mkt-chips\{[^}]*\}",
                      css).group(0).replace(" ", "")
    assert "flex-wrap:nowrap" in chips
    assert "overflow-x:auto" in chips
    assert "scroll-snap-type:xmandatory" in chips
    assert "scrollbar-width:none" in chips


def test_qr_uses_public_base_url(tmp_path):
    from app.outputs.qr import qr_png

    client = _seed(tmp_path)
    resp = client.get("/app-qr.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content == qr_png(client.app.state.settings.public_base_url)
