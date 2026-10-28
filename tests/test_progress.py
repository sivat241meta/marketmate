"""Task 24: upload progress and processing stepper."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.meta.transcribe import TranscribeError
from app.models import Box, Transcript, Turn
from app.pipeline.run import process_video_session, reprocess
from app.web.main import create_app

TURN_TEXT = "tomato kilo 18"

FRIENDLY_DEAF = (
    "We could not hear any prices. "
    "Try again closer to the phone, in a quieter spot."
)


def _settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "db")
    yield connection
    connection.close()


def _shop_session(conn, kind="video"):
    shop_id, _, _ = db.create_shop(
        conn, name="Shop", phone="+914400000000", area="A", language="ta",
        currency="INR", shop_type="vegetable")
    return shop_id, db.create_session(conn, shop_id, kind)


def _history(conn, session_id):
    row = conn.execute(
        "SELECT stages_json FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return json.loads(row["stages_json"] or "[]")


# --- db.set_stage ---

def test_set_stage_records_order_and_timestamps(conn):
    _, session_id = _shop_session(conn)
    db.set_stage(conn, session_id, "audio")
    db.set_stage(conn, session_id, "listening", detail="part 1 of 2")
    history = _history(conn, session_id)
    assert [entry["key"] for entry in history] == [
        "uploaded", "audio", "listening"]
    assert history[0]["ended_at"] is not None
    assert history[1]["ended_at"] is not None
    assert history[2]["ended_at"] is None
    assert all(entry["started_at"] for entry in history)
    row = conn.execute(
        "SELECT stage, stage_detail FROM sessions WHERE id = ?",
        (session_id,)).fetchone()
    assert row["stage"] == "listening"
    assert row["stage_detail"] == "part 1 of 2"


def test_set_stage_same_key_updates_detail_only(conn):
    _, session_id = _shop_session(conn)
    db.set_stage(conn, session_id, "photos", detail="item 1 of 5")
    db.set_stage(conn, session_id, "photos", detail="item 2 of 5")
    history = _history(conn, session_id)
    assert [entry["key"] for entry in history] == ["uploaded", "photos"]
    row = conn.execute(
        "SELECT stage_detail FROM sessions WHERE id = ?", (session_id,)).fetchone()
    assert row["stage_detail"] == "item 2 of 5"


def test_stage_columns_added_to_existing_db(tmp_path):
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    raw = sqlite3.connect(old_dir / "marketmate.db")
    raw.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,"
        " message TEXT NOT NULL DEFAULT '', cost REAL NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL)")
    raw.execute(
        "INSERT INTO sessions (shop_id, kind, status, created_at)"
        " VALUES (1, 'video', 'processing', '2026-10-28T00:00:00+00:00')")
    raw.commit()
    raw.close()
    connection = db.connect(old_dir)
    try:
        columns = {row[1] for row in
                   connection.execute("PRAGMA table_info(sessions)")}
        assert {"stage", "stage_detail", "stage_started_at",
                "stages_json"} <= columns
        db.set_stage(connection, 1, "listening")
        row = connection.execute(
            "SELECT stage FROM sessions WHERE id = 1").fetchone()
        assert row["stage"] == "listening"
    finally:
        connection.close()


def test_stage_labels_in_order():
    assert [key for key, _ in db.STAGES] == [
        "uploaded", "audio", "listening", "items", "photos", "checking",
        "ready"]
    labels = dict(db.STAGES)
    assert labels["uploaded"] == "Video received"
    assert labels["audio"] == "Getting the sound out"
    assert labels["listening"] == "Listening to your prices"
    assert labels["ready"] == "Ready to check"
    assert db.stages_for_kind("voice_update") == [
        "uploaded", "listening", "items", "checking", "ready"]


# --- /status JSON ---

def _client_with_token(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    response = client.post("/new", data={
        "name": "Kannan Store", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return client, response.headers["location"]


def test_status_json_shape_and_step_states(tmp_path):
    client, location = _client_with_token(tmp_path)
    connection = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(connection, location.split("/e/")[1])
        session_id = db.create_session(connection, shop["id"], "video")
        db.set_session_status(connection, session_id, "processing", "working")
        db.set_stage(connection, session_id, "audio")
        db.set_stage(connection, session_id, "listening", detail="hearing you")
    finally:
        connection.close()
    payload = client.get(f"{location}/s/{session_id}/status").json()
    assert payload["status"] == "processing"
    assert payload["message"] == "working"
    assert payload["stage"] == "listening"
    assert payload["step"] == 3
    assert payload["detail"] == "hearing you"
    assert payload["elapsed_s"] >= 0
    states = {step["key"]: step["state"] for step in payload["steps"]}
    assert states == {
        "uploaded": "done", "audio": "done", "listening": "active",
        "items": "todo", "photos": "todo", "checking": "todo", "ready": "todo"}
    for step in payload["steps"]:
        assert step["label"]
        assert step["seconds"] >= 0


def test_status_uses_short_list_for_voice_updates(tmp_path):
    client, location = _client_with_token(tmp_path)
    connection = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(connection, location.split("/e/")[1])
        session_id = db.create_session(connection, shop["id"], "voice_update")
        db.set_stage(connection, session_id, "listening")
    finally:
        connection.close()
    payload = client.get(f"{location}/s/{session_id}/status").json()
    assert [step["key"] for step in payload["steps"]] == [
        "uploaded", "listening", "items", "checking", "ready"]
    assert payload["step"] == 2


# --- pipeline stages ---

@pytest.fixture
def video(tmp_path):
    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=size=320x240:rate=30:duration=2", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt",
         "yuv420p", "-c:a", "aac", "-shortest", str(out)],
        check=True, capture_output=True)
    return out


def _item_json(name, price):
    return {
        "name_spoken": name, "name_en": name, "variety": None,
        "prices": [{"said": f"kilo {price}", "price": price, "per_amount": 1,
                    "unit": "kg"}],
        "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
        "turn_ids": [1], "quote": TURN_TEXT}


def _install_fakes(monkeypatch, transcript, extract_payloads):
    state = {"extract_calls": 0}

    def fake_transcribe(wav, **kwargs):
        return transcript

    def fake_chat_json(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content
                               if isinstance(part, dict))
        if "best shows" in content:
            return {"best_index": 0, "matches": True}
        index = min(state["extract_calls"], len(extract_payloads) - 1)
        state["extract_calls"] += 1
        return extract_payloads[index]

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat_json)
    monkeypatch.setattr("app.pipeline.frames.chat_json", fake_chat_json)
    monkeypatch.setattr(
        "app.pipeline.photos.find_boxes",
        lambda image, noun, **kwargs: [Box(10, 10, 50, 50, 320, 240, None)])


def _one_turn():
    return Transcript(
        text=TURN_TEXT, duration_ms=2000,
        turns=[Turn(id=1, start_ms=0, end_ms=2000, text=TURN_TEXT)])


def test_pipeline_records_stage_sequence(conn, tmp_path, video, monkeypatch):
    settings = _settings(tmp_path)
    _install_fakes(monkeypatch, _one_turn(),
                   [{"items": [_item_json("tomato", 18)]}])
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    _, session_id = _shop_session(conn)
    process_video_session(conn, session_id, video, settings=settings,
                          ledger=ledger)
    assert [entry["key"] for entry in _history(conn, session_id)] == [
        "uploaded", "audio", "listening", "items", "photos", "checking",
        "ready"]
    row = conn.execute("SELECT status, stage FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    assert (row["status"], row["stage"]) == ("review", "ready")


def test_pipeline_photos_detail_counts_items(conn, tmp_path, video, monkeypatch):
    settings = _settings(tmp_path)
    names = ["tomato", "onion", "potato", "carrot", "beans"]
    _install_fakes(
        monkeypatch, _one_turn(),
        [{"items": [_item_json(name, 10 + i)
                    for i, name in enumerate(names)]}])
    calls = []
    original = db.set_stage

    def recording(connection, session_id, key, detail=None):
        calls.append((key, detail))
        return original(connection, session_id, key, detail=detail)

    monkeypatch.setattr("app.db.set_stage", recording)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    _, session_id = _shop_session(conn)
    process_video_session(conn, session_id, video, settings=settings,
                          ledger=ledger)
    assert ("photos", "item 3 of 5") in calls


def test_pipeline_chunked_extraction_detail(conn, tmp_path, video, monkeypatch):
    settings = _settings(tmp_path)
    transcript = Transcript(
        text=TURN_TEXT, duration_ms=13000,
        turns=[Turn(id=i + 1, start_ms=i * 1000, end_ms=(i + 1) * 1000,
                    text=f"{TURN_TEXT} {i + 1}") for i in range(13)])
    _install_fakes(monkeypatch, transcript, [{"items": []}])
    calls = []
    original = db.set_stage

    def recording(connection, session_id, key, detail=None):
        calls.append((key, detail))
        return original(connection, session_id, key, detail=detail)

    monkeypatch.setattr("app.db.set_stage", recording)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    _, session_id = _shop_session(conn)
    process_video_session(conn, session_id, video, settings=settings,
                          ledger=ledger)
    assert ("items", "part 2 of 3") in calls


def test_failed_job_message_is_plain(conn, tmp_path, video, monkeypatch):
    settings = _settings(tmp_path)

    def deaf_transcribe(wav, **kwargs):
        raise TranscribeError("boom Traceback XYZ-SECRET")

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", deaf_transcribe)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    _, session_id = _shop_session(conn)
    process_video_session(conn, session_id, video, settings=settings,
                          ledger=ledger)
    row = conn.execute("SELECT status, message FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["message"] == FRIENDLY_DEAF
    assert db.load_drafts(conn, session_id) == []


def test_failed_job_hides_internal_errors(conn, tmp_path, video, monkeypatch):
    settings = _settings(tmp_path)
    _install_fakes(monkeypatch, _one_turn(),
                   [{"items": [_item_json("tomato", 18)]}])

    def exploding_extract(transcript, **kwargs):
        raise RuntimeError("kaboom-SECRET Traceback line 42")

    monkeypatch.setattr("app.pipeline.run.extract_items", exploding_extract)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    _, session_id = _shop_session(conn)
    process_video_session(conn, session_id, video, settings=settings,
                          ledger=ledger)
    row = conn.execute("SELECT status, message FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    assert row["status"] == "failed"
    assert "kaboom" not in row["message"]
    assert "Traceback" not in row["message"]
    assert row["message"]


# --- retry ---

def _seed_cache(data_dir, session_id):
    session_dir = Path(data_dir) / "sessions" / str(session_id)
    frames_dir = session_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "transcript.json").write_text(json.dumps({
        "text": TURN_TEXT, "duration_ms": 2000,
        "turns": [{"id": 1, "start_ms": 0, "end_ms": 2000,
                   "text": TURN_TEXT}]}))
    (session_dir / "audio.wav").write_bytes(b"fake-wav")
    from PIL import Image

    Image.new("RGB", (64, 48), (180, 40, 40)).save(frames_dir / "f_0.jpg")
    Image.new("RGB", (64, 48), (40, 180, 40)).save(frames_dir / "f_500.jpg")


def _retry_client(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = create_app(settings)
    monkeypatch.setattr(
        "app.pipeline.extract.chat_json",
        lambda messages, **kwargs: {"items": [_item_json("tomato", 18)]})
    monkeypatch.setattr(
        "app.pipeline.frames.chat_json",
        lambda messages, **kwargs: {"best_index": 0, "matches": True})
    monkeypatch.setattr(
        "app.pipeline.photos.find_boxes",
        lambda image, noun, **kwargs: [Box(5, 5, 40, 40, 64, 48, None)])

    def fake_clip(wav, start_ms, end_ms, out, pad_ms=300):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-clip")
        return out

    monkeypatch.setattr("app.pipeline.run.cut_audio_clip", fake_clip)
    # Retry now schedules a background job; run it inline for the end-to-end
    # assertion below.
    monkeypatch.setattr("app.web.seller.jobs.submit", lambda fn, *a: fn(*a))
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("start_status", ["failed", "review"])
def test_retry_works_for_failed_and_review(tmp_path, monkeypatch,
                                           start_status):
    client = _retry_client(tmp_path, monkeypatch)
    response = client.post("/new", data={
        "name": "Retry Shop", "phone": "+914400000000", "area": "A",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    location = response.headers["location"]
    connection = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(connection, location.split("/e/")[1])
        session_id = db.create_session(connection, shop["id"], "video")
        if start_status == "failed":
            db.set_session_status(connection, session_id, "failed", "old")
        else:
            db.set_session_status(connection, session_id, "review", "old")
    finally:
        connection.close()
    _seed_cache(tmp_path / "data", session_id)
    retry = client.post(f"{location}/s/{session_id}/retry")
    assert retry.status_code in (302, 303)
    connection = db.connect(tmp_path / "data")
    try:
        row = connection.execute(
            "SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row["status"] == "review"
        assert len(db.load_drafts(connection, session_id)) == 1
    finally:
        connection.close()


def test_reprocess_rejects_sessions_without_cache(conn, tmp_path):
    settings = _settings(tmp_path)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    _, session_id = _shop_session(conn)
    db.set_session_status(conn, session_id, "review", "old")
    with pytest.raises(ValueError):
        reprocess(conn, session_id, settings=settings, ledger=ledger)


# --- upload.js and forms ---

def test_upload_js_exists_with_xhr_cancel_and_redirect():
    source = (Path("app/web/static/upload.js")).read_text()
    assert "XMLHttpRequest" in source
    assert ".abort()" in source
    assert "responseURL" in source
    assert "progress" in source.lower()


def test_dashboard_form_posts_video_with_progress_ui(tmp_path):
    client, location = _client_with_token(tmp_path)
    html = client.get(location).text
    assert f'action="{location}/upload"' in html
    assert 'name="video"' in html
    assert "data-upload-form" in html
    assert "upload.js" in html
    assert "data-max-bytes" in html
    assert "data-upload-cancel" in html


def test_update_page_has_upload_progress_ui(tmp_path):
    client, location = _client_with_token(tmp_path)
    html = client.get(f"{location}/update").text
    assert "upload.js" in html
    assert "data-upload-form" in html
