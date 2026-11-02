from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.web.main import create_app

QUOTE = "secret quote tomato eighteen rupees"
CLIP = "/tmp/clips/item_0.m4a"


def draft():
    return DraftItem(
        name_spoken="tomato",
        name_local="தக்காளி",
        name_en="tomato",
        variety=None,
        price_lines=[PriceLine(Decimal(18), Decimal(1), "kg", "kilo eighteen")],
        qty=None,
        qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[1], start_ms=0, end_ms=1000,
                    audio_clip=CLIP),
        confirmed=True,
        condition_hint="ripe",
        photo="data/photos/s1_0.jpg",
    )


def seed(tmp_path, monkeypatch, name="Kannan Store", is_demo=False):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name=name, phone="+914400000000", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable",
            is_demo=is_demo)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [draft()])
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    client = TestClient(app, follow_redirects=False)
    return client, token, slug, version_id, item_id


def test_unpublished_shop_has_no_prices(tmp_path, monkeypatch):
    client, _, slug, _, _ = seed(tmp_path, monkeypatch)
    html = client.get(f"/s/{slug}").text
    assert "No prices published yet" in html


def test_publish_shows_price_without_proof(tmp_path, monkeypatch):
    client, token, slug, version_id, _ = seed(tmp_path, monkeypatch)
    response = client.post(f"/e/{token}/v/{version_id}/publish")
    assert response.status_code in (302, 303)
    html = client.get(f"/s/{slug}").text
    assert "₹18" in html
    # Task 164: the seller's own photo comes first on the shop
    # page; the v13 cut-out is only the fallback with no own photo.
    assert "/m/s1_0.jpg" in html
    assert "/static/img/v13/tomato.webp" not in html
    assert "✓ Voice-checked prices" in html
    assert "kilo eighteen" in html
    assert QUOTE not in html
    assert "/clip/" not in html
    assert "ripe" not in html
    assert "tel:+914400000000" in html
    assert "https://wa.me/914400000000" in html


def test_unpublish_hides_prices(tmp_path, monkeypatch):
    client, token, slug, version_id, _ = seed(tmp_path, monkeypatch)
    client.post(f"/e/{token}/v/{version_id}/publish")
    assert "₹18" in client.get(f"/s/{slug}").text
    client.post(f"/e/{token}/v/{version_id}/unpublish")
    assert "No prices published yet" in client.get(f"/s/{slug}").text


def test_sold_out_label(tmp_path, monkeypatch):
    client, token, slug, version_id, item_id = seed(tmp_path, monkeypatch)
    client.post(f"/e/{token}/v/{version_id}/publish")
    client.post(f"/e/{token}/item/{item_id}/soldout")
    html = client.get(f"/s/{slug}").text
    assert "Sold out" in html
    client.post(f"/e/{token}/item/{item_id}/soldout")
    assert "Sold out" not in client.get(f"/s/{slug}").text


def test_demo_badge_and_tamil(tmp_path, monkeypatch):
    client, token, slug, version_id, _ = seed(
        tmp_path, monkeypatch, name="Demo Stall", is_demo=True)
    client.post(f"/e/{token}/v/{version_id}/publish")
    html = client.get(f"/s/{slug}").text
    from app.web.i18n import t_for
    assert t_for("en")("hp.demo") in html
    assert "தக்காளி" in client.get(f"/s/{slug}?lang=ta").text
    assert "tomato" in client.get(f"/s/{slug}?lang=en").text


def test_relative_time_shown(tmp_path, monkeypatch):
    client, token, slug, version_id, _ = seed(tmp_path, monkeypatch)
    client.post(f"/e/{token}/v/{version_id}/publish")
    html = client.get(f"/s/{slug}").text
    # Task 127 polish: the green "(spoken and checked … ago)" box is
    # gone; the top strip keeps the said-today HH:MM line.
    assert "spoken and checked" not in html
    assert "Prices said by the seller today" in html
