"""Task 111: small-phone polish after Task 109 (320px, Tamil).

1. Seller header pill: at 320px the ellipsized pill squeezed to an empty
   box and the count vanished. Narrow screens now show a compact badge
   that always keeps the count, with the full text in title/aria-label.
2. Seller bottom nav: the Tamil Orders label broke mid-word. Nav labels
   never break inside a word, and ta uses a shorter Orders label.
3. Seller bottom nav centre item: the mic label was near-white on the
   white bar. It now inherits the same ink as the other labels.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

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


def app_css():
    return (ROOT / "app" / "web" / "static" / "app.css").read_text()


def _rule_block(css, selector):
    """Return the declaration block for an exact `selector { ... }` rule."""
    start = css.index(selector + " {")
    end = css.index("}", start)
    return css[start:end]


# --- 1. Header pill keeps the count on narrow screens ---


def test_header_pill_compact_badge_keeps_count(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    for _ in range(3):
        add_review_session(tmp_path, token)
    html = client.get(f"/e/{token}").text
    full = "3 பட்டியல்களைப் பார்க்கவும்"
    # Compact badge always carries the bare count.
    assert '<span class="ss-n" aria-hidden="true">3</span>' in html
    # Full text stays on the pill for wide screens and assistive tech.
    assert f'title="{full}"' in html
    assert f'aria-label="{full}"' in html
    assert f'<span class="ss-t">{full}</span>' in html
    # Mark + both round buttons stay in the header (Task 109, kept).
    assert "brand/logo.svg" in html
    assert 'class="circ"' in html
    assert "data-sound-toggle" in html


def test_header_pill_compact_css_narrow_only():
    css = app_css()
    # Badge hidden by default; on very narrow screens the full text hides
    # and the badge shows, and the pill never squeezes the count away.
    assert ".seller-status .ss-n { display: none; }" in css
    assert "@media (max-width: 359.98px)" in css
    narrow = css.split("@media (max-width: 359.98px)", 1)[1]
    assert ".seller-status .ss-t { display: none; }" in narrow
    assert ".seller-status .ss-n" in narrow
    assert "body.is-seller .hdr .seller-status { flex: none;" in narrow
    # Task 109 rules kept: pill shrinks with ellipsis above that width.
    assert "body.is-seller .hdr .seller-status { min-width: 0; " \
        "flex: 0 1 auto; }" in css
    assert "body.is-seller .hdr .logo { flex: none; }" in css


# --- 2. Bottom-nav labels never break inside a word ---


def test_bottom_nav_labels_no_midword_break(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    html = client.get(f"/e/{token}").text
    # Bottom nav uses the short Tamil Orders label; the full label stays
    # on the desktop nav.
    assert '<span class="bl">ஆர்டர்</span>' in html
    assert "ஆர்டர்கள்" in html
    css = app_css()
    block = _rule_block(css, ".bnav a .bl")
    assert "overflow-wrap: normal;" in block
    assert "word-break: normal;" in block
    assert "anywhere" not in block
    assert "break-all" not in block
    assert "break-word" not in block
    # Narrow label size stays at or above 11px.
    assert ".bnav a .bl { font-size: 11px; }" in css


def test_bottom_nav_short_orders_label_all_langs(tmp_path):
    from app.web.i18n import STRINGS, missing_keys

    assert missing_keys() == {"ta": [], "hi": []}
    assert STRINGS["en"]["nav.orders_short"] == "Orders"
    assert STRINGS["ta"]["nav.orders_short"] == "ஆர்டர்"
    assert STRINGS["hi"]["nav.orders_short"] == "ऑर्डर"
    client = make_client(tmp_path, lang="hi")
    token = create_shop(client, language="hi")
    publish(tmp_path, token, [_draft("tomato", 40, local="टमाटर")])
    html = client.get(f"/e/{token}").text
    assert '<span class="bl">ऑर्डर</span>' in html


# --- 3. Centre mic label matches the other labels' ink ---


def _rel_luminance(rgb):
    def lin(c):
        c /= 255
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def test_mic_label_same_ink_as_other_labels(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    html = client.get(f"/e/{token}").text
    assert '<span class="bl">நேரலை</span>' in html
    css = app_css()
    # The white icon-circle rule must not leak onto the label: it inherits
    # the anchor ink (muted, or --ink when on) at every width.
    block = _rule_block(css, ".bnav .mic .bl")
    assert "color: inherit;" in block
    # That ink keeps ≥ 4.5:1 contrast on the white bar.
    import re

    muted = re.search(r"--muted:\s*(#[0-9a-fA-F]{6})", css).group(1)
    rgb = tuple(int(muted[i:i + 2], 16) for i in (1, 3, 5))
    ratio = 1.05 / (_rel_luminance(rgb) + 0.05)
    assert ratio >= 4.5, f"--muted {muted} contrast {ratio:.2f}"
