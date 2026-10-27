import json
import re
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.models import DraftItem, PriceLine, Proof, Transcript, Turn
from app.pipeline.update import (
    apply_changes,
    build_update_messages,
    change_from_dict,
    change_to_dict,
    parse_update,
    parse_update_json,
)
from app.web.main import create_app

NOTICE = "Your voice recording is sent to Meta's AI service to be transcribed."

CANNED_UPDATE = {"changes": [
    {"name_en": "tomato", "action": "set_price",
     "prices": [{"said": "22", "price": 22, "per_amount": 1, "unit": "kg"}],
     "qty": None, "qty_unit": None, "turn_ids": [1],
     "quote": "thakkali 22 today"},
    {"name_en": "onion", "action": "sold_out",
     "prices": [], "qty": None, "qty_unit": None, "turn_ids": [2],
     "quote": "vengayam sold out"},
]}


def update_transcript():
    return Transcript(
        text="thakkali 22 today, vengayam sold out",
        duration_ms=6000,
        turns=[
            Turn(id=1, start_ms=0, end_ms=3000, text="thakkali 22 today"),
            Turn(id=2, start_ms=3000, end_ms=6000, text="vengayam sold out"),
        ],
    )


def seed_version(conn, shop_id, lines=(("tomato", 18), ("onion", 25), ("potato", 30))):
    from app.pipeline.names import CANONICAL_NAMES

    drafts = [
        DraftItem(
            name_spoken=name, name_ta=CANONICAL_NAMES[name], name_en=name,
            variety=None, price_lines=[PriceLine(Decimal(p), Decimal(1), "kg")],
            qty=None, qty_unit=None,
            proof=Proof(quote=f"{name} {p}", turn_ids=[1], start_ms=0, end_ms=1),
        )
        for name, p in lines
    ]
    session_id = db.create_session(conn, shop_id, "video")
    return db.approve(conn, session_id, drafts)


def seed_shop(conn, name="Kannan Store"):
    shop_id, slug, token = db.create_shop(
        conn, name=name, phone="+914400000000", area="Koyambedu",
        language="ta", currency="INR", shop_type="vegetable")
    return shop_id, slug, token


def test_parse_update_two_changes(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
    finally:
        conn.close()
    changes = parse_update_json(CANNED_UPDATE, update_transcript(), current)
    assert [(c.name_en, c.action) for c in changes] == [
        ("tomato", "set_price"), ("onion", "sold_out")]
    assert changes[0].price_lines[0].price == 22
    assert changes[0].proof.start_ms == 0
    assert changes[1].proof.start_ms == 3000
    assert not [f for f in changes[0].flags if f.blocking]
    assert changes[1].flags == []


def test_apply_changes_copies_untouched_and_new_price(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
        changes = parse_update_json(CANNED_UPDATE, update_transcript(), current)
        new_id = apply_changes(conn, shop_id, base, changes)
        assert new_id != base
        row = conn.execute("SELECT published FROM versions WHERE id = ?",
                           (new_id,)).fetchone()
        assert row["published"] == 0
        got = {i.name_en: i for i in db.version_items(conn, new_id)}
        assert got["tomato"].price_lines[0].price == 22
        assert got["potato"].price_lines[0].price == 30
        assert got["onion"].sold_out is True
        assert got["tomato"].sold_out is False
    finally:
        conn.close()


def test_unknown_item_gets_new_item(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
    finally:
        conn.close()
    data = {"changes": [{
        "name_en": "carrot", "action": "set_price",
        "prices": [{"said": "kilo thirty", "price": 30,
                    "per_amount": 1, "unit": "kg"}],
        "qty": None, "qty_unit": None, "turn_ids": [1],
        "quote": "carrot kilo thirty"}]}
    transcript = Transcript(text="carrot kilo thirty", duration_ms=3000,
                            turns=[Turn(id=1, start_ms=0, end_ms=3000,
                                        text="carrot kilo thirty")])
    (change,) = parse_update_json(data, transcript, current)
    flag = next(f for f in change.flags if f.code == "NEW_ITEM")
    assert flag.blocking is True


def test_jump_from_18_to_60_flagged(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
    finally:
        conn.close()
    data = {"changes": [{
        "name_en": "tomato", "action": "set_price",
        "prices": [{"said": "sixty", "price": 60, "per_amount": 1, "unit": "kg"}],
        "qty": None, "qty_unit": None, "turn_ids": [1],
        "quote": "thakkali sixty today"}]}
    transcript = Transcript(text="thakkali sixty today", duration_ms=3000,
                            turns=[Turn(id=1, start_ms=0, end_ms=3000,
                                        text="thakkali sixty today")])
    (change,) = parse_update_json(data, transcript, current)
    assert any(f.code == "JUMP" and f.blocking for f in change.flags)


def test_parse_update_uses_low_reasoning(monkeypatch, tmp_path):
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return CANNED_UPDATE

    monkeypatch.setattr("app.pipeline.update.chat_json", fake_chat_json)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
    finally:
        conn.close()
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    changes = parse_update(update_transcript(), current,
                           ledger=ledger, settings=settings)
    assert [c.name_en for c in changes] == ["tomato", "onion"]
    assert seen["kwargs"]["reasoning_effort"] == "low"
    assert "[1]" in seen["messages"][-1]["content"]


def test_prompt_lists_current_prices_and_turns(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
    finally:
        conn.close()
    content = build_update_messages(update_transcript(), current)[-1]["content"]
    assert "[1]" in content and "[2]" in content
    assert "tomato" in content and "18" in content


def test_change_json_round_trip(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        current = db.version_items(conn, base)
    finally:
        conn.close()
    (change,) = parse_update_json(
        {"changes": [CANNED_UPDATE["changes"][0]]}, update_transcript(), current)
    back = change_from_dict(json.loads(json.dumps(change_to_dict(change))))
    assert back.name_en == "tomato" and back.action == "set_price"
    assert back.price_lines[0].price == 22
    assert back.proof.quote == "thakkali 22 today"
    assert [f.code for f in back.flags] == [f.code for f in change.flags]


def test_apply_in_stock_and_set_qty(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_shop(conn)
        base = seed_version(conn, shop_id)
        items = {i.name_en: i for i in db.version_items(conn, base)}
        db.set_sold_out(conn, items["onion"].id, True)
        current = db.version_items(conn, base)
        transcript = Transcript(
            text="vengayam vanthiruchu, thakkali fifty kilo",
            duration_ms=6000,
            turns=[Turn(id=1, start_ms=0, end_ms=6000,
                        text="vengayam vanthiruchu, thakkali fifty kilo")])
        data = {"changes": [
            {"name_en": "onion", "action": "in_stock", "prices": [],
             "qty": None, "qty_unit": None, "turn_ids": [1],
             "quote": "vengayam vanthiruchu"},
            {"name_en": "tomato", "action": "set_qty", "prices": [],
             "qty": 50, "qty_unit": "kg", "turn_ids": [1],
             "quote": "thakkali fifty kilo"},
        ]}
        changes = parse_update_json(data, transcript, current)
        new_id = apply_changes(conn, shop_id, base, changes)
        got = {i.name_en: i for i in db.version_items(conn, new_id)}
        assert got["onion"].sold_out is False
        assert got["onion"].price_lines[0].price == 25
        assert (got["tomato"].qty, got["tomato"].qty_unit) == (Decimal(50), "kg")
        assert got["tomato"].price_lines[0].price == 18
    finally:
        conn.close()


def make_client(tmp_path, monkeypatch):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    calls = {}

    def fake_extract_audio(video, out_wav):
        calls["extract_audio"] = str(video)
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"RIFF-fake-wav")
        return Path(out_wav)

    def fake_transcribe(wav, **kwargs):
        calls["transcribe"] = str(wav)
        return update_transcript()

    def fake_chat_json(messages, **kwargs):
        calls["chat"] = kwargs.get("reasoning_effort")
        return CANNED_UPDATE

    monkeypatch.setattr("app.web.seller.extract_audio", fake_extract_audio)
    monkeypatch.setattr("app.web.seller.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.update.chat_json", fake_chat_json)
    return TestClient(create_app(settings), follow_redirects=False), calls


def create_shop(client):
    response = client.post("/new", data={
        "name": "Kannan Store", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"]


def approve_first_version(client, data_dir):
    conn = db.connect(Path(data_dir))
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        version_id = seed_version(conn, shop_id)
    finally:
        conn.close()
    return version_id


def test_update_page_has_recorder_and_notice(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    html = client.get(create_shop(client) + "/update").text
    assert "recorder.js" in html
    assert 'name="audio"' in html
    assert NOTICE in html


def test_update_requires_token(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.get("/e/badtoken/update").status_code == 404


def test_update_needs_approved_version_first(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    response = client.post(
        create_shop(client) + "/update",
        files={"audio": ("update.webm", b"fake-opus", "audio/webm")})
    assert response.status_code == 400


def test_voice_update_confirm_publishes_new_price(tmp_path, monkeypatch):
    client, calls = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    token = location.rsplit("/e/", 1)[1]
    data_dir = tmp_path / "data"
    first = approve_first_version(client, data_dir)
    client.post(f"{location}/v/{first}/publish")
    conn = db.connect(data_dir)
    try:
        slug = conn.execute("SELECT slug FROM shops").fetchone()["slug"]
    finally:
        conn.close()
    assert "₹18" in client.get(f"/s/{slug}").text

    posted = client.post(
        location + "/update",
        files={"audio": ("update.webm", b"fake-opus", "audio/webm")})
    assert posted.status_code == 200
    assert calls["extract_audio"].endswith(".webm")
    assert calls["transcribe"].endswith(".wav")
    assert calls["chat"] == "low"
    html = posted.text
    assert "thakkali 22 today" in html
    assert "vengayam sold out" in html
    assert "review.js" in html
    assert "opt-btn" in html or "flag-note" in html
    match = re.search(r"/e/\S+/update/(\d+)/confirm", html)
    assert match, "confirm page must link the confirm action"
    session_id = match.group(1)

    confirmed = client.post(f"/e/{token}/update/{session_id}/confirm", data={})
    assert confirmed.status_code in (302, 303)
    shop_html = client.get(f"/s/{slug}").text
    assert "₹22" in shop_html
    assert "Sold out" in shop_html
    conn = db.connect(data_dir)
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        assert db.latest_version(conn, shop_id, published_only=True) != first
    finally:
        conn.close()


def test_confirm_json_edits_price_and_enforces_flags(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    location = create_shop(client)
    token = location.rsplit("/e/", 1)[1]
    approve_first_version(client, tmp_path / "data")
    posted = client.post(
        location + "/update",
        files={"audio": ("update.webm", b"fake-opus", "audio/webm")})
    session_id = re.search(r"/update/(\d+)/confirm", posted.text).group(1)
    conn = db.connect(tmp_path / "data")
    try:
        slug = conn.execute("SELECT slug FROM shops").fetchone()["slug"]
    finally:
        conn.close()

    edited = json.loads(db._draft_to_json(
        DraftItem(name_spoken="tomato", name_ta="தக்காளி", name_en="tomato",
                  variety=None,
                  price_lines=[PriceLine(Decimal(23), Decimal(1), "kg")],
                  qty=None, qty_unit=None,
                  proof=Proof(quote="thakkali 22 today", turn_ids=[1],
                              start_ms=0, end_ms=3000))))
    sold_out = json.loads(db._draft_to_json(
        DraftItem(name_spoken="onion", name_ta="onion", name_en="onion",
                  variety=None, price_lines=[], qty=None, qty_unit=None,
                  proof=Proof(quote="vengayam sold out", turn_ids=[2],
                              start_ms=3000, end_ms=6000))))
    blocked = client.post(f"/e/{token}/update/{session_id}/confirm",
                            json={"items": [edited, sold_out], "confirmed": []})
    assert blocked.status_code == 400
    response = client.post(f"/e/{token}/update/{session_id}/confirm",
                           json={"items": [edited, sold_out], "confirmed": [0]})
    assert response.status_code in (302, 303)
    assert "₹23" in client.get(f"/s/{slug}").text
