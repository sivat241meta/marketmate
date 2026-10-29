"""Task 56 failing-tests-first: end-to-end MUST-FIX items."""

import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.web.main import create_app


def _clean_item(**over):
    base = {
        "name_spoken": "tomato",
        "name_local": "தக்காளி",
        "name_en": "tomato",
        "variety": None,
        "price_lines": [PriceLine(Decimal(20), Decimal(1), "kg", "")],
        "qty": Decimal(5),
        "qty_unit": "kg",
        "proof": Proof(
            quote="tomato 20 rupees 5 kg",
            turn_ids=[1],
            start_ms=0,
            end_ms=1000,
            frame="frame1.jpg",
            audio_clip="/tmp/clip.mp4",
        ),
        "flags": [],
        "photo": "photos/tomato.jpg",
        "condition_hint": "fresh",
    }
    base.update(over)
    return DraftItem(**base)


def _make_client(tmp_path, monkeypatch, seed=None):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, [seed or _clean_item()])
        db.set_session_status(conn, session_id, "review", "1 item needs review")

    monkeypatch.setattr("app.web.seller.jobs.submit", fake_submit)
    monkeypatch.setattr("app.web.seller.process_video_session", fake_process)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client):
    response = client.post(
        "/new",
        data={
            "name": "Kannan Store",
            "phone": "+914400000000",
            "area": "Koyambedu",
            "language": "ta",
            "currency": "INR",
            "type": "vegetable",
        },
    )
    assert response.status_code in (302, 303)
    return response.headers["location"]


def _upload_session(client, location):
    return client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]


def test_56_03_empty_per_becomes_one(tmp_path, monkeypatch):
    """Missing per_amount with a unit becomes 1; never prints None."""
    seed = _clean_item(
        price_lines=[PriceLine(Decimal(80), None, "kg", "")],
        proof=Proof(
            quote="beans 80 rupees kg",
            turn_ids=[1],
            start_ms=0,
            end_ms=1000,
        ),
    )
    client = _make_client(tmp_path, monkeypatch, seed=seed)
    location = _create_shop(client)
    session_url = _upload_session(client, location)
    edited = {
        "name_spoken": "beans",
        "name_local": "பீன்ஸ்",
        "name_en": "beans",
        "variety": None,
        "price_lines": [{"said": "", "price": 80, "per_amount": None, "unit": "kg"}],
        "range_said": False,
        "qty": None,
        "qty_unit": None,
        "proof": {},
        "flags": [],
        "photo": None,
        "condition_hint": None,
        "confirmed": False,
    }
    response = client.post(session_url + "/approve", json={"items": [edited], "confirmed": []})
    assert response.status_code in (302, 303), response.text
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        version_id = db.latest_version(conn, shop_id)
        items = db.version_items(conn, version_id)
        assert items[0].price_lines[0].per_amount == Decimal(1)
        # Home list must not print None.
        home = client.get(location).text
        assert "None" not in home
        assert "per 1 kg" in home or "/ 1 kg" in home or "1 kg" in home
        # CSV export must carry 1, not empty.
        token = location.split("/e/")[1]
        csv_text = client.get(f"/e/{token}/v/{version_id}/export.csv").text
        assert "None" not in csv_text
        assert ",1," in csv_text or ",1.00," in csv_text or "1" in csv_text.splitlines()[1]
    finally:
        conn.close()


def test_56_03_never_prints_none_for_legacy(tmp_path, monkeypatch):
    """Legacy per_amount=None rows must not render as 'None' anywhere."""
    client = _make_client(tmp_path, monkeypatch)
    location = _create_shop(client)
    token = location.split("/e/")[1]
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO versions (shop_id, created_at, published) VALUES (?, ?, 1)",
            (shop_id, "2026-01-01T00:00:00+00:00"),
        )
        vid = cur.lastrowid
        db.insert_version_item(
            conn,
            vid,
            "பீன்ஸ்",
            "beans",
            None,
            None,
            None,
            None,
            False,
            Proof(quote="q", turn_ids=[], start_ms=0, end_ms=0),
            [PriceLine(Decimal(80), None, "kg", "")],
        )
        conn.commit()
    finally:
        conn.close()
    home = client.get(location).text
    assert "None" not in home
    csv_text = client.get(f"/e/{token}/v/{vid}/export.csv").text
    assert "None" not in csv_text
    # Public shop page too.
    conn = db.connect(tmp_path / "data")
    try:
        slug = conn.execute("SELECT slug FROM shops WHERE id = 1").fetchone()["slug"]
    finally:
        conn.close()
    shop_html = client.get(f"/s/{slug}").text
    assert "None" not in shop_html


def _publish_two_bananas(tmp_path):
    from app.config import load_settings

    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn,
            name="Banana Shop",
            phone="+914400000001",
            area="Koyambedu",
            language="ta",
            currency="INR",
            shop_type="vegetable",
        )
        cur = conn.execute(
            "INSERT INTO versions (shop_id, created_at, published) VALUES (?, ?, 1)",
            (shop_id, "2026-01-01T00:00:00+00:00"),
        )
        vid = cur.lastrowid
        db.insert_version_item(
            conn,
            vid,
            "வாழை",
            "banana",
            "poovan",
            None,
            None,
            None,
            False,
            Proof(quote="q", turn_ids=[], start_ms=0, end_ms=0),
            [PriceLine(Decimal(60), Decimal(1), "kg", "")],
        )
        db.insert_version_item(
            conn,
            vid,
            "வாழை",
            "banana",
            "red",
            None,
            None,
            None,
            False,
            Proof(quote="q", turn_ids=[], start_ms=0, end_ms=0),
            [PriceLine(Decimal(100), Decimal(1), "kg", "")],
        )
        conn.commit()
        return settings, slug, token
    finally:
        conn.close()


def test_56_04_cart_varieties_match_exactly(tmp_path):
    from app.web.main import create_app

    settings, slug, _token = _publish_two_bananas(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    # Shop cards must carry the variety for the cart key.
    html = client.get(f"/s/{slug}").text
    assert "data-variety" in html
    assert "poovan" in html and "red" in html
    # Two varieties in one cart stay two lines with the right prices.
    resp = client.post(
        f"/s/{slug}/quote",
        json={
            "customer_name": "Test",
            "lines": [
                {"name_en": "banana", "variety": "poovan", "qty": 2, "unit": "kg"},
                {"name_en": "banana", "variety": "red", "qty": 1, "unit": "kg"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_token(conn, token)
        lines = json.loads(row["lines_json"])
        assert len(lines) == 2
        assert lines[0]["variety"] == "poovan"
        assert lines[1]["variety"] == "red"
        assert Decimal(str(lines[0]["line_total"])) == Decimal("120.00")
        assert Decimal(str(lines[1]["line_total"])) == Decimal("100.00")
    finally:
        conn.close()
    # Unknown variety is not_on_list, never a different variety.
    resp2 = client.post(
        f"/s/{slug}/quote",
        json={"customer_name": "Test",
              "lines": [{"name_en": "banana", "variety": "nosuch", "qty": 1, "unit": "kg"}]},
    )
    assert resp2.status_code == 200, resp2.text
    conn = db.connect(tmp_path / "data")
    try:
        row2 = db.get_quote_by_token(conn, resp2.json()["token"])
        only = json.loads(row2["lines_json"])[0]
        assert only["status"] == "not_on_list"
        assert only.get("unit_price") in (None, "")
    finally:
        conn.close()


def _publish_tamil_shop(tmp_path):
    from app.config import load_settings

    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn,
            name="Tamil Shop",
            phone="+914400000002",
            area="Koyambedu",
            language="ta",
            currency="INR",
            shop_type="vegetable",
        )
        cur = conn.execute(
            "INSERT INTO versions (shop_id, created_at, published) VALUES (?, ?, 1)",
            (shop_id, "2026-01-01T00:00:00+00:00"),
        )
        vid = cur.lastrowid
        for local, en, variety, price in [
            ("வாழை", "banana", "poovan", 60),
            ("பீன்ஸ்", "beans", None, 80),
            ("வாழை", "banana", "red", 100),
        ]:
            db.insert_version_item(
                conn,
                vid,
                local,
                en,
                variety,
                None,
                None,
                None,
                False,
                Proof(quote="q", turn_ids=[], start_ms=0, end_ms=0),
                [PriceLine(Decimal(price), Decimal(1), "kg", "")],
            )
        conn.commit()
        return settings, slug, token
    finally:
        conn.close()


def test_56_05_typed_bill_uses_local_first(tmp_path, monkeypatch):
    """Typed Tamil bill parses locally; Spark never called when nothing left."""
    from app.web.main import create_app

    settings, _slug, token = _publish_tamil_shop(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    text = "பூவன் பழம் ரெண்டு கிலோ, பீன்ஸ் அரை கிலோ, செவ்வாழை ஒரு கிலோ"

    def _boom(*args, **kwargs):
        raise AssertionError("Spark must not be called when local parses all")

    monkeypatch.setattr("app.web.bills.wanted_from_text", _boom)
    monkeypatch.setattr("app.market.quote.wanted_from_text", _boom)
    resp = client.post(f"/e/{token}/bills/new", data={"items": text})
    assert resp.status_code in (302, 303), resp.text
    bill_id = resp.headers["location"].rstrip("/").split("/")[-1]
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?", (bill_id,)).fetchone()
        lines = json.loads(row["lines_json"])
        assert len(lines) == 3
        assert [(ln["name_en"], ln["variety"], ln["status"]) for ln in lines] == [
            ("banana", "poovan", "priced"),
            ("beans", None, "priced"),
            ("banana", "red", "priced"),
        ]
        assert Decimal(str(lines[0]["qty"])) == Decimal(2)
        assert Decimal(str(lines[1]["qty"])) == Decimal("0.5")
    finally:
        conn.close()


def test_56_05_typed_quote_resolves_spark_alias(tmp_path, monkeypatch):
    """Spark-returned variety aliases resolve before matching."""
    from app.market.quote import WantedLine
    from app.web.main import create_app

    settings, slug, _token = _publish_tamil_shop(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    # Local finds nothing; Spark says the alias "sevvazhai".
    def _fake_spark(text, *, ledger, settings):
        return [WantedLine(name_en="sevvazhai", qty=Decimal(1), unit="kg", source="text")]

    monkeypatch.setattr("app.web.quotes.wanted_from_text", _fake_spark)
    monkeypatch.setattr("app.market.quote.wanted_from_text", _fake_spark)
    resp = client.post(f"/s/{slug}/quote", data={"items": "qqqzzz 1 kg",
                                                         "customer_name": "Test"})
    assert resp.status_code in (302, 303), resp.text
    quote_token = resp.headers["location"].split("/q/")[1].split("?")[0]
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_token(conn, quote_token)
        lines = json.loads(row["lines_json"])
        assert lines[0]["status"] == "priced"
        assert lines[0]["name_en"] == "banana"
        assert lines[0]["variety"] == "red"
    finally:
        conn.close()


def test_56_06_name_fallback_and_aliases():
    from app.models import Transcript
    from app.pipeline.extract import parse_extract_json
    from app.pipeline.names import resolve_name

    empty = Transcript(text="", duration_ms=0, turns=[])
    # Spark says "other" but the spoken word is a known variety.
    items = parse_extract_json(
        {"items": [{
            "name_spoken": "ujala",
            "name_en": "other",
            "name_local": "",
            "variety": None,
            "prices": [{"said": "40", "price": 40, "per_amount": 1, "unit": "kg"}],
            "quote": "ujala 40",
            "turn_ids": [],
        }]},
        empty,
        language="ta",
    )
    assert items[0].name_en == "brinjal"
    assert items[0].variety == "ujala"
    # Alias buried in the quote.
    items = parse_extract_json(
        {"items": [{
            "name_spoken": "",
            "name_en": "other",
            "name_local": "",
            "variety": None,
            "prices": [{"said": "50", "price": 50, "per_amount": 1, "unit": "kg"}],
            "quote": "வரி krishnagiri வரி 50",
            "turn_ids": [],
        }]},
        empty,
        language="ta",
    )
    assert items[0].name_en == "brinjal"
    assert items[0].variety == "krishnagiri"
    # New aliases.
    assert resolve_name("chevvazhai") == ("banana", "red")
    assert resolve_name("chevvalai") == ("banana", "red")
    assert resolve_name("pachai") == ("banana", "green")
    assert resolve_name("pacha") == ("banana", "green")
    assert resolve_name("பச்சை") == ("banana", "green")
    assert resolve_name("elaki mathi") == ("banana", "yelakki")
    assert resolve_name("then vaazhai") == ("banana", "thenvazhai")
    assert resolve_name("thenvazhai") == ("banana", "thenvazhai")
    # Two banana varieties at one price stay one line.
    items = parse_extract_json(
        {"items": [{
            "name_spoken": "karpooravalli then vaazhai",
            "name_en": "banana",
            "name_local": "வாழை",
            "variety": None,
            "prices": [{"said": "60", "price": 60, "per_amount": 1, "unit": "kg"}],
            "quote": "karpooravalli then vaazhai 60",
            "turn_ids": [],
        }]},
        empty,
        language="ta",
    )
    assert items[0].name_en == "banana"
    assert items[0].variety == "karpooravalli / thenvazhai"


def test_56_08_new_shop_defaults(tmp_path):
    from app.config import load_settings
    from app.web.main import create_app

    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    # Tamil visitor gets Tamil default; Indian languages first; INR first.
    client.cookies.set("ui_lang", "ta")
    html = client.get("/new").text
    assert 'value="ta" selected' in html or 'value="ta"selected' in html or '<option value="ta" selected' in html
    ta_pos = html.find('value="ta"')
    hi_pos = html.find('value="hi"')
    bn_pos = html.find('value="bn"')
    ar_pos = html.find('value="ar"')
    assert 0 <= ta_pos < hi_pos < bn_pos < ar_pos, "Indian languages first, Arabic later"
    inr_pos = html.find('value="INR"')
    aed_pos = html.find('value="AED"')
    assert 0 <= inr_pos < aed_pos, "INR first in currency list"
    assert "per None" not in html
    # No cookie → English default.
    client2 = TestClient(app, follow_redirects=False)
    html2 = client2.get("/new").text
    assert '<option value="en" selected' in html2
    # Server-side currency default when omitted.
    resp = client2.post(
        "/new",
        data={
            "name": "Def Shop",
            "phone": "+914400000003",
            "area": "Koyambedu",
            "language": "ta",
            "currency": "",
            "type": "vegetable",
        },
    )
    assert resp.status_code in (302, 303), resp.text


def test_56_09_approve_publishes_and_shows_live(tmp_path, monkeypatch):
    """Web approve publishes immediately and lands on a live success screen."""
    client = _make_client(tmp_path, monkeypatch, seed=_clean_item())
    location = _create_shop(client)
    session_url = _upload_session(client, location)
    token = location.split("/e/")[1]
    session_id = session_url.rstrip("/").split("/")[-1]
    edited = json.loads(db._draft_to_json(_clean_item()))
    # Quote needs words between numbers (see item 2).
    edited["proof"]["quote"] = "tomato 20 rupees 5 kg"
    response = client.post(session_url + "/approve", json={"items": [edited], "confirmed": []})
    assert response.status_code in (302, 303), response.text
    assert "/live" in response.headers["location"]
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        published = db.latest_version(conn, shop_id, published_only=True)
        assert published is not None, "approve must publish"
    finally:
        conn.close()
    html = client.get(f"/e/{token}/s/{session_id}/live").text
    assert "Your prices are live" in html
    assert "Send today" in html or "WhatsApp" in html
    assert "qr.png" in html or "qr" in html.lower()
    assert "board.pdf" in html
    assert "tags.pdf" in html


def test_56_10_accept_keeps_order_flow(tmp_path):
    from app.web.main import create_app

    settings, slug, seller_token = _publish_two_bananas(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    # Customer order: Red banana 1 kg.
    resp = client.post(
        f"/s/{slug}/quote",
        json={"customer_name": "Test",
              "lines": [{"name_en": "banana", "variety": "red", "qty": 1, "unit": "kg"}]},
    )
    assert resp.status_code == 200, resp.text
    quote_token = resp.json()["token"]
    conn = db.connect(tmp_path / "data")
    try:
        row = db.get_quote_by_token(conn, quote_token)
        bill_id = row["id"]
    finally:
        conn.close()
    from app.web.bills import _customer_label

    # Accept through HTTP: still Order #N with order + payment side by side.
    accept = client.post(f"/e/{seller_token}/bills/{bill_id}/accept")
    assert accept.status_code in (302, 303), accept.text
    seller_html = client.get(f"/e/{seller_token}/bills/{bill_id}").text
    assert "Order #" in seller_html
    assert "Walk-in" not in seller_html
    assert "order-status" in seller_html
    assert "/paid" in seller_html
    conn = db.connect(tmp_path / "data")
    try:
        row2 = db.get_quote_by_id(conn, bill_id)
        assert "Order" in _customer_label(row2, "en"), _customer_label(row2, "en")
        assert row2["status"] in ("packing", "billed")
        # Order flow still advances after accept.
        if row2["status"] == "billed":
            db.set_order_status(conn, bill_id, "packing")
            row2 = db.get_quote_by_id(conn, bill_id)
        assert row2["status"] == "packing"
        db.set_order_status(conn, bill_id, "ready")
        # Customer page keeps updating through the flow.
        customer_html = client.get(f"/q/{quote_token}").text
        assert "Ready for pickup" in customer_html or "ready" in customer_html.lower()
        db.set_order_status(conn, bill_id, "collected")
    finally:
        conn.close()
    # Button rename + rupee headline live in template/i18n.
    from app.web.i18n import t_for

    assert t_for("en")("bill.accept_order") == "Accept order"
    assert t_for("ta")("bill.accept_order")
    assert t_for("hi")("bill.accept_order")
    from pathlib import Path as _Path

    bill_html = _Path("app/web/templates/bill.html").read_text()
    assert "bill.accept_order" in bill_html
    assert "money(shop" in bill_html.split("is_quote")[0][-2000:] or "money" in bill_html


def test_56_11_view_opens_summary_before_send(tmp_path):
    """Float View opens a review sheet; only the Send pill posts the order."""
    from app.web.main import create_app

    settings, slug, _token = _publish_two_bananas(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    html = client.get(f"/s/{slug}").text
    # Bottom sheet with lines, total and a Send pill.
    assert "data-cart-sheet" in html
    assert "data-cart-sheet-lines" in html
    assert "data-cart-sheet-total" in html
    # Float View button is marked as view-only (still carries data-cart-submit
    # for backwards compat, but JS must open instead of sending).
    assert "data-cart-view" in html
    assert html.count("data-cart-submit") >= 2
    # Sheet + scroll logic present in the page script.
    assert "scrollIntoView" in html
    assert "data-cart-sheet-close" in html or "sheet-backdrop" in html


def test_56_02_approve_keeps_photo_and_proof(tmp_path, monkeypatch):
    """Approve must keep photo/proof from the stored draft, not client nulls."""
    client = _make_client(tmp_path, monkeypatch, seed=_clean_item())
    location = _create_shop(client)
    session_url = _upload_session(client, location)
    # collectCards shape: photo null, empty proof, names from h2.
    edited = {
        "name_spoken": "tomato",
        "name_local": "தக்காளி",
        "name_en": "tomato",
        "variety": None,
        "price_lines": [{"said": "", "price": 20, "per_amount": 1, "unit": "kg"}],
        "range_said": False,
        "qty": 5,
        "qty_unit": None,
        "proof": {
            "quote": "",
            "turn_ids": [],
            "start_ms": 0,
            "end_ms": 0,
            "frame": None,
            "audio_clip": None,
            "source": None,
        },
        "flags": [],
        "photo": None,
        "condition_hint": None,
        "confirmed": False,
    }
    # Also try to smuggle a client photo path: must be ignored.
    edited["photo"] = "/etc/passwd"
    edited["proof"]["audio_clip"] = "/etc/passwd"
    response = client.post(session_url + "/approve", json={"items": [edited], "confirmed": []})
    assert response.status_code in (302, 303), response.text
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        version_id = db.latest_version(conn, shop_id)
        items = db.version_items(conn, version_id)
        assert items[0].photo == "photos/tomato.jpg"
        assert items[0].proof.quote == "tomato 20 rupees 5 kg"
        assert items[0].proof.audio_clip == "/tmp/clip.mp4"
        assert items[0].proof.frame == "frame1.jpg"
    finally:
        conn.close()
