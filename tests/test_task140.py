"""Task 140: the photo step runs in parallel; the bubble waits on progress.

1. Per-item photo work (plus the per-item frame picks and checks) fans out
   over a bounded pool (PHOTO_WORKERS, default 6); rival SAM cross-checks
   inside an item run concurrently. Results equal the sequential run.
2. At most PHOTO_WORKERS Meta calls are ever in flight; HTTP 429 retries
   with back-off; the ledger stays correct; progress reports
   "item 7 of 21" and a timing row lands on the AI calls page.
3. composer.js keeps polling while the status JSON shows progress and only
   shows "Still working" after 3 minutes with no change or 20 minutes total.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.meta.sam import SamInstance
from app.models import Box, Frame, Transcript, Turn
from app.parallel import (
    api_slot,
    backoff_seconds,
    map_parallel_ordered,
    photo_workers,
)
from app.pipeline.run import process_turns
from app.web.main import create_app

ROOT = Path(__file__).resolve().parent.parent
COMPOSER_JS = ROOT / "app" / "web" / "static" / "composer.js"
_META_URL = "https://api.meta.ai/v1/chat/completions"
_SAM_URL = "https://api.meta.ai/v1/responses"

NAMES = ["tomato", "onion", "potato", "carrot", "beans", "banana"]
PRICES = [18, 19, 20, 21, 22, 23]


# --- 1. pool size ------------------------------------------------------------


def test_photo_workers_default_and_env(monkeypatch):
    monkeypatch.delenv("PHOTO_WORKERS", raising=False)
    assert photo_workers() == 6
    monkeypatch.setenv("PHOTO_WORKERS", "3")
    assert photo_workers() == 3
    monkeypatch.setenv("PHOTO_WORKERS", " 12 ")
    assert photo_workers() == 12
    for bad in ("", "0", "-2", "abc", "2.5"):
        monkeypatch.setenv("PHOTO_WORKERS", bad)
        assert photo_workers() == 6


def test_pool_size_bounds_concurrency():
    current = 0
    peak = 0
    lock = threading.Lock()

    def work(_):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.02)
        with lock:
            current -= 1

    results = map_parallel_ordered(work, list(range(10)), workers=2)
    assert results == [None] * 10
    assert peak <= 2
    assert peak >= 2  # sanity: the work really overlapped


def test_map_parallel_ordered_keeps_order_and_counts():
    import random

    seen: list[tuple[int, int]] = []

    def work(entry):
        time.sleep(random.uniform(0, 0.01))
        return entry * entry

    results = map_parallel_ordered(
        work, list(range(8)), workers=4,
        on_done=lambda done, total: seen.append((done, total)))
    assert results == [n * n for n in range(8)]
    assert sorted(seen) == [(n + 1, 8) for n in range(8)]


def test_map_parallel_ordered_empty_and_errors():
    assert map_parallel_ordered(lambda x: x, []) == []

    def boom(entry):
        if entry == 1:
            raise ValueError("nope")
        return entry

    with pytest.raises(ValueError, match="nope"):
        map_parallel_ordered(boom, [0, 1, 2], workers=2)


def test_api_in_flight_never_exceeds_workers(monkeypatch):
    monkeypatch.setenv("PHOTO_WORKERS", "3")
    current = 0
    peak = 0
    lock = threading.Lock()

    def work(_):
        nonlocal current, peak
        with api_slot():
            with lock:
                current += 1
                peak = max(peak, current)
            time.sleep(0.05)
            with lock:
                current -= 1

    map_parallel_ordered(work, list(range(12)), workers=12)
    assert peak <= 3
    assert peak >= 2  # sanity: the work really overlapped


def test_backoff_grows_and_caps():
    assert backoff_seconds(0) == 1.0
    assert backoff_seconds(1) == 2.0
    assert backoff_seconds(2) == 4.0
    assert backoff_seconds(3) == 8.0
    assert backoff_seconds(100) == 30.0


def test_ledger_add_is_thread_safe(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    ledger.bind(shop_id=1, session_id=2)
    map_parallel_ordered(
        lambda i: ledger.add("meta", "m", 0.001, f"r{i}", step="s"),
        list(range(100)), workers=8)
    assert len(ledger.rows_for_shop(1, limit=1000)) == 100


# --- 2. 429 back-off ----------------------------------------------------------


def _spark_body(content: str) -> dict:
    import json

    body = json.loads(
        Path("tests/fixtures/spark_text.json").read_text())
    body["choices"][0]["message"]["content"] = content
    return body


@pytest.fixture
def ledger(tmp_path):
    bound = CostLedger(tmp_path / "c.db", 100.0)
    bound.bind(shop_id=1, session_id=2)
    return bound


@pytest.fixture
def settings():
    return load_settings({"MODEL_API_KEY": "k"})


def _photo_image(tmp_path) -> Path:
    image = tmp_path / "f.jpg"
    image.write_bytes(b"fakejpeg")
    return image


def test_spark_429_retries_then_succeeds(respx_mock, ledger, settings,
                                         monkeypatch):
    from app.meta.spark import chat_json

    sleeps: list[float] = []
    monkeypatch.setattr("app.parallel._sleep", sleeps.append)
    route = respx_mock.post(_META_URL).mock(side_effect=[
        Response(429, json={"error": {"message": "slow down"}}),
        Response(200, json=_spark_body('{"a":1}')),
    ])
    data = chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings,
                     step="extract prices")
    assert data == {"a": 1}
    assert route.call_count == 2
    assert sleeps == [1.0]
    rows = ledger.rows_for_shop(1, session_id=2)
    assert len(rows) == 1  # the retried 429 logs one row, not two
    assert (rows[0]["step"], rows[0]["shop_id"], rows[0]["session_id"],
            rows[0]["ok"]) == ("extract prices", 1, 2, 1)


def test_spark_429_gives_up_after_retries(respx_mock, ledger, settings,
                                          monkeypatch):
    from app.meta.spark import SparkError, chat_json

    sleeps: list[float] = []
    monkeypatch.setattr("app.parallel._sleep", sleeps.append)
    route = respx_mock.post(_META_URL).mock(
        return_value=Response(429, json={"error": {"message": "slow"}}))
    with pytest.raises(SparkError):
        chat_json([{"role": "user", "content": "hi"}],
                  ledger=ledger, settings=settings)
    assert route.call_count == 5  # 1 try + 4 retries
    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert ledger.rows_for_shop(1, session_id=2)[0]["ok"] == 0


def _sam_sse() -> str:
    return ('data: {"type": "response.output_text.delta",'
            ' "delta": "<|box;x1=10;y1=20;x2=110;y2=220;w=640;h=480|>"}\n\n'
            'data: {"type": "response.completed", "response": {}}\n\n')


def test_sam_429_retries_then_succeeds(respx_mock, ledger, settings,
                                       monkeypatch, tmp_path):
    from app.meta.sam import find_boxes

    sleeps: list[float] = []
    monkeypatch.setattr("app.parallel._sleep", sleeps.append)
    route = respx_mock.post(_SAM_URL).mock(side_effect=[
        Response(429, text="slow down"),
        Response(200, text=_sam_sse()),
    ])
    boxes = find_boxes(_photo_image(tmp_path), "tomato",
                       ledger=ledger, settings=settings,
                       step="cut-out mask")
    assert boxes == [Box(10, 20, 110, 220, 640, 480, None)]
    assert route.call_count == 2
    assert sleeps == [1.0]
    rows = ledger.rows_for_shop(1, session_id=2)
    assert len(rows) == 1
    assert (rows[0]["step"], rows[0]["shop_id"], rows[0]["session_id"],
            rows[0]["ok"]) == ("cut-out mask", 1, 2, 1)


def test_sam_429_gives_up_after_retries(respx_mock, ledger, settings,
                                        monkeypatch, tmp_path):
    from app.meta.sam import SamError, find_boxes

    sleeps: list[float] = []
    monkeypatch.setattr("app.parallel._sleep", sleeps.append)
    route = respx_mock.post(_SAM_URL).mock(
        return_value=Response(429, text="slow"))
    with pytest.raises(SamError):
        find_boxes(_photo_image(tmp_path), "tomato",
                   ledger=ledger, settings=settings)
    assert route.call_count == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


# --- 3. parallel photo step: equal results, real speed-up --------------------


def _photo_transcript() -> Transcript:
    text = " ".join(f"{name} kilo {price}"
                    for name, price in zip(NAMES, PRICES))
    return Transcript(text=text, duration_ms=2000, turns=[
        Turn(id=1, start_ms=0, end_ms=2000, text=text)])


def _photo_items_payload() -> dict:
    text = _photo_transcript().text
    return {"items": [{
        "name_spoken": name, "name_en": name, "variety": None,
        "prices": [{"said": f"kilo {price}", "price": price,
                    "per_amount": 1, "unit": "kg"}],
        "range_said": False, "qty_said": None, "qty": None,
        "qty_unit": None, "turn_ids": [1], "quote": text,
    } for name, price in zip(NAMES, PRICES)]}


def _install_photo_fakes(monkeypatch, inst_sleep=0.4, face_sleep=0.1):
    """Fake Meta clients with sleeps; every item finds one whole instance."""

    def fake_instances(image, noun, **kwargs):
        time.sleep(inst_sleep)
        return [SamInstance(Box(40, 40, 200, 200, 320, 240, 0.9), None)]

    def fake_faces(image, noun, **kwargs):
        time.sleep(face_sleep)
        return []

    def fake_clip(wav, start_ms, end_ms, out, pad_ms=300):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-clip")
        return out

    monkeypatch.setattr("app.pipeline.extract.chat_json",
                        lambda messages, **kwargs: _photo_items_payload())
    monkeypatch.setattr("app.pipeline.frames.chat_json",
                        lambda messages, **kwargs: {"best_index": 0,
                                                   "matches": True})
    monkeypatch.setattr("app.pipeline.photos.chat_json",
                        lambda messages, **kwargs: {})
    monkeypatch.setattr("app.pipeline.photos.find_instances", fake_instances)
    monkeypatch.setattr("app.pipeline.photos.find_boxes", fake_faces)
    monkeypatch.setattr("app.pipeline.run.cut_audio_clip", fake_clip)


def _photo_frames(directory: Path) -> list[Frame]:
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for pos in range(4):
        path = directory / f"pf{pos}.jpg"
        Image.new("RGB", (320, 240), (100 + pos * 20, 80, 60)).save(path)
        frames.append(Frame(path=path, t_ms=pos * 500))
    return frames


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "db")
    yield connection
    connection.close()


def _run_photo_session(conn, tmp_path, settings, shop_id, tag: str):
    session_id = db.create_session(conn, shop_id, "video")
    session_ledger = CostLedger(tmp_path / f"c{tag}.db", 100.0)
    session_ledger.bind(shop_id=shop_id, session_id=session_id)
    transcript = _photo_transcript()
    wav = tmp_path / f"a{tag}.wav"
    wav.write_bytes(b"fake-wav")
    items = process_turns(
        conn, session_id, transcript.turns, None, wav,
        settings=settings, ledger=session_ledger, language="ta",
        all_frames=_photo_frames(tmp_path / f"fr{tag}"), video=None)
    return session_id, items, session_ledger


def _snapshot(items) -> list[tuple]:
    rows = []
    for item in items:
        photo = Path(item.photo).name.split("_", 1)[1] if item.photo else None
        rows.append((
            item.name_en, photo, len(item.photo_candidates),
            Path(item.proof.frame).name if item.proof.frame else None,
            Path(item.proof.audio_clip).name
            if item.proof.audio_clip else None,
            [(flag.code, flag.field, flag.blocking) for flag in item.flags],
        ))
    return rows


def test_photo_step_parallel_matches_sequential(conn, tmp_path, monkeypatch):
    _install_photo_fakes(monkeypatch)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    shop_id, _, _ = db.create_shop(
        conn, name="Shop", phone="+914400000000", area="A", language="ta",
        currency="INR", shop_type="vegetable")
    calls: list[tuple] = []
    original = db.set_stage

    def recording(connection, session_id, key, detail=None):
        calls.append((session_id, key, detail))
        return original(connection, session_id, key, detail=detail)

    monkeypatch.setattr("app.db.set_stage", recording)

    monkeypatch.setenv("PHOTO_WORKERS", "1")
    started = perf_counter()
    seq_id, seq_items, _ = _run_photo_session(
        conn, tmp_path, settings, shop_id, "seq")
    seq_s = perf_counter() - started

    monkeypatch.setenv("PHOTO_WORKERS", "6")
    started = perf_counter()
    par_id, par_items, par_ledger = _run_photo_session(
        conn, tmp_path, settings, shop_id, "par")
    par_s = perf_counter() - started

    assert seq_s >= 4.0  # sanity: the fake sleeps really ran
    assert seq_s / par_s >= 3.0  # the required speed-up with 6 workers
    assert [item.name_en for item in par_items] == NAMES
    assert _snapshot(par_items) == _snapshot(seq_items)

    par_details = {detail for session, key, detail in calls
                   if session == par_id and key == "photos"}
    assert {f"item {n} of 6" for n in range(1, 7)} <= par_details

    timing = [row for row in par_ledger.rows_for_shop(shop_id)
              if row["model"] == "timing"]
    assert len(timing) == 1
    assert timing[0]["step"] == "photos"
    assert timing[0]["session_id"] == par_id
    assert timing[0]["usd"] == 0.0
    assert re.fullmatch(r"6 items in [\d.]+ s with 6 workers",
                        timing[0]["summary"] or "")
    assert seq_id != par_id


def test_rival_cross_checks_run_concurrently(tmp_path, monkeypatch):
    """Inside one item, the two rival SAM queries overlap (Task 140)."""
    import app.pipeline.photos as photos_mod

    frames = _photo_frames(tmp_path / "fr")
    current = 0
    peak = 0
    lock = threading.Lock()

    def fake_instances(image, noun, **kwargs):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        try:
            time.sleep(0.5)
            return [SamInstance(Box(40, 40, 200, 200, 320, 240, 0.9), None)]
        finally:
            with lock:
                current -= 1

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kwargs: [])
    monkeypatch.setattr(photos_mod, "chat_json",
                        lambda messages, **kwargs: {})
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    names = ["tomato", "onion", "potato"]
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s9_0",
        ledger=ledger, settings=settings, session_items=names,
        picked_frames=[(name, frames[0]) for name in names],
        noun_cache={name: name for name in names}, category_cache={})
    assert len(saved) == 1  # the crop fallback, as in the sequential run
    assert peak >= 2  # the two rival queries overlapped


def test_timing_row_reaches_ai_calls_page(tmp_path, monkeypatch):
    """The photo timing line shows on the Meta AI calls page."""
    from app.web.i18n import t_for
    from app.web.seller import _ai_row_view

    ledger = CostLedger(tmp_path / "c.db", 100.0)
    ledger.bind(shop_id=1, session_id=7)
    ledger.add("local", "timing", 0.0, step="photos", ok=1,
               summary="21 items in 38.2 s with 6 workers")
    rows = ledger.rows_for_shop(1, session_id=7)
    assert len(rows) == 1
    view = _ai_row_view(rows[0], t_for("en"))
    assert view["summary"] == "21 items in 38.2 s with 6 workers"
    assert view["step"] == "photos"
    assert view["kind"] == "other"
    stats = ledger.today_stats(1)
    assert stats["cost_usd"] == 0.0
    assert stats["avg_latency_ms"] is None  # timing rows skew no average


# --- 4. status JSON counter --------------------------------------------------


def _client_with_token(tmp_path):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    app = create_app(settings)
    client = TestClient(app, follow_redirects=False)
    response = client.post("/new", data={
        "name": "Kannan Store", "phone": "+914400000000", "area": "Koyambedu",
        "language": "en", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return client, response.headers["location"]


def test_status_json_carries_photo_counter(tmp_path):
    client, location = _client_with_token(tmp_path)
    connection = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(connection, location.split("/e/")[1])
        session_id = db.create_session(connection, shop["id"], "video")
        db.set_session_status(connection, session_id, "processing", "working")
        db.set_stage(connection, session_id, "photos",
                     detail="item 7 of 21")
    finally:
        connection.close()
    payload = client.get(f"{location}/s/{session_id}/status").json()
    active = next(step for step in payload["steps"]
                  if step["state"] == "active")
    assert active["key"] == "photos"
    assert active["label"] == "Picking a photo for each item (7 of 21)"
    assert payload["detail"] == "item 7 of 21"


def test_status_json_leaves_other_details_alone(tmp_path):
    client, location = _client_with_token(tmp_path)
    connection = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(connection, location.split("/e/")[1])
        session_id = db.create_session(connection, shop["id"], "video")
        db.set_stage(connection, session_id, "listening", detail="hearing you")
    finally:
        connection.close()
    payload = client.get(f"{location}/s/{session_id}/status").json()
    active = next(step for step in payload["steps"]
                  if step["state"] == "active")
    assert active["label"] == "Listening to your prices"


# --- 5. composer keeps polling while progress changes ------------------------


def test_composer_poll140_node_tests():
    node = shutil.which("node")
    assert node, "node is required"
    result = subprocess.run(["node", "tests/js/composer_poll140.test.mjs"],
                            cwd=ROOT, check=False, capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_composer_checks_syntax():
    node = shutil.which("node")
    assert node, "node is required"
    result = subprocess.run(["node", "--check", str(COMPOSER_JS)],
                            check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_composer_stall_and_budget_wiring():
    source = COMPOSER_JS.read_text()
    stall = re.search(r"var POLL_STALL_MS = ([^;]+);", source)
    assert stall, "POLL_STALL_MS constant"
    assert eval(stall.group(1), {"__builtins__": {}}) == 3 * 60 * 1000
    budget = re.search(r"var POLL_BUDGET_MS = ([^;]+);", source)
    assert budget, "POLL_BUDGET_MS constant"
    assert eval(budget.group(1), {"__builtins__": {}}) == 20 * 60 * 1000
    poll = source.split("function pollStatus")[1].split("function postForm")[0]
    assert "pollElapsedMs(count) >= POLL_BUDGET_MS" in poll  # 20 min total
    assert "pollProgressKey(data)" in poll  # progress restarts the clock
    assert "pollStalled(" in poll  # 3 min with no change gives up
    assert "tracker" in poll
    assert "showOpenLink(ctx, bubble, finalUrl)" in poll
    assert "setActiveLabel(bubble, label)" in poll  # real step label stays
    hooks = source.split("initComposer.testHooks")[1]
    assert "pollProgressKey" in hooks
    assert "pollStalled" in hooks
    assert "POLL_STALL_MS" in hooks


def test_ledger_threads_share_one_db_file(tmp_path):
    """Parallel workers bind once; rows keep shop/session/step fields."""
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    ledger.bind(shop_id=3, session_id=9)

    def work(entry):
        ledger.add("meta", "sam-3.1", 0.0025, f"target:{entry}",
                   step="cut-out mask")

    map_parallel_ordered(work, list(range(20)), workers=6)
    with sqlite3.connect(tmp_path / "c.db") as conn:
        rows = conn.execute(
            "SELECT shop_id, session_id, step, COUNT(*) FROM costs"
            " GROUP BY shop_id, session_id, step").fetchall()
    assert rows == [(3, 9, "cut-out mask", 20)]
