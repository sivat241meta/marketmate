"""Task 41: installable app, offline billing sync, order status, helper link, link recovery."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote as url_quote

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

QUOTE = "t41 tomato secret"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client, name="T41 Stall", phone="+914400000041"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, per_amount=1, unit="kg", local="தக்காளி"):
    return DraftItem(
        name_spoken=name_en, name_local=local, name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None, qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def _publish(tmp_path, token, drafts) -> int:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def _customer_quote(tmp_path, token, lines=None):
    """Seed a customer quote (kind=quote, status=new); returns (quote_token, bill_id)."""
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=lines or [QuoteLine(
                name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
                unit="kg", unit_price=Decimal(20), per_amount=Decimal(1),
                line_total=Decimal(40), status="priced")],
            total=Decimal(40), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="customer", kind="quote", status="new")
        row = db.get_quote_by_token(conn, qtoken)
        return qtoken, row["id"]
    finally:
        conn.close()


# --- PWA -----------------------------------------------------------------


def test_manifest_served_with_json(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200, resp.text
    assert "application/manifest+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["name"] == "MarketMate"
    assert body["short_name"] == "MarketMate"
    assert body["theme_color"] == "#0B2A33"
    assert body["background_color"] == "#F3F8FA"
    assert body["display"] == "standalone"
    assert body["start_url"] == "/"
    sizes = {icon["sizes"] for icon in body["icons"]}
    assert "192x192" in sizes and "512x512" in sizes


def test_sw_served_with_js_content_type(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/sw.js")
    assert resp.status_code == 200, resp.text
    assert "javascript" in resp.headers["content-type"]
    assert resp.headers.get("Service-Worker-Allowed") == "/"
    assert "prices.json" in resp.text


def test_base_links_manifest_and_icons(tmp_path):
    client = _client(tmp_path)
    html = client.get("/").text
    assert 'href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="theme-color"' in html and "#0B2A33" in html


# Task 152: the unreferenced static/icons/icon-*.png files were deleted;
# the served brand icons are pinned by test_task80/test_task95 instead.


def test_dashboard_has_install_hint(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    assert "Install app" in html
    assert "Add to Home Screen" in html


# --- offline prices.json + sync -------------------------------------------


def test_prices_json_requires_seller_token(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft("tomato", 20)])
    resp = client.get("/e/unknown-token-xyz/prices.json")
    assert resp.status_code == 404
    resp = client.get(f"/e/{token}/prices.json")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version_id"] == version_id
    assert body["items"], "expected at least one item"
    item = body["items"][0]
    assert item["id"] and item["name_en"] == "tomato"
    assert item["name_local"] == "தக்காளி"
    assert item["lines"] and item["lines"][0]["price"] == "20"


def test_sync_is_idempotent_on_client_id(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft("tomato", 20)])
    payload = {"bills": [{
        "client_id": str(uuid.uuid4()), "version_id": version_id,
        "lines": [{"name_en": "tomato", "qty": "2", "unit": "kg"}]}]}
    first = client.post(f"/e/{token}/bills/sync", json=payload)
    assert first.status_code == 200, first.text
    second = client.post(f"/e/{token}/bills/sync", json=payload)
    assert second.status_code == 200, second.text
    assert (first.json()["results"][0]["bill_id"]
            == second.json()["results"][0]["bill_id"])
    conn = db.connect(tmp_path / "data")
    try:
        rows = conn.execute(
            "SELECT * FROM quotes WHERE client_id = ?",
            (payload["bills"][0]["client_id"],)).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()


def test_sync_recomputes_from_published_version(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft("tomato", 20)])
    payload = {"bills": [{
        "client_id": str(uuid.uuid4()), "version_id": version_id,
        "lines": [{"name_en": "tomato", "qty": "2", "unit": "kg",
                   "unit_price": "1", "line_total": "2"}]}]}
    resp = client.post(f"/e/{token}/bills/sync", json=payload)
    assert resp.status_code == 200, resp.text
    bill_id = resp.json()["results"][0]["bill_id"]
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, bill_id)
        lines = json.loads(row["lines_json"])
        assert lines[0]["unit_price"] == "20"
        assert lines[0]["line_total"] == "40.00"
        assert Decimal(str(row["total"])) == Decimal(40)
    finally:
        conn.close()


def test_sync_flags_changed_price(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    old_version = _publish(tmp_path, token, [_draft("tomato", 20)])
    # Price changes while the seller is offline: a new list is published.
    _publish(tmp_path, token, [_draft("tomato", 30)])
    payload = {"bills": [{
        "client_id": str(uuid.uuid4()), "version_id": old_version,
        "lines": [{"name_en": "tomato", "qty": "2", "unit": "kg",
                   "unit_price": "20", "line_total": "40.00"}]}]}
    resp = client.post(f"/e/{token}/bills/sync", json=payload)
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["price_changed"] is True
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, result["bill_id"])
        # Never silently repriced to the new Rs 30: kept at the offline Rs 20.
        lines = json.loads(row["lines_json"])
        assert lines[0]["unit_price"] == "20", lines
        assert Decimal(str(row["total"])) == Decimal(40), row["total"]
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills/{result['bill_id']}").text
    assert "price changed while offline" in html.lower()


def test_new_bill_page_has_offline_banner_and_needs_internet(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    html = client.get(f"/e/{token}/bills/new").text
    assert "will sync when you" in html
    assert "needs internet" in html.lower()
    assert "offline-bills.js" in html


# --- order status ----------------------------------------------------------


def test_order_status_transitions(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    _, bill_id = _customer_quote(tmp_path, token)
    for status in ("packing", "ready", "collected"):
        resp = client.post(f"/e/{token}/bills/{bill_id}/order-status",
                           data={"status": status})
        assert resp.status_code in (302, 303), f"{status}: {resp.text}"
    conn = db.connect(tmp_path / "data")
    try:
        assert db.get_quote_by_id(conn, bill_id)["status"] == "collected"
    finally:
        conn.close()
    # Invalid: collected is terminal.
    resp = client.post(f"/e/{token}/bills/{bill_id}/order-status",
                       data={"status": "packing"})
    assert resp.status_code == 400


def test_order_status_invalid_skips_rejected(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    _, bill_id = _customer_quote(tmp_path, token)
    resp = client.post(f"/e/{token}/bills/{bill_id}/order-status",
                       data={"status": "ready"})
    assert resp.status_code == 400, "new -> ready must be rejected"
    resp = client.post(f"/e/{token}/bills/{bill_id}/order-status",
                       data={"status": "billed"})
    assert resp.status_code == 400


def test_customer_page_shows_stepper(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    qtoken, bill_id = _customer_quote(tmp_path, token)
    client.post(f"/e/{token}/bills/{bill_id}/order-status",
                data={"status": "packing"})
    html = client.get(f"/q/{qtoken}").text
    assert "Packing your order" in html
    assert "Ready for pickup" in html


def test_ready_shows_whatsapp_button(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    _, bill_id = _customer_quote(tmp_path, token)
    conn = db.connect(tmp_path / "data")
    try:
        db.set_bill_phone(conn, bill_id, "+919876543210")
    finally:
        conn.close()
    client.post(f"/e/{token}/bills/{bill_id}/order-status",
                data={"status": "packing"})
    client.post(f"/e/{token}/bills/{bill_id}/order-status",
                data={"status": "ready"})
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Tell the customer on WhatsApp" in html
    assert "wa.me/919876543210" in html


def test_bills_page_has_order_filter_chips(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    html = client.get(f"/e/{token}/bills").text
    for chip in ("status=packing", "status=ready", "status=collected"):
        assert chip in html


# --- staff helper link ------------------------------------------------------


def _add_helper(client, token, name="Meena"):
    resp = client.post(f"/e/{token}/settings/helpers", data={"name": name})
    assert resp.status_code == 200, resp.text
    return resp


def _staff_token_from_page(text: str, owner_token: str) -> str | None:
    import re

    for chunk in text.split("/e/")[1:]:
        match = re.match(r"[A-Za-z0-9_-]+", chunk)
        if match and match.group(0) != owner_token:
            return match.group(0)
    return None


def test_helper_create_shows_link_once_and_stores_hash(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    resp = _add_helper(client, token)
    assert "/e/" in resp.text and "Remove" in resp.text
    # Extract the staff token from the one-time link.
    staff_token = _staff_token_from_page(resp.text, token)
    assert staff_token, "one-time helper link missing"
    # Afterwards the link is gone (shown once).
    assert staff_token not in client.get(f"/e/{token}/settings").text
    # Only a hash is stored.
    conn = db.connect(tmp_path / "data")
    try:
        rows = conn.execute("SELECT * FROM helpers").fetchall()
        assert len(rows) == 1 and rows[0]["name"] == "Meena"
        assert staff_token not in (rows[0]["token_hash"] or "")
    finally:
        conn.close()


def test_staff_permissions_matrix(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    _, bill_id = _customer_quote(tmp_path, token)
    resp = _add_helper(client, token)
    staff_token = _staff_token_from_page(resp.text, token)
    assert staff_token
    allowed = [
        ("GET", f"/e/{staff_token}"),
        ("GET", f"/e/{staff_token}/bills"),
        ("GET", f"/e/{staff_token}/bills/new"),
        ("GET", f"/e/{staff_token}/bills/{bill_id}"),
        ("GET", f"/e/{staff_token}/prices.json"),
    ]
    for method, url in allowed:
        got = client.request(method, url)
        assert got.status_code in (200, 303), f"{method} {url} -> {got.status_code}"
    forbidden = [
        ("GET", f"/e/{staff_token}/live"),
        ("GET", f"/e/{staff_token}/photos"),
        ("GET", f"/e/{staff_token}/purchases"),
        ("GET", f"/e/{staff_token}/settings"),
        ("GET", f"/e/{staff_token}/close"),
        ("GET", f"/e/{staff_token}/exports/sales.xlsx"),
        ("GET", f"/e/{staff_token}/update"),
        ("POST", f"/e/{staff_token}/s/1/approve"),
    ]
    for method, url in forbidden:
        kwargs = {"json": {}} if url.endswith("/approve") else {}
        got = client.request(method, url, **kwargs)
        assert got.status_code == 403, f"{method} {url} -> {got.status_code}"
    # Payments + order status allowed.
    got = client.post(f"/e/{staff_token}/bills/{bill_id}/order-status",
                      data={"status": "packing"})
    assert got.status_code in (302, 303, 200), got.status_code
    # Reopen is a billing action: staff may use it.
    got = client.post(f"/e/{staff_token}/bills/{bill_id}/reopen")
    assert got.status_code in (302, 303, 200, 400), got.status_code
    assert got.status_code != 403, "staff reopen must not be forbidden"
    # Tap billing as staff records created_by.
    got = client.post(f"/e/{staff_token}/bills/new", data={
        "name_en_0": "tomato", "qty_0": "1", "unit_0": "kg"})
    assert got.status_code in (302, 303), got.text
    staff_bill_id = int(got.headers["location"].rstrip("/").split("/")[-1])
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, staff_bill_id)
        assert row["created_by"] == "Meena", dict(row)
    finally:
        conn.close()


def test_staff_remove(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _add_helper(client, token)
    conn = db.connect(tmp_path / "data")
    try:
        helper_id = conn.execute("SELECT id FROM helpers").fetchone()["id"]
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/settings/helpers/{helper_id}/remove")
    assert resp.status_code in (302, 303, 200), resp.text
    conn = db.connect(tmp_path / "data")
    try:
        assert conn.execute("SELECT * FROM helpers").fetchall() == []
    finally:
        conn.close()


# --- link recovery -----------------------------------------------------------


def test_link_recovery_buttons_and_card(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, phone="+914400000099")
    seller_url = f"http://127.0.0.1:8000/e/{token}"
    for url in (f"/e/{token}", f"/e/{token}/settings"):
        html = client.get(url).text
        assert "Send my link to my WhatsApp" in html, url
        assert "wa.me/914400000099" in html, url
        assert url_quote(seller_url) in html, url
        assert "Keep this safe" in html, url
    pdf = client.get(f"/e/{token}/link-card.pdf")
    assert pdf.status_code == 200
    assert "application/pdf" in pdf.headers["content-type"]
    assert pdf.content[:4] == b"%PDF"


def test_home_has_lost_link(tmp_path):
    # Task 122: the sellers content (incl. lost-link) moved to /sellers.
    client = _client(tmp_path)
    html = client.get("/sellers").text
    assert "Lost your link?" in html
    assert "no passwords" in html.lower() or "without passwords" in html.lower()
