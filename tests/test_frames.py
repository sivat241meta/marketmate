import json
from pathlib import Path

from PIL import Image

from app.config import load_settings
from app.costs import CostLedger
from app.meta.transcribe import transcript_from_json
from app.models import DraftItem, Frame, Proof, Turn
from app.pipeline.frames import frames_for_window, item_window, pick_best_frame


def make_frames(tmp_path):
    frames = []
    for t in range(0, 10001, 500):
        path = tmp_path / f"f_{t}.jpg"
        Image.new("RGB", (64, 48), (10, 100, 10)).save(path, "JPEG")
        frames.append(Frame(path, t))
    return frames


def make_item(name_en="tomato"):
    return DraftItem(
        name_spoken=name_en, name_ta=name_en, name_en=name_en, variety=None,
        price_lines=[], qty=None, qty_unit=None,
        proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0),
    )


def make_ctx(tmp_path):
    return (CostLedger(tmp_path / "c.db", 100.0),
            load_settings({"MODEL_API_KEY": "k"}))


def fake_by_name(messages, **kwargs):
    content = messages[-1]["content"]
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    if "tomato" in content:
        return {"best_index": 0, "matches": True}
    if "onion" in content:
        return {"best_index": 2, "matches": True}
    return {"best_index": 0, "matches": True}


def test_window_bounds(tmp_path):
    chosen = frames_for_window(make_frames(tmp_path), 3000, 4000)
    assert len(chosen) == 4
    assert all(2500 <= f.t_ms <= 5500 for f in chosen)


def test_two_items_same_turn_get_own_frames(monkeypatch, tmp_path):
    monkeypatch.setattr("app.pipeline.frames.chat_json", fake_by_name)
    ledger, settings = make_ctx(tmp_path)
    cands = make_frames(tmp_path)[:3]
    first = pick_best_frame(make_item("tomato"), cands, ledger=ledger, settings=settings)
    second = pick_best_frame(make_item("onion"), cands, ledger=ledger, settings=settings)
    assert first[0] != second[0]


def test_best_frame_uses_low_reasoning(monkeypatch, tmp_path):
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["kwargs"] = kwargs
        return {"best_index": 0, "matches": True}

    monkeypatch.setattr("app.pipeline.frames.chat_json", fake_chat_json)
    ledger, settings = make_ctx(tmp_path)
    pick_best_frame(make_item("tomato"), make_frames(tmp_path)[:3],
                    ledger=ledger, settings=settings)
    assert seen["kwargs"]["reasoning_effort"] == "low"


def test_mismatch_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.pipeline.frames.chat_json",
        lambda messages, **kwargs: {"best_index": 0, "matches": False})
    ledger, settings = make_ctx(tmp_path)
    assert pick_best_frame(make_item("tomato"), make_frames(tmp_path)[:3],
                           ledger=ledger, settings=settings)[1] is False


def live_turns():
    data = json.loads(Path("tests/fixtures/transcribe_live_mixed.json").read_text())
    return transcript_from_json(data).turns


def live_item(quote):
    return DraftItem(
        name_spoken="x", name_ta="x", name_en="potato", variety=None,
        price_lines=[], qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[1], start_ms=0, end_ms=0),
    )


def test_item_window_long_turn_estimates_moment():
    turns = live_turns()
    assert turns[0].end_ms - turns[0].start_ms > 8000
    potato = live_item("urulaikizhangu kilo thirty rupees இல்ல இல்ல thirty five rupees")
    start, end = item_window(potato, turns)
    assert start <= 20900 and end >= 14800
    tomato = live_item("Bangalore thakkali kilo eighteen rupees")
    _, tomato_end = item_window(tomato, turns)
    assert tomato_end < 9000


def test_item_window_short_turn_returns_span():
    turns = [Turn(id=1, start_ms=0, end_ms=3000, text="thakkali kilo 18")]
    assert item_window(live_item("thakkali kilo 18"), turns) == (0, 3000)
