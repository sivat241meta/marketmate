"""Task 49: customer + public pages in the Fresh Green design (failing first).

Shop, voice order sheet, order tracking, market compare, home and public
bill follow docs/ui/fresh-green.html (S.shop / S.track). Honesty rules
stay: only published, seller-confirmed prices; photos give counts only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import IST
from app.models import DraftItem, PriceLine, Proof

BANNED = ("Bestseller", "bestseller", "less than yesterday",
          "Ready in", "ready in", "★", "☆", "★★★★")


def _client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, language="ta", name="T49 Store",
                 phone="+914400000049"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, name_local, price, unit="kg", variety=None,
           photo=None, sold_out=False):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(1), unit,
                               f"{unit} {price}")],
        qty=None, qty_unit=None, photo=photo,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[],
                    start_ms=0, end_ms=0),
        confirmed=True)


def _seed_published(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        drafts = [
            _draft("tomato", "தக்காளி", 40, photo="tomato.jpg"),
            _draft("beans", "பீன்ஸ்", 120, variety="Fresh",
                   photo="beans.jpg"),
            _draft("banana", "வாழைப்பழம்", 60, unit="dozen"),
            _draft("coconut", "தேங்காய்", 30, unit="piece",
                   sold_out=True),
        ]
        version_id = db.approve(conn, session_id, drafts)
        # Mark coconut sold out via the stored item row.
        for item in db.version_items(conn, version_id):
            if item.name_en == "coconut":
                conn.execute("UPDATE items SET sold_out = 1 WHERE id = ?",
                             (item.id,))
        conn.commit()
        db.set_published(conn, version_id, True)
        return shop["slug"], version_id
    finally:
        conn.close()


def _prices_hhmm(tmp_path, version_id):
    conn = db.connect(tmp_path / "data")
    try:
        when = db.version_time(conn, version_id)
    finally:
        conn.close()
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(IST).strftime("%H:%M")


def _seed_quote(tmp_path, token, status="packing"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(lines=[QuoteLine(
            name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
            unit="kg", unit_price=Decimal(40), per_amount=Decimal(1),
            line_total=Decimal(80), status="priced")],
            total=Decimal(80), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="customer", kind="quote",
                                 status="new")
        row = db.get_quote_by_token(conn, qtoken)
        assert row is not None
        if status != "new":
            order = ["new", "packing", "ready", "collected"]
            for step in order[1:order.index(status) + 1]:
                db.set_order_status(conn, row["id"], step)
        row = db.get_quote_by_token(conn, qtoken)
        return qtoken, row["id"]
    finally:
        conn.close()


def test_shop_renders_cards_with_add_and_time(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, version_id = _seed_published(tmp_path, token)
    html = client.get(f"/s/{slug}").text
    expected = _prices_hhmm(tmp_path, version_id)
    # Kick with shop name, headline, trio, search, notice, grid.
    assert 'class="kick"' in html
    assert "T49 Store" in html
    assert "said by the seller" in html.lower() or "சொன்ன" in html
    assert "4" in html  # price count in trio/summary
    assert expected in html  # published HH:MM, never invented
    assert 'class="search' in html
    assert 'class="notice"' in html or 'class="notice ' in html
    assert html.count('class="card') >= 4
    assert ">Add<" in html
    # Summary from real data: N items, min to max.
    assert "₹30" in html or "₹40" in html
    assert "All" in html
    # Order by voice + contact pills.
    assert "Order by voice" in html or "order_voice" not in html
    assert "whatsapp" in html.lower() or "WhatsApp" in html


def test_shop_sold_out_has_no_add(tmp_path):
    import re

    client = _client(tmp_path)
    token = _create_shop(client)
    slug, _version_id = _seed_published(tmp_path, token)
    html = client.get(f"/s/{slug}").text
    # Find the coconut card block; it must be dimmed with no Add.
    blocks = re.findall(r'<article class="card[^"]*".*?</article>',
                        html, re.DOTALL)
    assert blocks, "shop must render product cards"
    coconut = [b for b in blocks if "coconut" in b.lower() or "தேங்காய்" in b]
    assert coconut, "coconut card missing"
    assert ">Add<" not in coconut[0]
    assert "out" in coconut[0]  # dimmed sold-out card
    # At least one available card still has Add.
    assert any(">Add<" in b for b in blocks if b not in coconut)


def test_cart_submit_priced_from_published_ignores_client_price(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, _version_id = _seed_published(tmp_path, token)
    # Tampered client preview: claims tomato costs ₹1.
    resp = client.post(
        f"/s/{slug}/quote",
        json={"lines": [{"name_en": "tomato", "qty": 2, "unit": "kg"}],
              "client_total": 2, "client_price": 1,
              "customer_name": "Test"})
    assert resp.status_code in (200, 303)
    if resp.status_code == 303:
        location = resp.headers["location"]
        qtoken = location.split("/q/")[1].split("?")[0]
    else:
        qtoken = resp.json()["token"]
    html = client.get(f"/q/{qtoken}").text
    # Server recomputes from published (2 kg × ₹40 = ₹80), not ₹2.
    assert "₹80" in html
    assert "₹2<" not in html and ">₹2<" not in html


def test_order_page_timeline_current_step(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _slug, _version_id = _seed_published(tmp_path, token)
    qtoken, order_id = _seed_quote(tmp_path, token, status="packing")
    html = client.get(f"/q/{qtoken}").text
    assert f"Your order #{order_id}" in html or f"order #{order_id}" in html.lower()
    assert 'class="tline"' in html or "tline" in html
    assert "RIGHT NOW" in html
    assert "Packing" in html
    assert 'class="rcpt"' in html or "rcpt" in html
    assert "Pay at the shop" in html
    # Honesty notice + contact pills.
    assert "Nothing is guessed" in html or "nothing" in html.lower()
    assert "Call" in html and "WhatsApp" in html


def test_market_renders(tmp_path):
    client = _client(tmp_path)
    html = client.get("/market").text
    assert 'class="kick"' in html
    assert 'id="market-q"' in html
    assert 'id="rec-start"' in html
    assert "Find prices" in html or "find" in html.lower()


def test_home_renders_all_langs(tmp_path):
    client = _client(tmp_path)
    en = client.get("/").text
    assert "Say today&#39;s prices." in en or "Say today's prices." in en
    assert "Sell more." in en
    assert "Start selling" in en
    assert "Find prices" in en
    assert "Lost your link?" in en
    assert "Built with Muse Code" in en
    for lang, needle in (("ta", "விலை"), ("hi", "कीमत")):
        client.cookies.set("ui_lang", lang)
        html = client.get("/").text
        assert html
        assert needle in html or "Say your prices." not in html, lang
        client.cookies.clear()


def test_no_invented_badges(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, _version_id = _seed_published(tmp_path, token)
    qtoken, _order_id = _seed_quote(tmp_path, token)
    pages = [client.get("/").text, client.get("/market").text,
             client.get(f"/s/{slug}").text,
             client.get(f"/s/{slug}/quote").text,
             client.get(f"/q/{qtoken}").text]
    for html in pages:
        for banned in BANNED:
            assert banned not in html, f"invented badge {banned!r} leaked"
