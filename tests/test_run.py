import subprocess
import threading

import pytest

from app import db, jobs
from app.config import load_settings
from app.costs import CostCapExceeded, CostLedger
from app.models import Transcript, Turn
from app.pipeline.run import process_video_session, reprocess

TURN_TEXT = "tomato kilo 18"

CANNED_EXTRACT = {"items": [{
    "name_spoken": "tomato",
    "name_en": "tomato",
    "variety": None,
    "prices": [{"said": "kilo 18", "price": 18, "per_amount": 1, "unit": "kg"}],
    "range_said": False,
    "qty_said": None,
    "qty": None,
    "qty_unit": None,
    "turn_ids": [1],
    "quote": TURN_TEXT,
}]}


@pytest.fixture
def settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "db")
    yield connection
    connection.close()


@pytest.fixture
def video(tmp_path):
    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture
def fakes(monkeypatch):
    from app.meta.sam import SamInstance
    from app.models import Box

    calls = {"transcribe": 0, "extract": 0, "pick": 0}

    def fake_transcribe(wav, **kwargs):
        calls["transcribe"] += 1
        return Transcript(text=TURN_TEXT, duration_ms=2000, turns=[
            Turn(id=1, start_ms=0, end_ms=2000, text=TURN_TEXT)])

    def fake_chat_json(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content
                               if isinstance(p, dict))
        if "best shows" in content:
            calls["pick"] += 1
            return {"best_index": 0, "matches": True}
        calls["extract"] += 1
        return CANNED_EXTRACT

    def fake_find_instances(image, noun, **kwargs):
        return [SamInstance(Box(10, 10, 50, 50, 320, 240, None), None)]

    def fake_find_faces(image, noun, **kwargs):
        return []

    def fake_photo_chat_json(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content
                               if isinstance(p, dict))
        if "visual noun" in content:
            return {}
        return {"item": "none"}

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat_json)
    monkeypatch.setattr("app.pipeline.frames.chat_json", fake_chat_json)
    monkeypatch.setattr("app.pipeline.photos.chat_json", fake_photo_chat_json)
    monkeypatch.setattr("app.pipeline.photos.find_instances",
                        fake_find_instances)
    monkeypatch.setattr("app.pipeline.photos.find_boxes", fake_find_faces)
    return calls


def make_session(conn):
    shop_id, _, _ = db.create_shop(
        conn, name="Shop", phone="1", area="A", language="ta",
        currency="INR", shop_type="vegetable")
    return db.create_session(conn, shop_id, "video")


def status_of(conn, session_id):
    row = conn.execute("SELECT status, message FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    return row["status"], row["message"]


def test_submit_runs_fn():
    done = threading.Event()
    jobs.submit(done.set)
    assert done.wait(timeout=10)


def test_happy_path_reaches_review(conn, settings, fakes, video, tmp_path):
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    session_id = make_session(conn)
    process_video_session(conn, session_id, video, settings=settings, ledger=ledger)
    status, _ = status_of(conn, session_id)
    assert status == "review"
    assert len(db.load_drafts(conn, session_id)) == 1


def test_raw_video_deleted(conn, settings, fakes, video, tmp_path):
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    session_id = make_session(conn)
    process_video_session(conn, session_id, video, settings=settings, ledger=ledger)
    assert not video.exists()


def test_cap_mid_session_fails_cleanly(conn, settings, fakes, video, tmp_path,
                                       monkeypatch):
    def raising_find_instances(image, noun, **kwargs):
        raise CostCapExceeded("daily Meta budget reached")

    monkeypatch.setattr("app.pipeline.photos.find_instances",
                        raising_find_instances)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    session_id = make_session(conn)
    process_video_session(conn, session_id, video, settings=settings, ledger=ledger)
    status, message = status_of(conn, session_id)
    assert status == "failed"
    assert "budget" in message
    assert db.load_drafts(conn, session_id) == []


def test_reprocess_uses_cached_transcript(conn, settings, fakes, video, tmp_path,
                                          monkeypatch):
    from app.meta.sam import SamInstance
    from app.models import Box

    def raising_find_instances(image, noun, **kwargs):
        raise CostCapExceeded("daily Meta budget reached")

    monkeypatch.setattr("app.pipeline.photos.find_instances",
                        raising_find_instances)
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    session_id = make_session(conn)
    process_video_session(conn, session_id, video, settings=settings, ledger=ledger)
    assert status_of(conn, session_id)[0] == "failed"

    def working_find_instances(image, noun, **kwargs):
        return [SamInstance(Box(10, 10, 50, 50, 320, 240, None), None)]

    monkeypatch.setattr("app.pipeline.photos.find_instances",
                        working_find_instances)
    reprocess(conn, session_id, settings=settings, ledger=ledger)
    assert status_of(conn, session_id)[0] == "review"
    assert fakes["transcribe"] == 1


def test_run_clip_preserves_source_clip(monkeypatch, tmp_path, fakes, video):
    import sys

    from scripts import run_clip

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_clip.py", str(video)])
    run_clip.main()
    assert video.exists()
    assert (tmp_path / "eval" / "out" / "clip.json").exists()


def test_run_clip_reports_run_cost_not_day_total(monkeypatch, tmp_path, fakes, video):
    import json
    import sys

    from scripts import run_clip

    monkeypatch.chdir(tmp_path)
    earlier = CostLedger(tmp_path / "data" / "costs.db", 100.0)
    earlier.add("meta", "muse-spark-1.3", 0.05, "earlier run")
    monkeypatch.setattr(sys, "argv", ["run_clip.py", str(video)])
    run_clip.main()
    out = json.loads((tmp_path / "eval" / "out" / "clip.json").read_text())
    assert out["meta_usd"] == 0


def test_no_speech_gives_empty_review(conn, settings, video, tmp_path, monkeypatch):
    def empty_transcribe(wav, **kwargs):
        return Transcript(text="", duration_ms=2000, turns=[])

    extracted = []
    monkeypatch.setattr("app.pipeline.run.transcribe_wav", empty_transcribe)
    monkeypatch.setattr(
        "app.pipeline.extract.chat_json",
        lambda messages, **kwargs: extracted.append(messages) or {"items": []})
    ledger = CostLedger(tmp_path / "costs.db", 100.0)
    session_id = make_session(conn)
    process_video_session(conn, session_id, video, settings=settings, ledger=ledger)
    status, message = status_of(conn, session_id)
    assert status == "review"
    assert db.load_drafts(conn, session_id) == []
    assert "No prices heard" in message
    assert extracted == []
