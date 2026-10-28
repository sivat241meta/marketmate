"""Task 54: WhatsApp-first extras (failing first).

1. "Send today's prices on WhatsApp" from the latest PUBLISHED version only.
2. Voice-note upload: audio files skip frame/photo extraction.
3. Share straight from WhatsApp into the installed app (Web Share Target).
"""

import re
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal
from html import unescape
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import IST
from app.models import DraftItem, PriceLine, Proof, Transcript, Turn

OGG_EXTRACT = {"items": [
    {"name_spoken": "thakkali", "name_en": "tomato",
     "name_local": "தக்காளி", "variety": None,
     "prices": [{"said": "kilo forty", "price": 40,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None,
     "qty_unit": None, "turn_ids": [1],
     "quote": "thakkali kilo forty"},
    {"name_spoken": "vengayam", "name_en": "onion",
     "name_local": "வெங்காயம்", "variety": None,
     "prices": [{"said": "kilo thirty", "price": 30,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None,
     "qty_unit": None, "turn_ids": [2],
     "quote": "vengayam kilo thirty"},
]}


def make_client(tmp_path, monkeypatch):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    from app.web.main import create_app

    app = create_app(settings)
    monkeypatch.setattr("app.web.seller.jobs.submit",
                        lambda fn, *args: fn(*args))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client, settings


def create_shop(client, language="ta", name="T54 Store",
                phone="+914400000054"):
    response = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"].split("/e/")[1]


def make_draft(name_en="tomato", name_local="தக்காளி", price="40",
               variety=None, confirmed=True):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg", "said")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[],
                    start_ms=0, end_ms=0),
        confirmed=confirmed)


def seed_version(conn, shop_id, drafts, published=False):
    session_id = db.create_session(conn, shop_id, "video")
    version_id = db.approve(conn, session_id, drafts)
    if published:
        db.set_published(conn, version_id, True)
    return version_id


def make_ogg(path: Path, seconds: int = 3) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=880:duration={seconds}", str(path)],
        check=True, capture_output=True)
    return path


# --- build_price_message ------------------------------------------------------


def test_price_message_uses_only_published_version(tmp_path):
    from app.web.seller import build_price_message

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, _ = db.create_shop(
            conn, name="T54 Store", phone="+914400000054", area="A",
            language="ta", currency="INR", shop_type="vegetable")
        seed_version(conn, shop_id, [make_draft(price="40")], published=True)
        seed_version(conn, shop_id, [make_draft(price="999"),
                                    make_draft(name_en="brinjal",
                                               name_local="கத்தரி",
                                               price="50")])
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (shop_id,)).fetchone()
        text = build_price_message(conn, shop, "en",
                                   base_url="http://x.test")
    finally:
        conn.close()
    lines = text.splitlines()
    assert lines[0].startswith("T54 Store · today's prices · ")
    assert "தக்காளி (tomato) ₹40/kg" in text
    assert "999" not in text
    assert "brinjal" not in text
    assert lines[-1] == f"Order here: http://x.test/s/{slug}"


def test_price_message_nothing_published_is_empty(tmp_path):
    from app.web.seller import build_price_message

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="T54 Store", phone="+914400000054", area="A",
            language="ta", currency="INR", shop_type="vegetable")
        seed_version(conn, shop_id, [make_draft(price="40")])
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (shop_id,)).fetchone()
        assert build_price_message(conn, shop, "en") == ""
    finally:
        conn.close()


def test_price_message_variety_and_sold_out_at_end(tmp_path):
    from app.web.seller import build_price_message

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="T54 Store", phone="+914400000054", area="A",
            language="ta", currency="INR", shop_type="vegetable")
        version_id = seed_version(conn, shop_id, [
            make_draft(price="40", variety="Naati"),
            make_draft(name_en="onion", name_local="வெங்காயம்",
                       price="30")], published=True)
        onion = next(item for item in db.version_items(conn, version_id)
                       if item.name_en == "onion")
        db.set_sold_out(conn, onion.id, True)
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (shop_id,)).fetchone()
        text = build_price_message(conn, shop, "en",
                                   base_url="http://x.test")
    finally:
        conn.close()
    assert "தக்காளி (tomato, Naati) ₹40/kg" in text
    assert "வெங்காயம் (onion)" not in text
    lines = text.splitlines()
    assert lines[-2] == "Sold out: வெங்காயம்"
    assert lines[-1].startswith("Order here: http://x.test/s/")


def test_price_message_caps_at_60_items(tmp_path):
    from app.web.seller import build_price_message

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="T54 Store", phone="+914400000054", area="A",
            language="ta", currency="INR", shop_type="vegetable")
        drafts = [make_draft(name_en=f"item{i:02d}",
                             name_local=f"பொருள்{i:02d}",
                             price=str(10 + i)) for i in range(65)]
        seed_version(conn, shop_id, drafts, published=True)
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (shop_id,)).fetchone()
        text = build_price_message(conn, shop, "en",
                                   base_url="http://x.test")
    finally:
        conn.close()
    assert "+5 more on the link" in text
    assert "item60" not in text
    assert "item59" in text
    assert len(text) <= 3500


def test_price_message_caps_at_3500_chars(tmp_path):
    from app.web.seller import build_price_message

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="T54 Store", phone="+914400000054", area="A",
            language="ta", currency="INR", shop_type="vegetable")
        drafts = [make_draft(name_en=f"extra-long-name-{i:02d}-onion",
                             name_local="வெங்காயம்" * 20,
                             price="30") for i in range(30)]
        seed_version(conn, shop_id, drafts, published=True)
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (shop_id,)).fetchone()
        text = build_price_message(conn, shop, "en",
                                   base_url="http://x.test")
    finally:
        conn.close()
    assert len(text) <= 3500
    assert re.search(r"\+\d+ more on the link", text)
    assert text.splitlines()[-1].startswith("Order here: ")


def test_price_message_date_is_version_day(tmp_path):
    from app.web.seller import build_price_message

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="T54 Store", phone="+914400000054", area="A",
            language="ta", currency="INR", shop_type="vegetable")
        seed_version(conn, shop_id, [make_draft(price="40")], published=True)
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (shop_id,)).fetchone()
        text = build_price_message(conn, shop, "en",
                                   base_url="http://x.test")
    finally:
        conn.close()
    today = datetime.now(IST).strftime("%d %b %Y")
    assert text.splitlines()[0] == f"T54 Store · today's prices · {today}"


# --- seller home + shop pills -------------------------------------------------


def test_seller_home_pill_only_when_published(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client)
    html = client.get(f"/e/{token}").text
    assert "wa.me/?text=" not in html
    assert "Send today's prices on WhatsApp" not in html
    conn = db.connect(Path(settings.data_dir))
    try:
        shop = db.shop_by_token(conn, token)
        seed_version(conn, shop["id"], [make_draft(price="40")])
    finally:
        conn.close()
    html = client.get(f"/e/{token}").text
    assert "wa.me/?text=" not in html
    conn = db.connect(Path(settings.data_dir))
    try:
        shop = db.shop_by_token(conn, token)
        version_id = db.latest_version(conn, shop["id"])
        db.set_published(conn, version_id, True)
    finally:
        conn.close()
    html = unescape(client.get(f"/e/{token}").text)
    assert "wa.me/?text=" in html
    assert "Send today's prices on WhatsApp" in html
    assert "Copy text" in html


def test_approved_session_page_has_pill(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client)
    conn = db.connect(Path(settings.data_dir))
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, [make_draft(price="40")])
        db.set_published(conn, version_id, True)
    finally:
        conn.close()
    html = unescape(client.get(f"/e/{token}/s/{session_id}").text)
    assert "wa.me/?text=" in html
    assert "Send today's prices on WhatsApp" in html


def test_shop_page_share_list_has_no_prices(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client, name="Share Store")
    conn = db.connect(Path(settings.data_dir))
    try:
        shop = db.shop_by_token(conn, token)
        seed_version(conn, shop["id"], [make_draft(price="40")],
                     published=True)
        slug = shop["slug"]
    finally:
        conn.close()
    html = client.get(f"/s/{slug}").text
    assert "Share this list" in html
    match = re.search(r"https://wa\.me/\?text=([^\"']+)", html)
    assert match, "shop page must link wa.me/?text="
    text = unquote(match.group(1))
    assert "Share Store" in text
    assert f"/s/{slug}" in text
    assert "₹" not in text
    assert "40" not in text


# --- voice-note upload --------------------------------------------------------


def test_upload_card_accepts_audio(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client)
    html = client.get(f"/e/{token}").text
    assert 'accept="video/*,audio/*,.opus,.ogg,.oga,.m4a,.mp3,.aac,.wav,.amr"' \
        in html
    assert "Video or voice note" in html
    assert "Forward a WhatsApp voice note" in html


def test_voice_note_upload_has_no_photos(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)

    def fake_transcribe(wav, **kwargs):
        return Transcript(
            text="thakkali kilo forty vengayam kilo thirty",
            duration_ms=3000, turns=[
                Turn(id=1, start_ms=0, end_ms=1500,
                     text="thakkali kilo forty"),
                Turn(id=2, start_ms=1500, end_ms=3000,
                     text="vengayam kilo thirty")])

    def _must_not_run(*args, **kwargs):
        raise AssertionError("photo path must not run for audio")

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.extract.chat_json",
                        lambda messages, **kwargs: OGG_EXTRACT)
    monkeypatch.setattr("app.pipeline.checks.chat_json",
                        lambda messages, **kwargs: {})
    monkeypatch.setattr("app.pipeline.run.pick_best_frame", _must_not_run)
    monkeypatch.setattr("app.pipeline.run.make_photo", _must_not_run)
    token = create_shop(client)
    ogg = make_ogg(tmp_path / "note.ogg")
    response = client.post(
        f"/e/{token}/upload",
        files={"video": ("note.ogg", ogg.read_bytes(), "audio/ogg")},
        data={})
    assert response.status_code == 303
    session_id = int(response.headers["location"].rsplit("/s/", 1)[1])
    conn = db.connect(Path(settings.data_dir))
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        assert row["status"] == "review", row["message"]
        drafts = db.load_drafts(conn, session_id)
    finally:
        conn.close()
    assert len(drafts) == 2
    assert all(item.photo is None for item in drafts)
    assert all((Path(settings.data_dir) / "sessions" / str(session_id)
                / "clips" / f"item_{i}.m4a").is_file() for i in range(2))
    assert not (Path(settings.data_dir) / "sessions" / str(session_id)
                / "frames").exists()


def test_voice_note_length_limit_applies(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.pipeline.run.transcribe_wav",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("too long: must fail first")))
    token = create_shop(client)
    ogg = make_ogg(tmp_path / "long.ogg", seconds=200)
    response = client.post(
        f"/e/{token}/upload",
        files={"video": ("long.ogg", ogg.read_bytes(), "audio/ogg")},
        data={})
    assert response.status_code == 303
    session_id = int(response.headers["location"].rsplit("/s/", 1)[1])
    conn = db.connect(Path(settings.data_dir))
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
    finally:
        conn.close()
    assert row["status"] == "failed"
    assert "3 minutes" in row["message"]


# --- share target -------------------------------------------------------------


def test_manifest_has_share_target(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    payload = client.get("/manifest.webmanifest").json()
    target = payload["share_target"]
    assert target["action"] == "/share"
    assert target["method"] == "POST"
    assert target["enctype"] == "multipart/form-data"
    assert target["files"][0]["name"] == "media"


def test_share_page_renders_en_ta_hi(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    client.cookies.set("ui_lang", "en")
    english = client.get("/share")
    assert english.status_code == 200
    assert "Use this voice note" in english.text
    assert "Open your shop link once on this phone" in english.text
    client.cookies.set("ui_lang", "ta")
    tamil = client.get("/share")
    assert tamil.status_code == 200
    assert "குரல் குறிப்பை" in tamil.text
    client.cookies.set("ui_lang", "hi")
    hindi = client.get("/share")
    assert hindi.status_code == 200
    assert "वॉइस नोट" in hindi.text


def test_share_page_wires_cache_token_upload(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    html = client.get("/share").text
    assert "mm-share" in html
    assert "mm_seller_token" in html
    assert 'name="speak_lang"' in html
    assert "/upload" in html


def test_seller_pages_store_token(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    token = create_shop(client)
    html = client.get(f"/e/{token}").text
    assert "mm_seller_token" in html
    assert "localStorage" in html


def test_sw_js_check_and_offline_handlers():
    path = Path("app/web/static/sw.js")
    text = path.read_text()
    assert "mm-share" in text
    assert "/share" in text
    assert "isPricesJson" in text
    assert "isNewBillPage" in text
    assert "offline" in text.lower()
    node = shutil.which("node")
    assert node, "node is required for --check"
    result = subprocess.run([node, "--check", str(path)], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_missing_i18n_keys():
    from app.web.i18n import missing_keys

    assert missing_keys() == {"ta": [], "hi": []}
