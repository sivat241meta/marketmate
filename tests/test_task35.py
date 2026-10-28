"""Task 35: live price capture (realtime relay, captions, camera frames)."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import wave

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings


def _settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})


def _make_ledger(tmp_path, cap=100.0):
    from app.costs import CostLedger

    return CostLedger(tmp_path / "costs.db", cap)


class _FakeWS:
    def __init__(self, to_recv):
        self.sent = []
        self._recv = list(to_recv)
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self._recv:
            raise _FakeClosed(1000)
        item = self._recv.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True


class _FakeClosed(Exception):
    def __init__(self, code=1000):
        super().__init__(f"closed {code}")
        self.code = code


def test_realtime_handshake_fields_ta(tmp_path):
    from app.meta.realtime import REALTIME_URL, RealtimeASR
    from app.pipeline.names import keywords_for

    async def go():
        seen = {}

        async def fake_connect(url):
            seen["url"] = url
            return _FakeWS([json.dumps({"sessionId": "s1"})])

        settings = load_settings({"MODEL_API_KEY": "secret-key-xyz",
                                  "DATA_DIR": str(tmp_path)})
        ws_holder = {}
        orig = fake_connect

        async def cap_connect(url):
            ws = await orig(url)
            ws_holder["ws"] = ws
            return ws

        rt = RealtimeASR(settings=settings, ledger=_make_ledger(tmp_path),
                         language="ta", connect=cap_connect)
        await rt.start()
        assert seen["url"] == REALTIME_URL
        assert len(ws_holder["ws"].sent) == 1
        hs = json.loads(ws_holder["ws"].sent[0])
        assert hs["authorization"]["accessToken"] == "Bearer secret-key-xyz"
        assert hs["audioEncoding"] == "PCM_24KHZ"
        assert hs["model"] == "muse-voice-transcribe-1.0"
        assert hs["mode"] == "ENDPOINTING"
        assert hs["partialMode"] == "CUMULATIVE"
        assert hs["emitAudioProgress"] is False
        assert hs["languageBias"] == ["Tamil", "English"]
        assert hs["keywords"] == keywords_for("ta")
        await rt.close()

    asyncio.run(go())


def test_realtime_language_bias_variants(tmp_path):
    from app.meta.realtime import RealtimeASR
    from app.pipeline.names import keywords_for

    async def bias_for(lang):
        holder = {}

        async def fake_connect(url):
            ws = _FakeWS([json.dumps({"sessionId": "s"})])
            holder["ws"] = ws
            return ws

        settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path)})
        rt = RealtimeASR(settings=settings, ledger=_make_ledger(tmp_path),
                         language=lang, connect=fake_connect)
        await rt.start()
        hs = json.loads(holder["ws"].sent[0])
        await rt.close()
        return hs["languageBias"], hs["keywords"]

    async def go():
        bias, kw = await bias_for("hi")
        assert bias == ["Hindi", "English"]
        assert kw == keywords_for("hi")
        bias, _ = await bias_for("fr")
        assert bias == ["French", "English"]
        bias, _ = await bias_for("en")
        assert bias == ["English"]

    asyncio.run(go())


def test_realtime_key_never_in_logs(tmp_path, caplog):
    from app.meta.realtime import RealtimeASR, RealtimeError

    async def go():
        async def fake_connect(url):
            return _FakeWS([json.dumps({"type": "error", "message": "bad"})])

        settings = load_settings({"MODEL_API_KEY": "super-secret-12345",
                                  "DATA_DIR": str(tmp_path)})
        rt = RealtimeASR(settings=settings, ledger=_make_ledger(tmp_path),
                         language="ta", connect=fake_connect)
        with pytest.raises(RealtimeError):
            await rt.start()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    assert "super-secret-12345" not in caplog.text


def test_realtime_error_event_raises(tmp_path):
    from app.meta.realtime import RealtimeASR, RealtimeError

    async def go():
        async def fake_connect(url):
            return _FakeWS([
                json.dumps({"sessionId": "s1"}),
                json.dumps({"type": "speechStart", "turnId": 0}),
                json.dumps({"type": "error", "message": "quota gone"}),
            ])

        settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path)})
        rt = RealtimeASR(settings=settings, ledger=_make_ledger(tmp_path),
                         language="ta", connect=fake_connect)
        await rt.start()
        with pytest.raises(RealtimeError):
            async for _ in rt.events():
                pass
        await rt.close()

    asyncio.run(go())


def test_realtime_cost_logged_by_whole_seconds(tmp_path):
    from app.meta.realtime import RealtimeASR

    async def go():
        async def fake_connect(url):
            return _FakeWS([json.dumps({"sessionId": "s1"})])

        settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path)})
        ledger = _make_ledger(tmp_path)
        rt = RealtimeASR(settings=settings, ledger=ledger, language="ta",
                         connect=fake_connect)
        await rt.start()
        await rt.send_audio(b"\x00" * 48000 * 3)
        await rt.send_audio(b"\x00" * 1000)
        await rt.end()
        await rt.close()
        assert ledger.today_usd("meta") == pytest.approx(3 / 3600 * 0.18)

    asyncio.run(go())


def test_incremental_scheduler_single_flight_and_rerun():
    from app.web.live import IncrementalRunner

    async def go():
        running = 0
        max_running = 0
        runs = 0

        async def work():
            nonlocal running, max_running, runs
            running += 1
            max_running = max(max_running, running)
            runs += 1
            await asyncio.sleep(0.05)
            running -= 1

        runner = IncrementalRunner(work)
        t1 = asyncio.create_task(runner.notify())
        await asyncio.sleep(0.01)
        t2 = asyncio.create_task(runner.notify())
        t3 = asyncio.create_task(runner.notify())
        await asyncio.gather(t1, t2, t3)
        await asyncio.sleep(0.2)
        assert max_running == 1
        assert runs == 2

    asyncio.run(go())


JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AK//Z"
)


def _tiny_jpeg_b64():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


SCRIPTED_META = [
    {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
    {"type": "transcript", "transcript": "இது மாதுளை கிலோ"},
    {"type": "transcript",
     "transcript": "இது மாதுளை கிலோ எண்பத்தேழு ரூபா அது சாத்துக்குடி"},
    {"type": "speechEnd", "turnId": 0},
    {"type": "speechComplete", "turnId": 0,
     "transcript": "இது மாதுளை கிலோ எண்பத்தேழு ரூபா அது சாத்துக்குடி கிலோ முப்பத்தி ஆறு ரூபா",
     "startMs": 0, "endMs": 4000},
    {"type": "speechStart", "turnId": 1, "audioProcessedMs": 4100},
    {"type": "speechComplete", "turnId": 1, "transcript": "இது வாழைத்தண்டு",
     "startMs": 4000, "endMs": 6000},
    {"type": "speechStart", "turnId": 2, "audioProcessedMs": 6100},
    {"type": "speechComplete", "turnId": 2, "transcript": "கிலோ",
     "startMs": 6000, "endMs": 7000},
    {"type": "speechStart", "turnId": 3, "audioProcessedMs": 7100},
    {"type": "speechComplete", "turnId": 3, "transcript": "முப்பது ரூபா",
     "startMs": 7000, "endMs": 9000},
]


class _FakeRealtime:
    def __init__(self, *a, **k):
        self.audio = b""
        self.ended = False

    async def start(self):
        return "fake-session"

    async def send_audio(self, data: bytes):
        self.audio += bytes(data)

    async def end(self):
        self.ended = True

    async def events(self):
        for ev in SCRIPTED_META:
            await asyncio.sleep(0.005)
            yield dict(ev)

    async def close(self):
        pass


def _client(tmp_path):
    from app.web.main import create_app

    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    resp = client.post("/new", data={
        "name": "Live Shop", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303)
    token = resp.headers["location"].split("/e/")[1]
    return client, token, settings


def test_relay_happy_path(tmp_path, monkeypatch):
    from decimal import Decimal

    from app.models import DraftItem, PriceLine, Proof

    client, token, settings = _client(tmp_path)
    monkeypatch.setattr("app.web.live.RealtimeASR", _FakeRealtime)

    def fake_extract(transcript, *, ledger, settings, language="ta", progress=None):
        texts = " ".join(t.text for t in transcript.turns)
        items = []
        if "மாதுளை" in texts:
            items.append(DraftItem(
                name_spoken="mathulai", name_local="மாதுளை", name_en="pomegranate",
                variety=None,
                price_lines=[PriceLine(Decimal(87), Decimal(1), "kg", "kilo 87")],
                qty=None, qty_unit=None,
                proof=Proof(quote="இது மாதுளை கிலோ எண்பத்தேழு ரூபா",
                            turn_ids=[1], start_ms=0, end_ms=4000)))
        if "சாத்துக்குடி" in texts:
            items.append(DraftItem(
                name_spoken="sathukudi", name_local="சாத்துக்குடி", name_en="sweet lime",
                variety=None,
                price_lines=[PriceLine(Decimal(999), Decimal(1), "kg", "kilo 999")],
                qty=None, qty_unit=None,
                proof=Proof(quote="அது சாத்துக்குடி கிலோ முப்பத்தி ஆறு ரூபா",
                            turn_ids=[1], start_ms=0, end_ms=4000)))
        if "வாழைத்தண்டு" in texts and "முப்பது" in texts:
            items.append(DraftItem(
                name_spoken="vazhaithandu", name_local="வாழைத்தண்டு",
                name_en="banana stem", variety=None,
                price_lines=[PriceLine(Decimal(30), Decimal(1), "kg", "kilo 30")],
                qty=None, qty_unit=None,
                proof=Proof(quote="இது வாழைத்தண்டு கிலோ முப்பது ரூபா",
                            turn_ids=[2, 3, 4], start_ms=4000, end_ms=9000)))
        return items

    monkeypatch.setattr("app.web.live.extract_items", fake_extract)
    monkeypatch.setattr("app.pipeline.run.extract_items", fake_extract)

    from pathlib import Path

    def fake_make_photo(frame, noun, out, *, ledger, settings):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        try:
            data = Path(str(frame.path)).read_bytes()
        except OSError:
            data = base64.b64decode(_tiny_jpeg_b64())
        Path(out).write_bytes(data)
        return Path(out)

    monkeypatch.setattr("app.pipeline.run.make_photo", fake_make_photo)
    monkeypatch.setattr("app.web.live.make_photo", fake_make_photo, raising=False)

    jpeg = _tiny_jpeg_b64()
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "prices"}))
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        session_id = ready["session_id"]
        ws.send_bytes(b"\x00\x01" * 2400)
        ws.send_text(json.dumps({"type": "frame", "turn": 1, "at": "start", "jpeg": jpeg}))
        ws.send_text(json.dumps({"type": "frame", "turn": 1, "at": "end", "jpeg": jpeg}))
        ws.send_bytes(b"\x02\x03" * 2400)
        for n in (2, 3, 4):
            ws.send_text(json.dumps({"type": "frame", "turn": n, "at": "start", "jpeg": jpeg}))
            ws.send_text(json.dumps({"type": "frame", "turn": n, "at": "end", "jpeg": jpeg}))

        seen = {"partial": 0, "turn": [], "items": [], "done": None, "speech_start": 0}
        ws.send_text(json.dumps({"type": "stop"}))
        from starlette.websockets import WebSocketDisconnect

        try:
            while True:
                raw = ws.receive_text()
                msg = json.loads(raw)
                if msg["type"] == "partial":
                    seen["partial"] += 1
                elif msg["type"] == "turn":
                    seen["turn"].append(msg)
                elif msg["type"] == "items":
                    seen["items"].append(msg)
                elif msg["type"] == "speech_start":
                    seen["speech_start"] += 1
                elif msg["type"] == "done":
                    seen["done"] = msg
                    break
                elif msg["type"] == "error":
                    raise AssertionError(f"relay error: {msg}")
        except WebSocketDisconnect:
            pass
        assert seen["partial"] >= 1, "expected partial captions"
        assert len(seen["turn"]) == 4, f"turns: {seen['turn']}"
        assert seen["items"], "expected at least one items event"
        last = seen["items"][-1]["items"]
        by_key = {c["key"]: c for c in last}
        assert "pomegranate|" in by_key or "pomegranate" in str(by_key)
        for c in last:
            assert c.get("key")
            assert "name_local" in c and "name_en" in c
            assert "quote" in c
        sweet = [c for c in last if c["name_en"] == "sweet lime"]
        assert sweet, f"missing sweet lime in {last}"
        codes = [f["code"] for f in sweet[0]["flags"]]
        assert "NOT_HEARD" in codes, f"flags: {sweet[0]['flags']}"
        assert any(c.get("photo_url") for c in last), f"no photo urls: {last}"
        assert seen["done"] and seen["done"]["review_url"].endswith(
            f"/e/{token}/s/{session_id}")

    data_dir = settings.data_dir
    import pathlib

    wav = pathlib.Path(data_dir) / "sessions" / str(session_id) / "audio.wav"
    assert wav.is_file()
    with wave.open(str(wav), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getnframes() > 0
    frames_dir = pathlib.Path(data_dir) / "sessions" / str(session_id) / "frames"
    assert (frames_dir / "turn1_start.jpg").is_file()
    assert (frames_dir / "turn1_end.jpg").is_file()
    conn = db.connect(pathlib.Path(data_dir))
    try:
        row = conn.execute("SELECT status FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        assert row["status"] == "review"
        drafts = db.load_drafts(conn, session_id)
        assert len(drafts) == 3
        assert all(d.photo for d in drafts)
        assert all(d.proof.audio_clip for d in drafts)
    finally:
        conn.close()


def test_relay_bad_token_rejected(tmp_path):
    from app.web.main import create_app

    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/e/badtoken123/live/ws"
    ) as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "prices"}))
        ws.receive_text()


def test_live_html_renders_with_fallback_and_no_inline_styles(tmp_path):
    from app.web.main import create_app

    settings = _settings(tmp_path)
    app = create_app(settings)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("ui_lang", "en")
    resp = c.post("/new", data={
        "name": "S", "phone": "+914400000000", "area": "A",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    tok = resp.headers["location"].split("/e/")[1]
    html = c.get(f"/e/{tok}/live").text
    assert "Upload a video instead" in html or "upload" in html.lower()
    assert "live.js" in html
    assert "pcm-worklet.js" in html or "pcm-worklet" in html
    assert "style=" not in html
    assert "<style" not in html


def test_dashboard_shows_go_live(tmp_path):
    from app.web.main import create_app

    settings = _settings(tmp_path)
    app = create_app(settings)
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("ui_lang", "en")
    resp = c.post("/new", data={
        "name": "S", "phone": "+914400000000", "area": "A",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    seller_url = resp.headers["location"]
    html = c.get(seller_url).text
    assert "Go live" in html
    assert "/live" in html
