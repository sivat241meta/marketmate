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
        name_local="தக்காளி",
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


def potato_item():
    return DraftItem(
        name_spoken="urulaikizhangu",
        name_local="உருளைக்கிழங்கு",
        name_en="potato",
        variety=None,
        price_lines=[
            PriceLine(Decimal(30), Decimal(1), "kg", "kilo thirty"),
            PriceLine(Decimal(35), Decimal(1), "kg", "thirty five"),
        ],
        qty=None,
        qty_unit=None,
        proof=Proof(
            quote="urulaikizhangu kilo thirty rupees இல்ல இல்ல thirty five rupees",
            turn_ids=[1],
            start_ms=0,
            end_ms=1000,
        ),
        flags=[
            Flag(
                field="price",
                code="TWO_PRICES",
                message="two prices heard: 30 or 35?",
                options=["30", "35"],
            ),
            Flag(field="price", code="CORRECTION_SAID",
                 message="seller corrected themselves"),
        ],
    )


def make_client(tmp_path, monkeypatch, seed=None):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, [seed or canned_item()])
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
    assert client.post("/new", data={**base, "language": "xx"}).status_code == 422
    assert client.post("/new", data={**base, "currency": "XX"}).status_code == 422
    assert client.post("/new", data={**base, "language": "fr",
                                     "currency": "EUR"}).status_code in (302, 303)


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
    assert "₹18" in html and "₹80" in html
    assert 'data-value="18"' in html and 'data-value="80"' in html
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


def test_review_card_choice_controls(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, seed=potato_item())
    location = create_shop(client)
    session_url = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]
    html = client.get(session_url).text
    assert 'data-flag="TWO_PRICES"' in html
    assert "<select" in html
    for unit in ["kg", "g", "piece", "dozen", "bunch", "packet"]:
        assert f">{unit}</option>" in html
    assert "line-remove" in html
    assert "data-confirm=" not in html
    assert html.count("data-card-confirm") == 1


def test_approve_after_choosing_35_keeps_one_line(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, seed=potato_item())
    location = create_shop(client)
    session_url = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]
    chosen = json.loads(db._draft_to_json(potato_item()))
    chosen["price_lines"] = [chosen["price_lines"][1]]
    assert Decimal(chosen["price_lines"][0]["price"]) == 35
    response = client.post(
        session_url + "/approve", json={"items": [chosen], "confirmed": [0]})
    assert response.status_code in (302, 303)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        version_id = db.latest_version(conn, shop_id)
        assert version_id is not None
        stored = db.version_items(conn, version_id)
        assert len(stored) == 1
        lines = stored[0].price_lines
        assert len(lines) == 1
        assert (lines[0].price, lines[0].per_amount, lines[0].unit) == (
            Decimal(35), Decimal(1), "kg")
    finally:
        conn.close()


def test_approved_session_status(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    session_url = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]
    response = client.post(
        session_url + "/approve", json={"items": [canned_dict()], "confirmed": [0]})
    assert response.status_code in (302, 303)
    session_id = int(session_url.rsplit("/s/", 1)[1])
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute(
            "SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row["status"] == "approved"
    finally:
        conn.close()
    assert "Approved" in client.get(session_url).text
