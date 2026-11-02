"""Task 165: two live-demo fixes.

1. The Meta AI calls page for one list (/e/<token>/ai?session=N) showed
   today's header tiles (all zero when the list ran before midnight)
   above the session's own calls. With ?session= the tiles now describe
   that session: calls, cost, total wall time (first to last call),
   average call time and per-model counts, labelled "This list".
   Without ?session= today's tiles stay.
2. A red banana's spoken name carried price words ("sev vazhai date
   ..."): "date" is a mis-heard "rate" and the following token a
   mis-heard number the parser flagged as unclear. Spoken names stop
   before the first number/unclear-number/currency/unit word, drop
   rate words (rate/date/...) and collapse repeats.
No model calls.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import SAM_MODEL, SPARK_MODEL, VOICE_MODEL, load_settings
from app.costs import IST, CostLedger
from app.web.main import create_app


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data_dir = tmp_path / "data"
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(data_dir)})
    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client, data_dir


def _create_shop(client: TestClient) -> str:
    response = client.post("/new", data={
        "name": "T165 Store", "phone": "+914400000165", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"].rsplit("/e/", 1)[1]


def _seed_old_session(data_dir: Path, shop_id: int, session_id: int) -> None:
    """Two session calls stamped yesterday, 90 s apart (voice + spark)."""
    ledger = CostLedger(data_dir / "costs.db", 100.0)
    ledger.add("meta", VOICE_MODEL, 0.01, "s", shop_id=shop_id,
               session_id=session_id, step="transcribe", latency_ms=100,
               ok=1, summary="old voice")
    ledger.add("meta", SPARK_MODEL, 0.02, "s", shop_id=shop_id,
               session_id=session_id, step="extract prices", latency_ms=300,
               ok=1, summary="old text")
    base = datetime.now(IST).replace(
        hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
    with sqlite3.connect(data_dir / "costs.db") as conn:
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM costs WHERE session_id = ? ORDER BY id",
            (session_id,))]
        assert len(ids) == 2
        for pos, row_id in enumerate(ids):
            stamp = (base + timedelta(seconds=90 * pos)).isoformat()
            conn.execute("UPDATE costs SET day = ?, created_at = ? WHERE id = ?",
                         (base.date().isoformat(), stamp, row_id))


# --- 1. session tiles ----------------------------------------------------------


def test_session_view_shows_that_lists_own_totals(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    conn = db.connect(data_dir)
    try:
        shop_id = db.shop_by_token(conn, token)["id"]
        session_id = db.create_session(conn, shop_id, "video")
    finally:
        conn.close()
    _seed_old_session(data_dir, shop_id, session_id)

    html = client.get(f"/e/{token}/ai?session={session_id}").text
    assert f"This list · session {session_id}" in html
    assert 'data-ai-calls>2<' in html
    assert "$0.0300" in html
    assert "1 m 30 s" in html  # wall time, first call to last
    assert "200 ms" in html  # average call time
    assert "Voice · <b>1</b>" in html
    assert "Spark text · <b>1</b>" in html
    assert "Spark vision · <b>0</b>" in html
    assert "SAM · <b>0</b>" in html
    assert "old voice" in html and "old text" in html

    data = client.get(f"/e/{token}/ai.json?session={session_id}").json()
    assert data["stats"]["calls"] == 2
    assert data["stats"]["by_model"]["voice"] == 1
    assert data["stats"]["by_model"]["spark_text"] == 1
    assert data["wall_text"] == "1 m 30 s"


def test_default_view_keeps_todays_tiles(tmp_path):
    client, data_dir = _client(tmp_path)
    token = _create_shop(client)
    conn = db.connect(data_dir)
    try:
        shop_id = db.shop_by_token(conn, token)["id"]
        old_id = db.create_session(conn, shop_id, "video")
        new_id = db.create_session(conn, shop_id, "video")
    finally:
        conn.close()
    _seed_old_session(data_dir, shop_id, old_id)
    ledger = CostLedger(data_dir / "costs.db", 100.0)
    ledger.add("meta", SAM_MODEL, 0.005, "s", shop_id=shop_id,
               session_id=new_id, step="cut-out mask", latency_ms=50,
               ok=1, summary="today sam")

    html = client.get(f"/e/{token}/ai").text
    assert "This list" not in html
    assert 'data-ai-calls>1<' in html
    assert "$0.0050" in html
    assert "SAM · <b>1</b>" in html


# --- 2. spoken names -----------------------------------------------------------


def test_spoken_name_stops_before_price_words():
    from app.pipeline.spoken import spoken_item_name

    assert spoken_item_name(
        "sev vazhai இன்னைக்கு date மூத்திபத்து ரூபா கிலோ") == "sev vazhai"
    assert spoken_item_name("thakkali ரேட்டு இருபது ரூபாய்") == "thakkali"
    assert spoken_item_name("thakkali ரேட் இருபது ரூபாய்") == "thakkali"
    assert spoken_item_name("vengayam date 30") == "vengayam"


def test_task156_157_spoken_names_unchanged():
    from test_task156 import EXPECTED_SPANS
    from test_task157 import EXPECTED_QUOTES

    from app.pipeline.spoken import spoken_item_name

    assert [spoken_item_name(span) for span in EXPECTED_SPANS] == [
        "sev vazhai", "Nendran", "Karpuravalli", "பச்சை பழம்",
        "Tharpoosani", "Elaki", "poosani", "kathirikkai", "avaraikkai"]
    assert [spoken_item_name(quote) for quote in EXPECTED_QUOTES] == [
        "sev vazhai", "நேந்திரன்", "கற்பூரவள்ளி", "பச்சை பழம்",
        "தற்பூசணி", "ஏலகி", "பூசணி", "கத்தரிக்கா", "அவரக்கா",
        "கேரட்", "beans", "சுரக்கா", "பொடலங்கா", "வெண்டைக்கா",
        "குடமுளகா", "வெள்ளரிக்கா"]
