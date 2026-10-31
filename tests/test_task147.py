"""Task 147: items show a square original photo from the seller's video.

SAM still finds each item's box; the item photo is the square frame
crop around it (no cut-out picker anywhere). No network: SAM/Spark are
faked.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.models import Box, DraftItem, Frame, PriceLine, Proof
from app.pipeline import photos as photos_mod

IST = ZoneInfo("Asia/Kolkata")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, name="Orig Store", phone="+914400000147"):
    resp = client.post("/new", data={
        "name": name, "phone": phone,
        "area": "Koyambedu", "language": "ta", "currency": "INR",
        "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"].split("/e/")[1]


def pl(price):
    return PriceLine(Decimal(price), Decimal(1), "kg")


def draft(name_en="tomato", price=40):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None, price_lines=[pl(price)],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
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


def seed_pair(tmp_path, token, session_id, index=0, name_en="tomato",
              cut_colour=(255, 255, 255), orig_colour=(200, 30, 30)):
    """Real cut + orig files wired into the stored draft (old default)."""
    photos = tmp_path / "data" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    cut = photos / f"s{session_id}_{index}_cut.jpg"
    orig = photos / f"s{session_id}_{index}_orig.jpg"
    Image.new("RGB", (900, 900), cut_colour).save(cut, "JPEG")
    Image.new("RGB", (480, 480), orig_colour).save(orig, "JPEG")
    conn = db.connect(tmp_path / "data")
    try:
        items = db.load_drafts(conn, session_id)
        items[index].photo = str(cut)
        items[index].photo_candidates = [str(cut), str(orig)]
        db.save_drafts(conn, session_id, items)
    finally:
        conn.close()
    return cut, orig


# --- 1. the square crop helper -----------------------------------------------


def test_square_crop_centres_box_with_margin():
    box = photos_mod.square_crop_box(100, 100, 300, 200, 640, 480, floor=0)
    assert box == (85, 35, 315, 265)
    left, top, right, bottom = box
    assert right - left == bottom - top == 230  # 200 * 1.15
    assert (left + right) / 2 == 200 and (top + bottom) / 2 == 150


def test_square_crop_clamped_to_frame():
    assert photos_mod.square_crop_box(0, 0, 200, 100, 640, 480, floor=0) == (
        0, 0, 230, 230)
    box = photos_mod.square_crop_box(500, 400, 640, 480, 640, 480, floor=0)
    left, top, right, bottom = box
    assert right - left == bottom - top
    assert 0 <= left and top >= 0 and right <= 640 and bottom <= 480


def test_square_crop_min_480_when_frame_allows():
    left, top, right, bottom = photos_mod.square_crop_box(
        300, 200, 320, 220, 640, 480)
    assert right - left == bottom - top == 480
    assert 0 <= left and 0 <= top
    assert right <= 640 and bottom <= 480


def test_square_crop_small_frame_takes_largest_square():
    left, top, right, bottom = photos_mod.square_crop_box(
        10, 10, 60, 40, 320, 240)
    assert right - left == bottom - top == 240
    assert (left, top, right, bottom) == (0, 0, 240, 240)


def test_crop_square_saves_square_jpeg(tmp_path):
    src = tmp_path / "in.jpg"
    Image.new("RGB", (800, 600), (30, 120, 30)).save(src, "JPEG")
    out = tmp_path / "out.jpg"
    photos_mod.crop_square_to_boxes(
        src, [Box(100, 100, 300, 250, 800, 600, 0.9)], out)
    width, height = Image.open(out).size
    assert width == height >= 480


def test_make_candidates_orig_is_square(tmp_path, monkeypatch):
    from app.meta.sam import parse_sam_response

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    frames = []
    for t_ms in (4000, 4500, 5000):
        path = frames_dir / f"f_{t_ms}.jpg"
        Image.new("RGB", (576, 585), (200, 30, 30)).save(path, "JPEG")
        frames.append(Frame(path=path, t_ms=t_ms))
    instances = parse_sam_response(
        Path("tests/fixtures/sam/sam_pomegranate.txt").read_text())
    monkeypatch.setattr(
        photos_mod, "find_instances",
        lambda image, noun, **kwargs: list(instances))
    monkeypatch.setattr(
        photos_mod, "find_boxes", lambda image, noun, **kwargs: [])
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_0",
        ledger=ledger, settings=settings)
    assert len(saved) == 2
    width, height = Image.open(saved[1]).size
    assert saved[1].endswith("_orig.jpg")
    assert width == height >= 480


# --- 2. render prefers _orig over _cut ----------------------------------------


def test_prefer_original_swaps_when_sibling_exists(tmp_path):
    cut = tmp_path / "s1_0_cut.jpg"
    orig = tmp_path / "s1_0_orig.jpg"
    cut.write_bytes(b"cut")
    orig.write_bytes(b"orig")
    assert photos_mod.prefer_original(str(cut)) == str(orig)
    assert photos_mod.prefer_original(cut) == orig


def test_prefer_original_keeps_cut_without_sibling(tmp_path):
    cut = tmp_path / "s1_0_cut.jpg"
    cut.write_bytes(b"cut")
    assert photos_mod.prefer_original(str(cut)) == str(cut)


def test_prefer_original_passes_other_photos_through(tmp_path):
    assert photos_mod.prefer_original(None) is None
    assert photos_mod.prefer_original("") == ""
    retake = tmp_path / "s1_0_retake.jpg"
    retake.write_bytes(b"r")
    assert photos_mod.prefer_original(str(retake)) == str(retake)
    sample = tmp_path / "selvi-vegetable-stall__tomato.webp"
    sample.write_bytes(b"s")
    assert photos_mod.prefer_original(str(sample)) == str(sample)
    orig = tmp_path / "s1_0_orig.jpg"
    orig.write_bytes(b"o")
    assert photos_mod.prefer_original(str(orig)) == str(orig)


def test_pipeline_stores_original_as_photo(tmp_path, monkeypatch):
    from app.pipeline import run as run_mod
    from app.pipeline.extract import parse_extract_json

    conn = db.connect(tmp_path)
    shop_id, _, _ = db.create_shop(
        conn, name="T147 Stall", phone="+914400000147", area="Koyambedu",
        language="ta", currency="INR", shop_type="vegetable")
    session_id = db.create_session(conn, shop_id, "video")
    canned = {"items": [{
        "name_spoken": "tomato", "name_en": "tomato", "variety": None,
        "prices": [{"said": "kilo forty", "price": 40,
                  "per_amount": 1, "unit": "kg"}],
        "range_said": False, "qty_said": None, "qty": None,
        "qty_unit": None, "turn_ids": [1], "quote": "tomato kilo forty"}]}
    monkeypatch.setattr(
        run_mod, "extract_items",
        lambda *a, **k: parse_extract_json(
            canned, run_mod.Transcript(
                text="tomato kilo forty", duration_ms=3000, turns=[
                    run_mod.Turn(id=1, start_ms=0, end_ms=3000,
                                 text="tomato kilo forty")]),
            language="ta"))

    def fake_candidates(pool, frame, noun, prefix, **kwargs):
        return [f"{prefix}_cut.jpg", f"{prefix}_orig.jpg"]

    monkeypatch.setattr(run_mod, "pick_best_frame",
                        lambda item, candidates, **k: (candidates[0], True))
    monkeypatch.setattr(run_mod, "window_frames",
                        lambda frames, picked, **k: [picked])
    monkeypatch.setattr(run_mod, "make_candidates", fake_candidates)
    monkeypatch.setattr(run_mod, "check_item", lambda *a, **k: [])
    monkeypatch.setattr(run_mod, "cut_audio_clip",
                        lambda wav, start, end, dest: dest)
    frames = [Frame(path=tmp_path / f"f_{ms}.jpg", t_ms=ms)
              for ms in range(0, 3000, 500)]
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    run_mod.process_turns(
        conn, session_id,
        [run_mod.Turn(id=1, start_ms=0, end_ms=3000,
                      text="tomato kilo forty")],
        None, tmp_path / "audio.wav", settings=settings,
        ledger=CostLedger(tmp_path / "costs.db", 10.0), language="ta",
        all_frames=frames, video=None)
    drafts = db.load_drafts(conn, session_id)
    assert drafts[0].photo.endswith("_orig.jpg")
    assert [Path(p).name for p in drafts[0].photo_candidates] == [
        f"s{session_id}_0_cut.jpg", f"s{session_id}_0_orig.jpg"]


# --- 3. review page: no picker, one square photo ------------------------------


def test_review_page_has_no_picker_and_one_square_photo(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    _cut, orig = seed_pair(tmp_path, token, session_id)
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Pick the best photo" not in html
    assert "data-photo-pick" not in html
    assert "data-photo-index" not in html
    assert "photo-thumb" not in html
    assert html.count("data-photo-main") == 1
    assert f"/m/{orig.name}" in html
    assert "Take a new photo" in html
    assert "data-photo-retake" in html
    assert f"/e/{token}/s/{session_id}/photo/0/upload" in html
    width, height = Image.open(orig).size
    assert width == height


# --- 4. public shop row uses the original -------------------------------------


def test_public_shop_row_uses_original(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft("drumstick")])
    cut, orig = seed_pair(tmp_path, token, session_id, name_en="drumstick")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.approve(conn, session_id,
                                db.load_drafts(conn, session_id))
        db.set_published(conn, version_id, True)
        slug = shop["slug"]
    finally:
        conn.close()
    html = client.get(f"/s/{slug}").text
    assert f"/m/{orig.name}" in html
    assert cut.name not in html


# --- 5. the face rule ----------------------------------------------------------


def test_face_overlapping_square_crop_blocks_frame():
    from app.pipeline.photos import face_blocks_frame, square_box_for

    boxes = [Box(100, 100, 300, 300, 640, 480, 0.9)]
    crop = square_box_for(boxes, 640, 480)
    assert face_blocks_frame(
        [Box(150, 150, 200, 200, 640, 480, 0.9)], frame_size=(640, 480),
        crop_area=crop, cluster=(100, 100, 300, 300))
    # Small face far from the crop and the cluster: frame stays usable.
    assert not face_blocks_frame(
        [Box(500, 400, 540, 440, 640, 480, 0.9)], frame_size=(640, 480),
        crop_area=crop, cluster=(100, 100, 300, 300))
    # A selfie-sized face blocks whatever it overlaps.
    assert face_blocks_frame(
        [Box(400, 0, 639, 200, 640, 480, 0.9)], frame_size=(640, 480),
        crop_area=crop, cluster=(100, 100, 300, 300))


def test_make_candidates_skips_face_blocked_frame(tmp_path, monkeypatch):
    from app.meta.sam import SamInstance

    red = tmp_path / "red.jpg"
    blue = tmp_path / "blue.jpg"
    Image.new("RGB", (640, 480), (220, 30, 30)).save(red, "JPEG")
    Image.new("RGB", (640, 480), (30, 30, 220)).save(blue, "JPEG")
    frames = [Frame(path=red, t_ms=0), Frame(path=blue, t_ms=500)]
    product = [SamInstance(
        box=Box(100, 100, 300, 300, 640, 480, 0.9), mask=None)]

    def fake_faces(image, noun, **kwargs):
        if Path(image).name == "red.jpg":
            return [Box(150, 150, 200, 200, 640, 480, 0.9)]
        return []

    monkeypatch.setattr(photos_mod, "find_instances",
                        lambda image, noun, **kwargs: list(product))
    monkeypatch.setattr(photos_mod, "find_boxes", fake_faces)
    saved = photos_mod.make_candidates(
        frames, frames[0], "tomato", tmp_path / "photos" / "s1_0",
        ledger=CostLedger(tmp_path / "c.db", 100.0),
        settings=load_settings({"MODEL_API_KEY": "k"}))
    assert len(saved) == 1 and saved[0].endswith("_orig.jpg")
    photo = Image.open(saved[0])
    assert photo.size[0] == photo.size[1] >= 480
    centre = photo.load()[photo.size[0] // 2, photo.size[1] // 2]
    assert centre[2] > centre[0] + 50  # blue frame won, not red


# --- 6. board PDF uses the original --------------------------------------------


def test_board_pdf_uses_original(tmp_path):
    from pypdf import PdfReader

    from app.models import Item
    from app.outputs.pdf import price_board_pdf

    photos = tmp_path / "photos"
    photos.mkdir()
    cut = photos / "s1_0_cut.jpg"
    orig = photos / "s1_0_orig.jpg"
    Image.new("RGB", (480, 480), (220, 30, 30)).save(cut, "JPEG")
    Image.new("RGB", (480, 480), (30, 30, 220)).save(orig, "JPEG")
    goods = [Item(
        id=1, version_id=1, name_local="முருங்கை", name_en="drumstick",
        variety=None, qty=None, qty_unit=None, photo=str(cut),
        sold_out=False, price_lines=[pl(40)],
        proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0))]
    pdf = price_board_pdf(
        {"name": "Demo Stall", "slug": "demo-stall", "area": "Koyambedu",
         "phone": "+914400000000"},
        goods, datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/demo-stall")
    centres = []
    for image in PdfReader(io.BytesIO(pdf)).pages[0].images:
        shot = image.image
        centres.append(shot.load()[shot.width // 2, shot.height // 2])
    assert any(c[2] > 150 and c[0] < 100 for c in centres), centres
    assert not any(c[0] > 150 and c[2] < 100 for c in centres), centres


# --- 7. wording: found in the video, never cut out ------------------------------


def test_how_card_and_how_page_wording():
    from app.web.i18n import t_for

    en = t_for("en")
    assert en("v13.how_3t") == "Each item is found in the video"
    assert en("v13.how_3d") == (
        "sam-3.1 finds it, and we keep a square photo from the "
        "seller's own video. Faces are left out.")
    assert "square photo" in en("land.meta_sam")
    assert "Faces are left out" in en("v13.how_3d")
    for lang in ("ta", "hi"):
        text = t_for(lang)
        assert "sam-3.1" in text("v13.how_3d"), lang
        assert text("v13.how_3t") and text("land.meta_sam"), lang
    assert "cut out" not in en("v13.how_3t").lower()
    assert "cut out" not in en("v13.how_3d").lower()


# --- 8. no photo keeps the flag -------------------------------------------------


def test_no_photo_keeps_no_frame_flag(tmp_path, monkeypatch):
    from app.pipeline import run as run_mod
    from app.pipeline.extract import parse_extract_json

    conn = db.connect(tmp_path)
    shop_id, _, _ = db.create_shop(
        conn, name="T147 Stall", phone="+914400000148", area="Koyambedu",
        language="ta", currency="INR", shop_type="vegetable")
    session_id = db.create_session(conn, shop_id, "video")
    canned = {"items": [{
        "name_spoken": "tomato", "name_en": "tomato", "variety": None,
        "prices": [{"said": "kilo forty", "price": 40,
                  "per_amount": 1, "unit": "kg"}],
        "range_said": False, "qty_said": None, "qty": None,
        "qty_unit": None, "turn_ids": [1], "quote": "tomato kilo forty"}]}
    turns = [run_mod.Turn(id=1, start_ms=0, end_ms=3000,
                          text="tomato kilo forty")]
    transcript = run_mod.Transcript(text="tomato kilo forty",
                                    duration_ms=3000, turns=turns)
    monkeypatch.setattr(
        run_mod, "extract_items",
        lambda *a, **k: parse_extract_json(canned, transcript,
                                           language="ta"))
    monkeypatch.setattr(run_mod, "pick_best_frame",
                        lambda item, candidates, **k: (candidates[0], False))
    monkeypatch.setattr(run_mod, "window_frames",
                        lambda frames, picked, **k: [picked])
    monkeypatch.setattr(run_mod, "make_candidates",
                        lambda *a, **k: [])
    monkeypatch.setattr(run_mod, "check_item", lambda *a, **k: [])
    monkeypatch.setattr(run_mod, "cut_audio_clip",
                        lambda wav, start, end, dest: dest)
    frames = [Frame(path=tmp_path / f"f_{ms}.jpg", t_ms=ms)
              for ms in range(0, 3000, 500)]
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    run_mod.process_turns(
        conn, session_id, turns, None, tmp_path / "audio.wav",
        settings=settings, ledger=CostLedger(tmp_path / "costs.db", 10.0),
        language="ta", all_frames=frames, video=None)
    drafts = db.load_drafts(conn, session_id)
    assert drafts[0].photo is None
    flags = [f for f in drafts[0].flags if f.code == "PICTURE_MISMATCH"]
    assert len(flags) == 1
    assert flags[0].message == "no frame clearly shows tomato"
