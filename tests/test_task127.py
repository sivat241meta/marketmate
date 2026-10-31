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
    html = _seed(tmp_path).get("/").text
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


def test_qr_uses_public_base_url(tmp_path):
    from app.outputs.qr import qr_png

    client = _seed(tmp_path)
    resp = client.get("/app-qr.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content == qr_png(client.app.state.settings.public_base_url)
