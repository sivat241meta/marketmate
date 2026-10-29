"""Task 67: cleaner cut-outs (whole objects only, cross-checked, verified).

No network: SAM and Spark are faked; the SAM wire text is the saved
Task 65 fixture (mask text only, no shop photos).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw

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


def make_frame(path, size=(320, 240), colour=(200, 30, 30)):
    Image.new("RGB", size, colour).save(path, "JPEG", quality=90)
    return path


# --- Whole objects only -------------------------------------------------


def test_edge_touching_never_main_and_dropped():
    whole = make_inst(100, 100, 180, 180, 0.5)
    cut = make_inst(0, 100, 200, 220, 0.99)  # bigger, surer, but cut off
    cluster = photos_mod.select_whole([cut, whole], (320, 240))
    assert cluster and cluster[0] is whole
    assert cut not in cluster


def test_all_edge_touching_means_no_cluster():
    cut = [make_inst(0, 0, 100, 100, 0.9), make_inst(200, 200, 319, 239, 0.9)]
    assert photos_mod.select_whole(cut, (320, 240)) == []


def test_main_maximises_confidence_times_root_area():
    big_vague = make_inst(50, 50, 150, 150, 0.4)
    small_sure = make_inst(180, 50, 230, 100, 0.7)
    cluster = photos_mod.select_whole([big_vague, small_sure], (320, 240))
    # 0.4*sqrt(10201) = 40.4 > 0.7*sqrt(2601) = 35.7: the big one wins.
    assert cluster[0] is big_vague


def test_slivers_below_4_percent_removed():
    width, height = 20, 20
    raster = bytearray(width * height)
    for y in range(2, 12):  # 10x10 = 100 px main blob
        for x in range(2, 12):
            raster[y * width + x] = 1
    raster[19 * width + 19] = 1  # 1 px sliver (< 4% of 100)
    cleaned = photos_mod.clean_raster(bytes(raster), width, height, 100)
    assert sum(cleaned) == 100
    assert cleaned[19 * width + 19] == 0


def test_only_largest_component_kept():
    width, height = 30, 10
    raster = bytearray(width * height)
    for y in range(10):  # 10x10 blob vs 8x8 blob: both over 4% of 100
        for x in range(10):
            raster[y * width + x] = 1
        for x in range(20, 28):
            raster[y * width + x] = 1
    cleaned = photos_mod.clean_raster(bytes(raster), width, height, 100)
    assert sum(cleaned) == 100
    assert all(value == 0 for value in cleaned[20:30])


def test_small_holes_filled():
    width, height = 10, 10
    raster = bytearray([1]) * (width * height)
    raster[5 * width + 5] = 0  # 1 px hole (< 4% of 100)
    cleaned = photos_mod.clean_raster(bytes(raster), width, height, 100)
    assert sum(cleaned) == 100


def _neighbour_box(dx, conf=0.5, size=60):
    # Main lives at (100, 100, 160, 160); neighbours start at 100 + dx.
    return make_inst(100 + dx, 100, 100 + dx + size, 100 + size, conf)


def test_neighbours_need_touch_confidence_and_area():
    main = make_inst(100, 100, 160, 160, 0.9)  # area 3721
    good = _neighbour_box(62, conf=0.5, size=60)  # touches, area 3721
    shy = _neighbour_box(-62, conf=0.4, size=60)  # under 0.45
    tiny = _neighbour_box(62, conf=0.9, size=30)  # 961 < 45% of 3721
    far = make_inst(250, 100, 310, 160, 0.9)  # big and sure but apart
    cluster = photos_mod.select_whole([main, good, shy, tiny, far], (320, 240))
    assert cluster[0] is main
    assert cluster[1:] == [good]


def test_at_most_two_neighbours():
    main = make_inst(120, 90, 200, 170, 0.9)
    pals = [make_inst(37, 91, 119, 171, 0.5),   # touches main's left edge
            make_inst(121, 91, 201, 171, 0.6),  # overlaps main
            make_inst(201, 91, 281, 171, 0.7)]  # touches main's right edge
    cluster = photos_mod.select_whole([main, *pals], (640, 480))
    assert len(cluster) == 3
    assert cluster[0] is main


def test_select_whole_on_fixture():
    instances = parse_sam_response(FIXTURE.read_text())
    cluster = photos_mod.select_whole(instances, FRAME_SIZE)
    assert 1 <= len(cluster) <= 3
    for inst in cluster:
        assert not photos_mod.touches_edge(inst.box, *FRAME_SIZE)


def test_cleaned_matte_has_no_islands(tmp_path):
    frame = make_frame(tmp_path / "frame.jpg", (100, 80), (210, 40, 40))
    width, height = 40, 30
    raster = bytearray(width * height)
    for y in range(5, 25):  # main blob
        for x in range(5, 35):
            raster[y * width + x] = 1
    raster[0] = 1  # detached sliver pixel inside the same mask
    inst = make_inst(30, 25, 30 + width - 1, 25 + height - 1, 0.9,
                     100, 80, raster)
    matte = photos_mod.place_masks((100, 80), [inst], clean=True)
    pixels = matte.load()
    assert pixels[30, 25] == 0  # sliver gone
    assert pixels[30 + 10, 25 + 10] == 255  # blob kept
    out = tmp_path / "tile.jpg"
    photos_mod.cutout_from_instances(frame, [inst], out, clean=True)
    assert Image.open(out).size == (900, 900)


def test_defringe_drops_dark_edge_pixels():
    rgb = Image.new("RGB", (10, 10), (200, 50, 50))
    draw = ImageDraw.Draw(rgb)
    draw.rectangle([0, 0, 9, 1], fill=(10, 10, 10))  # dark fringe row
    alpha = Image.new("L", (10, 10), 255)
    alpha.putpixel((5, 0), 100)  # partial alpha on the fringe
    alpha.putpixel((5, 5), 100)  # partial alpha on the product
    cleaned = photos_mod.defringe(rgb, alpha)
    assert cleaned.getpixel((5, 0)) == 0
    assert cleaned.getpixel((5, 5)) == 100


# --- Cross-check ----------------------------------------------------------


def test_cross_check_drops_confused_instance():
    apple = make_inst(100, 100, 200, 200, 0.6)  # really a pomegranate
    pom = make_inst(105, 105, 195, 195, 0.9)
    assert photos_mod.drop_confused([apple], [pom]) == []


def test_cross_check_keeps_when_target_surer_or_apart():
    sure = make_inst(100, 100, 200, 200, 0.9)
    rival = make_inst(105, 105, 195, 195, 0.6)
    apart = make_inst(100, 100, 150, 150, 0.5)
    far = make_inst(200, 200, 280, 280, 0.95)
    assert photos_mod.drop_confused([sure], [rival]) == [sure]
    assert photos_mod.drop_confused([apart], [far]) == [apart]


def test_cross_check_uses_mask_iou():
    target = make_inst(50, 50, 59, 59, 0.6, raster=full_raster(50, 50, 59, 59))
    rival = make_inst(50, 50, 59, 59, 0.9, raster=full_raster(50, 50, 59, 59))
    assert photos_mod.instances_iou(target, rival) == 1.0
    assert photos_mod.drop_confused([target], [rival]) == []


def test_other_nouns_share_frame_or_window():
    picked = Frame(path=Path("a.jpg"), t_ms=10_000)
    same = Frame(path=Path("a.jpg"), t_ms=10_000)
    near = Frame(path=Path("b.jpg"), t_ms=11_500)
    edge = Frame(path=Path("c.jpg"), t_ms=12_000)
    far = Frame(path=Path("d.jpg"), t_ms=20_000)
    others = photos_mod._other_nouns(
        "apple", picked,
        [("apple", same), ("pomegranate", far), ("sweet lime", near),
         ("tomato", edge), ("banana stem", same)])
    assert others == ["banana stem", "sweet lime"]


def test_cross_check_runs_inside_candidates(tmp_path, monkeypatch):
    frame = make_frame(tmp_path / "frame.jpg")
    target = make_inst(100, 80, 220, 200, 0.6, 320, 240,
                       full_raster(100, 80, 220, 200))
    rival = make_inst(100, 80, 220, 200, 0.9, 320, 240,
                      full_raster(100, 80, 220, 200))

    def fake_instances(image, noun, **kwargs):
        return [rival] if noun == "pomegranate" else [target]

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kwargs: [])
    monkeypatch.setattr(photos_mod, "chat_json", lambda *a, **k: {})
    frames = [Frame(path=frame, t_ms=0)]
    saved = photos_mod.make_candidates(
        frames, frames[0], "apple", tmp_path / "photos" / "s1_5",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["apple", "pomegranate"],
        picked_frames=[("apple", frames[0]), ("pomegranate", frames[0])],
        noun_cache={})
    assert saved == []  # the "apple" was really a pomegranate: no photo


# --- Spark verification failover -------------------------------------------


def _masked_window(tmp_path):
    red = make_frame(tmp_path / "red.jpg", colour=(220, 30, 30))
    blue = make_frame(tmp_path / "blue.jpg", colour=(30, 30, 220))
    return [Frame(path=red, t_ms=0), Frame(path=blue, t_ms=500)]


def _whole_masked(conf=0.9):
    return make_inst(100, 80, 220, 200, conf, 320, 240,
                     full_raster(100, 80, 220, 200))


def test_failed_verify_moves_to_next_frame(tmp_path, monkeypatch):
    frames = _masked_window(tmp_path)
    answers = iter(["pomegranate", "tomato"])

    def fake_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, str):
            return {}
        return {"item": next(answers)}

    monkeypatch.setattr(photos_mod, "find_instances",
                        lambda image, noun, **kw: [_whole_masked()])
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_1",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["tomato", "pomegranate"], picked_frames=[],
        noun_cache={})
    assert len(saved) == 2  # frame 2 verified after frame 1 failed
    assert Image.open(saved[0]).size == (900, 900)


def test_failed_verify_everywhere_means_no_photo(tmp_path, monkeypatch):
    frames = _masked_window(tmp_path)

    def fake_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, str):
            return {}
        return {"item": "pomegranate"}  # never the target

    monkeypatch.setattr(photos_mod, "find_instances",
                        lambda image, noun, **kw: [_whole_masked()])
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: [])
    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    out = tmp_path / "photos" / "s1_1"
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", out,
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["tomato", "pomegranate"], picked_frames=[],
        noun_cache={})
    assert saved == []
    assert list((tmp_path / "photos").glob("*_cut.jpg")) == []  # never wrong


# --- Visual nouns ------------------------------------------------------------


def test_visual_noun_asked_once_per_session(monkeypatch, tmp_path):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[0]["content"])
        return {"tomato": "red tomato", "banana stem": "pale stalk"}

    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    cache: dict = {}
    ledger, settings = make_ledger(tmp_path), make_settings()
    first = photos_mod.ensure_visual_nouns(["tomato", "banana stem"], cache,
                                           ledger=ledger, settings=settings)
    second = photos_mod.ensure_visual_nouns(["tomato"], cache,
                                            ledger=ledger, settings=settings)
    assert len(calls) == 1
    assert "tomato" in calls[0] and "banana stem" in calls[0]
    assert first == {"tomato": "red tomato", "banana stem": "pale stalk"}
    assert second == {"tomato": "red tomato"}
    assert cache == first


def test_visual_noun_falls_back_to_name(monkeypatch, tmp_path):
    monkeypatch.setattr(photos_mod, "chat_json",
                        lambda *a, **k: {"tomato": "  "})
    nouns = photos_mod.ensure_visual_nouns(
        ["tomato", "apple"], {}, ledger=make_ledger(tmp_path),
        settings=make_settings())
    assert nouns == {"tomato": "tomato", "apple": "apple"}


# --- Budget ------------------------------------------------------------------


def test_per_item_sam_cap_and_ledger(tmp_path, monkeypatch):
    frames = [Frame(path=make_frame(tmp_path / f"f{pos}.jpg"), t_ms=pos * 100)
              for pos in range(5)]
    ledger = make_ledger(tmp_path)

    def fake_instances(image, noun, **kwargs):
        ledger.add("meta", SAM_MODEL, SAM_USD_PER_IMAGE, f"target:{noun}")
        return [_whole_masked()]

    def fake_faces(image, noun, **kwargs):
        ledger.add("meta", SAM_MODEL, SAM_USD_PER_IMAGE, "face")
        return []

    def fake_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, str):
            return {}
        ledger.add("meta", "muse-spark", 0.001, "verify")
        return {"item": "none"}

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes", fake_faces)
    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_1",
        ledger=ledger, settings=make_settings(),
        session_items=["tomato"], picked_frames=[], noun_cache={})
    assert saved == []
    with sqlite3.connect(tmp_path / "c.db") as conn:
        rows = conn.execute(
            "SELECT detail FROM costs WHERE detail != 'verify'").fetchall()
    assert len(rows) <= photos_mod.MAX_SAM_PER_ITEM
    assert {row[0] for row in rows} <= {"target:tomato", "face"}
    assert len(rows) == photos_mod.MAX_SAM_PER_ITEM  # the cap binds


def test_passing_frame_stops_early(tmp_path, monkeypatch):
    frames = _masked_window(tmp_path)
    sam_calls: list[str] = []

    def fake_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, str):
            return {}
        return {"item": "tomato"}

    monkeypatch.setattr(
        photos_mod, "find_instances",
        lambda image, noun, **kw: sam_calls.append(str(image)) or [_whole_masked()])
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kw: sam_calls.append("face") or [])
    monkeypatch.setattr(photos_mod, "chat_json", fake_chat)
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_1",
        ledger=make_ledger(tmp_path), settings=make_settings(),
        session_items=["tomato"], picked_frames=[], noun_cache={})
    assert len(saved) == 2
    assert sam_calls == [str(frames[0].path), "face"]  # frame 2 never tried
