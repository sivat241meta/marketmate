import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof
from app.web.main import create_app


def clean_item():
    return DraftItem(
        name_spoken="ginger",
        name_ta="இஞ்சி",
        name_en="ginger",
        variety=None,
        price_lines=[PriceLine(Decimal(180), Decimal(1), "kg", "")],
        qty=Decimal(5),
        qty_unit="kg",
        proof=Proof(
            quote="ginger 180 5",
            turn_ids=[1],
            start_ms=0,
            end_ms=1000,
        ),
        flags=[],
    )


def make_client(tmp_path, monkeypatch, seed=None):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, [seed or clean_item()])
        db.set_session_status(conn, session_id, "review", "1 item needs review")

    monkeypatch.setattr("app.web.seller.jobs.submit", fake_submit)
    monkeypatch.setattr("app.web.seller.process_video_session", fake_process)
    return TestClient(app, follow_redirects=False)


def create_shop(client):
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


def upload_session(client, location):
    return client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]


def test_review_has_confirm_for_every_card(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    session_url = upload_session(client, location)
    html = client.get(session_url).text
    assert html.count('data-card="0"') == 1
    assert html.count("data-card-confirm") == 1
    assert "data-edit-note" in html
    assert "hidden" in html
    assert "You changed this from what was heard. Play the clip, then tick I confirm." in html
    assert "data-original" in html


def test_approve_edited_unheard_needs_confirm(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    session_url = upload_session(client, location)
    edited = json.loads(db._draft_to_json(clean_item()))
    edited["price_lines"][0]["price"] = "150"
    response = client.post(
        session_url + "/approve", json={"items": [edited], "confirmed": []}
    )
    assert response.status_code == 400
    body = response.json()
    assert "needs_confirm" in body
    assert body["needs_confirm"][0]["index"] == 0
    assert body["needs_confirm"][0]["name"] == "ginger"
    assert body["needs_confirm"][0]["messages"]
    assert "blocking" not in body["detail"].lower()
    assert "Please check ginger:" in body["detail"]
    assert "tick I confirm" in body["detail"]


def test_approve_edited_unheard_confirmed_saves(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    session_url = upload_session(client, location)
    edited = json.loads(db._draft_to_json(clean_item()))
    edited["price_lines"][0]["price"] = "150"
    response = client.post(
        session_url + "/approve", json={"items": [edited], "confirmed": [0]}
    )
    assert response.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        assert db.latest_version(conn, shop_id) is not None
    finally:
        conn.close()
