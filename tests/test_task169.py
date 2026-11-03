"""Task 169: gzip text responses and cache static files.

HTML/CSS/JS and other text bodies compress when the client accepts
gzip; media, downloads, and range replies never do. /static files get
a public Cache-Control; HTML pages get none.
"""

from __future__ import annotations

import json as jsonmod
from pathlib import Path

from test_task84 import draft as market_draft
from test_task84 import make_client, seed_shop

from app import db

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"

PLAIN = {"Accept-Encoding": "identity"}


def _seed_clip(tmp_path):
    slug, _token = seed_shop(tmp_path, "Clip Store", "Koyambedu", [
        market_draft("tomato", "thakkali", "40")])
    data_dir = tmp_path / "data"
    clip = data_dir / "voice" / "clip.m4a"
    clip.parent.mkdir(parents=True, exist_ok=True)
    audio = bytes(range(256)) * 20
    clip.write_bytes(audio)
    conn = db.connect(data_dir)
    try:
        shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                            (slug,)).fetchone()
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        item = next(it for it in db.version_items(conn, version_id)
                    if it.name_en == "tomato")
        conn.execute(
            "UPDATE items SET proof = ? WHERE id = ?",
            (jsonmod.dumps({
                "quote": item.proof.quote, "turn_ids": [],
                "start_ms": 0, "end_ms": 0, "frame": None,
                "audio_clip": str(clip), "number_check": None,
                "source": None}), item.id))
        conn.commit()
        return slug, item.id, audio
    finally:
        conn.close()


def test_html_gzips_and_matches_uncompressed(tmp_path):
    client = make_client(tmp_path)
    plain = client.get("/", headers=PLAIN)
    assert plain.status_code == 200
    assert len(plain.content) >= 1000
    zipped = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert zipped.status_code == 200
    assert zipped.headers.get("content-encoding") == "gzip"
    assert "Accept-Encoding" in zipped.headers.get("vary", "")
    assert zipped.content == plain.content


def test_html_without_accept_encoding_not_compressed(tmp_path):
    resp = make_client(tmp_path).get("/", headers=PLAIN)
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") is None


def test_html_has_no_public_caching(tmp_path):
    resp = make_client(tmp_path).get("/")
    assert resp.status_code == 200
    assert "public" not in resp.headers.get("cache-control", "")


def test_small_json_not_compressed(tmp_path):
    resp = make_client(tmp_path).get(
        "/market/suggest.json", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert len(resp.content) < 1000
    assert resp.headers.get("content-encoding") is None


def test_audio_clip_never_compressed(tmp_path):
    client = make_client(tmp_path)
    slug, item_id, audio = _seed_clip(tmp_path)
    full = client.get(f"/s/{slug}/voice/{item_id}",
                      headers={"Accept-Encoding": "gzip"})
    assert full.status_code == 200
    assert full.headers.get("content-encoding") is None
    assert full.content == audio


def test_audio_range_still_206_with_content_range(tmp_path):
    client = make_client(tmp_path)
    slug, item_id, audio = _seed_clip(tmp_path)
    resp = client.get(
        f"/s/{slug}/voice/{item_id}",
        headers={"Accept-Encoding": "gzip", "Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert resp.headers.get("content-encoding") is None
    assert resp.headers["content-range"] == f"bytes 0-99/{len(audio)}"
    assert resp.content == audio[:100]


def test_xlsx_download_not_compressed(tmp_path):
    from test_task39 import create_shop, draft_tomato, seed_published, token_of
    from test_task39 import make_client as close_client

    client = close_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [draft_tomato()])
    resp = client.get(f"/e/{token}/exports/sales.xlsx?range=today",
                      headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "spreadsheet" in resp.headers["content-type"]
    assert resp.headers.get("content-encoding") is None
    assert resp.content[:2] == b"PK"


def test_static_css_cached_and_gzipped(tmp_path):
    client = make_client(tmp_path)
    plain = client.get("/static/app.css", headers=PLAIN)
    assert plain.status_code == 200
    assert plain.headers["cache-control"] == "public, max-age=3600"
    assert plain.headers.get("content-encoding") is None
    assert plain.content == APP_CSS.read_bytes()
    zipped = client.get("/static/app.css",
                        headers={"Accept-Encoding": "gzip"})
    assert zipped.headers.get("content-encoding") == "gzip"
    assert zipped.headers["cache-control"] == "public, max-age=3600"
    assert "Accept-Encoding" in zipped.headers.get("vary", "")
    assert zipped.content == APP_CSS.read_bytes()


def test_static_brand_uses_longer_cache(tmp_path):
    resp = make_client(tmp_path).get("/static/brand/logo.svg",
                                     headers=PLAIN)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=86400"
