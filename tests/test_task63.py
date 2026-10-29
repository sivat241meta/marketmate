"""Task 63: MARKET "NEAR ME" AND OPENING HOURS. Failing-tests-first."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, name="Hours Store", phone="+914400000063",
                language="ta", area="Koyambedu"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": area,
        "language": language, "currency": "INR", "type": "vegetable"})
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


def publish(tmp_path, token, drafts=None):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(
            conn, session_id, list(drafts or [_draft("tomato", 40)]))
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def set_listed(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET listed = 1 WHERE id = ?",
                     (shop["id"],))
        conn.commit()
        return shop["slug"]
    finally:
        conn.close()


def shop_row(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)
    finally:
        conn.close()


def update_market(tmp_path, token, **kwargs):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        db.update_shop_settings(
            conn, shop["id"], name=shop["name"], area=shop["area"],
            phone=shop["phone"], language=shop["language"],
            currency=shop["currency"], shop_type=shop["type"],
            upi_id=shop["upi_id"], upi_payee=shop["upi_payee"],
            round_bills=True, **kwargs)
    finally:
        conn.close()


def at_ist(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# --- 1. hours parser + open/closed decision (IST) ---


def test_hours_two_slots_open_and_closed():
    from app.market.hours import open_status

    # Monday 2026-11-02: 06:00-13:00 and 16:30-21:30.
    raw = json.dumps({"closed": [],
                      "slots": {"0": [["06:00", "13:00"],
                                      ["16:30", "21:30"]]}})
    assert open_status(raw, at_ist(2026, 11, 2, 7))["state"] == "open"
    midday = open_status(raw, at_ist(2026, 11, 2, 14))
    assert midday["state"] == "closed"
    assert midday["time"] == "4:30 pm"
    evening = open_status(raw, at_ist(2026, 11, 2, 17))
    assert evening["state"] == "open"
    assert evening["time"] == "9:30 pm"


def test_hours_closed_days():
    from app.market.hours import open_status

    raw = json.dumps({"closed": [6],
                      "slots": {"6": [["06:00", "21:00"]]}})
    # Sunday 2026-11-01 is closed even though a slot is stored.
    assert open_status(raw, at_ist(2026, 11, 1, 10))["state"] == "closed"
    assert open_status(raw, at_ist(2026, 11, 1, 10))["time"] == ""


def test_hours_overnight_around_midnight():
    from app.market.hours import open_status

    # Friday 16:00 -> Saturday 02:00.
    raw = json.dumps({"closed": [],
                      "slots": {"4": [["16:00", "02:00"]]}})
    assert open_status(raw, at_ist(2026, 10, 30, 23))["state"] == "open"
    assert open_status(raw, at_ist(2026, 10, 31, 1))["state"] == "open"
    assert open_status(raw, at_ist(2026, 10, 31, 3))["state"] == "closed"
    assert open_status(raw, at_ist(2026, 10, 30, 15))["state"] == "closed"


def test_hours_unknown_when_unset():
    from app.market.hours import has_hours, open_status

    assert open_status(None)["state"] == "unknown"
    assert open_status("")["state"] == "unknown"
    assert open_status("not-json")["state"] == "unknown"
    assert has_hours(None) is False
    assert has_hours("") is False


def test_hours_form_parser_two_slots_and_closed():
    from app.market.hours import parse_hours_form

    form = {"closed_6": "1",
            "open_0_1": "06:00", "close_0_1": "13:00",
            "open_0_2": "16:30", "close_0_2": "21:30"}
    data = json.loads(parse_hours_form(form))
    assert data["closed"] == [6]
    assert data["slots"]["0"] == [["06:00", "13:00"],
                                  ["16:30", "21:30"]]
    assert parse_hours_form({}) == ""
    with pytest.raises(ValueError):
        parse_hours_form({"open_0_1": "25:00", "close_0_1": "13:00"})


# --- 2. pincode: 6 digits ---


def test_pincode_must_be_6_digits():
    from app.market.hours import validate_pincode

    assert validate_pincode("") is None
    assert validate_pincode(None) is None
    assert validate_pincode("600001") == "600001"
    for bad in ("60001", "6000011", "6000a1", " 600 001 "):
        with pytest.raises(ValueError):
            validate_pincode(bad)


def test_settings_rejects_bad_pincode(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    shop = shop_row(tmp_path, token)
    resp = client.post(f"/e/{token}/settings", data={
        "name": shop["name"], "area": shop["area"], "phone": shop["phone"],
        "language": shop["language"], "currency": shop["currency"],
        "type": shop["type"], "pincode": "123"})
    assert resp.status_code == 400, resp.text
    assert shop_row(tmp_path, token)["pincode"] is None


# --- 3. lat/lng rounded to 3 decimals, removable ---


def test_coords_rounded_and_removable(tmp_path):
    from app.market.hours import round_coord

    assert round_coord("13.082684") == pytest.approx(13.083)
    assert round_coord("") is None
    assert round_coord(None) is None
    with pytest.raises(ValueError):
        round_coord("999")

    client = make_client(tmp_path)
    token = create_shop(client)
    shop = shop_row(tmp_path, token)
    base = {"name": shop["name"], "area": shop["area"],
            "phone": shop["phone"], "language": shop["language"],
            "currency": shop["currency"], "type": shop["type"]}
    resp = client.post(f"/e/{token}/settings", data={
        **base, "lat": "13.0826844", "lng": "80.2707184"})
    assert resp.status_code == 303, resp.text
    saved = shop_row(tmp_path, token)
    assert saved["lat"] == pytest.approx(13.083)
    assert saved["lng"] == pytest.approx(80.271)
    # Remove location clears both.
    resp = client.post(f"/e/{token}/settings", data={
        **base, "remove_location": "1"})
    assert resp.status_code == 303, resp.text
    cleared = shop_row(tmp_path, token)
    assert cleared["lat"] is None
    assert cleared["lng"] is None


def test_migration_adds_nullable_columns(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        cols = {row[1] for row in
                conn.execute("PRAGMA table_info(shops)")}
        assert {"hours_json", "pincode", "lat", "lng"} <= cols
        shop_id, _, _ = db.create_shop(
            conn, name="Mig", phone="+911234567890", area="X",
            language="ta", currency="INR", shop_type="vegetable")
        row = conn.execute("SELECT * FROM shops WHERE id = ?",
                           (shop_id,)).fetchone()
        assert row["hours_json"] is None
        assert row["pincode"] is None
        assert row["lat"] is None and row["lng"] is None
    finally:
        conn.close()


# --- 4. market filters on the server ---


def seed_market(tmp_path):
    """Two listed shops: cheap Anna Nagar (600001) + pricey Koyambedu."""
    from app.market.search import Query, Want  # noqa: F401

    conn = db.connect(tmp_path / "data")
    try:
        a_id, a_slug, _ = db.create_shop(
            conn, name="Anna Cheap", phone="+914400000001",
            area="Anna Nagar", language="ta", currency="INR",
            shop_type="vegetable", listed=True)
        b_id, b_slug, _ = db.create_shop(
            conn, name="Koya Pricy", phone="+914400000002",
            area="Koyambedu", language="ta", currency="INR",
            shop_type="vegetable", listed=True)
        for shop_id, price in ((a_id, 18), (b_id, 30)):
            session_id = db.create_session(conn, shop_id, "video")
            version_id = db.approve(conn, session_id,
                                    [_draft("tomato", price)])
            db.set_published(conn, version_id, True)
        conn.execute("UPDATE shops SET pincode = '600001' WHERE id = ?",
                     (a_id,))
        conn.execute("UPDATE shops SET pincode = '600002' WHERE id = ?",
                     (b_id,))
        conn.commit()
    finally:
        conn.close()
    return a_slug, b_slug


def fake_query(monkeypatch, **kwargs):
    from app.market.search import Query, Want

    def fake_parse_query(text, **kw):
        return Query([Want("tomato", Decimal(2), "kg", None)],
                     Decimal(500), None, **kwargs)

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)


def test_market_filters_area_pincode_open_now(tmp_path, monkeypatch):
    from app.market.search import Query, Want, find_listings

    a_slug, b_slug = seed_market(tmp_path)
    query = Query([Want("tomato", None, None, None)], None, None)
    conn = db.connect(tmp_path / "data")
    try:
        rows = find_listings(conn, query, datetime.now(IST),
                             pincode="600001")
        assert [r.shop_name for r in rows] == ["Anna Cheap"]
        rows = find_listings(conn, query, datetime.now(IST),
                             area="koyambedu")
        assert [r.shop_name for r in rows] == ["Koya Pricy"]
    finally:
        conn.close()

    fake_query(monkeypatch)
    client = make_client(tmp_path)
    html = client.get("/market", params={"q": "tomato 2 kg",
                                         "pincode": "600002"}).text
    assert "Koya Pricy" in html
    assert "Anna Cheap" not in html
    html = client.get("/market", params={"q": "tomato 2 kg",
                                         "area": "Anna Nagar"}).text
    assert "Anna Cheap" in html
    assert "Koya Pricy" not in html
    assert a_slug and b_slug


def test_market_open_now_filter_server_side(tmp_path, monkeypatch):
    from app.market.search import Query, Want, find_listings

    seed_market(tmp_path)
    today = datetime.now(IST).weekday()
    closed_today = json.dumps({"closed": [today], "slots": {}})
    always_open = json.dumps({"closed": [], "slots": {
        str(d): [["00:00", "00:00"]] for d in range(7)}})
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE shops SET hours_json = ? WHERE name = ?",
                     (closed_today, "Anna Cheap"))
        conn.execute("UPDATE shops SET hours_json = ? WHERE name = ?",
                     (always_open, "Koya Pricy"))
        conn.commit()
        query = Query([Want("tomato", None, None, None)], None, None)
        rows = find_listings(conn, query, datetime.now(IST),
                             open_only=True)
        assert [r.shop_name for r in rows] == ["Koya Pricy"]
        rows = find_listings(conn, query, datetime.now(IST),
                             open_only=False)
        assert {r.shop_name for r in rows} == {"Anna Cheap",
                                               "Koya Pricy"}
    finally:
        conn.close()

    fake_query(monkeypatch)
    client = make_client(tmp_path)
    html = client.get("/market", params={"q": "tomato 2 kg",
                                         "open_now": "1"}).text
    assert "Koya Pricy" in html
    assert "Anna Cheap" not in html
    html = client.get("/market", params={"q": "tomato 2 kg",
                                         "open_now": "0"}).text
    assert "Anna Cheap" in html and "Koya Pricy" in html


def test_market_areas_and_basket_extras(tmp_path, monkeypatch):
    seed_market(tmp_path)
    fake_query(monkeypatch)
    client = make_client(tmp_path)
    html = client.get("/market", params={"q": "tomato 2 kg"}).text
    # Area chips list both live-price areas.
    assert "Anna Nagar" in html and "Koyambedu" in html
    # Sort control + pincode box + open-now toggle exist.
    assert 'name="sort"' in html
    assert 'name="pincode"' in html
    assert 'name="open_now"' in html
    assert "Near me" in html
    # Basket keeps total, under-budget, best tag and missing-words wiring.
    assert "under budget" in html
    assert "Best" in html
    assert "₹" in html


# --- 5. privacy: customer location never leaves the phone ---


def _market_scripts(html):
    srcs = []
    for match in re.finditer(
            r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>', html):
        src = match.group(1).split("?")[0]
        if src.startswith("/static/"):
            path = ROOT / "app/web/static" / src[len("/static/"):]
            if path.is_file():
                srcs.append(path.read_text(encoding="utf-8"))
    for match in re.finditer(r"<script(?![^>]*src=)[^>]*>(.*?)</script>",
                             html, re.DOTALL):
        srcs.append(match.group(1))
    return srcs


def test_market_js_never_posts_customer_coords(tmp_path, monkeypatch):
    seed_market(tmp_path)
    fake_query(monkeypatch)
    client = make_client(tmp_path)
    html = client.get("/market", params={"q": "tomato 2 kg"}).text
    assert "near-me" in html
    for src in _market_scripts(html):
        has_net = ("fetch(" in src) or ("XMLHttpRequest" in src)
        has_coord = re.search(
            r"\b(lat|lng|latitude|longitude)\b", src,
            re.IGNORECASE) is not None
        assert not (has_net and has_coord), src[:200]


def test_near_me_js_has_no_network_calls():
    src = (ROOT / "app/web/static/near-me.js").read_text(
        encoding="utf-8")
    assert "fetch(" not in src
    assert "XMLHttpRequest" not in src
    assert "haversine" in src.lower()


def test_node_distance_helper():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/near_me.test.mjs"], cwd=ROOT, check=False,
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- 6. shop page chip ---


def test_shop_page_shows_open_chip(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = set_listed(tmp_path, token)
    publish(tmp_path, token)
    always_open = json.dumps({"closed": [], "slots": {
        str(d): [["00:00", "00:00"]] for d in range(7)}})
    update_market(tmp_path, token, hours_json=always_open)
    html = client.get(f"/s/{slug}").text
    assert "Open now" in html
    assert "data-open-chip" in html


def test_shop_page_shows_closed_chip(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = set_listed(tmp_path, token)
    publish(tmp_path, token)
    today = datetime.now(IST).weekday()
    tomorrow = (today + 1) % 7
    raw = json.dumps({"closed": [today],
                      "slots": {str(tomorrow): [["06:00", "21:00"]]}})
    update_market(tmp_path, token, hours_json=raw)
    html = client.get(f"/s/{slug}").text
    assert "Closed" in html
    assert "opens 6:00 am" in html


# --- 7. order page closed notice ---


def test_order_page_closed_notice(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = set_listed(tmp_path, token)
    publish(tmp_path, token)
    today = datetime.now(IST).weekday()
    tomorrow = (today + 1) % 7
    raw = json.dumps({"closed": [today],
                      "slots": {str(tomorrow): [["06:00", "21:00"]]}})
    update_market(tmp_path, token, hours_json=raw)
    html = client.get(f"/s/{slug}/quote").text
    assert "Shop is closed now" in html
    assert "6:00 am" in html


# --- 8. seller nudge ---


def test_seller_nudge_until_hours_set(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token)
    assert "Add your hours" in client.get(f"/e/{token}").text
    assert "Add your hours" in client.get(
        f"/e/{token}/settings").text
    update_market(tmp_path, token, hours_json=json.dumps(
        {"closed": [], "slots": {"0": [["06:00", "13:00"]]}}))
    assert "Add your hours" not in client.get(f"/e/{token}").text
    assert "Add your hours" not in client.get(
        f"/e/{token}/settings").text


# --- 9. pages render in en/ta/hi ---


@pytest.mark.parametrize("lang,word", [("ta", "சந்தை"), ("hi", "बाज़ार")])
def test_market_renders_ta_hi(tmp_path, monkeypatch, lang, word):
    seed_market(tmp_path)
    fake_query(monkeypatch)
    client = make_client(tmp_path)
    client.cookies.set("ui_lang", lang)
    html = client.get("/market", params={"q": "tomato 2 kg"}).text
    assert word in html
    assert "data-open-chip" in html or "Open now" in html or \
        "இப்போது" in html or "खुला" in html


def test_shop_quote_settings_render_ta(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client, language="ta")
    slug = set_listed(tmp_path, token)
    publish(tmp_path, token)
    update_market(tmp_path, token, hours_json=json.dumps(
        {"closed": [], "slots": {
            str(d): [["00:00", "00:00"]] for d in range(7)}}))
    assert "இப்போது" in client.get(f"/s/{slug}?lang=ta").text
    client.cookies.set("ui_lang", "ta")
    settings = client.get(f"/e/{token}/settings").text
    assert "அஞ்சல் குறியீடு" in settings
    assert "திறந்திருக்கும் நேரம்" in settings


def test_quote_start_renders_hi(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client, language="hi")
    slug = set_listed(tmp_path, token)
    publish(tmp_path, token)
    today = datetime.now(IST).weekday()
    tomorrow = (today + 1) % 7
    update_market(tmp_path, token, hours_json=json.dumps(
        {"closed": [today],
         "slots": {str(tomorrow): [["06:00", "21:00"]]}}))
    html = client.get(f"/s/{slug}/quote?lang=hi").text
    assert "बंद है" in html
