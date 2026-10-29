"""Task 72: whole-object shape test (no half fruit) and a verified generic
fallback when SAM misses the item noun.

No network: SAM and Spark are faked; the SAM wire text is the saved
Task 65 fixture (mask text only, no shop photos).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PIL import Image

from app.config import SAM_MODEL, load_settings
from app.costs import CostLedger
from app.meta.sam import SAM_USD_PER_IMAGE, SamInstance, SamMask, parse_sam_response
from app.models import Box, Frame
from app.pipeline import photos as photos_mod

FIXTURE = Path("tests/fixtures/sam/sam_pomegranate.txt")
FRAME_SIZE = (576, 585)


def make_ledger(tmp_path):
    return CostLedger(tmp_path / "c.db", 100.0)


def make_settings():
    return load_settings({"MODEL_API_KEY": "k"})


def make_inst(x1, y1, x2, y2, conf, width=320, height=240, raster=None):
    box = Box(x1, y1, x2, y2, width, height, conf)
    if raster is None:
        return SamInstance(box=box, mask=None)
    mask = SamMask(width=x2 - x1 + 1, height=y2 - y1 + 1,
                   encoding="one_bit", payload="!x", confidence=conf)
    mask._raster = bytes(raster)
    return SamInstance(box=box, mask=mask)


def full_raster(x1, y1, x2, y2):
    return bytes([1]) * ((x2 - x1 + 1) * (y2 - y1 + 1))


def l_raster(size, missing):
    """Square side ``size`` with a ``missing``-side corner cut out."""
    raster = bytearray([1]) * (size * size)
    for y in range(missing):
        for x in range(size - missing, size):
            raster[y * size + x] = 0
    return bytes(raster)


def make_frame(path, size=(320, 240), colour=(200, 30, 30)):
    Image.new("RGB", size, colour).save(path, "JPEG", quality=90)
    return path


def whole_masked(x1=100, y1=80, x2=220, y2=200, conf=0.9):
    return make_inst(x1, y1, x2, y2, conf, 320, 240,
                     full_raster(x1, y1, x2, y2))


# --- Whole-object shape test -----------------------------------------------


def test_mask_solidity_full_square_is_one():
    inst = whole_masked()
    assert photos_mod.mask_solidity(inst) == 1.0


def test_mask_solidity_l_shape_below_floor():
    inst = make_inst(100, 100, 159, 159, 0.9, 320, 240, l_raster(60, 30))
    solidity = photos_mod.mask_solidity(inst)
    assert solidity is not None
    assert solidity < photos_mod.SOLIDITY_FLOOR


def test_mask_solidity_missing_mask_is_none():
    assert photos_mod.mask_solidity(make_inst(10, 10, 50, 50, 0.9)) is None


def test_half_slice_neighbour_dropped_low_solidity():
    main = make_inst(100, 100, 160, 160, 0.9, 320, 240,
                     full_raster(100, 100, 160, 160))
    # L-shaped: 75% of the main area (passes the area gate) but concave.
    half = make_inst(162, 100, 221, 159, 0.9, 320, 240, l_raster(60, 30))
    assert photos_mod.mask_solidity(half) < photos_mod.SOLIDITY_FLOOR
    cluster = photos_mod.select_whole([main, half], (320, 240))
    assert cluster == [main]


def test_thin_slice_neighbour_dropped_bad_aspect():
    main = make_inst(100, 100, 160, 160, 0.9, 320, 240,
                     full_raster(100, 100, 160, 160))
    # Tall thin full mask: solid and big enough, but 4x off the main aspect.
    thin = make_inst(162, 40, 191, 159, 0.9, 320, 240,
                     full_raster(162, 40, 191, 159))
    assert photos_mod.mask_solidity(thin) == 1.0
    cluster = photos_mod.select_whole([main, thin], (320, 240))
    assert cluster == [main]


def test_round_neighbours_over_60_percent_stay():
    main = make_inst(100, 100, 160, 160, 0.9, 320, 240,
                     full_raster(100, 100, 160, 160))
    left = make_inst(49, 100, 98, 149, 0.9, 320, 240,
                     full_raster(49, 100, 98, 149))
    right = make_inst(162, 100, 211, 149, 0.9, 320, 240,
                      full_raster(162, 100, 211, 149))
    cluster = photos_mod.select_whole([main, left, right], (320, 240))
    assert cluster == [main, left, right]


def test_neighbour_under_60_percent_dropped():
    main = make_inst(100, 100, 160, 160, 0.9, 320, 240,
                     full_raster(100, 100, 160, 160))
    # 43x43 = 1849 px, ~50% of main: passed the old 45% gate, fails 60%.
    small = make_inst(162, 100, 204, 142, 0.9, 320, 240,
                      full_raster(162, 100, 204, 142))
    assert photos_mod.NEIGHBOUR_AREA_FRACTION == 0.60
    cluster = photos_mod.select_whole([main, small], (640, 480))
    assert cluster == [main]


def test_main_defers_to_whole_candidate():
    # Big confident L: top scorer, but half-cut, so it cannot be main
    # while a whole candidate exists.
    half = make_inst(100, 100, 219, 219, 0.9, 640, 480, l_raster(120, 60))
    whole = make_inst(300, 100, 360, 160, 0.5, 640, 480,
                      full_raster(300, 100, 360, 160))
    assert photos_mod.mask_solidity(half) < photos_mod.SOLIDITY_FLOOR
    cluster = photos_mod.select_whole([half, whole], (640, 480))
    assert cluster == [whole]


def test_main_kept_when_no_whole_alternative():
    half = make_inst(100, 100, 219, 219, 0.9, 640, 480, l_raster(120, 60))
    cluster = photos_mod.select_whole([half], (640, 480))
    assert cluster == [half]


def test_shape_test_on_fixture():
    instances = parse_sam_response(FIXTURE.read_text())
    for inst in instances:
        solidity = photos_mod.mask_solidity(inst)
        assert solidity is None or 0.0 < solidity <= 1.0
    cluster = photos_mod.select_whole(instances, FRAME_SIZE)
    assert 1 <= len(cluster) <= 3


# --- Generic fallback --------------------------------------------------------


def _window(tmp_path):
    red = make_frame(tmp_path / "red.jpg", colour=(220, 30, 30))
    blue = make_frame(tmp_path / "blue.jpg", colour=(30, 30, 220))
    return [Frame(path=red, t_ms=0), Frame(path=blue, t_ms=500)]


def _noun_chat(answers):
    def fake_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, str):
            return dict(answers["nouns"])
        return dict(answers["verify"])
    return fake_chat


def test_generic_fallback_runs_when_nouns_miss(tmp_path, monkeypatch):
    frames = _window(tmp_path)
    seen_nouns: list[str] = []

    def fake_instances(image, noun, **kwargs):
        seen_nouns.append(noun)
        if noun == "vegetable":
            return [whole_masked(conf=0.8),
                    whole_masked(100, 80, 200, 180, 0.7)]
        return []

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    monkeypatch.setattr(photos_mod, "chat_json", _noun_chat({
        "nouns": {"beetroot": {"noun": "red beet", "category": "vegetable"}},
        "verify": {"keep": [1, 2]}}))
    categories: dict = {}
    saved = photos_mod.make_candidates(
        frames, frames[0], "beetroot", tmp_path / "photos" / "s3_0",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["beetroot"], picked_frames=[], noun_cache={},
        category_cache=categories)
    assert len(saved) == 2
    assert Image.open(saved[0]).size == (900, 900)
    assert seen_nouns.count("vegetable") == 1  # once, on the best frame
    assert categories == {"beetroot": "vegetable"}


def test_generic_fallback_skipped_when_nouns_hit(tmp_path, monkeypatch):
    frames = _window(tmp_path)
    seen_nouns: list[str] = []

    def fake_instances(image, noun, **kwargs):
        seen_nouns.append(noun)
        return [whole_masked()]

    def fake_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, str):
            return {"beetroot": {"noun": "red beet", "category": "vegetable"}}
        return {"item": "beetroot"}

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    saved = photos_mod.make_candidates(
        frames, frames[0], "beetroot", tmp_path / "photos" / "s3_0",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["beetroot"], picked_frames=[], noun_cache={},
        category_cache={})
    assert len(saved) == 2
    assert "vegetable" not in seen_nouns
    assert "produce" not in seen_nouns


def test_generic_fallback_reject_all_means_no_photo(tmp_path, monkeypatch):
    frames = _window(tmp_path)
    seen_nouns: list[str] = []

    def fake_instances(image, noun, **kwargs):
        seen_nouns.append(noun)
        if noun in ("vegetable", "produce"):
            return [whole_masked(conf=0.8)]
        return []

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    monkeypatch.setattr(photos_mod, "chat_json", _noun_chat({
        "nouns": {"beetroot": {"noun": "red beet", "category": "vegetable"}},
        "verify": {"keep": []}}))
    saved = photos_mod.make_candidates(
        frames, frames[0], "beetroot", tmp_path / "photos" / "s3_0",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["beetroot"], picked_frames=[], noun_cache={},
        category_cache={})
    assert saved == []
    assert seen_nouns.count("vegetable") == 1  # tried once, then gave up


def test_generic_fallback_uses_produce_when_unknown(tmp_path, monkeypatch):
    frames = _window(tmp_path)[:1]
    seen_nouns: list[str] = []

    def fake_instances(image, noun, **kwargs):
        seen_nouns.append(noun)
        if noun == "produce":
            return [whole_masked(conf=0.8)]
        return []

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    # Old-format visual noun answer carries no category.
    monkeypatch.setattr(photos_mod, "chat_json", _noun_chat({
        "nouns": {"beetroot": "red beet"}, "verify": {"keep": [1]}}))
    categories: dict = {}
    saved = photos_mod.make_candidates(
        frames, frames[0], "beetroot", tmp_path / "photos" / "s3_0",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["beetroot"], picked_frames=[], noun_cache={},
        category_cache=categories)
    assert len(saved) == 2
    assert "produce" in seen_nouns
    assert categories == {"beetroot": "produce"}


def test_generic_fallback_drops_low_confidence(tmp_path, monkeypatch):
    frames = _window(tmp_path)[:1]

    def fake_instances(image, noun, **kwargs):
        if noun == "produce":
            return [whole_masked(conf=0.3), whole_masked(conf=0.9)]
        return []

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    # Only the c=0.9 candidate is shown, so keeping "2" keeps nothing.
    monkeypatch.setattr(photos_mod, "chat_json", _noun_chat({
        "nouns": {}, "verify": {"keep": [2]}}))
    saved = photos_mod.make_candidates(
        frames, frames[0], "beetroot", tmp_path / "photos" / "s3_0",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["beetroot"], picked_frames=[], noun_cache={},
        category_cache={})
    assert saved == []


def test_visual_noun_categories_cached(monkeypatch, tmp_path):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[0]["content"])
        return {"tomato": {"noun": "red tomato", "category": "vegetable"},
                "apple": "red apple"}

    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    cache: dict = {}
    categories: dict = {}
    ledger, settings = make_ledger(tmp_path), make_settings()
    nouns = photos_mod.ensure_visual_nouns(
        ["tomato", "apple"], cache, ledger=ledger, settings=settings,
        category_cache=categories)
    assert nouns == {"tomato": "red tomato", "apple": "red apple"}
    assert categories == {"tomato": "vegetable", "apple": "produce"}
    assert len(calls) == 1
    # Second call hits both caches: no new Spark call.
    photos_mod.ensure_visual_nouns(
        ["tomato", "apple"], cache, ledger=ledger, settings=settings,
        category_cache=categories)
    assert len(calls) == 1


# --- Budget ------------------------------------------------------------------


def test_fallback_cost_caps_hold(tmp_path, monkeypatch):
    frames = _window(tmp_path)
    ledger = make_ledger(tmp_path)
    spark_calls: list = []

    def fake_instances(image, noun, **kwargs):
        ledger.add("meta", SAM_MODEL, SAM_USD_PER_IMAGE, f"n:{noun}")
        if noun == "vegetable":
            return [whole_masked(conf=0.8)]
        return []

    def fake_chat(messages, **kwargs):
        spark_calls.append(messages)
        content = messages[-1]["content"]
        if isinstance(content, str):
            ledger.add("meta", "muse-spark", 0.001, "nouns")
            return {"beetroot": {"noun": "red beet",
                                 "category": "vegetable"}}
        ledger.add("meta", "muse-spark", 0.001, "verify")
        return {"keep": [1]}

    def fake_faces(image, noun, **kwargs):
        ledger.add("meta", SAM_MODEL, SAM_USD_PER_IMAGE, "face")
        return []

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes", fake_faces)
    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    saved = photos_mod.make_candidates(
        frames, frames[0], "beetroot", tmp_path / "photos" / "s3_0",
        ledger=ledger, settings=make_settings(),
        session_items=["beetroot"], picked_frames=[], noun_cache={},
        category_cache={})
    assert len(saved) == 2
    with sqlite3.connect(tmp_path / "c.db") as conn:
        sam_rows = conn.execute(
            "SELECT detail FROM costs WHERE model = ?", (SAM_MODEL,)).fetchall()
    assert len(sam_rows) <= photos_mod.MAX_SAM_PER_ITEM
    assert len(spark_calls) <= 2
