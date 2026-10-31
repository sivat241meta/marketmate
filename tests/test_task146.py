"""Task 146: Tamil shop page and bill grid fit phone screens.

1. Every horizontal scroller (.deal-cards, .filters, fresh/category/shop/
   lowest rows, market chips/tabs/filter-row) and its parents carry
   min-width:0 + max-width:100%, so they scroll inside 320/390px screens
   instead of growing to their Tamil/Hindi content (flex/grid
   min-width:auto blowout).
2. The bills tap grid uses minmax(0, 1fr) columns with min-width:0 cards;
   the chip row wraps and long Tamil names wrap without overflow.
3. All "Shop by category" tiles are exactly the same height (the Greens
   full-bleed photo tile included) so labels share one baseline.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_bills import make_client as bills_client
from test_task84 import draft as market_draft
from test_task84 import make_client as market_client
from test_task84 import seed_shop

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"


def _bodies_for(css: str, selector: str) -> str:
    """Joined normalised bodies of every rule mentioning *selector*."""
    found = []
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        if selector in match.group(1):
            found.append(match.group(2))
    assert found, selector
    return "".join(found).replace(" ", "").lower()


def _assert_shrink(css: str, selector: str) -> None:
    body = _bodies_for(css, selector)
    assert "min-width:0" in body, selector
    assert "max-width:100%" in body, selector


# --- 1. scrollers + parents shrink -------------------------------------------


def test_shop_scrollers_shrink():
    css = SHOP13_CSS.read_text()
    for selector in ("body.v13 .deal-cards", "body.v13 .filters"):
        _assert_shrink(css, selector)
    assert "overflow-x:auto" in _bodies_for(css, "body.v13 .deal-cards")
    for parent in ("body.v13 .menu-wrap", "body.v13 .deals"):
        _assert_shrink(css, parent)


def test_home_and_market_scrollers_shrink():
    css = V13_CSS.read_text()
    for selector in (
        "body.v13 .scroller",
        "body.v13 .fresh-grid",
        "body.v13 .cat-row",
        "body.v13 .shop-row",
        "body.v13 .deal-row",
        "body.v13 .mkt-chips",
        "body.v13 .mkt-tabs",
        "body.v13 .filter-row",
    ):
        _assert_shrink(css, selector)
    for parent in (
        "body.v13 .wrap",
        "body.v13 .sec",
        "body.v13 .sec-head",
        "body.v13 .mkt-main",
        "body.v13 .mkt-sec",
    ):
        _assert_shrink(css, parent)


# --- 1b. footer columns wrap long Tamil words -------------------------------
# The 442px Tamil page width came from a footer link column: a single
# long word spilled past its 1fr track (flex items + no soft breaks).


def test_footer_columns_wrap():
    css = V13_CSS.read_text()
    col = _bodies_for(css, "body.v13 .foot-col")
    assert "overflow-wrap:anywhere" in col or "overflow-wrap:break-word" in col
    assert "min-width:0" in _bodies_for(css, "body.v13 .foot-col>*")


# --- 2. bills tap grid --------------------------------------------------------


def test_bills_grid_columns_shrink():
    css = APP_CSS.read_text()
    grids = _bodies_for(css, ".grid-products")
    assert "minmax(0,1fr)" in grids or "min(112px,100%)" in grids
    assert "repeat(3,1fr)" not in grids.replace("minmax(0,1fr)", "")
    for selector in (".grid-products .card", ".tap-grid .card"):
        assert "min-width:0" in _bodies_for(css, selector), selector
    assert "flex-wrap:wrap" in _bodies_for(css, ".quick-chips")
    assert "minmax(0,1fr)" in _bodies_for(css, ".bill-split")


def test_tap_names_wrap_without_overflow():
    css = APP_CSS.read_text()
    assert "overflow-wrap" in _bodies_for(css, ".card .nm")
    assert "flex-wrap:wrap" in _bodies_for(css, ".card .pr")


# --- 3. equal category tiles --------------------------------------------------


def test_category_tiles_equal_height():
    css = V13_CSS.read_text()
    tile = _bodies_for(css, "body.v13 .cat .tile")
    photo = _bodies_for(css, "body.v13 .cat .tile.photo")
    assert "height:150px" in tile
    assert "height:150px" in photo
    assert "aspect-ratio" not in photo
    phone = css.split("@media (max-width:700px)", 1)[1]
    phone_tile = _bodies_for(phone, ".cat .tile")
    phone_photo = _bodies_for(phone, ".cat .tile.photo")
    assert "height:112px" in phone_tile
    assert "height:112px" in phone_photo


# --- 4. rendered pages carry no wide fixed widths -----------------------------

_WIDE_STYLE = re.compile(
    r'style="[^"]*(?:^|[;\s])(?:width|min-width)\s*:\s*(\d+)px')
_WIDTH_ATTR = re.compile(r"<(?!img\b)[a-z][^>]*?\swidth=\"(\d+)\"")


def _assert_no_wide_fixed_widths(html: str) -> None:
    for match in _WIDE_STYLE.finditer(html):
        assert int(match.group(1)) <= 390, match.group(0)[:80]
    for match in _WIDTH_ATTR.finditer(html):
        assert int(match.group(1)) <= 390, match.group(0)[:80]


def test_tamil_shop_and_bill_pages_have_no_wide_fixed_widths(tmp_path):
    slug, token = seed_shop(tmp_path, "T146 Veg", "Koyambedu", [
        market_draft("cabbage", "முட்டைகோஸ்", "30"),
        market_draft("small onion", "சின்ன வெங்காயம்", "35"),
        market_draft("greens", "கீரை", "20"),
    ])
    client = market_client(tmp_path)
    shop = client.get(f"/s/{slug}?lang=ta")
    assert shop.status_code == 200
    assert "முட்டைகோஸ்" in shop.text
    assert "deal-cards" in shop.text and "filters" in shop.text
    _assert_no_wide_fixed_widths(shop.text)

    seller = bills_client(tmp_path)
    seller.cookies.set("ui_lang", "ta")
    bills = seller.get(f"/e/{token}/bills/new")
    assert bills.status_code == 200
    assert "grid-products tap-grid" in bills.text
    _assert_no_wide_fixed_widths(bills.text)
