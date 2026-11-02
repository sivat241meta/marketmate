"""Task 154: price-list story first; Bills + Excel visible; extras behind SHOW_EXTRAS."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from test_task84 import draft, seed_shop

from app import db
from app.config import load_settings, show_extras_enabled

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"


def _client(tmp_path, extras: bool = False) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    if extras:
        env["SHOW_EXTRAS"] = "1"
    # Ensure env var does not leak between cases.
    old = os.environ.get("SHOW_EXTRAS")
    if extras:
        os.environ["SHOW_EXTRAS"] = "1"
    else:
        os.environ.pop("SHOW_EXTRAS", None)
    try:
        client = TestClient(create_app(load_settings(env)),
                            follow_redirects=False)
    finally:
        if old is None:
            os.environ.pop("SHOW_EXTRAS", None)
        else:
            os.environ["SHOW_EXTRAS"] = old
    client.cookies.set("ui_lang", "en")
    return client


def _seed(tmp_path):
    _slug, token = seed_shop(
        tmp_path, "T154 Veg", "Koyambedu",
        [draft("tomato", "தக்காளி", "30"),
         draft("onion", "வெங்காயம்", "40")])
    return token


def _version_id(tmp_path, token) -> int | None:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        return db.latest_version(conn, shop["id"], published_only=True)
    finally:
        conn.close()


# --- setting ---------------------------------------------------------------


def test_show_extras_defaults_off():
    assert show_extras_enabled(load_settings(
        {"MODEL_API_KEY": "k", "DATA_DIR": "/tmp/x"})) is False
    assert show_extras_enabled(load_settings(
        {"MODEL_API_KEY": "k", "DATA_DIR": "/tmp/x",
         "SHOW_EXTRAS": "1"})) is True


def test_env_example_documents_show_extras():
    text = (ROOT / ".env.example").read_text()
    assert "SHOW_EXTRAS" in text


# --- nav -------------------------------------------------------------------


def test_nav_off_has_five_core_items(tmp_path):
    token = _seed(tmp_path)
    html = _client(tmp_path, extras=False).get(f"/e/{token}").text
    for href in (f"/e/{token}/update", f"/e/{token}/live",
                 "/bills?range=today", f"/e/{token}/bills"):
        assert href in html, href
    # Hidden from menus when off.
    assert "/purchases" not in html
    assert "/photos" not in html or "/photos/" not in html
    assert "tags.pdf" not in html
    assert "link-card.pdf" not in html
    assert "pos.csv" not in html
    assert "export.csv" not in html
    assert "pricelist.csv" not in html


def test_nav_on_restores_extras(tmp_path):
    token = _seed(tmp_path)
    html = _client(tmp_path, extras=True).get(f"/e/{token}").text
    assert f"/e/{token}/purchases" in html
    assert "tags.pdf" in html
    assert "link-card.pdf" in html
    assert "export.csv" in html


def test_bottom_nav_five_slots_off(tmp_path):
    token = _seed(tmp_path)
    html = _client(tmp_path, extras=False).get(f"/e/{token}").text
    bnav = html.split('<nav class="bnav"')[1].split("</nav>")[0]
    assert bnav.count("<a ") == 5, bnav
    assert f'href="/e/{token}/update"' in bnav
    assert f'href="/e/{token}/live"' in bnav


# --- hidden routes 404 / core works ----------------------------------------


def test_hidden_routes_404_when_off(tmp_path):
    token = _seed(tmp_path)
    client = _client(tmp_path, extras=False)
    version_id = _version_id(tmp_path, token)
    assert client.get(f"/e/{token}/purchases").status_code == 404
    assert client.get(f"/e/{token}/photos").status_code == 404
    assert client.post(
        f"/e/{token}/settings/helpers", data={"name": "x"}).status_code == 404
    assert client.get(
        f"/e/{token}/exports/pos.csv").status_code == 404
    assert client.get(f"/e/{token}/tags.pdf").status_code == 404
    assert client.get(f"/e/{token}/link-card.pdf").status_code == 404
    assert client.get(
        f"/e/{token}/exports/pricelist.csv").status_code == 404
    assert client.get(
        f"/e/{token}/v/{version_id}/export.csv").status_code == 404


def test_core_routes_work_when_off(tmp_path):
    token = _seed(tmp_path)
    client = _client(tmp_path, extras=False)
    assert client.get(f"/e/{token}/bills").status_code == 200
    assert client.get(f"/e/{token}/credit").status_code == 200
    assert client.get(f"/e/{token}/close").status_code == 200
    assert client.get(
        f"/e/{token}/exports/sales.xlsx?range=today").status_code == 200
    assert client.get(
        f"/e/{token}/exports/pricelist.xlsx").status_code == 200
    assert client.get(
        f"/e/{token}/bills?range=today&status=waiting").status_code == 200
    assert client.get(f"/e/{token}/update").status_code == 200
    assert client.get(f"/e/{token}/orders/pending.json").status_code == 200


def test_hidden_routes_work_when_on(tmp_path):
    token = _seed(tmp_path)
    client = _client(tmp_path, extras=True)
    version_id = _version_id(tmp_path, token)
    assert client.get(f"/e/{token}/purchases").status_code == 200
    assert client.get(f"/e/{token}/photos").status_code == 200
    assert client.get(f"/e/{token}/exports/pos.csv").status_code == 200
    assert client.get(f"/e/{token}/tags.pdf").status_code == 200
    assert client.get(f"/e/{token}/link-card.pdf").status_code == 200
    assert client.get(
        f"/e/{token}/exports/pricelist.csv").status_code == 200
    assert client.get(
        f"/e/{token}/v/{version_id}/export.csv").status_code == 200


# --- Bills tabs / Excel buttons / settings ---------------------------------


def test_bills_has_credit_close_tabs_when_off(tmp_path):
    token = _seed(tmp_path)
    html = _client(tmp_path, extras=False).get(f"/e/{token}/bills").text
    assert f'href="/e/{token}/credit"' in html
    assert f'href="/e/{token}/close"' in html
    assert "pos.csv" not in html
    assert "pricelist.csv" not in html


def test_excel_buttons_visible_when_off(tmp_path):
    token = _seed(tmp_path)
    client = _client(tmp_path, extras=False)
    prices = client.get(f"/e/{token}/update").text
    assert "pricelist.xlsx" in prices
    assert "Download Excel" in prices
    close = client.get(f"/e/{token}/close").text
    assert "sales.xlsx" in close
    assert "Download Excel" in close


def test_settings_hides_rounding_currency_helpers_when_off(tmp_path):
    token = _seed(tmp_path)
    off = _client(tmp_path, extras=False).get(f"/e/{token}/settings").text
    assert 'name="round_bills"' not in off or 'type="hidden"' in off
    assert 'id="set-currency"' not in off
    assert 'id="helpers"' not in off
    assert "link-card.pdf" not in off
    assert 'name="upi_id"' in off
    on = _client(tmp_path, extras=True).get(f"/e/{token}/settings").text
    assert 'id="set-currency"' in on
    assert 'id="helpers"' in on


def test_dashboard_order_when_off(tmp_path):
    token = _seed(tmp_path)
    html = _client(tmp_path, extras=False).get(f"/e/{token}").text
    morning = html.index('id="step-morning"')
    price_list = html.index('id="todays-list"')
    day = html.index('id="step-day"')
    ai_link = html.index('id="ai-link"')
    assert morning < price_list < day < ai_link
    assert "board.pdf" in html
    assert "qr.png" in html


# --- phone fixes -----------------------------------------------------------


def test_status_pill_12px_and_tap_areas():
    css = APP_CSS.read_text()
    assert "body.is-seller .hdr .seller-status { font-size: 12px;" in css
    assert ".grp-more .hp-more" in css
    assert "min-height: 44px" in css
    shop_css = SHOP13_CSS.read_text()
    assert "crumbs a::after" in shop_css
    assert "height:44px" in shop_css.replace(" ", "")
    review = (ROOT / "app" / "web" / "templates" / "review.html").read_text()
    assert "back-link" in review


# --- README ----------------------------------------------------------------


def test_readme_story_order():
    text = (ROOT / "README.md").read_text()
    assert ("Not a ledger app: MarketMate turns a market stall's spoken "
            "prices into a proof-checked public price list that customers "
            "can compare and order from.") in text
    assert ("Also built (off by default, SHOW_EXTRAS=1): purchases, stock "
            "photo counts, helpers, POS CSV, shelf tags.") in text
    one = text.index("1. The seller films")
    two = text.index("2. Approve publishes")
    three = text.index("3. Customers compare")
    four = text.index("4. The same list runs")
    assert one < two < three < four
