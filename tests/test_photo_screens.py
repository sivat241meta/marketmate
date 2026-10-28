"""Task 26: seller photo screens - scan stock, boxes overlay, counts, suggestions."""

import io
import json
from decimal import Decimal

from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import load_settings
from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostLedger
from app.limits import RATE_LIMIT_MESSAGE
from app.models import Box, DraftItem, Item, PriceLine, Proof
from app.outputs.value import stock_value
from app.pipeline.vision import DetectedProduct, PhotoReport, Suggestion
from app.web.main import create_app


def jpeg_bytes(size=(64, 48), color="red"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def make_client(tmp_path, monkeypatch, *, analyse=None, extra_env=None):
    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    if extra_env:
        env.update(extra_env)
    app = create_app(load_settings(env))
    monkeypatch.setattr("app.web.photos.jobs.submit", lambda fn, *a: fn(*a))
    if analyse is not None:
        monkeypatch.setattr("app.web.photos.analyse_photo", analyse)
    client = TestClient(app, follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client):
    response = client.post("/new", data={
        "name": "Kannan Store", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"]


def token_of(location):
    return location.split("/e/")[1]


def canned_report():
    return PhotoReport(
        products=[DetectedProduct(
            name_en="tomato", name_local="தக்காளி", countable=True,
            count_spark=24, count_sam=24, count=24,
            boxes=[Box(1, 2, 10, 20, 64, 48, None),
                   Box(12, 4, 22, 26, 64, 48, None)],
            condition="looks fresh")],
        quality="good",
        suggestions=[Suggestion(
            kind="set_stock", item_name="tomato", action="set_stock", value=24,
            text="About 24 tomato visible. Save as today's stock?")],
        cost_usd=0.0125)


def fake_analyse(report=None):
    canned = report or canned_report()

    def run(image, *, shop_items, ledger, settings):
        return canned

    return run


def make_draft(name_en="tomato", name_local="தக்காளி", price=5, unit="piece"):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), unit, "")],
        qty=None, qty_unit=None,
        proof=Proof(quote=name_en, turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def seed_version(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        return db.approve(conn, session_id, list(drafts))
    finally:
        conn.close()


def report_payload():
    return {
        "quality": "good", "image_w": 64, "image_h": 48,
        "products": [
            {"name_en": "tomato", "name_local": "தக்காளி", "countable": True,
             "count": 24, "count_range": None, "needs_check": False,
             "count_spark": 24, "count_sam": 24,
             "boxes": [{"x1": 1, "y1": 2, "x2": 10, "y2": 20, "w": 64,
                        "h": 48, "confidence": None},
                       {"x1": 12, "y1": 4, "x2": 22, "y2": 26, "w": 64,
                        "h": 48, "confidence": None}],
             "condition": "looks fresh"},
            {"name_en": "coriander", "name_local": "கொத்தமல்லி",
             "countable": False, "count": None, "count_range": None,
             "needs_check": False, "count_spark": None, "count_sam": None,
             "boxes": [], "condition": None},
        ],
        "suggestions": [
            {"kind": "set_stock", "text": "About 24 tomato visible.",
             "item_name": "tomato", "action": "set_stock", "value": 24},
            {"kind": "back_on_sale", "text": "Tomato is back.",
             "item_name": "tomato", "action": "unsold", "value": None},
            {"kind": "add_price", "text": "Coriander is not on your list.",
             "item_name": "coriander", "action": "voice_update",
             "value": None},
            {"kind": "retake", "text": "Photo looks dark.",
             "item_name": None, "action": None, "value": None},
        ],
    }


def seed_check(tmp_path, token, report=None):
    data_dir = tmp_path / "data"
    photos = data_dir / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    image = photos / "seed.jpg"
    image.write_bytes(jpeg_bytes())
    conn = db.connect(data_dir)
    try:
        shop = db.shop_by_token(conn, token)
        return db.save_photo_check(
            conn, shop_id=shop["id"], image_path=str(image),
            report_json=json.dumps(report or report_payload()), cost=0.0125)
    finally:
        conn.close()


# --- upload ---

def test_upload_creates_photo_session_and_check(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    response = client.post(
        location + "/photos",
        files={"photo": ("stall.jpg", jpeg_bytes(), "image/jpeg")})
    assert response.status_code in (302, 303)
    session_url = response.headers["location"]
    assert "/s/" in session_url
    session_id = int(session_url.rsplit("/s/", 1)[1])
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row["kind"] == "photo"
        assert row["status"] == "review"
        assert row["stage"] == "ready"
        shop = db.shop_by_token(conn, token_of(location))
        checks = db.load_photo_checks(conn, shop["id"])
        assert len(checks) == 1
        saved = json.loads(checks[0]["report_json"])
        assert saved["products"][0]["name_en"] == "tomato"
        assert saved["products"][0]["count"] == 24
    finally:
        conn.close()


def test_photo_session_uses_photo_stages(tmp_path):
    conn = db.connect(tmp_path / "db")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000000", area="A", language="ta",
            currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "photo")
        assert db.stages_for_kind("photo") == [
            "uploaded", "looking", "counting", "suggesting", "ready"]
        db.set_stage(conn, session_id, "looking")
        db.set_stage(conn, session_id, "ready")
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        progress = db.session_progress(row)
        assert [step["key"] for step in progress["steps"]] == [
            "uploaded", "looking", "counting", "suggesting", "ready"]
        assert progress["steps"][0]["label"] == "Photo received"
        assert progress["steps"][1]["label"] == "Looking at your photo"
    finally:
        conn.close()


def test_session_page_forwards_to_result_when_ready(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    session_url = client.post(
        location + "/photos",
        files={"photo": ("stall.jpg", jpeg_bytes(), "image/jpeg")},
    ).headers["location"]
    forwarded = client.get(session_url)
    assert forwarded.status_code in (302, 303)
    assert "/photos/" in forwarded.headers["location"]
    assert client.get(forwarded.headers["location"]).status_code == 200


# --- list page ---

def test_photos_list_shows_scan_card_and_checks(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    check_id = seed_check(tmp_path, token_of(location))
    html = client.get(location + "/photos").text
    assert "Scan a stock photo" in html
    assert 'accept="image/*"' in html
    assert 'capture="environment"' in html
    assert f"/photos/{check_id}" in html
    assert "Tomato" in html
    assert "/m/" in html
    assert "style=" not in html


# --- result page ---

def test_result_page_renders_products_boxes_and_suggestions(tmp_path,
                                                            monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    check_id = seed_check(tmp_path, token_of(location))
    html = client.get(f"{location}/photos/{check_id}").text
    assert "தக்காளி" in html and "tomato" in html
    assert "About 24 visible" in html
    assert "Sold by weight - no count" in html
    assert "<svg" in html and "<rect" in html
    assert "Show boxes" in html
    assert "Save stock" in html
    assert "Put back on sale" in html
    assert "Say its price" in html
    assert "Retake photo" in html
    assert "Seller only" in html
    assert "looks fresh" in html
    assert ("Counts are estimates from the photo."
            " Prices only come from what you say.") in html
    assert "photo.js" in html
    assert "style=" not in html


def test_result_page_needs_check_renders_range(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    report = report_payload()
    report["products"][0].update(
        {"count": None, "count_range": [24, 32], "needs_check": True})
    check_id = seed_check(tmp_path, token_of(location), report)
    html = client.get(f"{location}/photos/{check_id}").text
    assert "Between 24 and 32 - please check" in html
    assert "pill-check" in html


def test_result_page_404_for_other_shop(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    first = create_shop(client)
    check_id = seed_check(tmp_path, token_of(first))
    second = create_shop(client)
    assert client.get(f"{second}/photos/{check_id}").status_code == 404


# --- apply ---

def test_apply_set_stock_updates_item_and_dashboard(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    seed_version(tmp_path, token_of(location), [make_draft()])
    check_id = seed_check(tmp_path, token_of(location))
    response = client.post(
        f"{location}/photos/{check_id}/apply",
        data={"action": "set_stock", "item": "tomato", "qty": "26"})
    assert response.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute(
            "SELECT stock_qty, stock_unit, stock_source FROM items").fetchone()
        assert (row["stock_qty"], row["stock_unit"],
                row["stock_source"]) == ("26", "piece", "photo")
    finally:
        conn.close()
    assert "Stock: about 26 (photo)" in client.get(location).text


def test_apply_unsold_clears_sold_out(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    seed_version(tmp_path, token_of(location), [make_draft()])
    conn = db.connect(tmp_path / "data")
    try:
        item_id = conn.execute("SELECT id FROM items").fetchone()["id"]
        db.set_sold_out(conn, item_id, True)
    finally:
        conn.close()
    check_id = seed_check(tmp_path, token_of(location))
    response = client.post(
        f"{location}/photos/{check_id}/apply",
        data={"action": "unsold", "item": "tomato"})
    assert response.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute(
            "SELECT sold_out FROM items WHERE id = ?", (item_id,)).fetchone()
        assert row["sold_out"] == 0
    finally:
        conn.close()


def test_apply_voice_update_redirects_with_hint(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    seed_version(tmp_path, token_of(location), [make_draft()])
    check_id = seed_check(tmp_path, token_of(location))
    response = client.post(
        f"{location}/photos/{check_id}/apply",
        data={"action": "voice_update", "item": "banana"})
    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"{location}/update?hint=banana"
    assert "banana" in client.get(response.headers["location"]).text


# --- upload failures ---

def test_oversize_upload_gives_friendly_400(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    big = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        location + "/photos",
        files={"photo": ("big.jpg", big, "image/jpeg")})
    assert response.status_code == 400
    assert "too big" in response.text.lower()


def test_non_image_upload_gives_friendly_400(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    response = client.post(
        location + "/photos",
        files={"photo": ("note.txt", b"not an image", "text/plain")})
    assert response.status_code == 400
    assert "photo" in response.text.lower()


def test_photo_upload_rate_limited(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse(),
                         extra_env={"UPLOADS_PER_IP_HOUR": "1"})
    location = create_shop(client)
    first = client.post(
        location + "/photos",
        files={"photo": ("a.jpg", jpeg_bytes(), "image/jpeg")})
    assert first.status_code in (302, 303)
    second = client.post(
        location + "/photos",
        files={"photo": ("b.jpg", jpeg_bytes(), "image/jpeg")})
    assert second.status_code == 429
    assert RATE_LIMIT_MESSAGE in second.text


def test_photo_upload_blocked_by_cost_cap(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    CostLedger(tmp_path / "data" / "costs.db", 3.0).add(
        "meta", "muse-spark-1.3", 5.0)
    response = client.post(
        location + "/photos",
        files={"photo": ("a.jpg", jpeg_bytes(), "image/jpeg")})
    assert response.status_code == 503
    assert BUDGET_EXHAUSTED_MESSAGE in response.text


# --- dashboard and shop page ---

def test_dashboard_links_photos_and_scan_tile(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    html = client.get(location).text
    assert f'href="{location}/photos"' in html
    assert "Scan stock photo" in html


def test_condition_never_on_public_shop_page(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, analyse=fake_analyse())
    location = create_shop(client)
    version_id = seed_version(tmp_path, token_of(location), [make_draft()])
    conn = db.connect(tmp_path / "data")
    try:
        db.set_published(conn, version_id, True)
        slug = db.shop_by_token(conn, token_of(location))["slug"]
    finally:
        conn.close()
    seed_check(tmp_path, token_of(location))
    html = client.get(f"/s/{slug}").text
    assert "looks fresh" not in html
    assert "Seller only" not in html


# --- stock value ---

def pl(price, per_amount, unit):
    return PriceLine(Decimal(price), Decimal(per_amount), unit, "")


def stock_item(**kwargs):
    values = {"id": 1, "version_id": 1, "name_local": "தக்காளி",
              "name_en": "tomato", "variety": None, "qty": None,
              "qty_unit": None, "photo": None, "sold_out": False,
              "price_lines": [pl(5, 1, "piece")],
              "proof": Proof(quote="", turn_ids=[], start_ms=0, end_ms=0),
              "stock_qty": None, "stock_unit": None, "stock_source": None}
    values.update(kwargs)
    return Item(**values)


def test_stock_value_uses_photo_stock():
    goods = [stock_item(stock_qty=Decimal(24), stock_unit="piece",
                        stock_source="photo")]
    total, left_out = stock_value(goods)
    assert total == 120
    assert left_out == []


def test_stock_value_falls_back_when_unit_matches_no_line():
    goods = [stock_item(qty=Decimal(2), qty_unit="kg",
                        price_lines=[pl(10, 1, "kg")],
                        stock_qty=Decimal(24), stock_unit="piece",
                        stock_source="photo")]
    total, left_out = stock_value(goods)
    assert total == 20
    assert left_out == []
