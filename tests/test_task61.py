"""Task 61: the "TODAY" seller home (morning prices, orders and bills, close day).

The seller home follows the seller's day: step 1 morning prices, step 2
daytime orders and bills, step 3 evening close; then Today's list, then a
collapsed More section. Every figure comes from existing rows.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path("/tmp/mm_t61/html")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, name="T61 Store", phone="+914400000061",
                language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, local=None, flags=()):
    return DraftItem(
        name_spoken=name_en, name_local=local or name_en, name_en=name_en,
        variety=None, price_lines=[PriceLine(Decimal(price), Decimal(1),
                                             "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        flags=list(flags), confirmed=True)


def publish(tmp_path, token, drafts, *, at=None) -> int:
    """Publish drafts; ``at`` backdates the version (an aware datetime)."""
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
        if at is not None:
            conn.execute("UPDATE versions SET created_at = ? WHERE id = ?",
                         (at.astimezone(UTC).isoformat(), version_id))
            conn.commit()
        return version_id
    finally:
        conn.close()


def seed_taps(tmp_path, token, need=2):
    drafts = [_draft("tomato", 50, flags=[Flag(
        field="price", code="TWO_PRICES",
        message="Did you say 50 or 80?", options=["50", "80"],
        blocking=True)]) for _ in range(need)]
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "live")
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review",
                              f"{need} items need review")
        return session_id
    finally:
        conn.close()


def seed_order(tmp_path, token, *, status="new", name="Priya",
               phone="9876543210", total="40.00"):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=[QuoteLine(
                name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
                unit="kg", unit_price=Decimal(20), per_amount=Decimal(1),
                line_total=Decimal(total), status="priced")],
            total=Decimal(total), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(
            conn, shop_id=shop["id"], quote=quote, source="customer",
            kind="quote", status=status, customer_name=name,
            customer_phone=phone)
        return db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()


def seed_bill(tmp_path, token, *, status="billed", total="36.00",
              mode=None, day_offset=0):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=[QuoteLine(
                name_en="tomato", name_local="தக்காளி", qty=Decimal(2),
                unit="kg", unit_price=Decimal(18), per_amount=Decimal(1),
                line_total=Decimal(total), status="priced")],
            total=Decimal(total), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status=status)
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        if status == "paid":
            db.mark_bill_paid(conn, bill_id, mode or "cash")
        if day_offset:
            when = (datetime.now(IST) - timedelta(days=day_offset))
            conn.execute("UPDATE quotes SET created_at = ? WHERE id = ?",
                         (when.astimezone(UTC).isoformat(), bill_id))
            conn.commit()
        return bill_id
    finally:
        conn.close()


def section(html: str, marker: str) -> str:
    """Slice one home block: from its id to the next block start."""
    start = html.index(f'id="{marker}"')
    ends = [len(html)]
    for other in ("step-morning", "step-day", "step-evening",
                  "todays-list", "more"):
        if other == marker:
            continue
        at = html.find(f'id="{other}"', start + 1)
        if at != -1:
            ends.append(at)
    return html[start:min(ends)]


def _yesterday_noon() -> datetime:
    now_ist = datetime.now(IST)
    return now_ist.replace(hour=12, minute=0, second=0,
                           microsecond=0) - timedelta(days=1)


# --- 1. step 1 states: exactly one primary action ---------------------------


def test_step1_say_state_one_primary(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)],
            at=_yesterday_noon())
    html = client.get(f"/e/{token}").text
    morning = section(html, "step-morning")
    assert "Say today&#39;s prices" in morning \
        or "Say today's prices" in morning
    assert morning.count("pill dark") == 1
    assert f'href="/e/{token}/live"' in morning
    # Language picker + upload form live in this state.
    assert 'name="speak_lang"' in morning
    assert "data-upload-form" in morning
    assert "Upload video or voice note" in morning
    assert "Check now" not in morning
    assert "Send today&#39;s prices on WhatsApp" not in morning
    assert "Send today's prices on WhatsApp" not in morning


def test_step1_taps_state_one_primary(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    session_id = seed_taps(tmp_path, token, need=2)
    html = client.get(f"/e/{token}").text
    morning = section(html, "step-morning")
    assert "2 prices need one tap" in morning
    assert "Check now" in morning
    assert f"/e/{token}/s/{session_id}" in morning
    assert morning.count("pill dark") == 1
    # Task 131: an upload entry stays on the dashboard while items wait.
    assert "data-upload-form" in morning
    assert "Send today&#39;s prices on WhatsApp" not in morning
    assert "Send today's prices on WhatsApp" not in morning


def test_step1_live_state_one_primary(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40),
                              _draft("onion", 30)])
    html = client.get(f"/e/{token}").text
    morning = section(html, "step-morning")
    assert "Live · 2 prices since" in morning
    assert "Send today&#39;s prices on WhatsApp" in morning \
        or "Send today's prices on WhatsApp" in morning
    assert morning.count("pill dark") == 1
    assert "Update prices" in morning
    assert f'href="/e/{token}/update"' in morning
    for label in ("Print board", "Print price tags", "Shop QR"):
        assert label in morning, label
    assert "Check now" not in morning
    # Task 131: after publishing, the compact "Update today's prices" card.
    assert "data-upload-form" in morning


def test_step1_first_run_get_started_takes_its_place(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    html = client.get(f"/e/{token}").text
    assert "Get started" in html
    assert "Save your link" in html
    assert "Share your shop" in html
    # No live/taps morning actions for a brand-new shop.
    assert "Check now" not in html
    assert "Send today&#39;s prices on WhatsApp" not in html
    assert "Send today's prices on WhatsApp" not in html
    # Task 131: first-run shops get the upload card (step 2 links to it).
    assert "data-upload-form" in html


# --- 2. step 2 counts match the database ------------------------------------


def test_step2_counts_match_seeded_day(tmp_path):
    from app.outputs.money import format_money

    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    new_a = seed_order(tmp_path, token, status="new", name="Priya")
    new_b = seed_order(tmp_path, token, status="new", name="Kani",
                       phone="+919876543211")
    packing = seed_order(tmp_path, token, status="packing", name="Velu")
    ready = seed_order(tmp_path, token, status="ready", name="Muthu")
    seed_order(tmp_path, token, status="collected", name="Old")
    seed_order(tmp_path, token, status="cancelled", name="Gone")
    seed_bill(tmp_path, token, status="billed", total="36.00")
    seed_bill(tmp_path, token, status="paid", total="30.00", mode="cash")

    conn = db.connect(tmp_path / "data")
    try:
        rows = db.list_quotes(conn, db.shop_by_token(conn, token)["id"])
    finally:
        conn.close()
    assert sum(1 for r in rows if r["source"] == "customer"
               and r["status"] == "new") == 2
    assert sum(1 for r in rows if r["source"] == "customer"
               and r["status"] == "packing") == 1

    html = client.get(f"/e/{token}").text
    day = section(html, "step-day")
    for needle, name in ((">2<", "new"), (">1<", "packing"),
                         (">1<", "ready")):
        assert needle in day, (name, day)
    assert "Unpaid bills" in day
    assert format_money(Decimal("66.00"), "INR") in day
    # New orders are highlighted when there are any (Task 64: is-new).
    assert "is-new" in day
    # Actions.
    assert "New bill" in day
    assert f'href="/e/{token}/bills/new"' in day
    assert "Orders" in day and "Bills" in day
    assert "data-orders-badge" in day
    # The 3 newest open orders, newest first, with the next status button.
    assert f"Order #{ready}" in day
    assert f"Order #{packing}" in day
    assert f"Order #{new_b}" in day
    assert f"Order #{new_a}" not in day
    assert day.index(f"Order #{ready}") < day.index(f"Order #{packing}")
    assert day.index(f"Order #{packing}") < day.index(f"Order #{new_b}")
    assert "Start packing" in day
    assert "Ready for pickup" in day
    assert "Collected" in day
    assert day.count("/order-status") >= 3


def test_step2_new_orders_plain_at_zero(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}").text
    day = section(html, "step-day")
    assert ">0<" in day
    assert "is-new" not in day.split("Unpaid bills")[0]


# --- 3. step 3 preview matches close day ------------------------------------


def test_step3_preview_matches_close_day(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    seed_bill(tmp_path, token, status="paid", total="36.00", mode="cash")
    seed_bill(tmp_path, token, status="paid", total="30.00", mode="upi")
    seed_bill(tmp_path, token, status="billed", total="18.00")

    home = section(client.get(f"/e/{token}").text, "step-evening")
    close = client.get(f"/e/{token}/close").text
    # Same formatted figures on both pages.
    for needle in ("₹84", "3", "₹36", "₹30"):
        assert needle in home, (needle, home)
        assert needle in close, (needle, close)
    assert "Close day" in home
    hour = datetime.now(IST).hour
    if hour >= 18:
        assert 'class="pill dark"' in home or "pill dark" in home
    else:
        assert "pill ghost" in home


def test_step3_closed_state_after_post(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    resp = client.post(f"/e/{token}/close")
    assert resp.status_code in (302, 303), resp.text
    home = section(client.get(f"/e/{token}").text, "step-evening")
    assert "Closed at" in home
    assert "✓" in home


# --- 4. More holds every other destination once ------------------------------


def test_more_contains_each_destination_once(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    version_id = publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}").text
    more = section(html, "more")
    hrefs = re.findall(r'href="([^"]+)"', more)
    wants = [
        f"/e/{token}/settings",
        f"/e/{token}/settings#helpers",
        f"/e/{token}/purchases",
        f"/e/{token}/update#board",
        f"/e/{token}/tags.pdf",
        f"/e/{token}/v/{version_id}/export.csv",
        f"/e/{token}/exports/sales.xlsx?range=today",
        "/#lost-link",
    ]
    for want in wants:
        count = sum(1 for href in hrefs
                    if href.replace("&amp;", "&") == want)
        assert count == 1, (want, hrefs)
    assert more.count("Send my link to my WhatsApp") == 1
    assert more.count("link-card.pdf") == 1
    assert 'id="install-card"' in more


# --- 5. hooks the JS and tests need are still rendered -----------------------


def _js_selectors(*names: str) -> set[str]:
    found: set[str] = set()
    for name in names:
        text = (ROOT / "app" / "web" / "static" / name).read_text()
        for match in re.findall(r'\[data-([a-z0-9-]+)', text):
            found.add(f"data-{match}")
        for match in re.findall(r'getElementById\("([^"]+)"\)', text):
            found.add(f'id="{match}"')
    return found


def test_js_hooks_still_in_rendered_home(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)],
            at=_yesterday_noon())
    say_html = client.get(f"/e/{token}").text
    for hook in _js_selectors("upload.js"):
        assert hook in say_html, f"say state missing {hook}"
    for hook in _js_selectors("order-alert.js"):
        assert hook in say_html, f"home missing {hook}"
    # Item rows keep their photo + sold-out hooks.
    assert "data-item-photo-form" in say_html
    assert "data-item-photo-input" in say_html
    assert f"/e/{token}/item/" in say_html and "/soldout" in say_html
    assert "list-row" in say_html and "list-thumb" in say_html
    # Step 2 order rows keep the existing status route.
    seed_order(tmp_path, token, status="new")
    day = section(client.get(f"/e/{token}").text, "step-day")
    assert "/order-status" in day
    assert 'name="status"' in day


# --- 6. en/ta/hi render (in-process) -----------------------------------------


def test_home_renders_en_ta_hi_saved(tmp_path):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    seed_order(tmp_path, token, status="new")
    seed_bill(tmp_path, token, status="paid", total="36.00", mode="cash")
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        resp = client.get(f"/e/{token}")
        assert resp.status_code == 200, lang
        assert "style=" not in resp.text, f"{lang} inline style"
        if lang != "en":
            assert any(ord(c) > 127 for c in resp.text), lang
        (OUT_DIR / f"home-{lang}.html").write_text(resp.text)
    client.cookies.set("ui_lang", "en")
    # One markup serves the 360px phone and the 1280px laptop: both navs
    # render and the stylesheet switches between them at 900px.
    html = (OUT_DIR / "home-en.html").read_text()
    assert 'class="bnav"' in html and 'class="nav"' in html
    css = (ROOT / "app" / "web" / "static" / "app.css").read_text()
    assert "@media (min-width: 900px)" in css
    assert "desk-only" in html and "mob-only" in css
