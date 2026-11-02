"""Task 107: full-flow test fixes.

Covers the night-market open-now default + closed-shops notice, the
basket summary currency + no-call rule, refused Rs.0 orders + the
seller nothing-priced note, the phone-overflow CSS guards, and the
small wording/style fixes, plus a render sweep over every page in
en/ta/hi (no browser is available here, so the sweep renders each
template with sample data).
"""

from __future__ import annotations

import json
from datetime import datetime
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


def make_client(tmp_path, lang="en"):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    return client


def create_shop(client, name="Night Veg", phone="+914400000101",
                language="ta", area="Koyambedu", **extra):
    data = {"name": name, "phone": phone, "area": area,
            "language": language, "currency": "INR", "type": "vegetable"}
    data.update(extra)
    resp = client.post("/new", data=data)
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, variety=None, unit="kg", local=None):
    return DraftItem(
        name_spoken=name_en, name_local=local or name_en, name_en=name_en,
        variety=variety, price_lines=[PriceLine(Decimal(price), Decimal(1),
                                               unit)],
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
        return version_id
    finally:
        conn.close()


def shop_row(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)
    finally:
        conn.close()


def set_hours(tmp_path, token, payload):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET hours_json = ? WHERE id = ?",
                     (json.dumps(payload), shop["id"]))
        conn.commit()
    finally:
        conn.close()


def fake_market(monkeypatch, wants, explain="Basket picks."):
    """Fake market query + explanation; records explanation calls."""
    from app.market.search import Query

    calls = []

    def fake_parse_query(text, **kwargs):
        return Query(list(wants), None, None)

    def fake_explain(plans, budget, **kwargs):
        calls.append((plans, budget))
        return explain

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    monkeypatch.setattr("app.web.main.explain_basket", fake_explain)
    return calls


def seed_night_shop(tmp_path, monkeypatch=None):
    """Closed-today shop with brinjal Rs.100 + beans Rs.80."""
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("brinjal", 100),
                              _draft("beans", 80)])
    today = datetime.now().weekday()
    set_hours(tmp_path, token, {"closed": [today], "slots": {}})
    if monkeypatch is not None:
        from app.market.search import Want

        fake_market(monkeypatch, [Want("brinjal", Decimal(1), "kg", None),
                                  Want("beans", Decimal(1), "kg", None)])
    return client, token


def seed_order(tmp_path, token, wanted, **kwargs):
    """Customer order straight from wanted lines; returns (id, token)."""
    from app.market.quote import build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = build_quote(conn, shop["id"], wanted)
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 customer_name=kwargs.get("customer_name",
                                                          "Kannan"),
                                 customer_phone=kwargs.get(
                                     "customer_phone", "+919876543210"))
        row = db.get_quote_by_token(conn, qtoken)
        return row["id"], qtoken
    finally:
        conn.close()


def set_quote_status(tmp_path, quote_id, status):
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE quotes SET status = ? WHERE id = ?",
                     (status, quote_id))
        conn.commit()
    finally:
        conn.close()


# --- 1. Open-now defaults OFF; closed shops get a notice, not "No fresh" ---


def test_market_open_now_off_by_default_finds_closed_shop(tmp_path,
                                                           monkeypatch):
    client, _token = seed_night_shop(tmp_path, monkeypatch)
    html = client.get("/market",
                      params={"q": "brinjal 1 kg, beans 1 kg"}).text
    assert "₹180" in html
    assert "Closed" in html
    assert "No fresh prices" not in html
    assert 'id="market-open"' in html
    assert 'value="1" checked' not in html


def test_market_open_now_ticked_shows_closed_notice(tmp_path, monkeypatch):
    from app.market.search import Want

    client, _token = seed_night_shop(tmp_path)
    calls = fake_market(monkeypatch, [Want("brinjal", Decimal(1), "kg",
                                           None),
                                      Want("beans", Decimal(1), "kg",
                                           None)])
    html = client.get("/market", params={"q": "brinjal 1 kg, beans 1 kg",
                                         "open_now": "1"}).text
    assert "1 shop has these but is closed now." in html
    assert "No fresh prices" not in html
    assert "No shops have what you asked" not in html
    assert "data-closed-notice" in html
    assert "open_now=0" in html
    assert "Show all shops" in html
    # Fixed sentence, so the basket explainer never runs.
    assert calls == []


def test_market_open_now_untick_link_finds_prices(tmp_path, monkeypatch):
    client, _token = seed_night_shop(tmp_path, monkeypatch)
    html = client.get("/market", params={"q": "brinjal 1 kg, beans 1 kg",
                                         "open_now": "0"}).text
    assert "₹180" in html
    assert "data-closed-notice" not in html


# --- 2. Basket summary keeps the currency; empty baskets skip Spark ---


def test_basket_prompt_formats_money_with_currency():
    from app.market.basket import build_basket_messages, plan_basket
    from app.market.search import Listing, Want
    from app.models import PriceLine

    def listing(shop, name, price):
        return Listing(shop_name=shop, slug=shop.lower(), area="A",
                       is_demo=False, name_en=name, variety=None,
                       line=PriceLine(Decimal(price), Decimal(1), "kg"),
                       rate=Decimal(price), rate_unit="kg",
                       updated_at=datetime.now(), stale=False)

    wants = [Want("brinjal", Decimal(1), "kg", None),
             Want("beans", Decimal(1), "kg", None)]
    plans = plan_basket(wants, [listing("Night Veg", "brinjal", 100),
                                listing("Night Veg", "beans", 80)],
                        Decimal(500))
    user_text = build_basket_messages(plans, Decimal(500))[1]["content"]
    assert "₹180" in user_text
    assert "₹500" in user_text
    assert "currency sign" in user_text
    assert '"total": "180"' not in user_text


def test_empty_basket_skips_spark_and_shows_fixed_sentence(tmp_path,
                                                            monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    from app.market.search import Want

    calls = fake_market(monkeypatch, [Want("brinjal", Decimal(1), "kg",
                                           None),
                                      Want("beans", Decimal(1), "kg",
                                           None)])
    html = client.get("/market",
                      params={"q": "brinjal 1 kg, beans 1 kg"}).text
    assert "No shop has these in today&#39;s lists yet." in html or \
        "No shop has these in today's lists yet." in html
    assert calls == []


def test_explain_basket_never_calls_spark_without_lines(tmp_path):
    from app.costs import CostLedger
    from app.market.basket import explain_basket, plan_basket
    from app.market.search import Want

    def boom(messages, **kwargs):
        raise AssertionError("Spark must not be called")

    import app.market.basket as basket_mod

    original = basket_mod.chat_json
    basket_mod.chat_json = boom
    try:
        ledger = CostLedger(tmp_path / "c.db", 100.0)
        settings = load_settings({"MODEL_API_KEY": "k"})
        plans = plan_basket([Want("brinjal", Decimal(1), "kg", None)], [],
                            None)
        text = explain_basket(plans, None, ledger=ledger, settings=settings)
    finally:
        basket_mod.chat_json = original
    assert "brinjal" in text


# --- 3. A Rs.0 order can neither be sent nor collected ---


def fake_typed_wanted(monkeypatch, wanted):
    def fake_parse(text, *args, **kwargs):
        return (list(wanted), "")

    monkeypatch.setattr("app.web.quotes.wanted_local_first", fake_parse)


def quote_count(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        return len(db.list_quotes(conn, shop["id"]))
    finally:
        conn.close()


def test_text_order_nothing_priced_not_sent(tmp_path, monkeypatch):
    from app.market.quote import WantedLine

    client = make_client(tmp_path)
    token = create_shop(client)
    slug = shop_row(tmp_path, token)["slug"]
    publish(tmp_path, token, [_draft("tomato", 40)])
    fake_typed_wanted(monkeypatch, [WantedLine(
        name_en="mango", qty=Decimal(1), unit="kg", source="text")])
    resp = client.post(f"/s/{slug}/quote",
                       data={"items": "mango 1 kg",
                             "customer_name": "Kannan"})
    assert resp.status_code == 200
    assert "This shop doesn&#39;t have these today" in resp.text or \
        "This shop doesn't have these today" in resp.text
    assert "data-quote-empty" in resp.text
    assert f"/s/{slug}" in resp.text
    assert f"/s/{slug}/quote" in resp.text
    assert quote_count(tmp_path, token) == 0


def test_partly_priced_order_still_sends(tmp_path, monkeypatch):
    from app.market.quote import WantedLine

    client = make_client(tmp_path)
    token = create_shop(client)
    slug = shop_row(tmp_path, token)["slug"]
    publish(tmp_path, token, [_draft("tomato", 40)])
    fake_typed_wanted(monkeypatch, [
        WantedLine(name_en="tomato", qty=Decimal(1), unit="kg",
                   source="text"),
        WantedLine(name_en="mango", qty=Decimal(1), unit="kg",
                   source="text")])
    resp = client.post(f"/s/{slug}/quote",
                       data={"items": "tomato 1 kg, mango 1 kg",
                             "customer_name": "Kannan"})
    assert resp.status_code in (302, 303)
    assert quote_count(tmp_path, token) == 1
    html = client.get(resp.headers["location"]).text
    assert "not on this shop&#39;s list" in html or \
        "not on this shop's list" in html
    assert "₹40" in html


def test_cart_nothing_priced_rejected(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = shop_row(tmp_path, token)["slug"]
    publish(tmp_path, token, [_draft("tomato", 40)])
    resp = client.post(f"/s/{slug}/quote", json={
        "lines": [{"name_en": "mango", "qty": 1, "unit": "kg"}],
        "customer_name": "Kannan"})
    assert resp.status_code == 400
    assert "doesn" in resp.json()["error"]
    assert quote_count(tmp_path, token) == 0


def _voice_fakes(monkeypatch, transcript, wants_json):
    from pathlib import Path as _Path

    from app.market.search import parse_query_json
    from app.models import Transcript

    monkeypatch.setattr(
        "app.web.quotes.extract_audio",
        lambda video, out: _Path(out).parent.mkdir(parents=True,
                                                   exist_ok=True)
        or _Path(out).write_bytes(b"RIFF") or _Path(out))
    monkeypatch.setattr(
        "app.web.quotes.transcribe_wav",
        lambda wav, **kw: Transcript(text=transcript, duration_ms=1000,
                                     turns=[]))
    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(wants_json))


def test_voice_session_nothing_priced_shows_empty_page(tmp_path,
                                                       monkeypatch):
    from app.costs import CostLedger
    from app.web.quotes import process_quote_voice_session

    client = make_client(tmp_path)
    token = create_shop(client)
    shop = shop_row(tmp_path, token)
    publish(tmp_path, token, [_draft("tomato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        session_id = db.create_session(conn, shop["id"], "quote_voice")
    finally:
        conn.close()
    _voice_fakes(monkeypatch, "mango 1 kg",
                 {"wants": [{"name": "mango", "amount": 1, "unit": "kg",
                              "max_rate": None}],
                  "budget": None, "area": None})
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    conn = db.connect(tmp_path / "data")
    try:
        ledger = CostLedger(tmp_path / "c.db", 100.0)
        assert process_quote_voice_session(
            conn, session_id, tmp_path / "q.webm", settings=settings,
            ledger=ledger) is None
    finally:
        conn.close()
    assert quote_count(tmp_path, token) == 0
    html = client.get(f"/s/{shop['slug']}/quote/{session_id}").text
    assert "data-quote-empty" in html
    assert "have these today" in html


def test_voice_session_priced_still_sends(tmp_path, monkeypatch):
    from app.costs import CostLedger
    from app.web.quotes import process_quote_voice_session

    client = make_client(tmp_path)
    token = create_shop(client)
    shop = shop_row(tmp_path, token)
    publish(tmp_path, token, [_draft("tomato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        session_id = db.create_session(conn, shop["id"], "quote_voice")
    finally:
        conn.close()
    _voice_fakes(monkeypatch, "tomato 1 kg",
                 {"wants": [{"name": "tomato", "amount": 1, "unit": "kg",
                              "max_rate": None}],
                  "budget": None, "area": None})
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    conn = db.connect(tmp_path / "data")
    try:
        ledger = CostLedger(tmp_path / "c.db", 100.0)
        qtoken = process_quote_voice_session(
            conn, session_id, tmp_path / "q.webm", settings=settings,
            ledger=ledger)
    finally:
        conn.close()
    assert qtoken
    assert quote_count(tmp_path, token) == 1


def seed_nothing_priced(tmp_path):
    from app.market.quote import WantedLine

    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    order_id, _qtoken = seed_order(
        tmp_path, token,
        [WantedLine(name_en="mango", qty=Decimal(1), unit="kg",
                    source="voice"),
         WantedLine(name_en="papaya", qty=Decimal(2), unit="kg",
                    source="voice")])
    return client, token, order_id


def test_seller_bill_nothing_priced_note_no_payment(tmp_path):
    client, token, order_id = seed_nothing_priced(tmp_path)
    html = client.get(f"/e/{token}/bills/{order_id}").text
    assert "Nothing from today&#39;s list" in html or \
        "Nothing from today's list" in html
    assert "data-nothing-priced" in html
    # Cancel order is the primary action, ahead of Start packing.
    assert html.index('value="cancelled"') < html.index('value="packing"')
    set_quote_status(tmp_path, order_id, "ready")
    html = client.get(f"/e/{token}/bills/{order_id}").text
    assert "data-nothing-priced" in html
    assert "Collect payment" not in html
    assert "bill-bar" not in html
    assert "₹0 to collect" not in html


def test_nothing_priced_order_cannot_be_paid(tmp_path):
    client, token, order_id = seed_nothing_priced(tmp_path)
    set_quote_status(tmp_path, order_id, "ready")
    resp = client.post(f"/e/{token}/bills/{order_id}/paid",
                       data={"mode": "cash"})
    assert resp.status_code == 400
    assert "call the customer" in resp.text
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_id(conn, order_id)
        assert row["status"] == "ready"
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/bills/{order_id}/credit",
                       data={"customer_name": "Kannan",
                             "customer_phone": "+919876543210"})
    assert resp.status_code == 400


def test_board_card_nothing_priced_cancel_first(tmp_path):
    client, token, _order_id = seed_nothing_priced(tmp_path)
    html = client.get(f"/e/{token}/bills").text
    assert "data-nothing-priced" in html
    assert "call the customer" in html
    assert 'value="cancelled"' in html
    assert "Cancel order" in html


# --- 4-7, 8a-b, 8h. Phone CSS guards (no browser here, so the rules
# themselves are pinned; the sweep below renders every page). ---


def app_css():
    return (ROOT / "app" / "web" / "static" / "app.css").read_text()


def public_css():
    return (ROOT / "app" / "web" / "static" / "css" / "public.css").read_text()


def seller_css():
    return (ROOT / "app" / "web" / "static" / "css" / "seller.css").read_text()


def test_bill_page_css_fits_phones():
    css = app_css()
    assert ".bill-layout { display: grid; gap: var(--space-4); " \
        "grid-template-columns: minmax(0, 1fr); }" in css
    assert ".bill-layout > *, .bill-actions > * { min-width: 0; }" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert ".pill.cta, .pill.ghost, .pill.dark, .pill.bar" in css
    seller = seller_css()
    assert ".sticky-bar.bill-bar .sticky-total" in seller
    assert "flex: 1 1 100%;" in seller
    assert ".sticky-bar.bill-bar .pill" in seller


def test_market_rows_css_scroll_or_wrap():
    css = public_css()
    # Task 127: the v13 tab row scrolls inside its own container.
    v13 = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
    assert "overflow-x:auto" in v13.split(".mkt-tabs{")[1].split("}")[0].replace(
        " ", "")
    # Filter row scrolls on laptop, wraps with pincode on its own line.
    assert "body.pub .filter-row {" in css
    assert "overflow-x: auto;" in css
    assert "body.pub .filter-row { flex-wrap: wrap; }" in css
    assert "body.pub .filter-row .pin-wrap { flex: 1 1 100%; }" in css
    assert ".shop-row > *, .result-head > *" in app_css()


def test_bag_sheet_css_mirrors_order_column():
    css = public_css()
    assert "body.pub .sheet .rl {" in css
    assert "body.pub .sheet .rl small { display: block;" in css
    assert "body.pub .sheet .rl > b:last-child" in css
    assert "body.pub .sheet .rt {" in css
    assert "justify-content: space-between;" in css


def test_tap_grid_add_button_in_flow():
    css = app_css()
    assert ".tap-grid .card .add {" in css
    assert "position: static;" in css


def test_public_header_css_band_and_menu():
    assert "body.pub .content { padding-top: 0; }" in public_css()
    menu = app_css()
    assert ".hp-menu-btn {" in menu
    assert "width: 44px;\n  height: 44px;" in menu
    assert "border: 1.5px solid var(--line-2);" in menu


def test_get_started_buttons_wrap():
    assert ".hero-cta > * { min-width: 0; }" in app_css()


# --- 8c-g. Small wording/style fixes ---


def test_seller_pill_and_strip_count_lists(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        conn.execute("UPDATE sessions SET status = 'review' WHERE id = ?",
                     (session_id,))
        conn.commit()
    finally:
        conn.close()
    html = client.get(f"/e/{token}").text
    assert html.count("1 list to check") >= 2
    assert "needs you" not in html
    assert "need a tap" not in html


def test_today_list_item_without_variety(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("beans", 60)])
    html = client.get(f"/e/{token}").text
    assert "beans · 1 kg" in html
    assert "· /" not in html


def closed_reopening_shop(tmp_path):
    """Shop closed today that opens tomorrow at 6:00 am."""
    from app.market.quote import WantedLine

    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("tomato", 40)])
    today = datetime.now().weekday()
    set_hours(tmp_path, token,
              {"closed": [today],
               "slots": {str((today + 1) % 7): [["06:00", "22:00"]]}})
    order_id, qtoken = seed_order(
        tmp_path, token,
        [WantedLine(name_en="tomato", qty=Decimal(1), unit="kg",
                    source="text")])
    return client, token, order_id, qtoken


def test_order_closed_banner_only_while_new(tmp_path):
    client, _token, order_id, qtoken = closed_reopening_shop(tmp_path)
    html = client.get(f"/q/{qtoken}").text
    assert "will be seen at 6:00 am" in html
    for status in ("packing", "ready", "collected", "cancelled"):
        set_quote_status(tmp_path, order_id, status)
        html = client.get(f"/q/{qtoken}").text
        assert "will be seen at" not in html


def test_order_wording_uses_order(tmp_path):
    client, token, _order_id, qtoken = closed_reopening_shop(tmp_path)
    slug = shop_row(tmp_path, token)["slug"]
    shop_html = client.get(f"/s/{slug}").text
    assert "Order by voice" in shop_html
    assert "Get a price quote" not in shop_html
    quote_html = client.get(f"/q/{qtoken}").text
    assert "Update order" in quote_html
    assert "Update quote" not in quote_html


def test_settings_shop_type_select_translated(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    html = client.get(f"/e/{token}/settings").text
    assert 'name="type"' in html
    assert '<select class="field-input" id="set-type" name="type"' in html
    assert '<option value="vegetable" selected>Vegetables</option>' in html
    client.cookies.set("ui_lang", "ta")
    assert "காய்கறிகள்" in client.get(f"/e/{token}/settings").text
    client.cookies.set("ui_lang", "hi")
    assert "सब्ज़ियाँ" in client.get(f"/e/{token}/settings").text
    client.cookies.set("ui_lang", "en")
    shop = shop_row(tmp_path, token)
    resp = client.post(f"/e/{token}/settings", data={
        "name": shop["name"], "area": shop["area"], "phone": shop["phone"],
        "language": shop["language"], "currency": shop["currency"],
        "type": "vegetable"})
    assert resp.status_code in (302, 303)
    assert shop_row(tmp_path, token)["type"] == "vegetable"
    # A custom stored value is kept, never dropped by the select.
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE shops SET type = 'kirana' WHERE id = ?",
                     (shop["id"],))
        conn.commit()
    finally:
        conn.close()
    html = client.get(f"/e/{token}/settings").text
    assert '<option value="kirana" selected>kirana</option>' in html


# --- Sweep: every page renders in en/ta/hi ---
#
# No browser is available in this environment, so the sweep renders each
# template with sample data (the phone CSS guards above pin the actual
# no-overflow rules for 320px and 390px).


def seed_sweep_shop(tmp_path):
    from app.market.quote import WantedLine

    client = make_client(tmp_path)
    token = create_shop(client, language="ta", area="Koyambedu")
    publish(tmp_path, token, [_draft("brinjal", 100, local="கத்திரி"),
                              _draft("beans", 80, local="பீன்ஸ்"),
                              _draft("carrot", 80, variety="ooty",
                                     local="கேரட்"),
                              _draft("tomato", 40, local="தக்காளி")])
    shop = shop_row(tmp_path, token)
    order_id, qtoken = seed_order(
        tmp_path, token,
        [WantedLine(name_en="brinjal", qty=Decimal(1), unit="kg",
                    source="text")])
    empty_id, _empty_token = seed_order(
        tmp_path, token,
        [WantedLine(name_en="mango", qty=Decimal(1), unit="kg",
                    source="voice")])
    conn = db.connect(tmp_path / "data")
    try:
        review_sid = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, review_sid, [_draft("brinjal", 100)])
        db.set_session_status(conn, review_sid, "review", "check")
        quote_sid = db.create_session(conn, shop["id"], "quote_voice")
        bill_sid = db.create_session(conn, shop["id"], "bill_voice")
        bill_token = db.ensure_bill_token(conn, order_id)
    finally:
        conn.close()
    return {"client": client, "token": token, "slug": shop["slug"],
            "order_id": order_id, "qtoken": qtoken, "empty_id": empty_id,
            "review_sid": review_sid, "quote_sid": quote_sid,
            "bill_sid": bill_sid, "bill_token": bill_token}


def sweep_urls(seed):
    token = seed["token"]
    slug = seed["slug"]
    return [
        # Public pages.
        "/", "/?area=Koyambedu", "/market", "/new", "/my", "/share",
        "/sellers", "/how",
        f"/s/{slug}", f"/s/{slug}?lang=ta", f"/s/{slug}/quote",
        f"/s/{slug}/quote?lang=ta",
        f"/s/{slug}/quote/{seed['quote_sid']}",
        f"/s/{slug}/quote/{seed['quote_sid']}/status",
        f"/q/{seed['qtoken']}", f"/q/{seed['qtoken']}?lang=ta",
        f"/q/{seed['qtoken']}/status.json",
        f"/b/{seed['bill_token']}",
        # Seller pages.
        f"/e/{token}", f"/e/{token}/live", f"/e/{token}/bills",
        f"/e/{token}/bills?range=today&status=waiting",
        f"/e/{token}/bills/new",
        f"/e/{token}/bills/{seed['order_id']}",
        f"/e/{token}/bills/{seed['empty_id']}",
        f"/e/{token}/bills/new/{seed['bill_sid']}",
        f"/e/{token}/bills/new/{seed['bill_sid']}/status",
        f"/e/{token}/settings", f"/e/{token}/close",
        f"/e/{token}/credit", f"/e/{token}/purchases",
        f"/e/{token}/update", f"/e/{token}/photos", f"/e/{token}/ai",
        f"/e/{token}/s/{seed['review_sid']}",
        f"/e/{token}/prices.json",
    ]


def test_every_page_renders_en_ta_hi(tmp_path, monkeypatch):
    from app.market.search import Want

    seed = seed_sweep_shop(tmp_path)
    fake_market(monkeypatch, [Want("brinjal", Decimal(1), "kg", None),
                              Want("beans", Decimal(1), "kg", None)],
                explain="Sweep picks.")
    client = seed["client"]
    market_url = "/market?q=brinjal%201%20kg%2C%20beans%201%20kg"
    market_open = market_url + "&open_now=1"
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in sweep_urls(seed) + [market_url, market_open]:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url}: {resp.status_code}"
    # First-run seller home (the /try landing page with Save your link).
    client.cookies.set("ui_lang", "en")
    resp = client.get("/try")
    assert resp.status_code in (302, 303)
    first = client.get(resp.headers["location"])
    assert first.status_code == 200
    assert "Save your link" in first.text
    # A credit row renders its detail page too.
    bill_id = seed["order_id"]
    accept = client.post(f"/e/{seed['token']}/bills/{bill_id}/accept")
    assert accept.status_code in (302, 303), accept.text
    paid = client.post(f"/e/{seed['token']}/bills/{bill_id}/credit",
                       data={"customer_name": "Kannan",
                             "customer_phone": "+919876543210"})
    assert paid.status_code in (302, 303), paid.text
    credit_html = client.get(f"/e/{seed['token']}/credit").text
    assert "Kannan" in credit_html
    detail = client.get(f"/e/{seed['token']}/credit/+919876543210")
    assert detail.status_code == 200
