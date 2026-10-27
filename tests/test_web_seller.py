import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof
from app.web.main import create_app

NOTICE = "Your voice recording is sent to Meta's AI service to be transcribed."


def canned_item():
    return DraftItem(
        name_spoken="tomato",
        name_ta="தக்காளி",
        name_en="tomato",
        variety=None,
        price_lines=[PriceLine(Decimal(18), Decimal(1), "kg", "kilo eighteen")],
        qty=None,
        qty_unit=None,
        proof=Proof(quote="tomato eighteen rupees", turn_ids=[1], start_ms=0, end_ms=1000),
        flags=[
            Flag(
                field="price",
                code="SOUND_ALIKE",
                message="did you say 18 or 80?",
                options=["18", "80"],
            ),
            Flag(field="qty", code="QTY_MISSING", message="no quantity", blocking=False),
        ],
    )


def canned_dict():
    return json.loads(db._draft_to_json(canned_item()))


def make_client(tmp_path, monkeypatch):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, [canned_item()])
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


def test_create_shop_validation(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    base = {
        "name": "S",
        "phone": "+914400000000",
        "area": "A",
        "language": "ta",
        "currency": "INR",
        "type": "vegetable",
    }
    assert client.post("/new", data={}).status_code == 422
    assert client.post("/new", data={**base, "phone": "abc"}).status_code == 422
    assert client.post("/new", data={**base, "language": "fr"}).status_code == 422


def test_create_shop_redirect_contains_token(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    assert location.startswith("/e/")
    assert len(location) > 4


def test_wrong_token_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.get("/e/badtoken").status_code == 404


def test_upload_flow_statuses(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    response = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    )
    assert response.status_code in (302, 303)
    session_url = response.headers["location"]
    assert "/s/" in session_url
    assert client.get(session_url).status_code == 200


def test_review_html_shows_quote_options_and_names(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    session_url = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]
    html = client.get(session_url).text
    assert "tomato eighteen rupees" in html
    assert ">18<" in html and ">80<" in html
    assert "opt-btn" in html
    assert "தக்காளி" in html and "tomato" in html
    assert "flag-note" in html
    assert "viewport" in html


def test_upload_page_has_meta_notice(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert NOTICE in client.get(create_shop(client)).text


def test_approve_blocked_then_resolved(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    session_url = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]
    approve_url = session_url + "/approve"
    blocked = client.post(approve_url, json={"items": [canned_dict()], "confirmed": []})
    assert blocked.status_code == 400
    resolved = client.post(approve_url, json={"items": [canned_dict()], "confirmed": [0]})
    assert resolved.status_code in (302, 303)
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        shops = conn.execute("SELECT id FROM shops").fetchall()
        assert len(shops) == 1
        assert db.latest_version(conn, shops[0]["id"]) is not None
    finally:
        conn.close()
