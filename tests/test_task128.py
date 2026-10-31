"""Task 128: phones can pick a saved video, voice note or photo.

``capture="environment"`` on a file input forces the camera on phones with
no way to choose an already-saved file. It may stay only where a
capture-free file input sits next to it (photos.html camera + gallery,
composer "Take a video" + "Upload a video").
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "web" / "templates"

CLIP_ACCEPT = ("video/*,audio/*,.opus,.ogg,.oga,.m4a,.mp3,.aac,.wav,.amr")
CLIP_LABEL_EN = ("Choose a video or voice note "
                 "(gallery, WhatsApp or record now)")

# Templates allowed to keep a capture-bearing file input: each also has a
# capture-free file input next to it (same card / same menu).
CAPTURE_OK = {"_composer.html", "photos.html"}


def _file_inputs(text: str) -> tuple[list[str], list[str]]:
    """Split a template's file inputs into (with_capture, without)."""
    tags = re.findall(r"<input\b[^>]*>", text)
    found = [t for t in tags
             if 'type="file"' in t or "type='file'" in t]
    # ui.field() macro calls that render a file input (update.html).
    calls = re.findall(r"ui\.field\((?:[^()]|\([^()]*\))*\)", text)
    found += [c for c in calls
              if 'type="file"' in c or "type='file'" in c]
    with_cap = [f for f in found if "capture" in f]
    without = [f for f in found if "capture" not in f]
    return with_cap, without


def test_no_camera_only_file_input_in_any_template():
    bad: dict[str, list[str]] = {}
    for path in sorted(TEMPLATES.glob("*.html")):
        with_cap, without = _file_inputs(path.read_text())
        if with_cap and not without:
            bad[path.name] = with_cap
    assert not bad, bad
    keepers = {p.name for p in TEMPLATES.glob("*.html")
               if _file_inputs(p.read_text())[0]}
    assert keepers == CAPTURE_OK, keepers


def test_changed_inputs_keep_hooks_without_capture():
    seller = (TEMPLATES / "seller.html").read_text()
    clip = (f'<input id="clip" class="file-hidden" type="file" '
            f'name="video" accept="{CLIP_ACCEPT}" required>')
    assert clip in seller
    item = ('<input id="item-photo-{{ item.id }}" class="file-hidden" '
            'type="file" name="photo" accept="image/*" '
            'data-item-photo-input onchange="this.form.requestSubmit()" '
            'required>')
    assert item in seller
    bills = (TEMPLATES / "bills_new.html").read_text()
    assert ('<input id="bill-photo" class="file-hidden" type="file" '
            'name="photo" accept="image/*" required>') in bills
    update = (TEMPLATES / "update.html").read_text()
    assert ('attrs={"id": "board-photo", "accept": "image/*"}') in update
    assert '"capture"' not in update
    review = (TEMPLATES / "review.html").read_text()
    retake = ('<input id="retake-{{ card.index }}" class="file-hidden" '
              'type="file" accept="image/*" data-photo-retake '
              'data-upload-url="/e/{{ token }}/s/{{ session[\'id\'] }}'
              '/photo/{{ card.index }}/upload">')
    assert review.count(retake) == 2
    quote = (TEMPLATES / "quote_start.html").read_text()
    assert ('<input id="quote-photo" class="file-hidden" type="file" '
            'name="photo" accept="image/*" required>') in quote
    for name in ("seller.html", "bills_new.html", "review.html",
                 "quote_start.html"):
        with_cap, _ = _file_inputs((TEMPLATES / name).read_text())
        assert with_cap == [], name


def test_seller_clip_form_posts_video_upload():
    src = (TEMPLATES / "seller.html").read_text()
    form = re.search(
        r'<form[^>]*action="/e/\{\{ token \}\}/upload"[^>]*>(.*?)</form>',
        src, re.DOTALL)
    assert form, "upload form missing"
    assert 'id="clip"' in form.group(1)


def _client_and_token(tmp_path, monkeypatch):
    from test_task54 import create_shop, make_client, make_draft, seed_version

    from app import db

    client, settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client)
    conn = db.connect(Path(settings.data_dir))
    try:
        shop = db.shop_by_token(conn, token)
        version_id = seed_version(conn, shop["id"], [make_draft()],
                                  published=True)
        noon = datetime.now(ZoneInfo("Asia/Kolkata")).replace(
            hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        conn.execute("UPDATE versions SET created_at = ? WHERE id = ?",
                     (noon.astimezone(UTC).isoformat(), version_id))
        conn.commit()
    finally:
        conn.close()
    return client, token


def test_seller_clip_upload_live(tmp_path, monkeypatch):
    client, token = _client_and_token(tmp_path, monkeypatch)
    html = client.get(f"/e/{token}").text
    form = re.search(
        rf'<form[^>]*action="/e/{re.escape(token)}/upload"[^>]*>(.*?)</form>',
        html, re.DOTALL)
    assert form, "upload form missing on seller page"
    body = form.group(1)
    tag = re.search(r'<input[^>]*id="clip"[^>]*>', body)
    assert tag, "clip input missing"
    assert 'name="video"' in tag.group(0)
    assert f'accept="{CLIP_ACCEPT}"' in tag.group(0)
    assert "required" in tag.group(0)
    assert "capture" not in tag.group(0)
    assert CLIP_LABEL_EN in body


def test_photos_keeps_camera_and_gallery(tmp_path):
    from test_task59 import create_shop, make_client

    src = (TEMPLATES / "photos.html").read_text()
    assert 'id="photo-camera"' in src
    assert 'id="photo-gallery"' in src
    with_cap, without = _file_inputs(src)
    assert len(with_cap) == 1 and 'id="photo-camera"' in with_cap[0]
    assert len(without) == 1 and 'id="photo-gallery"' in without[0]

    client = make_client(tmp_path)
    token = create_shop(client)
    html = client.get(f"/e/{token}/photos").text
    camera = re.search(r'<input[^>]*id="photo-camera"[^>]*>', html)
    gallery = re.search(r'<input[^>]*id="photo-gallery"[^>]*>', html)
    assert camera and gallery
    assert 'capture="environment"' in camera.group(0)
    assert "capture" not in gallery.group(0)


def test_composer_upload_video_first_and_with_take_video():
    src = (TEMPLATES / "_composer.html").read_text()
    menu = re.search(r"\{% if video_menu %\}(.*?)\{% endif %\}", src, re.DOTALL)
    assert menu, "video menu block missing"
    block = menu.group(1)
    upload_at = block.find("composer.upload_video")
    take_at = block.find("composer.take_video")
    assert upload_at != -1 and take_at != -1
    assert upload_at < take_at, "Upload a video must come first"
    labels = re.findall(
        r"<label[^>]*data-composer-video-only[^>]*>.*?</label>", block, re.DOTALL)
    assert len(labels) == 2
    assert "capture" not in labels[0]
    assert "capture" in labels[1]


def test_media_label_wording_en_ta_hi():
    from app.web.i18n import lookup, missing_keys

    assert lookup("wa.media_label", "en") == CLIP_LABEL_EN
    assert "கேலரி" in lookup("wa.media_label", "ta")
    assert "गैलरी" in lookup("wa.media_label", "hi")
    assert missing_keys() == {"ta": [], "hi": []}
