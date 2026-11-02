"""Task 113: /try and other header states fit 320px.

The browser sweep passes everywhere except the demo shop page /try at
320px (358px en, 412px ta, 351px hi). When no list is waiting the header
pill shows the green "shop open" state, but the Tasks 109/111
narrow-screen rules only compact the "lists to check" state: Task 111's
``flex: none`` narrow rule leaves the full-text shop-open pill
unshrinkable, so it pushes the round buttons off the screen. The same
page also shows "0 lists to check" in the status strip, and the bottom
nav stretches with the overflowed page. No browser is available here, so
the uniform pill markup, the hidden zero count and the nav rules are
pinned and both pages are rendered in every language.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.web.i18n import t_for

ROOT = Path(__file__).resolve().parent.parent


def make_client(tmp_path, lang="ta"):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", lang)
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


def try_html(client):
    # Task 159: /try lands on the light judge page; the seller chrome
    # assertions below read the full dashboard linked from it.
    resp = client.get("/try")
    assert resp.status_code in (302, 303), resp.text
    token = resp.headers["location"].split("/e/")[1].rsplit("/judge", 1)[0]
    return client.get(f"/e/{token}").text


def app_css():
    return (ROOT / "app" / "web" / "static" / "app.css").read_text()


def _rule_block(css, selector):
    """Return the declaration block for an exact `selector { ... }` rule."""
    start = css.index(selector + " {")
    end = css.index("}", start)
    return css[start:end]


def _assert_shop_open_pill_compact_ready(html, lang):
    """Every non-count pill state compacts exactly like the lists state."""
    t = t_for(lang)
    full = t("shell.shop_open")
    assert 'class="chip c-live seller-status"' in html
    assert f'title="{full}"' in html
    assert f'aria-label="{full}"' in html
    assert f'<span class="ss-t">{full}</span>' in html


def _assert_no_zero_lists(html, lang):
    t = t_for(lang)
    assert t("ann.need_tap", n=0, count=0) not in html
    assert t("shell.needs_you", n=0, count=0) not in html


# --- 1. /try with nothing waiting: every language ---


def test_try_no_waiting_pill_compacts_and_no_zero_lists(tmp_path):
    for lang in ("en", "ta", "hi"):
        client = make_client(tmp_path, lang=lang)
        html = try_html(client)
        t = t_for(lang)
        _assert_shop_open_pill_compact_ready(html, lang)
        _assert_no_zero_lists(html, lang)
        # The strip keeps the open state, without a zero count part.
        assert t("ann.shop_open") in html
        # Mark + both round buttons stay in the header.
        assert "brand/logo.svg" in html
        assert 'class="circ"' in html
        assert "data-sound-toggle" in html
        # All five bottom-nav items carry wrapping labels.
        assert html.count('class="bl"') == 5


# --- 2. A normal seller page behaves exactly like /try ---


def test_seller_today_no_waiting_matches_try(tmp_path):
    for lang in ("en", "ta", "hi"):
        client = make_client(tmp_path, lang=lang)
        token = create_shop(client, language=lang)
        publish(tmp_path, token, [_draft("tomato", 40)])
        html = client.get(f"/e/{token}").text
        _assert_shop_open_pill_compact_ready(html, lang)
        _assert_no_zero_lists(html, lang)
        assert html.count('class="bl"') == 5


# --- 3. The lists state keeps its count badge; the strip keeps counts > 0 ---


def test_lists_state_and_strip_keep_count(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    for _ in range(3):
        add_review_session(tmp_path, token)
    html = client.get(f"/e/{token}").text
    full = "3 பட்டியல்களைப் பார்க்கவும்"
    assert 'class="chip c-need seller-status"' in html
    assert '<span class="ss-n" aria-hidden="true">3</span>' in html
    assert f'title="{full}"' in html
    assert f'aria-label="{full}"' in html
    assert f'<span class="ss-t">{full}</span>' in html
    # The strip still shows the same non-zero count (Task 109, kept).
    assert html.count(full) >= 2


# --- 4. Narrow-screen pill rules apply to every pill state ---


def test_header_pill_narrow_css_state_agnostic():
    css = app_css()
    # Above the very-narrow breakpoint every state shrinks with ellipsis.
    assert "body.is-seller .hdr .seller-status { min-width: 0; " \
        "flex: 0 1 auto; }" in css
    assert "body.is-seller .hdr .seller-status .ss-t" in css
    assert "text-overflow: ellipsis;" in css
    # The badge hides by default; on very narrow screens the full text of
    # EVERY state hides and only the compact badge/dot shows. The selectors
    # target .seller-status/.ss-t/.ss-n, never one state class.
    assert ".seller-status .ss-n { display: none; }" in css
    assert "@media (max-width: 359.98px)" in css
    narrow = css.split("@media (max-width: 359.98px)", 1)[1]
    assert ".seller-status .ss-t { display: none; }" in narrow
    assert ".seller-status .ss-n" in narrow
    assert "body.is-seller .hdr .seller-status { flex: none;" in narrow
    assert "c-need" not in narrow.split(
        "body.is-seller .hdr .seller-status")[1].split("}")[0]
    # The mark never shrinks away; round buttons never shrink below 40px.
    assert "body.is-seller .hdr .logo { flex: none; }" in css
    assert "body.is-seller .hdr .iconbtn, " \
        "body.is-seller .hdr .circ" in css
    assert "min-width: 40px;" in css
    assert "min-height: 40px;" in css


# --- 5. Bottom nav: five equal columns, word-boundary wrap, >= 11px ---


def test_bottom_nav_css_fits_320px_everywhere():
    css = app_css()
    block = _rule_block(css, ".bnav a")
    assert "flex: 1 1 0;" in block
    assert "min-width: 0;" in block
    label = _rule_block(css, ".bnav a .bl")
    assert "white-space: normal;" in label
    assert "overflow-wrap: normal;" in label
    assert "word-break: normal;" in label
    assert "anywhere" not in label
    assert "break-all" not in label
    assert "break-word" not in label
    assert ".bnav a .bl { font-size: 11px; }" in css
    assert ".bnav .mic .bl" in css
