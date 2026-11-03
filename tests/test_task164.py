"""Task 164: the seller's own photo comes first on every shop item.

Own photo wins everywhere a specific shop's item is shown; the v13
cut-out is only the fallback with no own photo; otherwise the letter
tile. Generic category art keeps the cut-outs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    monkeypatch.setenv("SHOW_EXTRAS", "1")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def draft(name_en, name_local, price, photo=None):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg",
                               f"{price} said")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"said {name_en}", turn_ids=[1], start_ms=0,
                    end_ms=500, audio_clip="/tmp/clip.m4a"),
        confirmed=True, photo=photo)


def seed_shop(tmp_path):
    """Banana has its own photo, onion only a cut-out name, watermelon
    neither (no stock cut-out exists for it)."""
    items = [
        draft("banana", "வாழைப்பழம்", "60",
              photo="data/photos/banana_own.jpg"),
        draft("onion", "வெங்காயம்", "35"),
        draft("watermelon", "தர்பூசணி", "25"),
    ]
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name="Own Photo Veg", phone="+914400000001",
            area="Koyambedu", language="ta", currency="INR",
            shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, items)
        db.set_published(conn, version_id, True)
    finally:
        conn.close()
    return slug, token


def _chunk(html, marker, name, end=None):
    parts = [part for part in html.split(marker) if name in part]
    assert parts, name
    out = parts[0]
    return out.split(end)[0] if end else out


def _after_attr(html, attr, name, length=600):
    """HTML right after the opening tag whose attr value mentions name."""
    start = 0
    while True:
        pos = html.find(attr + '="', start)
        assert pos != -1, name
        end = html.index('"', pos + len(attr) + 2)
        if name.lower() in html[pos:end].lower():
            close = html.index(">", end) + 1
            return html[close:close + length]
        start = end


def test_shop_page_own_photo_first(tmp_path):
    slug, _token = seed_shop(tmp_path)
    html = make_client(tmp_path).get(f"/s/{slug}").text
    banana = _chunk(html, "<article", 'data-name-en="banana"',
                    "</article>")
    assert "/m/banana_own.jpg" in banana
    assert "data-cutout" not in banana
    assert "/static/img/v13/banana.webp" not in html
    onion = _chunk(html, "<article", 'data-name-en="onion"',
                   "</article>")
    assert "/static/img/v13/onion.webp" in onion
    assert "data-cutout" in onion
    melon = _chunk(html, "<article", 'data-name-en="watermelon"',
                   "</article>")
    assert "<img" not in melon
    assert "til-g" in melon


def test_prices_page_own_photo_first(tmp_path):
    _slug, token = seed_shop(tmp_path)
    html = make_client(tmp_path).get(f"/e/{token}").text
    banana = _after_attr(html, "data-search-row", "banana")
    assert "/m/banana_own.jpg" in banana
    onion = _after_attr(html, "data-search-row", "onion")
    assert "/static/img/v13/onion.webp" in onion
    melon = _after_attr(html, "data-search-row", "watermelon")
    assert "<img" not in melon
    assert "list-thumb letter" in melon


def test_tap_items_grid_own_photo_first(tmp_path):
    _slug, token = seed_shop(tmp_path)
    html = make_client(tmp_path).get(f"/e/{token}/bills/new").text
    banana = _after_attr(html, "data-search-row", "banana")
    assert "/m/banana_own.jpg" in banana
    assert "/static/img/v13/banana.webp" not in html
    onion = _after_attr(html, "data-search-row", "onion")
    assert "/static/img/v13/onion.webp" in onion
    melon = _after_attr(html, "data-search-row", "watermelon")
    assert "<img" not in melon
    assert "til-g" in melon


def test_order_view_own_photo_first(tmp_path, monkeypatch):
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json({
            "wants": [
                {"name": "banana", "amount": 1, "unit": "dozen",
                 "max_rate": None},
                {"name": "onion", "amount": 1, "unit": "kg",
                 "max_rate": None},
                {"name": "watermelon", "amount": 1, "unit": "kg",
                 "max_rate": None},
            ],
            "budget": None, "area": None}))
    slug, _token = seed_shop(tmp_path)
    client = make_client(tmp_path)
    location = client.post(
        f"/s/{slug}/quote",
        data={"items": "banana, onion, watermelon",
              "customer_name": "Test"}).headers["location"]
    html = client.get(location).text
    assert "/m/banana_own.jpg" in html
    assert "/static/img/v13/banana.webp" not in html
    assert "/static/img/v13/onion.webp" in html
    # Watermelon has neither photo nor cut-out: no third thumbnail.
    assert html.count("line-thumb") == 2


def test_market_best_price_row_own_photo_first(tmp_path, monkeypatch):
    from decimal import Decimal as _Decimal

    from app.market.search import Query, Want

    seed_shop(tmp_path)
    client = make_client(tmp_path)
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")

    def _market_for(name):
        monkeypatch.setattr(
            "app.web.main.parse_query",
            lambda text, **_kw: Query(
                [Want(name, _Decimal(1), "kg", None)], None, None))
        html = client.get(f"/market?q={name}").text
        return html.split("results-grid", 1)[1]

    banana = _market_for("banana")
    assert "/m/banana_own.jpg" in banana
    assert "/static/img/v13/banana.webp" not in banana
    onion = _market_for("onion")
    assert "/static/img/v13/onion.webp" in onion


def test_review_page_own_photo_first(tmp_path):
    _slug, token = seed_shop(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.ensure_session_base(conn, session_id)
        db.save_drafts(conn, session_id, [
            draft("banana", "வாழைப்பழம்", "60",
                  photo="data/photos/banana_own.jpg"),
            draft("onion", "வெங்காயம்", "35"),
        ])
        db.set_session_status(conn, session_id, "review", "seeded")
    finally:
        conn.close()
    html = make_client(tmp_path).get(f"/e/{token}/s/{session_id}").text
    assert "/m/banana_own.jpg" in html
    assert "/static/img/v13/banana.webp" not in html
    assert "/static/img/v13/onion.webp" in html


def test_home_category_art_keeps_cutouts(tmp_path):
    seed_shop(tmp_path)
    html = make_client(tmp_path).get("/").text
    cats = html.split('id="cats"')[1].split('id="shops"')[0]
    for stem in ("cauliflower", "tomato", "capsicum",
                 "papaya", "apple", "guava"):
        assert f"/static/img/v13/{stem}.webp" in cats, stem
    assert "/m/banana_own.jpg" not in cats
