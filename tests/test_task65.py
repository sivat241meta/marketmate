"""Task 65: real cut-out product photos with SAM 3.1 masks, safety gates.

No network: the SAM wire text is a saved fixture (mask text only, no shop
photos); live SAM calls are faked or respx-mocked.
"""

from __future__ import annotations

import io
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image, ImageDraw, ImageStat

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.meta.sam import (
    SAM_USD_PER_IMAGE,
    SamInstance,
    parse_sam_response,
)
from app.models import Box, DraftItem, Frame, PriceLine, Proof
from app.pipeline import photos as photos_mod

FIXTURE = Path("tests/fixtures/sam/sam_pomegranate.txt")
_SAM_URL = "https://api.meta.ai/v1/responses"
FRAME_SIZE = (576, 585)


def make_ledger(tmp_path):
    return CostLedger(tmp_path / "c.db", 100.0)


def make_settings():
    return load_settings({"MODEL_API_KEY": "k"})


def make_frame(path, size=FRAME_SIZE, bg=(255, 255, 255),
               blob=(200, 30, 30)):
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    draw.ellipse([size[0] * 0.2, size[1] * 0.2,
                  size[0] * 0.8, size[1] * 0.8], fill=blob)
    img.save(path, "JPEG", quality=90)
    return path


def fixture_instances():
    return parse_sam_response(FIXTURE.read_text())


def test_fixture_decodes_five_masks_with_plausible_fill():
    instances = fixture_instances()
    assert len(instances) == 5
    for inst in instances:
        assert inst.mask is not None
        raster = inst.mask.raster()
        assert len(raster) == inst.mask.width * inst.mask.height
        assert set(raster) <= {0, 1}
        fill = sum(raster) / len(raster)
        assert 0.10 <= fill <= 0.90


def test_mask_dimensions_match_box():
    for inst in fixture_instances():
        box = inst.box
        assert (inst.mask.width, inst.mask.height) == (
            box.x2 - box.x1 + 1, box.y2 - box.y1 + 1)


def test_mask_placement_matches_box():
    cluster = photos_mod.main_cluster(fixture_instances())
    matte = photos_mod.place_masks(FRAME_SIZE, cluster)
    pixels = matte.load()
    assert pixels[0, 0] == 0  # far outside every box
    boxes = [inst.box for inst in cluster]
    for inst in cluster:
        box = inst.box
        ones = sum(1 for y in range(box.y1, box.y2 + 1, 3)
                   for x in range(box.x1, box.x2 + 1, 3)
                   if pixels[x, y])
        sampled = sum(1 for y in range(box.y1, box.y2 + 1, 3)
                      for x in range(box.x1, box.x2 + 1, 3))
        assert ones / sampled > 0.05
    # No mask pixel leaks outside the union of boxes.
    for y in range(0, FRAME_SIZE[1], 5):
        for x in range(0, FRAME_SIZE[0], 5):
            if pixels[x, y]:
                assert any(b.x1 <= x <= b.x2 and b.y1 <= y <= b.y2
                           for b in boxes)


def test_main_cluster_is_largest_plus_touching():
    cluster = photos_mod.main_cluster(fixture_instances())
    assert len(cluster) == 3
    assert (cluster[0].box.x1, cluster[0].box.y1) == (37, 113)
    assert len(cluster) <= photos_mod.MAX_CLUSTER


def test_cutout_canvas_white_corners_product_inside(tmp_path):
    frame = make_frame(tmp_path / "frame.jpg")
    out = tmp_path / "tile.jpg"
    photos_mod.cutout_from_instances(
        frame, photos_mod.main_cluster(fixture_instances()), out)
    tile = Image.open(out)
    assert tile.size == (900, 900)
    assert tile.format == "JPEG"
    pixels = tile.load()
    for corner in [(5, 5), (894, 5), (5, 894), (894, 894)]:
        assert all(band >= 250 for band in pixels[corner])
    middle = tile.crop((350, 350, 550, 550))
    mid_pixels = middle.load()
    reddish = sum(1 for y in range(middle.height)
                  for x in range(middle.width)
                  if mid_pixels[x, y][0] > 150
                  and mid_pixels[x, y][0] - mid_pixels[x, y][2] > 30)
    assert reddish > 100


def test_cutout_needs_masks(tmp_path):
    frame = make_frame(tmp_path / "frame.jpg")
    box = Box(100, 100, 200, 200, *FRAME_SIZE, 0.9)
    try:
        photos_mod.cutout_from_instances(
            frame, [SamInstance(box=box, mask=None)],
            tmp_path / "tile.jpg")
    except photos_mod.NoCutout:
        pass
    else:
        raise AssertionError("mask-less cluster must not cut out")


def _two_frames(tmp_path):
    red = tmp_path / "red.jpg"
    blue = tmp_path / "blue.jpg"
    Image.new("RGB", (640, 480), (220, 30, 30)).save(red, "JPEG")
    Image.new("RGB", (640, 480), (30, 30, 220)).save(blue, "JPEG")
    return [Frame(path=red, t_ms=0), Frame(path=blue, t_ms=500)]


def test_empty_response_means_no_photo(tmp_path, monkeypatch):
    frames = _two_frames(tmp_path)

    def no_product(image, noun, **kwargs):
        assert noun != "face"  # no face call without product
        return []

    monkeypatch.setattr(photos_mod, "find_instances", no_product)
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_0",
        ledger=make_ledger(tmp_path), settings=make_settings())
    assert saved == []
    assert list((tmp_path / "photos").glob("*.jpg")) == []
    assert photos_mod.make_photo(
        frames[0], "tomato", tmp_path / "photo.jpg",
        ledger=make_ledger(tmp_path), settings=make_settings()) is None


def test_face_hit_inside_crop_skips_frame(tmp_path, monkeypatch):
    frames = _two_frames(tmp_path)
    seen = []
    product = [SamInstance(
        box=Box(100, 100, 300, 300, 640, 480, 0.9), mask=None)]

    def fake_instances(image, noun, **kwargs):
        seen.append(Path(image).name)
        return list(product)

    def fake_faces(image, noun, **kwargs):
        assert noun == "face"
        if Path(image).name == "red.jpg":
            # Small face (under 2% of the frame) inside the crop area.
            return [Box(150, 150, 200, 200, 640, 480, 0.9)]
        return []

    monkeypatch.setattr(photos_mod, "find_instances", fake_instances)
    monkeypatch.setattr(photos_mod, "find_boxes", fake_faces)
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_0",
        ledger=make_ledger(tmp_path), settings=make_settings())
    assert seen[0] == "red.jpg"  # sharpest tried first, then skipped
    assert len(saved) == 1 and saved[0].endswith("_orig.jpg")
    pixels = Image.open(saved[0]).load()
    width, height = Image.open(saved[0]).size
    centre = pixels[width // 2, height // 2]
    assert centre[2] > centre[0] + 50  # blue frame won, not red


def test_all_frames_face_blocked_means_no_photo(tmp_path, monkeypatch):
    frames = _two_frames(tmp_path)
    product = [SamInstance(
        box=Box(100, 100, 300, 300, 640, 480, 0.9), mask=None)]
    monkeypatch.setattr(
        photos_mod, "find_instances",
        lambda image, noun, **kwargs: list(product))
    monkeypatch.setattr(
        photos_mod, "find_boxes",
        lambda image, noun, **kwargs: [
            Box(150, 150, 200, 200, 640, 480, 0.9)])
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_0",
        ledger=make_ledger(tmp_path), settings=make_settings())
    assert saved == []
    assert photos_mod.make_photo(
        frames[0], "tomato", tmp_path / "photo.jpg",
        ledger=make_ledger(tmp_path), settings=make_settings()) is None


def test_low_confidence_boxes_ignored(tmp_path, monkeypatch):
    frames = _two_frames(tmp_path)
    weak = [SamInstance(
        box=Box(100, 100, 300, 300, 640, 480, 0.2), mask=None)]
    monkeypatch.setattr(
        photos_mod, "find_instances",
        lambda image, noun, **kwargs: list(weak))
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_0",
        ledger=make_ledger(tmp_path), settings=make_settings())
    assert saved == []


# save_retake centre-crops the 800 by 600 upload to (120, 90, 680, 510),
# so regions below are compared with the (120, 90) offset applied.
_CROP_OFFSET = (120, 90)
_FACE_BOX = (200, 150, 400, 350)


def _checker_upload():
    img = Image.new("RGB", (800, 600), (120, 120, 120))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = _FACE_BOX
    for y in range(top, bottom, 20):
        for x in range(left, right, 20):
            shade = 0 if (x + y) // 20 % 2 else 255
            draw.rectangle([x, y, x + 19, y + 19], fill=(shade,) * 3)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _shifted(box):
    left, top, right, bottom = box
    dx, dy = _CROP_OFFSET
    return (left - dx, top - dy, right - dx, bottom - dy)


def test_retake_blurs_mocked_face(tmp_path, monkeypatch):
    data = _checker_upload()
    calls = []
    left, top, right, bottom = _FACE_BOX
    face = [Box(left, top, right - 1, bottom - 1, 800, 600, 0.9)]

    def fake_faces(image, noun, **kwargs):
        calls.append(noun)
        assert Path(image).is_file()
        return list(face)

    monkeypatch.setattr(photos_mod, "find_boxes", fake_faces)
    out = tmp_path / "photos" / "retake.jpg"
    photos_mod.save_retake(data, out, ledger=make_ledger(tmp_path),
                           settings=make_settings())
    assert calls == ["face"]
    assert [p.name for p in out.parent.iterdir()] == ["retake.jpg"]
    saved = Image.open(out)
    before = Image.open(io.BytesIO(data))
    blurred_var = ImageStat.Stat(
        saved.crop(_shifted(_FACE_BOX)).convert("L")).var[0]
    plain_var = ImageStat.Stat(
        before.crop(_FACE_BOX).convert("L")).var[0]
    assert blurred_var < plain_var / 10


def test_retake_without_face_keeps_pixels(tmp_path, monkeypatch):
    data = _checker_upload()
    monkeypatch.setattr(photos_mod, "find_boxes",
                        lambda image, noun, **kwargs: [])
    out = tmp_path / "photos" / "retake.jpg"
    photos_mod.save_retake(data, out, ledger=make_ledger(tmp_path),
                           settings=make_settings())
    saved = Image.open(out).convert("L")
    before = Image.open(io.BytesIO(data)).convert("L")
    # Plain grey corner, well clear of the checkerboard.
    corner = saved.crop(_shifted((600, 450, 670, 500)))
    was = before.crop((600, 450, 670, 500))
    diff = sum(abs(a - b) for a, b in zip(corner.tobytes(), was.tobytes()))
    assert diff / (70 * 50) < 30


def _sam_sse(text):
    lines = []
    if text:
        lines.append("data: " + json.dumps(
            {"type": "response.output_text.delta", "delta": text}))
    lines.append("data: " + json.dumps(
        {"type": "response.completed", "response": {}}))
    return "\n\n".join(lines) + "\n\n"


def test_cost_ledger_logs_product_and_face_calls(tmp_path, respx_mock):
    frame = make_frame(tmp_path / "frame.jpg")
    respx_mock.post(_SAM_URL).mock(side_effect=[
        Response(200, text=_sam_sse(FIXTURE.read_text())),
        Response(200, text=_sam_sse("")),
    ])
    ledger = make_ledger(tmp_path)
    saved = photos_mod.make_candidates(
        [Frame(path=frame, t_ms=0)], Frame(path=frame, t_ms=0),
        "pomegranate", tmp_path / "photos" / "s1_0",
        ledger=ledger, settings=make_settings())
    assert len(saved) == 2
    assert saved[0].endswith("_cut.jpg") and saved[1].endswith("_orig.jpg")
    assert ledger.today_usd("meta") == SAM_USD_PER_IMAGE * 2
    with sqlite3.connect(tmp_path / "c.db") as conn:
        details = [row[0] for row in conn.execute(
            "SELECT detail FROM costs ORDER BY id")]
    assert details == ["find_instances", "find_boxes"]


# --- Check page toggle + cards -----------------------------------------------


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client):
    resp = client.post("/new", data={
        "name": "Cutout Store", "phone": "+914400000065",
        "area": "Koyambedu", "language": "ta", "currency": "INR",
        "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"].split("/e/")[1]


def draft(name_en="tomato"):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None, price_lines=[PriceLine(Decimal(40), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} 40", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def seed_session(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.ensure_session_base(conn, session_id)
        db.save_drafts(conn, session_id, list(drafts))
        db.set_session_status(conn, session_id, "review", "seeded")
        return session_id
    finally:
        conn.close()


def seed_candidates(tmp_path, token, session_id):
    photos = tmp_path / "data" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    cut = photos / "s9_0_cut.jpg"
    orig = photos / "s9_0_orig.jpg"
    Image.new("RGB", (900, 900), (255, 255, 255)).save(cut, "JPEG")
    Image.new("RGB", (800, 600), (200, 30, 30)).save(orig, "JPEG")
    conn = db.connect(tmp_path / "data")
    try:
        items = db.load_drafts(conn, session_id)
        items[0].photo = str(cut)
        items[0].photo_candidates = [str(cut), str(orig)]
        db.save_drafts(conn, session_id, items)
    finally:
        conn.close()
    return [str(cut), str(orig)]


def test_toggle_sends_index_only(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    names = seed_candidates(tmp_path, token, session_id)
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0",
                       json={"index": 1, "photo": "/etc/passwd",
                             "path": names[0]})
    assert resp.status_code == 200
    assert resp.json() == {"photo_url": "/m/s9_0_orig.jpg",
                           "cutout": False}
    conn = db.connect(tmp_path / "data")
    try:
        assert db.load_drafts(conn, session_id)[0].photo == names[1]
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0",
                       json={"index": 0})
    assert resp.json()["cutout"] is True


def test_check_page_shows_original_photo_no_picker(tmp_path):
    # Task 147: the stored cut-out renders as its original sibling, with
    # no Cut-out/Original picker — one photo plus the retake upload.
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    seed_candidates(tmp_path, token, session_id)
    resp = client.get(f"/e/{token}/s/{session_id}")
    assert resp.status_code == 200
    html = resp.text
    assert "/m/s9_0_orig.jpg" in html
    assert "s9_0_cut.jpg" not in html
    assert "Pick the best photo" not in html
    assert "photo-thumb" not in html
    assert "data-photo-pick" not in html
    assert 'data-photo-index="' not in html
    assert "data-cutout" not in html
    assert "data-photo-main" in html
    assert "Take a new photo" in html
    assert "data-photo-retake" in html


def test_shop_card_uses_contain_for_cutout(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    names = seed_candidates(tmp_path, token, session_id)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.approve(conn, session_id,
                                db.load_drafts(conn, session_id))
        db.set_published(conn, version_id, True)
        slug = shop["slug"]
        assert db.version_items(conn, version_id)[0].photo == names[0]
    finally:
        conn.close()
    resp = client.get(f"/s/{slug}")
    assert resp.status_code == 200
    assert "data-cutout" in resp.text
