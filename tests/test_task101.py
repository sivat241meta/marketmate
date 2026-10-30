"""Task 101: five usability fixes from the 30 Oct end-to-end test.

1. Order bill page: "Accept order" before acceptance, "Take payment"
   once packing, payment panel directly when ready.
2. Cash helper: focus selects the prefill; first keypad press replaces it.
3. Plurals via the count-aware t() (0/1/2, en/ta/hi) + template sweep.
4. Public header fits a 390px phone (compact sell, icon-only bag).
5. Shop cart bar: bottom-fixed on phones, sticky right column >=1000px.
"""

from __future__ import annotations

import html as htmlmod
import re
import shutil
import subprocess
from pathlib import Path

from test_task52 import (
    _client,
    _create_shop,
    _draft,
    _publish,
    _seed_bill,
    _seed_customer_order,
    _slug,
    _start_review_session,
    _two_price_draft,
)
from test_task64 import SHOP_HOOKS
from test_task84 import draft as market_draft
from test_task84 import make_client as market_client
from test_task84 import seed_market, seed_shop

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_CSS = ROOT / "app" / "web" / "static" / "css" / "public.css"
HEADER = ROOT / "app" / "web" / "templates" / "_public_header.html"
MY_JS = ROOT / "app" / "web" / "static" / "my.js"


def _bill(client, token, order_id):
    resp = client.get(f"/e/{token}/bills/{order_id}")
    assert resp.status_code == 200
    return resp.text


# --- 1. Take payment label by state ------------------------------------------


def test_order_new_keeps_accept_order(tmp_path):
    from app.web.i18n import t_for

    t = t_for("en")
    client = _client(tmp_path)
    token = _create_shop(client)
    order_id, _ = _seed_customer_order(tmp_path, token, status="new")
    html = _bill(client, token, order_id)
    assert t("bill.accept_order") in html
    assert t("bill.take_payment") not in html
    assert t("bill.start_packing") in html  # status bar next step stays
    assert "data-cash-gave" not in html  # no payment panel yet


def test_order_packing_shows_take_payment(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    order_id, _ = _seed_customer_order(tmp_path, token, status="new")
    resp = client.post(f"/e/{token}/bills/{order_id}/order-status",
                       data={"status": "packing"})
    assert resp.status_code == 303, resp.text
    html = _bill(client, token, order_id)
    assert "Take payment" in html
    assert "Accept order" not in html
    form = re.search(
        r'<form method="post" action="/e/[^/]+/bills/\d+/accept">(.*?)</form>',
        html, re.DOTALL).group(1)
    assert "cash.svg" in form  # cash/UPI icon, not the check
    assert "check.svg" not in form
    from app.web.i18n import t_for

    assert t_for("en")("bill.mark_ready") in html  # next step stays
    assert "data-cash-gave" not in html


def test_order_ready_shows_payment_panel(tmp_path):
    from app.web.i18n import t_for

    t = t_for("en")
    client = _client(tmp_path)
    token = _create_shop(client)
    order_id, _ = _seed_customer_order(tmp_path, token, status="new")
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "packing"})
    client.post(f"/e/{token}/bills/{order_id}/order-status",
                data={"status": "ready"})
    html = _bill(client, token, order_id)
    assert "data-cash-gave" in html  # panel inline, no extra click
    assert t("bill.paid_cash") in html
    assert t("bill.paid_upi") in html
    assert "/accept" not in html
    assert "Take payment" not in html
    assert "Accept order" not in html
    assert t("bill.mark_collected") in html  # status bar next step stays


def test_ready_order_paid_post_works_without_accept_click(tmp_path):
    from app import db
    from app.web.i18n import t_for

    t = t_for("en")
    client = _client(tmp_path)
    token = _create_shop(client)
    order_id, _ = _seed_customer_order(tmp_path, token, status="ready")
    resp = client.post(f"/e/{token}/bills/{order_id}/paid",
                       data={"mode": "cash"})
    assert resp.status_code == 303, resp.text
    html = _bill(client, token, order_id)
    assert t("bill.paid_by", mode=t("bills.cash")) in html
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, order_id)
        assert row["kind"] == "bill" and row["status"] == "paid"
    finally:
        conn.close()


def test_new_order_paid_post_still_needs_accept(tmp_path):
    from app import db

    client = _client(tmp_path)
    token = _create_shop(client)
    order_id, _ = _seed_customer_order(tmp_path, token, status="new")
    resp = client.post(f"/e/{token}/bills/{order_id}/paid",
                       data={"mode": "cash"})
    assert resp.status_code == 200
    assert "accept it first" in resp.text
    conn = db.connect(tmp_path / "data")
    try:
        assert db.get_quote_by_id(conn, order_id)["status"] == "new"
    finally:
        conn.close()


def test_take_payment_label_all_langs(tmp_path):
    from app.web.i18n import t_for

    assert t_for("en")("bill.take_payment") == "Take payment"
    assert t_for("ta")("bill.take_payment") == "பணம் வாங்குக"
    assert t_for("hi")("bill.take_payment") == "भुगतान लें"
    client = _client(tmp_path)
    token = _create_shop(client)
    order_id, _ = _seed_customer_order(tmp_path, token, status="packing")
    client.cookies.set("ui_lang", "ta")
    assert "பணம் வாங்குக" in _bill(client, token, order_id)
    client.cookies.set("ui_lang", "hi")
    assert "भुगतान लें" in _bill(client, token, order_id)


# --- 2. cash helper -----------------------------------------------------------


def test_cash_node_replaces_prefill():
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/cash_replace.test.mjs"], cwd=ROOT, check=False,
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bill_page_loads_cash_js(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    bill_id = _seed_bill(tmp_path, token)
    html = _bill(client, token, bill_id)
    assert "cash.js" in html
    for hook in ("data-cash", "data-cash-gave", "data-cash-chip",
                 "data-cash-keys", "data-cash-back"):
        assert hook in html, hook


# --- 3. plurals ---------------------------------------------------------------


def test_plural_forms_zero_one_two():
    from app.web.i18n import t_for

    cases = {
        "credit.bill": {"en": ("bill", "bills"), "ta": ("பில்", "பில்கள்"),
                        "hi": ("बिल", "बिल")},
        "close.bill": {"en": ("bill", "bills"), "ta": ("பில்", "பில்கள்"),
                       "hi": ("बिल", "बिल")},
    }
    for key, langs in cases.items():
        for lang, (one, other) in langs.items():
            t = t_for(lang)
            assert t(key, count=0) == other, (key, lang, 0)
            assert t(key, count=1) == one, (key, lang, 1)
            assert t(key, count=2) == other, (key, lang, 2)
    sentences = {
        "shop.summary": (
            {"n": 0, "min": "₹1", "max": "₹2"},
            {"en": ("0 items, from ₹1 to ₹2", "1 item, from ₹1 to ₹2",
                    "2 items, from ₹1 to ₹2"),
             "ta": ("0 பொருட்கள், ₹1 முதல் ₹2 வரை",
                    "1 பொருள், ₹1 முதல் ₹2 வரை",
                    "2 பொருட்கள், ₹1 முதல் ₹2 வரை"),
             "hi": ("0 सामान, ₹1 से ₹2 तक", "1 सामान, ₹1 से ₹2 तक",
                    "2 सामान, ₹1 से ₹2 तक")}),
        "shop.search_ph": (
            {"n": 0},
            {"en": ("Search 0 items", "Search 1 item", "Search 2 items"),
             "ta": ("0 பொருட்களில் தேடு", "1 பொருளில் தேடு",
                    "2 பொருட்களில் தேடு"),
             "hi": ("0 सामान में खोजें", "1 सामान में खोजें",
                    "2 सामान में खोजें")}),
        "dash.live_pill": (
            {},
            {"en": ("Live · 0 prices", "Live · 1 price", "Live · 2 prices"),
             "ta": ("நேரலை · 0 விலைகள்", "நேரலை · 1 விலை",
                    "நேரலை · 2 விலைகள்"),
             "hi": ("लाइव · 0 दाम", "लाइव · 1 दाम", "लाइव · 2 दाम")}),
        "t61.live_status": (
            {"n": 0, "time": "9:00"},
            {"en": ("Live · 0 prices since 9:00", "Live · 1 price since 9:00",
                    "Live · 2 prices since 9:00"),
             "ta": ("நேரலை · 9:00 முதல் 0 விலைகள்",
                    "நேரலை · 9:00 முதல் 1 விலை",
                    "நேரலை · 9:00 முதல் 2 விலைகள்"),
             "hi": ("लाइव · 9:00 से 0 भाव", "लाइव · 9:00 से 1 भाव",
                    "लाइव · 9:00 से 2 भाव")}),
        "shell.needs_you": (
            {"n": 0},
            {"en": ("0 lists to check", "1 list to check",
                    "2 lists to check"),
             "ta": ("0 பட்டியல்களைப் பார்க்கவும்",
                    "1 பட்டியலைப் பார்க்கவும்",
                    "2 பட்டியல்களைப் பார்க்கவும்"),
             "hi": ("0 सूचियाँ देखनी हैं", "1 सूची देखनी है",
                    "2 सूचियाँ देखनी हैं")}),
        "ann.need_tap": (
            {"n": 0},
            {"en": ("0 lists to check", "1 list to check",
                    "2 lists to check"),
             "ta": ("0 பட்டியல்களைப் பார்க்கவும்",
                    "1 பட்டியலைப் பார்க்கவும்",
                    "2 பட்டியல்களைப் பார்க்கவும்"),
             "hi": ("0 सूचियाँ देखनी हैं", "1 सूची देखनी है",
                    "2 सूचियाँ देखनी हैं")}),
        "review.head_need": (
            {"n": 0},
            {"en": ("0 prices need one tap.", "1 price needs one tap.",
                    "2 prices need one tap."),
             "ta": ("0 விலைக்கு ஒரு தட்டு தேவை.",
                    "1 விலைக்கு ஒரு தட்டு தேவை.",
                    "2 விலைக்கு ஒரு தட்டு தேவை."),
             "hi": ("0 दामों पर एक टैप चाहिए।",
                    "1 दाम पर एक टैप चाहिए।",
                    "2 दामों पर एक टैप चाहिए।")}),
        "cpdf.sales_bills": (
            {"n": 0},
            {"en": ("Sales (0 bills)", "Sales (1 bill)", "Sales (2 bills)"),
             "ta": ("விற்பனை (0 பில்கள்)", "விற்பனை (1 பில்)",
                    "விற்பனை (2 பில்கள்)"),
             "hi": ("बिक्री (0 बिल)", "बिक्री (1 बिल)", "बिक्री (2 बिल)")}),
    }
    for key, (extra, langs) in sentences.items():
        for lang, expected in langs.items():
            t = t_for(lang)
            for count, want in enumerate(expected):
                args = dict(extra, count=count, n=count)
                assert t(key, **args) == want, (key, lang, count)


def _credit_bill(client, token, tmp_path, phone, name="Kumar"):
    bill_id = _seed_bill(tmp_path, token, phone=None)
    resp = client.post(f"/e/{token}/bills/{bill_id}/credit",
                       data={"customer_name": name,
                             "customer_phone": phone})
    assert resp.status_code == 303, resp.text


def test_credit_list_one_bill(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _credit_bill(client, token, tmp_path, "+919876543211")
    html = htmlmod.unescape(client.get(f"/e/{token}/credit").text)
    assert "1 bill" in html
    assert "1 Bills" not in html
    client.cookies.set("ui_lang", "ta")
    html = htmlmod.unescape(client.get(f"/e/{token}/credit").text)
    assert "1 பில்" in html


def test_credit_list_two_bills(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _credit_bill(client, token, tmp_path, "+919876543212")
    _credit_bill(client, token, tmp_path, "+919876543212")
    html = htmlmod.unescape(client.get(f"/e/{token}/credit").text)
    assert "2 bills" in html


def test_close_page_zero_bills(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/close").text
    assert "0 bills" in html


def test_shop_summary_singular(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = htmlmod.unescape(client.get(f"/s/{_slug(tmp_path, token)}").text)
    assert "1 item, from" in html
    assert "Search 1 item" in html


def test_market_group_shop_counts(tmp_path, monkeypatch):
    from app.market.search import Query, Want
    from app.web import main as main_mod

    seed_market(tmp_path)
    seed_shop(tmp_path, "Devi Veg", "Koyambedu",
              [market_draft("tomato", "தக்காளி", "41")],
              phone="+914400000099")
    client = market_client(tmp_path)

    def fake_parse(text, **_kw):
        return Query([Want(text, None, None, None)], None, None)

    monkeypatch.setattr(main_mod, "parse_query", fake_parse)
    one = htmlmod.unescape(client.get("/market?q=potato").text)
    assert "1 shop" in one
    assert "1 shops" not in one
    two = htmlmod.unescape(client.get("/market?q=tomato").text)
    assert "2 shops" in two


def test_review_headline_singular(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    session_id = _start_review_session(
        tmp_path, token, [_two_price_draft(), _draft("tomato", 40)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "1 price needs one tap." in html


def test_dashboard_live_singular(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}").text
    assert "Live · 1 price" in html
    assert "Live · 1 prices" not in html


# --- 4. phone header fit ------------------------------------------------------


def test_phone_header_compact_structure(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/s/{_slug(tmp_path, token)}").text
    head = re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)
    bag = re.search(r'<a class="pill ghost sm hp-bag"[^>]*>(.*?)</a>', head,
                    re.DOTALL)
    assert bag, "no Bag button in header"
    assert 'aria-label="Bag"' in head
    assert 'class="bag-label"' in bag.group(1)
    assert "data-bag-count" in bag.group(1)
    # Task 122: the sell pill moved to the phone menu; location +
    # search buttons join the compact header.
    assert "data-loc-open" in head
    assert "data-search-open" in head
    assert "data-menu-open" in head  # menu button kept


def test_phone_header_css_420_rules():
    css = PUBLIC_CSS.read_text()
    block = css.split("@media (max-width: 420px)", 1)[1]
    block = block.split("@media", 1)[0]
    assert ".hp-sell .free-badge" in block and "display: none" in block
    assert ".hp-bag .bag-label" in block
    assert ".hp-sell" in block and "font-size: 13px" in block
    # Task 125: one row — the header never wraps; the location
    # button ellipsizes instead.
    assert "flex-wrap: nowrap" in block
    assert "flex-wrap: wrap" not in block
    assert ".hp-menu-btn" in block


def test_bag_badge_js_wiring():
    js = MY_JS.read_text()
    assert "data-bag-count" in js
    assert "hidden" in js


# --- 5. cart bar layout -------------------------------------------------------


def test_shop_cart_layout_structure(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/s/{_slug(tmp_path, token)}").text
    for hook in SHOP_HOOKS:
        assert hook in html, hook
    grid_at = html.index("data-shop-grid")
    side_at = html.index('class="shop-side"')
    bar_at = html.index("data-cart-bar")
    summary_at = html.index("data-cart-summary")
    layout_at = html.index('class="shop-layout"')
    assert layout_at < grid_at < side_at < bar_at < summary_at
    side = html[side_at:html.index("</aside>", side_at)]
    assert "data-cart-bar" in side and "data-cart-summary" in side
    assert "data-cart-error" in side


def test_cart_bar_css_phone_and_laptop():
    css = PUBLIC_CSS.read_text()
    phone = re.search(r"body\.pub \.float\.shop-float \{(.*?)\}", css,
                      re.DOTALL).group(1)
    assert "position: fixed" in phone
    assert "left: 12px" in phone and "right: 12px" in phone
    laptop = css.split("@media (min-width: 1000px)", 1)[1]
    assert "grid-template-columns: minmax(0, 1fr) 340px" in laptop
    assert ".shop-side" in laptop and "position: sticky" in laptop
    assert "position: static" in laptop  # bar docks, never overlaps
    assert "display: none" not in laptop.split(
        ".float.shop-float", 1)[1][:80]
