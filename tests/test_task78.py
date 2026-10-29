"""Task 78: "Meta AI calls" page (per-shop log of every Meta model call).

Covers: ledger migration + old add() args, owner-only shop-scoped page and
JSON, summaries never holding transcripts or phone numbers, since_id polling,
filter chips, en/ta/hi rendering.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response

from app import db
from app.config import SPARK_MODEL, VOICE_MODEL, load_settings
from app.costs import CostLedger
from app.web.main import create_app

_TRANSCRIBE_URL = "https://api.meta.ai/v1/asr/transcribe"


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data_dir = tmp_path / "data"
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(data_dir)})
    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client, data_dir


def _create_shop(client: TestClient, name: str = "Kannan Store") -> str:
    response = client.post("/new", data={
        "name": name, "phone": "+914400000001", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"].rsplit("/e/", 1)[1]


def _shop_id(data_dir: Path, token: str) -> int:
    conn = db.connect(data_dir)
    try:
        return db.shop_by_token(conn, token)["id"]
    finally:
        conn.close()


def _ledger(data_dir: Path) -> CostLedger:
    return CostLedger(data_dir / "costs.db", 100.0)


def _seed_call(ledger: CostLedger, shop_id: int, model: str, **kwargs) -> None:
    params = {"shop_id": shop_id, "step": "transcribe", "ok": 1}
    params.update(kwargs)
    ledger.add("meta", model, 0.001, "seed", **params)


# --- ledger migration --------------------------------------------------------


def test_migration_adds_columns_and_old_rows_still_read(tmp_path):
    path = tmp_path / "c.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE costs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "day TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, "
            "usd REAL NOT NULL, detail TEXT NOT NULL DEFAULT '', "
            "created_at TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO costs (day, provider, model, usd, detail, created_at)"
            " VALUES ('2099-01-01', 'meta', 'm', 0.5, 'old', 't')")
    ledger = CostLedger(path, 100.0)
    with sqlite3.connect(path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(costs)")}
        old = conn.execute("SELECT usd, detail FROM costs").fetchall()
    assert {"shop_id", "session_id", "step", "latency_ms", "ok",
            "summary"} <= cols
    assert old == [(0.5, "old")]
    ledger.add("meta", VOICE_MODEL, 0.01, "new", shop_id=3, step="transcribe",
               latency_ms=120, ok=1, summary="Tamil · 4 s audio")
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT shop_id, step, latency_ms, ok, summary FROM costs"
            " WHERE detail = 'new'").fetchone()
    assert tuple(row) == (3, "transcribe", 120, 1, "Tamil · 4 s audio")


def test_add_still_works_with_old_args(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    ledger.add("meta", "m", 0.02)
    ledger.add("meta", "m", 0.03, "detail-here")
    with sqlite3.connect(tmp_path / "c.db") as conn:
        rows = conn.execute(
            "SELECT usd, detail, shop_id, summary FROM costs ORDER BY id"
        ).fetchall()
    assert rows[0][:2] == (0.02, "")
    assert rows[1][:2] == (0.03, "detail-here")
    assert rows[0][2:] == (None, None)


def test_summary_sanitized_phone_and_length(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    ledger.add("meta", "m", 0.0, "d", summary="call +914400000001 now")
    ledger.add("meta", "m", 0.0, "d", summary="x" * 500)
    with sqlite3.connect(tmp_path / "c.db") as conn:
        rows = [row[0] for row in conn.execute(
            "SELECT summary FROM costs ORDER BY id")]
    assert "914400000001" not in rows[0]
    assert len(rows[1]) <= 140


def test_transcribe_logs_step_without_transcript_text(respx_mock, tmp_path):
    from app.meta.transcribe import transcribe_wav

    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    secret = "thakkali secret eighteen rupees call 9876543210"
    respx_mock.post(_TRANSCRIBE_URL).mock(return_value=Response(200, json={
        "transcript": secret, "audioDurationMs": 42000, "turns": []}))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"fakewav")
    ledger.bind(shop_id=7, session_id=9)
    out = transcribe_wav(wav, keywords=["thakkali"], ledger=ledger,
                         settings=settings)
    assert out.text == secret
    with sqlite3.connect(tmp_path / "c.db") as conn:
        row = conn.execute(
            "SELECT shop_id, session_id, step, latency_ms, ok, summary,"
            " detail FROM costs").fetchone()
    assert row[0:3] == (7, 9, "transcribe")
    assert row[3] is not None and row[4] == 1
    assert "secret eighteen" not in (row[5] or "")
    assert "9876543210" not in (row[5] or "")
    assert row[6] == "transcribe_wav"


# --- page + JSON -------------------------------------------------------------


def test_page_owner_only_and_shop_scoped(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client, "Shop A")
    other = _create_shop(client, "Shop B")
    shop_id = _shop_id(data_dir, token)
    other_id = _shop_id(data_dir, other)
    ledger = _ledger(data_dir)
    _seed_call(ledger, shop_id, VOICE_MODEL, summary="Tamil · 4 s audio")
    _seed_call(ledger, other_id, VOICE_MODEL, summary="Hindi · 9 s audio")
    conn = db.connect(data_dir)
    try:
        _, helper = db.create_helper(conn, shop_id, "Muthu")
    finally:
        conn.close()

    page = client.get(f"/e/{token}/ai")
    assert page.status_code == 200
    assert "Tamil · 4 s audio" in page.text
    assert "Hindi · 9 s audio" not in page.text
    assert "Meta AI calls" in page.text

    denied = client.get(f"/e/{helper}/ai")
    assert denied.status_code == 403

    data = client.get(f"/e/{token}/ai.json").json()
    assert [row["summary"] for row in data["rows"]] == ["Tamil · 4 s audio"]
    assert client.get(f"/e/{helper}/ai.json").status_code == 403
    assert client.get("/e/badtoken/ai").status_code == 404


def test_page_links_from_more_menu_and_session(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    home = client.get(f"/e/{token}")
    assert f'href="/e/{token}/ai"' in home.text
    shop_id = _shop_id(data_dir, token)
    conn = db.connect(data_dir)
    try:
        session_id = db.create_session(conn, shop_id, "video")
        db.set_session_status(conn, session_id, "failed", "boom")
    finally:
        conn.close()
    session_page = client.get(f"/e/{token}/s/{session_id}")
    assert session_page.status_code == 200
    assert f"/e/{token}/ai?session={session_id}" in session_page.text


def test_json_returns_only_newer_rows(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    shop_id = _shop_id(data_dir, token)
    ledger = _ledger(data_dir)
    for pos in range(3):
        _seed_call(ledger, shop_id, VOICE_MODEL, summary=f"clip {pos}")
    first = client.get(f"/e/{token}/ai.json").json()
    assert [row["summary"] for row in first["rows"]] == [
        "clip 2", "clip 1", "clip 0"]
    since = first["rows"][1]["id"]
    newer = client.get(f"/e/{token}/ai.json?since_id={since}").json()
    assert [row["summary"] for row in newer["rows"]] == ["clip 2"]
    assert newer["max_id"] == first["max_id"]


def test_filters_work(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    shop_id = _shop_id(data_dir, token)
    ledger = _ledger(data_dir)
    _seed_call(ledger, shop_id, VOICE_MODEL, summary="voice one")
    _seed_call(ledger, shop_id, SPARK_MODEL, step="extract prices",
               summary="text one")
    _seed_call(ledger, shop_id, "sam-3.1", step="cut-out mask",
               summary="sam one")
    page = client.get(f"/e/{token}/ai?show=voice")
    assert "voice one" in page.text
    assert "text one" not in page.text and "sam one" not in page.text
    data = client.get(f"/e/{token}/ai.json?show=sam").json()
    assert [row["summary"] for row in data["rows"]] == ["sam one"]
    both = client.get(f"/e/{token}/ai.json?show=spark").json()
    assert [row["summary"] for row in both["rows"]] == ["text one"]


def test_renders_en_ta_hi(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    shop_id = _shop_id(data_dir, token)
    _seed_call(_ledger(data_dir), shop_id, VOICE_MODEL)
    for lang, title in (("en", "Meta AI calls"),
                        ("ta", "மெட்டா AI அழைப்புகள்"),
                        ("hi", "Meta AI कॉल")):
        client.cookies.set("ui_lang", lang)
        page = client.get(f"/e/{token}/ai")
        assert page.status_code == 200, lang
        assert title in page.text, lang


def test_live_mode_polls_while_processing(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    shop_id = _shop_id(data_dir, token)
    conn = db.connect(data_dir)
    try:
        session_id = db.create_session(conn, shop_id, "video")
        db.set_session_status(conn, session_id, "processing", "working")
    finally:
        conn.close()
    page = client.get(f"/e/{token}/ai")
    assert "data-ai-live=\"1\"" in page.text
    assert "Live — new calls appear here" in page.text
    ledger = _ledger(data_dir)
    _seed_call(ledger, shop_id, VOICE_MODEL, session_id=session_id,
               summary="fresh clip")
    data = client.get(f"/e/{token}/ai.json?since_id=0").json()
    assert data["processing"] is True
    assert [row["summary"] for row in data["rows"]] == ["fresh clip"]
    assert data["rows"][0]["session_title"] == f"Session {session_id}"
    conn = db.connect(data_dir)
    try:
        db.set_session_status(conn, session_id, "review", "done")
    finally:
        conn.close()
    assert client.get(f"/e/{token}/ai.json").json()["processing"] is False


def test_extract_logs_step_counts_without_transcript(
        respx_mock, tmp_path):
    import json as json_lib

    from app.meta.spark import chat_json  # noqa: F401 (warms import path)

    body = json_lib.loads(
        Path("tests/fixtures/spark_text.json").read_text())
    body["choices"][0]["message"]["content"] = (
        '{"items": [{"name_en": "tomato", "price_lines": []},'
        ' {"name_en": "onion", "price_lines": []}]}')
    respx_mock.post("https://api.meta.ai/v1/chat/completions").mock(
        return_value=Response(200, json=body))
    from app.models import Transcript, Turn
    from app.pipeline.extract import extract_items

    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    ledger.bind(shop_id=5, session_id=6)
    transcript = Transcript(text="ultrasound supersecret tomato talk",
                            duration_ms=1000,
                            turns=[Turn(1, 0, 1000, "tomato talk")])
    extract_items(transcript, ledger=ledger, settings=settings)
    with sqlite3.connect(tmp_path / "c.db") as conn:
        row = conn.execute(
            "SELECT shop_id, session_id, step, ok, summary FROM costs"
        ).fetchone()
    assert tuple(row[:4]) == (5, 6, "extract prices", 1)
    assert "supersecret" not in (row[4] or "")
    assert "2 items" in (row[4] or "")
