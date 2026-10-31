"""Task 144: every photo on the site is square.

Shop cards, the shop info cover, seller review photos + thumbnails,
check-result thumbs and the /sellers + /how marketing photos all render
in square boxes (aspect-ratio 1/1, cover for real photos, contain +
padding for cut-outs). The shop card keeps its name-on-photo, SAMPLE
SHOP ribbon and voice-checked badge.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_task84 import _home, _section, draft, make_client, seed_shop

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"
HOME_HTML = ROOT / "app" / "web" / "templates" / "home.html"
MARKET_HTML = ROOT / "app" / "web" / "templates" / "market.html"


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1).replace(" ", "").lower()


def test_photo_boxes_are_square():
    v13 = V13_CSS.read_text()
    assert "aspect-ratio:1/1" in _rule(v13, "body.v13 .shop-photo")
    # Phone cards stay swipeable but the square never exceeds 300px.
    assert "min(82%,300px)" in v13.replace(" ", "").lower()
    assert "max-width:300px" in v13.replace(" ", "").lower()

    app = APP_CSS.read_text()
    assert "aspect-ratio:1/1" in _rule(app, ".review-photo")
    thumb = _rule(app, ".photo-thumb")
    assert "aspect-ratio:1/1" in thumb
    assert "width:72px" in thumb and "height:72px" in thumb
    assert "aspect-ratio:1/1" in _rule(app, ".check-thumb")
    assert "aspect-ratio:1/1" in _rule(app, ".land-photo img")
    assert "aspect-ratio:1/1" in _rule(app, ".land-photo.tall img")
    assert "aspect-ratio:1/1" in _rule(app, ".land-split .land-photo img")
    assert "aspect-ratio:1/1" in _rule(app, ".hp-band-img")
    # The sellers band is two columns (text + square photo) on laptop.
    assert "1fr1fr" in _rule(app, ".hp-band").replace(" ", "")

    shop = SHOP13_CSS.read_text()
    info = _rule(shop, "body.v13 .info-cover")
    assert "width:120px" in info and "height:120px" in info


def test_shop_card_keeps_name_badge_ribbon(tmp_path):
    for src in (HOME_HTML.read_text(), MARKET_HTML.read_text()):
        assert 'class="shop-photo"' in src
        assert 'class="shop-name"' in src
        assert 'class="badge-ok"' in src
        assert 'class="tag-sample"' in src
    seed_shop(tmp_path, "T144 Demo Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "40")], is_demo=True)
    client = make_client(tmp_path)
    shops = _section(_home(client, "en"), "shops", "lowest")
    assert "T144 Demo Veg" in shops
    assert 'class="shop-photo"' in shops
    assert 'class="shop-name"' in shops
    assert 'class="badge-ok"' in shops
    assert 'class="tag-sample"' in shops
    market = client.get("/market", params={"cat": "veg"}).text
    assert "T144 Demo Veg" in market
    assert 'class="shop-photo"' in market
    assert 'class="shop-name"' in market
    assert 'class="badge-ok"' in market
    assert 'class="tag-sample"' in market
