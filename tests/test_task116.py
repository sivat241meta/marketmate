"""Task 116: five labelled sample shops (voice-processed prices, photos).

Covers the deliverable gates: the shops.cover_photo migration, the
Settings cover upload, cover_url/photo_url in home_data, SAMPLE_SHOPS=0
hiding, seed idempotency + --remove cleanup, no phone/UPI on samples,
the Sample label and test-order notice in en/ta/hi, photo-credits
completeness with matching SHA-256, and the committed image size
limits. Seeding makes no API calls.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import load_settings
from scripts import seed_samples

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA = ROOT / "scripts" / "sample_data"
COVERS = ROOT / "app/web/static/sample/covers"
ITEMS = ROOT / "app/web/static/sample/items"

LANGS = ("en", "ta", "hi")


def make_client(tmp_path, lang="en", extra_env=None):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    env.update(extra_env or {})
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def seed(data_dir):
    return seed_samples.seed(Path(data_dir), SAMPLE_DATA,
                             "http://localhost:8000")


def test_migration_adds_cover_photo(tmp_path):
    db_path = tmp_path / "data" / "marketmate.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE shops (id INTEGER PRIMARY KEY, slug TEXT,"
                 " name TEXT, phone TEXT, area TEXT, language TEXT)")
    conn.commit()
    conn.close()
    conn = db.connect(tmp_path / "data")
    try:
        columns = {row[1] for row in
                   conn.execute("PRAGMA table_info(shops)").fetchall()}
        assert "cover_photo" in columns
        assert db.shop_cover({"cover_photo": None}) is None
    finally:
        conn.close()


def test_settings_cover_upload_saves_and_resizes(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/new", data={
        "name": "Cover Veg", "phone": "+914400000101", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    token = resp.headers["location"].split("/e/")[1]
    photo = Image.new("RGB", (2000, 1000), (40, 120, 60))
    buf = io.BytesIO()
    photo.save(buf, "PNG")
    resp = client.post(f"/e/{token}/settings/cover",
                       files={"cover": ("stall.png", buf.getvalue(),
                                        "image/png")})
    assert resp.status_code in (302, 303), resp.text
    assert resp.headers["location"].endswith("/settings?cover=1")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        cover = db.shop_cover(shop)
        assert cover and cover.endswith(".jpg")
    finally:
        conn.close()
    big = tmp_path / "data" / "photos" / cover
    small = big.with_name(big.stem + "-800.jpg")
    assert big.is_file() and small.is_file()
    assert Image.open(big).size[0] == 1600
    assert Image.open(small).size[0] == 800
    assert not Image.open(big).getexif()
    assert client.get(f"/m/{cover}").status_code == 200


def test_settings_cover_upload_rejects_bad_file(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/new", data={
        "name": "Cover Veg", "phone": "+914400000101", "area": "Koyambedu",
        "language": "en", "currency": "INR", "type": "vegetable"})
    token = resp.headers["location"].split("/e/")[1]
    resp = client.post(f"/e/{token}/settings/cover",
                       files={"cover": ("stall.txt", b"not a photo",
                                        "text/plain")})
    assert resp.status_code == 200
    assert "JPEG or PNG" in resp.text


def _seeded_counts(data_dir):
    conn = db.connect(Path(data_dir))
    try:
        shops = conn.execute(
            "SELECT * FROM shops WHERE is_demo = 1").fetchall()
        counts = {}
        for shop in shops:
            version_id = db.latest_version(conn, shop["id"],
                                           published_only=True)
            counts[shop["slug"]] = (len(db.version_items(conn, version_id))
                                    if version_id else 0)
        return shops, counts
    finally:
        conn.close()


def test_seed_creates_five_labelled_shops(tmp_path):
    seed(tmp_path / "data")
    shops, counts = _seeded_counts(tmp_path / "data")
    assert counts == {"selvi-vegetable-stall": 12,
                      "pandian-fruit-centre": 10,
                      "amma-keerai-kadai": 11,
                      "gupta-sabzi-wale": 10,
                      "green-basket": 10}
    for shop in shops:
        assert shop["listed"] == 1
        assert (shop["phone"] or "") == ""
        assert db.shop_upi_id(shop) in (None, "")
        assert db.shop_cover(shop) == f"{shop['slug']}.jpg"
        assert shop["lat"] is not None and shop["lng"] is not None
    photos = list((tmp_path / "data" / "photos").glob("*"))
    assert len(photos) == 53 + 10
    links = (tmp_path / "data" / seed_samples.LINKS_FILE).read_text()
    assert len(links.strip().splitlines()) == 5


def test_sample_json_has_no_blocking_flags_and_matches_scripts():
    for slug in seed_samples.SLUGS:
        doc = json.loads((SAMPLE_DATA / f"{slug}.json").read_text())
        lines = [line for line in
                 (SAMPLE_DATA / "scripts" / f"{slug}.txt").read_text()
                 .splitlines() if line.strip()]
        assert len(doc["items"]) == len(lines) == len(
            {item["photo"] for item in doc["items"]})
        for item in doc["items"]:
            assert not [flag for flag in item["flags"]
                        if flag.get("blocking")]
            assert any(line.get("price") not in (None, "")
                       for line in item["price_lines"])


def test_seed_is_idempotent(tmp_path):
    seed(tmp_path / "data")
    _, first = _seeded_counts(tmp_path / "data")
    seed(tmp_path / "data")
    shops, second = _seeded_counts(tmp_path / "data")
    assert first == second
    assert len(shops) == 5


def test_remove_leaves_no_trace(tmp_path):
    seed(tmp_path / "data")
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute(
            "SELECT id FROM shops WHERE slug = 'selvi-vegetable-stall'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO quotes (shop_id, token, source, kind, status,"
            " lines_json, total, created_at, updated_at)"
            " VALUES (?, 'tok', 'customer', 'text', 'quoted', '[]', '0',"
            " '2026-10-30', '2026-10-30')", (shop_id,))
        conn.commit()
    finally:
        conn.close()
    gone = seed_samples.remove_all(tmp_path / "data", SAMPLE_DATA)
    assert gone == list(seed_samples.SLUGS)
    conn = db.connect(tmp_path / "data")
    try:
        for table in ("shops", "sessions", "versions", "items",
                      "price_lines", "drafts", "quotes"):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        conn.close()
    assert list((tmp_path / "data" / "photos").glob("*")) == []
    assert not (tmp_path / "data" / seed_samples.LINKS_FILE).exists()
    assert seed_samples.remove_all(tmp_path / "data", SAMPLE_DATA) == []


def test_home_data_exposes_cover_and_area_photos(tmp_path):
    from app.web.home_data import home_data

    seed(tmp_path / "data")
    conn = db.connect(tmp_path / "data")
    try:
        data = home_data(conn)
    finally:
        conn.close()
    from app.web.home_data import MAX_SHOPS

    assert len(data["shops"]) == MAX_SHOPS == 4
    for card in data["shops"]:
        assert card["cover_url"] == f"/m/{card['slug']}.jpg", card
    assert data["picks"]
    for card in data["picks"]:
        assert card["cover_url"] == f"/m/{card['slug']}.jpg", card
    by_area = {entry["name"]: entry for entry in data["areas"]}
    assert len(by_area) == 5
    for entry in by_area.values():
        assert entry["photo_url"] is not None
        assert entry["photo_url"].startswith("/m/")
        assert entry["lat"] is not None and entry["lng"] is not None


def test_sample_shops_sort_after_real_shops(tmp_path):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.market.search import Query, Want, find_listings
    from app.models import DraftItem, PriceLine, Proof
    from app.web.home_data import home_data

    seed(tmp_path / "data")
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _slug, _token = db.create_shop(
            conn, name="Real Veg", phone="+914400000102",
            area="Koyambedu Market, Chennai", language="ta",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        db.approve(conn, session_id, [DraftItem(
            name_spoken="tomato", name_local="தக்காளி",
            name_en="tomato", variety=None,
            price_lines=[PriceLine(Decimal(99), Decimal(1), "kg")],
            qty=None, qty_unit=None,
            proof=Proof(quote="tomato", turn_ids=[], start_ms=0,
                        end_ms=0))])
        db.set_published(conn, db.latest_version(conn, shop_id), True)
        data = home_data(conn)
        assert [card["is_demo"] for card in data["shops"]].count(False) == 1
        assert data["shops"][0]["is_demo"] is False
        listings = find_listings(
            conn, Query(wants=[Want("tomato", None, None, None)],
                        budget=None, area=None), datetime.now(UTC))
        assert listings and listings[0].is_demo is False
    finally:
        conn.close()


def test_sample_shops_hidden_by_env(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from app.market.search import Query, Want, find_listings
    from app.web.home_data import home_data

    seed(tmp_path / "data")
    monkeypatch.setenv("SAMPLE_SHOPS", "0")
    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data"),
           "SAMPLE_SHOPS": "0"}
    settings = load_settings(env)
    conn = db.connect(tmp_path / "data")
    try:
        data = home_data(conn, settings=settings)
        assert data["shops"] == [] and data["picks"] == []
        assert db.listed_areas(conn, include_samples=False) == []
        listings = find_listings(
            conn, Query(wants=[Want("tomato", None, None, None)],
                        budget=None, area=None), datetime.now(UTC),
            settings=settings)
        assert listings == []
    finally:
        conn.close()
    client = make_client(tmp_path, extra_env={"SAMPLE_SHOPS": "0"})
    assert client.get("/").status_code == 200
    assert "Sample shop" not in client.get("/").text
    assert client.get("/s/selvi-vegetable-stall").status_code == 404


def test_sample_label_renders_in_all_languages(tmp_path):
    import re

    from app.web.i18n import t_for

    seed(tmp_path / "data")
    for lang in LANGS:
        client = make_client(tmp_path, lang=lang)
        html = client.get("/").text
        assert t_for(lang)("hp.demo") in html, lang
        assert t_for(lang)("hp.said_sample") in html, lang
    home_en = make_client(tmp_path, lang="en").get("/").text
    assert re.search(r"said today \d\d:\d\d", home_en) is None


def test_sample_shop_page_has_no_phone_or_upi(tmp_path):
    seed(tmp_path / "data")
    client = make_client(tmp_path)
    html = client.get("/s/selvi-vegetable-stall").text
    # v11 hides the call button when the shop has no phone (share +
    # quote stay), so sample pages carry no tel: link at all.
    assert "tel:" not in html
    assert "upi" not in html.lower().replace("sample", "")


def _quote_html(tmp_path, monkeypatch, lang, slug):
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [{"name": "tomato", "amount": 2, "unit": "kg",
                        "max_rate": None}],
             "budget": None, "area": None}))
    client = make_client(tmp_path, lang=lang)
    resp = client.post(f"/s/{slug}/quote?lang={lang}",
                       data={"items": "2 kg tomato",
                             "customer_name": "Test"})
    assert resp.status_code in (302, 303), resp.text
    location = resp.headers["location"]
    if "?lang=" not in location:
        location += f"?lang={lang}"
    return client.get(location).text


def test_sample_order_notice_in_all_languages(tmp_path, monkeypatch):
    from app.web.i18n import t_for

    seed(tmp_path / "data")
    # Quote pages render in English or the shop's own language.
    for lang, slug in (("en", "green-basket"),
                       ("ta", "selvi-vegetable-stall"),
                       ("hi", "gupta-sabzi-wale")):
        html = _quote_html(tmp_path, monkeypatch, lang, slug)
        assert t_for(lang)("order.sample_notice") in html, lang
        assert "data-sample-notice" in html, lang
        assert "tel:" not in html, lang


def test_photo_credits_list_every_sample_image(tmp_path):
    del tmp_path  # committed files, not the tmp dir
    credits = (ROOT / "docs/photo-credits.md").read_text()
    committed = ([f"covers/{path.name}" for path in sorted(COVERS.glob("*.jpg"))]
                 + [f"items/{path.name}" for path in sorted(ITEMS.glob("*"))])
    assert len(committed) == 10 + 53
    for entry in committed:
        disk = (COVERS if entry.startswith("covers/")
                else ITEMS) / entry.split("/", 1)[1]
        digest = hashlib.sha256(disk.read_bytes()).hexdigest()
        assert f"| {entry} |" in credits, entry
        assert digest in credits, entry


def test_sample_images_within_size_limits(tmp_path):
    del tmp_path  # committed files, not the tmp dir
    for path in sorted(COVERS.glob("*.jpg")):
        assert path.stat().st_size <= 300 * 1024, path.name
        image = Image.open(path)
        assert image.size[0] in (1600, 800), path.name
        assert image.info.get("progressive"), path.name
        assert not image.getexif(), path.name
    for path in sorted(ITEMS.glob("*")):
        assert path.suffix in (".webp", ".png"), path.name
        assert path.stat().st_size <= 120 * 1024, path.name
