"""Task 60: close the order loop (alert, name/phone, ready, my orders, sold-out).

Failing-tests-first: pending.json counts + owner-only permission, alert
script hooks + node --check + latest_id decision, name required / phone
validation / stored / shown, ready WhatsApp text, status.json, /my in
en/ta/hi, sold-out flagging of open orders, remove recomputes the total.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
QUOTE = "t60 tomato secret"


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, name="T60 Stall", phone="+914400000060",
                language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def draft(name_en, price, per_amount=1, unit="kg", local="தக்காளி",
          variety=None):
    return DraftItem(
        name_spoken=name_en, name_local=local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None, qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def publish(tmp_path, token, drafts) -> int:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def slug_of(tmp_path, token) -> str:
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def seed_order(tmp_path, token, *, status="new", name_en="tomato",
               qty=2, unit="kg", unit_price=20, variety=None,
               customer_name=None, customer_phone=None):
    """Seed one customer order; returns (quote_token, order_id)."""
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        line_total = Decimal(qty) * Decimal(unit_price)
        quote = Quote(
            lines=[QuoteLine(
                name_en=name_en, name_local="தக்காளி", qty=Decimal(qty),
                unit=unit, unit_price=Decimal(unit_price),
                per_amount=Decimal(1), line_total=line_total,
                status="priced", variety=variety)],
            total=line_total, priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(
            conn, shop_id=shop["id"], quote=quote, source="customer",
            kind="quote", status=status, customer_name=customer_name,
            customer_phone=customer_phone)
        row = db.get_quote_by_token(conn, qtoken)
        return qtoken, row["id"]
    finally:
        conn.close()


def add_helper(client, token, name="Meena") -> str:
    import re

    resp = client.post(f"/e/{token}/settings/helpers", data={"name": name})
    assert resp.status_code == 200, resp.text
    for chunk in resp.text.split("/e/")[1:]:
        match = re.match(r"[A-Za-z0-9_-]+", chunk)
        if match and match.group(0) != token:
            return match.group(0)
    raise AssertionError("one-time helper link missing")


# --- 1. pending.json ----------------------------------------------------------


def test_pending_json_counts_new_only(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    _, first = seed_order(tmp_path, token, status="new")
    _, second = seed_order(tmp_path, token, status="new")
    seed_order(tmp_path, token, status="packing")
    seed_order(tmp_path, token, status="collected")
    resp = client.get(f"/e/{token}/orders/pending.json")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new"] == 2
    assert body["latest_id"] == max(first, second)
    assert [entry["id"] for entry in body["orders"]] == [first, second]
    entry = body["orders"][0]
    assert set(entry) >= {"id", "label", "total", "at"}
    assert f"Order #{first}" in entry["label"]


def test_pending_json_empty(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    resp = client.get(f"/e/{token}/orders/pending.json")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"new": 0, "latest_id": None, "orders": []}


def test_pending_json_helper_forbidden_and_unknown_404(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    staff = add_helper(client, token)
    assert client.get(f"/e/{staff}/orders/pending.json").status_code == 403
    assert client.get("/e/no-such-token/orders/pending.json").status_code == 404


# --- 1b. alert script hooks + node --------------------------------------------


def test_seller_pages_include_alert_hooks(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    for url in (f"/e/{token}", f"/e/{token}/bills"):
        html = client.get(url).text
        assert "order-alert.js" in html, url
        assert "data-pending-url" in html, url
        assert html.count("data-orders-badge") >= 2, url
        assert "data-sound-toggle" in html, url
        assert "data-order-banner" in html, url


def test_changed_js_passes_node_check():
    node = shutil.which("node")
    assert node, "node is required for --check"
    for name in ("order-alert.js", "order-status.js", "my.js",
                 "customer-contact.js"):
        path = ROOT / "app" / "web" / "static" / name
        assert path.is_file(), name
        proc = subprocess.run([node, "--check", str(path)], check=False,
                              capture_output=True, text=True)
        assert proc.returncode == 0, name + proc.stderr


def test_latest_id_grew_decision_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/order_alert.test.mjs"], cwd=ROOT, check=False,
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- 2. customer name + phone -------------------------------------------------


_CART_N = iter(range(50, 250))


def post_cart(client, slug, payload):
    ip = f"10.60.60.{next(_CART_N)}"
    return client.post(f"/s/{slug}/quote", json=payload,
                       headers={"x-forwarded-for": ip})


def test_cart_requires_name(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = slug_of(tmp_path, token)
    publish(tmp_path, token, [draft("tomato", 40)])
    lines = [{"name_en": "tomato", "qty": 1, "unit": "kg"}]
    assert post_cart(client, slug, {"lines": lines}).status_code == 400
    assert post_cart(
        client, slug, {"lines": lines, "customer_name": "  "}).status_code == 400
    assert post_cart(
        client, slug,
        {"lines": lines, "customer_name": "x" * 41}).status_code == 400
    ok = post_cart(client, slug, {"lines": lines, "customer_name": "Priya"})
    assert ok.status_code == 200, ok.text


def test_cart_phone_validation(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = slug_of(tmp_path, token)
    publish(tmp_path, token, [draft("tomato", 40)])
    lines = [{"name_en": "tomato", "qty": 1, "unit": "kg"}]
    for bad in ("123", "abcdefghij", "5123456789", "+91", "98765 4321x"):
        resp = post_cart(client, slug, {"lines": lines,
                                        "customer_name": "Priya",
                                        "customer_phone": bad})
        assert resp.status_code == 400, (bad, resp.text)
    for good in ("9876543210", "+919876543210", "+1 4155552671"):
        resp = post_cart(client, slug, {"lines": lines,
                                        "customer_name": "Priya",
                                        "customer_phone": good})
        assert resp.status_code == 200, (good, resp.text)


def test_typed_quote_requires_name_and_valid_phone(tmp_path, monkeypatch):
    from app.market.search import parse_query_json
    from tests.test_quote import fake_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(fake_query_json()))
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = slug_of(tmp_path, token)
    publish(tmp_path, token, [draft("tomato", 40)])
    resp = client.post(f"/s/{slug}/quote",
                       data={"items": "2 kg tomato"})
    assert resp.status_code == 400
    resp = client.post(f"/s/{slug}/quote",
                       data={"items": "2 kg tomato", "customer_name": "Priya",
                             "customer_phone": "nope"})
    assert resp.status_code == 400
    resp = client.post(f"/s/{slug}/quote",
                       data={"items": "2 kg tomato", "customer_name": "Priya",
                             "customer_phone": "9876543210"})
    assert resp.status_code in (302, 303), resp.text


def test_contact_stored_and_shown(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = slug_of(tmp_path, token)
    publish(tmp_path, token, [draft("tomato", 40)])
    resp = post_cart(client, slug, {
        "lines": [{"name_en": "tomato", "qty": 1, "unit": "kg"}],
        "customer_name": "Priya", "customer_phone": "9876543210"})
    assert resp.status_code == 200, resp.text
    qtoken = resp.json()["token"]
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_token(conn, qtoken)
        assert row["customer_name"] == "Priya"
        assert row["customer_phone"] == "9876543210"
        order_id = row["id"]
    finally:
        conn.close()
    assert f"Order #{order_id} · Priya" in client.get(
        f"/e/{token}/bills/{order_id}").text
    assert f"Order #{order_id} · Priya" in client.get(
        f"/e/{token}/bills").text


def test_contact_fields_render_with_note(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = slug_of(tmp_path, token)
    publish(tmp_path, token, [draft("tomato", 40)])
    shop_html = client.get(f"/s/{slug}").text
    assert "customer-contact.js" in shop_html
    assert "data-customer-name" in shop_html
    assert "data-customer-phone" in shop_html
    assert "Only this shop sees your number." in shop_html
    start_html = client.get(f"/s/{slug}/quote").text
    assert "customer-contact.js" in start_html
    assert "data-customer-name" in start_html
    assert "Only this shop sees your number." in start_html


# --- 3. ready on WhatsApp + status.json ---------------------------------------


def test_ready_whatsapp_link_text(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client, name="T60 Greens", language="en")
    publish(tmp_path, token, [draft("tomato", 20)])
    _, order_id = seed_order(tmp_path, token, qty=2, unit_price=20,
                             customer_name="Priya",
                             customer_phone="+919876543210")
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "packing"})
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "ready"})
    html = client.get(f"/e/{token}/bills/{order_id}").text
    assert "Tell the customer on WhatsApp" in html
    assert "wa.me/919876543210?text=" in html
    import html as html_lib
    from urllib.parse import unquote

    text = unquote(html_lib.unescape(html))
    assert f"Your order #{order_id} at T60 Greens is ready." in text
    assert "Total ₹40" in text
    assert "Pay by UPI or cash at pickup." in text
    assert "/q/" in text


def test_ready_without_phone_shows_no_phone(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    _, order_id = seed_order(tmp_path, token, customer_name="Priya")
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "packing"})
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "ready"})
    assert "No phone given" in client.get(
        f"/e/{token}/bills/{order_id}").text


def test_status_json_returns_status_and_total(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    qtoken, order_id = seed_order(tmp_path, token, qty=2, unit_price=20)
    body = client.get(f"/q/{qtoken}/status.json").json()
    assert body["status"] == "new"
    assert "40" in str(body["total"])
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "packing"})
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "ready"})
    body = client.get(f"/q/{qtoken}/status.json").json()
    assert body["status"] == "ready"
    assert "40" in str(body["total"])
    assert client.get("/q/no-such-token/status.json").status_code == 404


def test_order_page_polls_status(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    qtoken, _ = seed_order(tmp_path, token)
    html = client.get(f"/q/{qtoken}").text
    assert "order-status.js" in html
    assert f"/q/{qtoken}/status.json" in html
    assert "data-ready-banner" in html


# --- 4. /my -------------------------------------------------------------------


def test_my_renders_en_ta_hi(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    for lang, heading in (("en", "My orders"), ("ta", "என் ஆர்டர்கள்"),
                          ("hi", "मेरे ऑर्डर")):
        client.cookies.set("ui_lang", lang)
        resp = client.get("/my")
        assert resp.status_code == 200, lang
        assert heading in resp.text, lang
        assert "my.js" in resp.text, lang


def test_bag_links_to_my_and_hooks_present(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = slug_of(tmp_path, token)
    publish(tmp_path, token, [draft("tomato", 20)])
    qtoken, _ = seed_order(tmp_path, token)
    shop_html = client.get(f"/s/{slug}").text
    assert 'href="/my"' in shop_html
    assert "data-shop-visit" in shop_html
    assert "my.js" in shop_html
    quote_html = client.get(f"/q/{qtoken}").text
    assert 'href="/my"' in quote_html
    assert "data-order-record" in quote_html


# --- 5. sold out after order --------------------------------------------------


def test_soldout_flags_open_orders_but_not_collected(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20), draft("onion", 30)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        item_id = next(item for item in db.version_items(conn, version_id)
                         if item.name_en == "tomato").id
    finally:
        conn.close()
    ids = {}
    for status in ("new", "packing", "ready", "collected", "cancelled"):
        _, order_id = seed_order(tmp_path, token, status=status)
        ids[status] = order_id
    resp = client.post(f"/e/{token}/item/{item_id}/soldout")
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        for status, order_id in ids.items():
            lines = json.loads(
                db.get_quote_by_id(conn, order_id)["lines_json"])
            flagged = bool(lines[0].get("sold_out"))
            if status in ("new", "packing", "ready"):
                assert flagged, status
            else:
                assert not flagged, status
    finally:
        conn.close()


def test_soldout_notice_and_seller_chip(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    qtoken, order_id = seed_order(tmp_path, token, customer_name="Priya",
                                  customer_phone="+919876543210")
    client.post(f"/e/{token}/item/{item_id}/soldout")
    customer = client.get(f"/q/{qtoken}").text
    assert "Sold out today" in customer
    seller = client.get(f"/e/{token}/bills/{order_id}").text
    assert "Sold out" in seller
    assert "Tell customer" in seller
    assert "wa.me/919876543210?text=" in seller


def test_remove_flagged_line_recomputes_total(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20), draft("onion", 30)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        item_id = next(item for item in db.version_items(conn, version_id)
                         if item.name_en == "tomato").id
    finally:
        conn.close()
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=[
                QuoteLine(name_en="tomato", name_local="தக்காளி",
                          qty=Decimal(2), unit="kg", unit_price=Decimal(20),
                          per_amount=Decimal(1), line_total=Decimal(40),
                          status="priced"),
                QuoteLine(name_en="onion", name_local="வெங்காயம்",
                          qty=Decimal(1), unit="kg", unit_price=Decimal(30),
                          per_amount=Decimal(1), line_total=Decimal(30),
                          status="priced"),
            ],
            total=Decimal(70), priced_count=2, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="customer", kind="quote",
                                 status="new")
        order_id = db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()
    client.post(f"/e/{token}/item/{item_id}/soldout")
    resp = client.post(f"/e/{token}/bills/{order_id}/remove",
                       data={"index": "0"})
    assert resp.status_code in (302, 303), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, order_id)
        assert Decimal(str(row["total"])) == Decimal(30), row["total"]
    finally:
        conn.close()


def test_soldout_still_owner_only(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [draft("tomato", 20)])
    staff = add_helper(client, token)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    assert client.post(
        f"/e/{staff}/item/{item_id}/soldout").status_code == 403
