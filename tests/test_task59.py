"""Task 59: sharper, tighter item photos with seller pick/retake; one CSV.

Failing-tests-first: sharpness picker, 4:3 crop floor, 3 candidates,
candidate pick by index, retake upload checks, published photo change,
vendor-CSV removal, CSV labels, en/ta/hi rendering.
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageFilter

from app import db
from app.config import load_settings
from app.models import Box, DraftItem, Frame, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def create_shop(client, language="ta"):
    resp = client.post("/new", data={
        "name": "Photo Store", "phone": "+914400000059",
        "area": "Koyambedu", "language": language, "currency": "INR",
        "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"].split("/e/")[1]


def pl(price, per_amount=1, unit="kg", said=""):
    return PriceLine(Decimal(price), Decimal(per_amount), unit, said)


def draft(name_en="tomato", price=40):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None, price_lines=[pl(price)],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def seed_session(tmp_path, token, drafts, kind="video"):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        if kind in ("video", "live", "board"):
            db.ensure_session_base(conn, session_id)
        db.save_drafts(conn, session_id, list(drafts))
        db.set_session_status(conn, session_id, "review", "seeded")
        return session_id
    finally:
        conn.close()


def seed_published(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.ensure_session_base(conn, session_id)
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
        return session_id, version_id
    finally:
        conn.close()


def photo_with_candidates(tmp_path, token, session_id, index=0):
    """Real photo + candidate files wired into the stored draft."""
    photos = tmp_path / "data" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    names = []
    for pos in range(3):
        path = photos / f"s{session_id}_{index}_c{pos}.jpg"
        Image.new("RGB", (400, 300), (30 + pos * 60, 120, 40)).save(path, "JPEG")
        names.append(str(path))
    conn = db.connect(tmp_path / "data")
    try:
        items = db.load_drafts(conn, session_id)
        items[index].photo = names[0]
        items[index].photo_candidates = names
        db.save_drafts(conn, session_id, items)
    finally:
        conn.close()
    return names


def sharp_image(size=(320, 240)):
    img = Image.new("RGB", size, "white")
    pixels = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            if (x // 8 + y // 8) % 2:
                pixels[x, y] = (0, 0, 0)
    return img


# --- Part A: sharpness + crop -------------------------------------------------


def test_sharpness_picker_prefers_sharp(tmp_path):
    from app.pipeline.photos import sharpness_score

    sharp = tmp_path / "sharp.jpg"
    sharp_image().save(sharp, "JPEG")
    blurred = tmp_path / "blur.jpg"
    sharp_image().filter(ImageFilter.GaussianBlur(4)).save(blurred, "JPEG")
    assert sharpness_score(sharp) > sharpness_score(blurred)


def test_crop_is_4_3_and_capped(tmp_path):
    from app.pipeline.photos import crop_to_boxes

    src = tmp_path / "in.jpg"
    Image.new("RGB", (1600, 1200), (200, 30, 30)).save(src, "JPEG")
    out = tmp_path / "out.jpg"
    crop_to_boxes(src, [Box(100, 100, 1500, 1100, 1600, 1200, None)], out)
    saved = Image.open(out)
    assert saved.size == (1200, 900)
    assert out.stat().st_size > 0
    ref = tmp_path / "ref.jpg"
    Image.open(out).save(ref, "JPEG", quality=88)
    assert saved.quantization == Image.open(ref).quantization


def test_crop_never_under_360_short_side(tmp_path):
    from app.pipeline.photos import crop_to_boxes

    src = tmp_path / "in.jpg"
    Image.new("RGB", (800, 600), (30, 120, 30)).save(src, "JPEG")
    out = tmp_path / "out.jpg"
    crop_to_boxes(src, [Box(390, 290, 410, 310, 800, 600, None)], out)
    width, height = Image.open(out).size
    assert min(width, height) >= 360
    assert abs(width / height - 4 / 3) < 0.02


def test_crop_no_boxes_centre_4_3(tmp_path):
    from app.pipeline.photos import crop_to_boxes

    src = tmp_path / "in.jpg"
    Image.new("RGB", (800, 600), (30, 30, 180)).save(src, "JPEG")
    out = tmp_path / "out.jpg"
    crop_to_boxes(src, [], out)
    width, height = Image.open(out).size
    assert (width, height) == (560, 420)


def test_cutout_and_original_candidates_stored(tmp_path, monkeypatch):
    # Task 65 replaces the 3 centre-crop candidates with Cut-out + Original.
    import app.pipeline.photos as photos_mod
    from app.config import load_settings as _load
    from app.costs import CostLedger
    from app.meta.sam import parse_sam_response

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    frames = []
    for pos, t_ms in enumerate((4000, 4500, 5000, 5500, 6000)):
        path = frames_dir / f"f_{t_ms}.jpg"
        if pos == 2:
            sharp_image((576, 585)).save(path, "JPEG")
        else:
            sharp_image((576, 585)).filter(
                ImageFilter.GaussianBlur(2 + pos)).save(path, "JPEG")
        frames.append(Frame(path=path, t_ms=t_ms))
    instances = parse_sam_response(
        Path("tests/fixtures/sam/sam_pomegranate.txt").read_text())
    monkeypatch.setattr(
        photos_mod, "find_instances",
        lambda image, noun, **kwargs: list(instances))
    monkeypatch.setattr(
        photos_mod, "find_boxes", lambda image, noun, **kwargs: [])
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = _load({"MODEL_API_KEY": "k"})
    picked = frames[2]
    saved = photos_mod.make_candidates(
        frames, picked, "tomato", tmp_path / "photos" / "s1_0",
        ledger=ledger, settings=settings)
    assert len(saved) == 2
    assert saved[0].endswith("_cut.jpg")
    assert saved[1].endswith("_orig.jpg")
    assert all(Path(p).is_file() for p in saved)
    assert Image.open(saved[0]).size == (900, 900)


# --- Part B: seller pick / retake ---------------------------------------------


def test_pick_candidate_index_updates_draft(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    names = photo_with_candidates(tmp_path, token, session_id)
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0",
                       json={"index": 2})
    assert resp.status_code == 200
    conn = db.connect(tmp_path / "data")
    try:
        assert db.load_drafts(conn, session_id)[0].photo == names[2]
    finally:
        conn.close()


def test_pick_candidate_ignores_path(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    names = photo_with_candidates(tmp_path, token, session_id)
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0",
                       json={"index": 1, "photo": "/etc/passwd",
                             "path": names[2]})
    assert resp.status_code == 200
    conn = db.connect(tmp_path / "data")
    try:
        assert db.load_drafts(conn, session_id)[0].photo == names[1]
    finally:
        conn.close()


def test_photo_upload_rejects_non_image(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0/upload",
                       files={"photo": ("evil.txt", b"not an image",
                                        "text/plain")})
    assert resp.status_code == 400


def test_photo_upload_rejects_big_file(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    big = b"\xff" * (8 * 1024 * 1024 + 1)
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0/upload",
                       files={"photo": ("big.jpg", big, "image/jpeg")})
    assert resp.status_code == 400


def test_photo_upload_strips_exif(tmp_path, monkeypatch):
    import app.pipeline.photos as photos_mod

    monkeypatch.setattr(
        photos_mod, "find_boxes", lambda image, noun, **kwargs: [])
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "TestMake"
    gps = exif.get_ifd(0x8825)
    gps[0] = b"\x02\x03\x00\x00"
    gps[2] = (12.0, 58.0, 0.0)
    sharp_image((800, 600)).save(buf, "JPEG", exif=exif)
    resp = client.post(f"/e/{token}/s/{session_id}/photo/0/upload",
                       files={"photo": ("retake.jpg", buf.getvalue(),
                                        "image/jpeg")})
    assert resp.status_code == 200
    conn = db.connect(tmp_path / "data")
    try:
        saved = db.load_drafts(conn, session_id)[0].photo
    finally:
        conn.close()
    assert saved
    width, height = Image.open(saved).size
    assert abs(width / height - 4 / 3) < 0.02
    assert "exif" not in Image.open(saved).info


def test_change_photo_keeps_price_and_version(tmp_path, monkeypatch):
    import app.pipeline.photos as photos_mod

    monkeypatch.setattr(
        photos_mod, "find_boxes", lambda image, noun, **kwargs: [])
    client = make_client(tmp_path)
    token = create_shop(client)
    _session_id, version_id = seed_published(tmp_path, token, [draft()])
    buf = io.BytesIO()
    sharp_image((800, 600)).save(buf, "JPEG")
    conn = db.connect(tmp_path / "data")
    try:
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/item/{item_id}/photo",
                       files={"photo": ("fresh.jpg", buf.getvalue(),
                                        "image/jpeg")})
    assert resp.status_code == 200
    conn = db.connect(tmp_path / "data")
    try:
        assert db.latest_version(conn, db.shop_by_token(conn, token)["id"],
                                 published_only=True) == version_id
        item = db.version_items(conn, version_id)[0]
        assert str(item.price_lines[0].price) == "40"
        assert item.photo and Path(item.photo).is_file()
    finally:
        conn.close()


def test_review_page_shows_single_photo_and_retake(tmp_path):
    # Task 147: no "Pick the best photo" picker any more — one photo
    # plus the retake upload.
    client = make_client(tmp_path)
    token = create_shop(client)
    session_id = seed_session(tmp_path, token, [draft()])
    names = photo_with_candidates(tmp_path, token, session_id)
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Pick the best photo" not in html
    assert "data-photo-pick" not in html
    assert "data-photo-index" not in html
    assert "Take a new photo" in html
    assert "data-photo-main" in html
    assert "data-photo-retake" in html
    assert Path(names[0]).name in html
    # Task 128: retake is the only picker on its card, so it must not
    # force the camera — the phone chooser offers gallery/files instead.
    assert 'capture="environment"' not in html


# --- Part C: one CSV -----------------------------------------------------------


# The removed vendor name, split so the "no vendor text" grep stays clean.
VENDOR = "zoh" + "o"


def test_vendor_route_gone(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    _session_id, version_id = seed_published(tmp_path, token, [draft()])
    assert client.get(f"/e/{token}/v/{version_id}/{VENDOR}.csv").status_code == 404


def test_no_vendor_text_in_pages_or_templates(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    seed_published(tmp_path, token, [draft()])
    for url in (f"/e/{token}", f"/e/{token}/close"):
        assert VENDOR not in client.get(url).text.lower()
    for template in (ROOT / "app" / "web" / "templates").glob("*.html"):
        assert VENDOR not in template.read_text().lower(), template.name


def test_csv_links_with_new_labels(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    _session_id, version_id = seed_published(tmp_path, token, [draft()])
    home = client.get(f"/e/{token}").text
    assert f"/v/{version_id}/export.csv" in home
    assert ">CSV</a>" in home or ">CSV<" in home
    close = client.get(f"/e/{token}/close").text
    assert "/exports/pos.csv" in close
    assert "CSV (works with any billing software)" in close
    assert "Excel (.xlsx)" in close
    bills = client.get(f"/e/{token}/bills").text
    assert "/exports/pricelist.csv" in bills


def test_pages_render_en_ta_hi(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    seed_published(tmp_path, token, [draft()])
    conn = db.connect(tmp_path / "data")
    try:
        slug = db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        assert client.get(f"/e/{token}").status_code == 200
        assert client.get(f"/e/{token}/close").status_code == 200
        assert client.get(f"/s/{slug}").status_code == 200
