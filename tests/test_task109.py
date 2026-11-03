"""Task 109: 320px Tamil layout fixes.

On a 320px phone with ui_lang=ta the seller pages were 349px wide and
the homepage 357px wide. The seller header pill pushed the round
buttons off-screen, the bottom nav's last item ended at 337px, the
homepage compare link forced the page wide, and the status strip
wrapped to five lines. No browser is available here, so the narrow
rules themselves are pinned and the pages are rendered in Tamil.
"""

from __future__ import annotations

import html as htmlmod
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent


def make_client(tmp_path, lang="ta"):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def create_shop(client, name="Night Veg", phone="+914400000101",
                language="ta", area="Koyambedu"):
    data = {"name": name, "phone": phone, "area": area,
            "language": language, "currency": "INR", "type": "vegetable"}
    resp = client.post("/new", data=data)
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, local=None):
    return DraftItem(
        name_spoken=name_en, name_local=local or name_en, name_en=name_en,
        variety=None, price_lines=[PriceLine(Decimal(price), Decimal(1),
                                             "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def publish(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
    finally:
        conn.close()


def add_review_session(tmp_path, token):
    """One session waiting for a tap, so the pill and strip count it."""
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        conn.execute("UPDATE sessions SET status = 'review' WHERE id = ?",
                     (session_id,))
        conn.commit()
    finally:
        conn.close()


def app_css():
    return (ROOT / "app" / "web" / "static" / "app.css").read_text()


# --- 1+2+4. Seller base layout + Today page in Tamil ---


def test_seller_today_tamil_renders_compact_header_nav_and_strip(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    add_review_session(tmp_path, token)
    html = client.get(f"/e/{token}").text
    # The long pill keeps its full text in title + inner span, and the
    # strip shows the same count.
    assert 'class="chip c-need seller-status"' in html
    assert 'title="1 பட்டியலைப் பார்க்கவும்"' in html
    assert '<span class="ss-t">1 பட்டியலைப் பார்க்கவும்</span>' in html
    assert html.count("பட்டியலைப் பார்க்கவும்") >= 2
    # Mark + both round buttons stay in the header.
    assert "brand/logo.svg" in html
    assert 'class="circ"' in html
    assert "data-sound-toggle" in html
    # All five bottom-nav items carry wrapping labels.
    assert html.count('class="bl"') == 5
    for label in ("இன்று", "பில்", "நேரலை", "ஆர்டர்கள்", "நாள் முடி"):
        assert label in html
    # Status strip with the language switch, and every hook kept.
    assert 'class="ann"' in html
    assert "கடை திறந்திருக்கு" in html
    assert "data-ui-toggle" in html
    assert "data-orders-link" in html
    assert "data-orders-badge" in html


# --- 3. Homepage in Tamil ---


def test_homepage_tamil_renders_compare_link(tmp_path):
    # Task 127: the v13 Tamil homepage links /market from the nav,
    # the hero service card and the footer.
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    client.cookies.set("ui_lang", "ta")
    html = client.get(
        "/", headers={"referer": "http://testserver/market"}).text
    assert 'href="/market"' in html
    assert t_for("ta")("hp.nav_find") in html
    assert t_for("ta")("v13.hero_a") in htmlmod.unescape(html)


# --- Narrow-width CSS rules ---


def test_seller_header_css_fits_320px():
    css = app_css()
    # The pill shrinks and ellipsizes instead of pushing buttons away.
    assert "body.is-seller .hdr .seller-status { min-width: 0; " \
        "flex: 0 1 auto; }" in css
    assert "body.is-seller .hdr .seller-status .ss-t" in css
    assert "text-overflow: ellipsis;" in css
    # The mark never shrinks away.
    assert "body.is-seller .hdr .logo { flex: none; }" in css
    # Round buttons never shrink below 40px.
    assert "body.is-seller .hdr .iconbtn, " \
        "body.is-seller .hdr .circ" in css
    assert "min-width: 40px;" in css
    assert "min-height: 40px;" in css


def test_bottom_nav_css_equal_flexible_columns():
    css = app_css()
    assert "flex: 1 1 0;" in css
    assert ".bnav a .bl" in css
    assert "overflow-wrap: anywhere;" in css
    assert ".bnav a .bl { font-size: 11px; }" in css
    assert ".bnav .mic .bl" in css


def test_homepage_link_css_wraps():
    css = app_css()
    assert "flex-wrap: wrap;" in css
    assert ".hp-more" in css
    assert "white-space: normal;" in css
    assert "max-width: 100%;" in css


def test_status_strip_css_stacks_on_narrow():
    css = app_css()
    assert "body.is-seller .ann { flex-wrap: wrap; }" in css
    assert "body.is-seller .ann > span:first-child " \
        "{ flex: 1 1 100%; min-width: 0; }" in css
    assert "body.is-seller .ann .lang { margin-left: auto; }" in css
