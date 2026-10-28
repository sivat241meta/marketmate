"""Task 53: spoken-language picker + script-mismatch guard.

A Tamil seller on an English shop once got a transcript written in Kannada
letters; every price was then blocked as NOT_HEARD. The picker + guard mean a
wrong language choice interrupts with a question instead of blocking prices.
"""

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import Transcript, Turn
from app.pipeline.scripts import dominant_script, expected_scripts
from app.web.main import create_app

KANNADA_TEXT = ("ಇದು ಏಲಗಿ ಮತ್ತಿಪಳಂ. ಒಂದು ಕಿಲೋ ನೂರು ರೂಪಾಯಿ. "
                "ಇದು ಪಚ್ಚ, ಒಂದು ಕಿಲೋ ನಾಲ್ಪತ್ತು ರೂಪಾಯಿ.")
TAMIL_TEXT = ("இது ஏலக்கி மத்திப்பழம். ஒரு கிலோ நூறு ரூபாய். "
              "இது பச்சை, ஒரு கிலோ நாற்பது ரூபாய்.")

TAMIL_EXTRACT = {"items": [
    {"name_spoken": "yelakki", "name_en": "banana",
     "name_local": "வாழைப்பழம்", "variety": None,
     "prices": [{"said": "ஒரு கிலோ நூறு", "price": 100,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None,
     "qty_unit": None, "turn_ids": [1],
     "quote": "ஒரு கிலோ நூறு ரூபாய்"},
    {"name_spoken": "patchai", "name_en": "banana",
     "name_local": "வாழைப்பழம்", "variety": None,
     "prices": [{"said": "ஒரு கிலோ நாற்பது", "price": 40,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None,
     "qty_unit": None, "turn_ids": [1],
     "quote": "ஒரு கிலோ நாற்பது ரூபாய்"},
]}


# --- dominant_script --------------------------------------------------------


def test_dominant_script_tamil():
    assert dominant_script("இது ஏலக்கி பழம் ஒரு கிலோ") == "Tamil"


def test_dominant_script_kannada():
    assert dominant_script(KANNADA_TEXT) == "Kannada"


def test_dominant_script_latin():
    assert dominant_script("tomato kilo 18 rupees") == "Latin"


def test_dominant_script_mixed_tamil_english():
    assert dominant_script("தக்காளி வெங்காயம் tomato கிலோ பத்து") == "Tamil"


def test_dominant_script_digits_only():
    assert dominant_script("100 200") == "other"


def test_expected_scripts_always_allows_latin():
    assert expected_scripts(["Tamil", "English"]) == {"Tamil", "Latin"}
    assert expected_scripts(["English"]) == {"Latin"}


# --- helpers ----------------------------------------------------------------


def make_client(tmp_path, monkeypatch):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)
    monkeypatch.setattr("app.web.seller.jobs.submit",
                        lambda fn, *args: fn(*args))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client, settings


def create_shop(client, language="en"):
    response = client.post("/new", data={
        "name": "Guard Store", "phone": "+914400000000", "area": "A",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"].split("/e/")[1]


def mock_media(monkeypatch):
    monkeypatch.setattr("app.pipeline.run.check_length",
                        lambda *args, **kwargs: None)

    def fake_audio(video, out):
        Path(out).write_bytes(b"fake-wav")
        return Path(out)

    def fake_frames(video, outdir):
        Path(outdir).mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr("app.pipeline.run.extract_audio", fake_audio)
    monkeypatch.setattr("app.pipeline.run.extract_frames", fake_frames)


def mock_continue(monkeypatch):
    """Mocks for the extract/photo tail of the video pipeline."""
    from app.models import Frame

    def fake_pick(item, frames, **kwargs):
        return Frame(path=Path("f.jpg"), t_ms=0), True

    monkeypatch.setattr("app.pipeline.run.pick_best_frame", fake_pick)
    monkeypatch.setattr("app.pipeline.run.make_photo",
                        lambda frame, noun, out, **kwargs: Path(out))
    monkeypatch.setattr("app.pipeline.run.make_candidates",
                        lambda frames, picked, noun, out_stem, **kwargs:
                        [str(out_stem) + "_c0.jpg"])
    monkeypatch.setattr("app.pipeline.run.cut_audio_clip",
                        lambda wav, start, end, out: Path(out))
    monkeypatch.setattr("app.pipeline.extract.chat_json",
                        lambda messages, **kwargs: TAMIL_EXTRACT)
    monkeypatch.setattr("app.pipeline.checks.chat_json",
                        lambda messages, **kwargs: {})


def langcheck_session(data_dir, *, shop_lang="en", text=KANNADA_TEXT,
                      retries=0):
    """A video session already stopped in language_check, with saved files."""
    data_dir = Path(data_dir)
    conn = db.connect(data_dir)
    try:
        shop_id, _, token = db.create_shop(
            conn, name="S", phone="+911234567890", area="A",
            language=shop_lang, currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")
        session_dir = data_dir / "sessions" / str(session_id)
        (session_dir / "frames").mkdir(parents=True, exist_ok=True)
        (session_dir / "audio.wav").write_bytes(b"fake-wav")
        (session_dir / "frames" / "f_1000.jpg").write_bytes(b"fake-jpg")
        (session_dir / "transcript.json").write_text(json.dumps({
            "text": text, "duration_ms": 9000,
            "turns": [{"id": 1, "start_ms": 0, "end_ms": 9000,
                       "text": text}]}))
        db.set_session_status(conn, session_id, "processing", "test")
        db.set_stage(conn, session_id, "language_check",
                     detail=dominant_script(text))
        for _ in range(retries):
            db.bump_session_lang_retries(conn, session_id)
        return token, session_id
    finally:
        conn.close()


def session_row(data_dir, session_id):
    conn = db.connect(Path(data_dir))
    try:
        return dict(conn.execute("SELECT * FROM sessions WHERE id = ?",
                                 (session_id,)).fetchone())
    finally:
        conn.close()


# --- upload with speak_lang -------------------------------------------------


def test_upload_speak_lang_sets_bias(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    mock_media(monkeypatch)
    calls = {}

    def fake_transcribe(wav, **kwargs):
        calls["languages"] = kwargs.get("languages")
        return Transcript(text=KANNADA_TEXT, duration_ms=9000, turns=[
            Turn(id=1, start_ms=0, end_ms=9000, text=KANNADA_TEXT)])

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    token = create_shop(client, "en")
    response = client.post(
        f"/e/{token}/upload",
        files={"video": ("clip.mp4", b"fakebytes", "video/mp4")},
        data={"speak_lang": "ta"})
    assert response.status_code == 303
    session_id = int(response.headers["location"].rsplit("/s/", 1)[1])
    assert calls["languages"] == ("Tamil", "English")
    row = session_row(settings.data_dir, session_id)
    assert row["speak_lang"] == "ta"


def test_upload_without_speak_lang_uses_shop(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    mock_media(monkeypatch)
    calls = {}

    def fake_transcribe(wav, **kwargs):
        calls["languages"] = kwargs.get("languages")
        return Transcript(text="tomato kilo 18", duration_ms=2000, turns=[
            Turn(id=1, start_ms=0, end_ms=2000, text="tomato kilo 18")])

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.extract.chat_json",
                        lambda messages, **kwargs: {"items": []})
    token = create_shop(client, "en")
    response = client.post(
        f"/e/{token}/upload",
        files={"video": ("clip.mp4", b"fakebytes", "video/mp4")},
        data={})
    assert response.status_code == 303
    assert calls["languages"] == ("English",)


def test_kannada_transcript_stops_before_spark(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    mock_media(monkeypatch)
    spark_calls = []

    def fake_transcribe(wav, **kwargs):
        return Transcript(text=KANNADA_TEXT, duration_ms=9000, turns=[
            Turn(id=1, start_ms=0, end_ms=9000, text=KANNADA_TEXT)])

    def fake_chat(messages, **kwargs):
        spark_calls.append(messages)
        return {"items": []}

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat)
    monkeypatch.setattr("app.pipeline.frames.chat_json", fake_chat)
    monkeypatch.setattr("app.pipeline.checks.chat_json", fake_chat)
    token = create_shop(client, "en")
    response = client.post(
        f"/e/{token}/upload",
        files={"video": ("clip.mp4", b"fakebytes", "video/mp4")},
        data={})
    assert response.status_code == 303
    session_id = int(response.headers["location"].rsplit("/s/", 1)[1])
    row = session_row(settings.data_dir, session_id)
    assert row["stage"] == "language_check"
    assert row["status"] == "processing"
    assert spark_calls == []


# --- choosing a language ----------------------------------------------------


def test_choose_tamil_retranscribes_and_continues(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    mock_continue(monkeypatch)
    calls = []

    def fake_transcribe(wav, **kwargs):
        calls.append(kwargs.get("languages"))
        return Transcript(text=TAMIL_TEXT, duration_ms=9000, turns=[
            Turn(id=1, start_ms=0, end_ms=9000, text=TAMIL_TEXT)])

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    token, session_id = langcheck_session(settings.data_dir)
    response = client.post(f"/e/{token}/s/{session_id}/language",
                           data={"speak_lang": "ta"})
    assert response.status_code == 303
    assert calls == [("Tamil", "English")]
    row = session_row(settings.data_dir, session_id)
    assert row["status"] == "review"
    assert row["stage"] == "ready"
    conn = db.connect(Path(settings.data_dir))
    try:
        drafts = db.load_drafts(conn, session_id)
    finally:
        conn.close()
    assert [str(line.price) for item in drafts
            for line in item.price_lines] == ["100", "40"]
    assert all(flag.code != "NOT_HEARD" for item in drafts
               for flag in item.flags)


def test_choose_kannada_continues_without_retranscribing(tmp_path,
                                                         monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    mock_continue(monkeypatch)
    calls = []

    def fake_transcribe(wav, **kwargs):
        calls.append(kwargs.get("languages"))
        raise AssertionError("must not re-transcribe")

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    token, session_id = langcheck_session(settings.data_dir)
    response = client.post(f"/e/{token}/s/{session_id}/language",
                           data={"speak_lang": "kn"})
    assert response.status_code == 303
    assert calls == []
    row = session_row(settings.data_dir, session_id)
    assert row["status"] == "review"
    assert row["speak_lang"] == "kn"


def test_third_rerun_is_refused(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    mock_continue(monkeypatch)
    calls = []

    def fake_transcribe(wav, **kwargs):
        calls.append(kwargs.get("languages"))
        raise AssertionError("third re-run must be refused")

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    token, session_id = langcheck_session(settings.data_dir, retries=2)
    response = client.post(f"/e/{token}/s/{session_id}/language",
                           data={"speak_lang": "ta"})
    assert response.status_code == 303
    assert calls == []
    row = session_row(settings.data_dir, session_id)
    assert row["status"] == "review"
    assert row["speak_lang"] == "ta"
    saved = json.loads((Path(settings.data_dir) / "sessions"
                        / str(session_id) / "transcript.json").read_text())
    assert saved["text"] == KANNADA_TEXT


def test_ledger_records_second_voice_call(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    mock_media(monkeypatch)
    mock_continue(monkeypatch)
    payloads = [
        {"transcript": KANNADA_TEXT, "audioDurationMs": 9000, "turns": [
            {"turnId": 0, "startMs": 0, "endMs": 9000,
             "transcript": KANNADA_TEXT}]},
        {"transcript": TAMIL_TEXT, "audioDurationMs": 9000, "turns": [
            {"turnId": 0, "startMs": 0, "endMs": 9000,
             "transcript": TAMIL_TEXT}]},
    ]
    biases = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        request_json = kwargs["files"]["request"][1]
        biases.append(json.loads(request_json)["languageBias"])
        return _Resp(payloads.pop(0))

    monkeypatch.setattr("app.meta.transcribe.httpx.post", fake_post)
    token = create_shop(client, "en")
    response = client.post(
        f"/e/{token}/upload",
        files={"video": ("clip.mp4", b"fakebytes", "video/mp4")},
        data={})
    session_id = int(response.headers["location"].rsplit("/s/", 1)[1])
    assert session_row(settings.data_dir, session_id)["stage"] == \
        "language_check"
    response = client.post(f"/e/{token}/s/{session_id}/language",
                           data={"speak_lang": "ta"})
    assert response.status_code == 303
    assert biases == [["English"], ["Tamil", "English"]]
    with sqlite3.connect(Path(settings.data_dir) / "costs.db") as conn:
        rows = conn.execute(
            "SELECT usd FROM costs WHERE detail = 'transcribe_wav'"
        ).fetchall()
    assert len(rows) == 2
    assert all(row[0] > 0 for row in rows)


# --- pages ------------------------------------------------------------------


def test_language_check_page_renders_en_ta_hi(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    token, session_id = langcheck_session(settings.data_dir)
    url = f"/e/{token}/s/{session_id}"
    client.cookies.set("ui_lang", "en")
    english = client.get(url)
    assert english.status_code == 200
    assert "Kannada" in english.text
    assert KANNADA_TEXT[:40] in english.text
    assert "தமிழ்" in english.text
    assert "Which language did you speak" in english.text
    client.cookies.set("ui_lang", "ta")
    tamil = client.get(url)
    assert tamil.status_code == 200
    assert "எந்த மொழியில் பேசினீர்கள்" in tamil.text
    client.cookies.set("ui_lang", "hi")
    hindi = client.get(url)
    assert hindi.status_code == 200
    assert "किस भाषा में बोला था" in hindi.text


def test_upload_form_has_picker(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client, "en")
    html = client.get(f"/e/{token}").text
    assert 'name="speak_lang"' in html
    assert "Pick the language you will speak" in html
    assert "Mixing in English words is fine" in html


def test_live_page_has_picker_with_shop_selected(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client, "en")
    html = client.get(f"/e/{token}/live").text
    assert 'name="speak_lang"' in html
    assert 'value="en" selected' in html


def test_migration_adds_speak_lang(tmp_path):
    data = tmp_path / "old"
    data.mkdir()
    raw = sqlite3.connect(data / "marketmate.db")
    raw.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER NOT NULL, kind TEXT NOT NULL,"
        " status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',"
        " cost REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    raw.commit()
    raw.close()
    conn = db.connect(data)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert "speak_lang" in cols
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+911234567890", area="A",
            language="en", currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")
        assert db.session_speak_lang(conn, session_id) is None
        db.set_session_speak_lang(conn, session_id, "ta")
        assert db.session_speak_lang(conn, session_id) == "ta"
    finally:
        conn.close()
