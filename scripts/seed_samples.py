"""Seed (or remove) the five labelled sample shops. No API calls, ever.

Usage:
  PYTHONPATH=$PWD .venv/bin/python scripts/seed_samples.py [--data-dir DIR]
  PYTHONPATH=$PWD .venv/bin/python scripts/seed_samples.py --remove [--data-dir DIR]
  PYTHONPATH=$PWD .venv/bin/python scripts/seed_samples.py --list [--data-dir DIR]

Seeding reads scripts/sample_data/<slug>.json -- the committed Meta
pipeline output (voice transcripts, Spark items/prices, SAM photo
methods) -- creates each shop as listed + is_demo with NO phone number
and NO UPI id, approves and publishes its list, copies the cover and
item photos into DATA_DIR/photos, and writes the seller links to
DATA_DIR/sample-shop-links.txt (tokens are never printed).

Seeding is idempotent: each sample shop is rebuilt from its JSON, so
running it twice leaves the same five shops. --remove deletes the
sample shops, their versions, sessions and photo files, leaving no
trace. A SAMPLE_SHOPS=0 env var hides them everywhere without deleting.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db
from app.models import DraftItem, Flag, PriceLine, Proof

SLUGS = (
    "selvi-vegetable-stall",
    "pandian-fruit-centre",
    "amma-keerai-kadai",
    "gupta-sabzi-wale",
    "green-basket",
)

LINKS_FILE = "sample-shop-links.txt"


def _dec(value):
    return None if value is None else Decimal(str(value))


def _draft_from_sample(raw: dict) -> DraftItem:
    proof = raw["proof"]
    return DraftItem(
        name_spoken=raw["name_spoken"],
        name_local=raw["name_local"],
        name_en=raw["name_en"],
        variety=raw["variety"],
        price_lines=[PriceLine(_dec(line["price"]),
                               _dec(line["per_amount"]),
                               line["unit"], line.get("said", ""))
                     for line in raw["price_lines"]],
        qty=_dec(raw["qty"]),
        qty_unit=raw["qty_unit"],
        proof=Proof(quote=proof["quote"],
                    turn_ids=list(proof.get("turn_ids", [])),
                    start_ms=int(proof.get("start_ms", 0)),
                    end_ms=int(proof.get("end_ms", 0)),
                    frame=None, audio_clip=None,
                    number_check=proof.get("number_check"),
                    source=proof.get("source")),
        flags=[Flag(field=flag.get("field", ""), code=flag.get("code", ""),
                    message=flag.get("message", ""),
                    options=list(flag.get("options", [])),
                    blocking=bool(flag.get("blocking", False)))
               for flag in raw.get("flags", [])],
        photo=raw["photo"],
        match_key=raw.get("match_key") or raw["name_en"],
    )


def _photo_files(doc: dict) -> list[str]:
    files = [doc["cover"]["file"], doc["cover"]["file_800"]]
    files.extend(item["photo"] for item in doc["items"])
    return files


def remove_shop(conn: sqlite3.Connection, data_dir: Path, slug: str,
                sample_data: Path) -> bool:
    """Delete one sample shop and its files; False when not present."""
    shop = db.shop_by_slug(conn, slug)
    if shop is None or not shop["is_demo"]:
        return False
    shop_id = shop["id"]
    session_ids = [row[0] for row in conn.execute(
        "SELECT id FROM sessions WHERE shop_id = ?", (shop_id,)).fetchall()]
    version_ids = [row[0] for row in conn.execute(
        "SELECT id FROM versions WHERE shop_id = ?", (shop_id,)).fetchall()]
    for table in ("quotes", "helpers", "chosen_names", "photo_checks",
                  "credit_payments", "day_closes", "name_changes",
                  "purchases", "wastage"):
        conn.execute(f"DELETE FROM {table} WHERE shop_id = ?", (shop_id,))
    for session_id in session_ids:
        conn.execute("DELETE FROM drafts WHERE session_id = ?", (session_id,))
    for version_id in version_ids:
        item_ids = [row[0] for row in conn.execute(
            "SELECT id FROM items WHERE version_id = ?", (version_id,)).fetchall()]
        for item_id in item_ids:
            conn.execute("DELETE FROM price_lines WHERE item_id = ?",
                         (item_id,))
        conn.execute("DELETE FROM items WHERE version_id = ?", (version_id,))
    conn.execute("DELETE FROM sessions WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM versions WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM shops WHERE id = ?", (shop_id,))
    conn.commit()
    for session_id in session_ids:
        shutil.rmtree(data_dir / "sessions" / str(session_id),
                      ignore_errors=True)
    doc_path = sample_data / f"{slug}.json"
    if doc_path.is_file():
        doc = json.loads(doc_path.read_text())
        for name in _photo_files(doc):
            (data_dir / "photos" / Path(name).name).unlink(missing_ok=True)
    return True


def seed_shop(conn: sqlite3.Connection, doc: dict) -> tuple[int, str]:
    """Create one sample shop from its JSON; returns (shop_id, token)."""
    shop_id, _slug, token = db.create_shop(
        conn, name=doc["name"], phone="", area=doc["area"],
        language=doc["language"], currency=doc.get("currency", "INR"),
        shop_type="vegetable", is_demo=True, listed=True)
    conn.execute("UPDATE shops SET phone = '', upi_id = NULL,"
                 " upi_payee = NULL, lat = ?, lng = ?, hours_json = ?,"
                 " cover_photo = ? WHERE id = ?",
                 (doc["lat"], doc["lng"], json.dumps(doc["hours"]),
                  doc["cover"]["file"], shop_id))
    conn.commit()
    return shop_id, token


def copy_photos(doc: dict, data_dir: Path) -> None:
    photos_dir = data_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    covers = ROOT / "app/web/static/sample/covers"
    items = ROOT / "app/web/static/sample/items"
    shutil.copy(covers / doc["cover"]["file"], photos_dir / doc["cover"]["file"])
    shutil.copy(covers / doc["cover"]["file_800"],
                photos_dir / doc["cover"]["file_800"])
    for item in doc["items"]:
        shutil.copy(items / item["photo"], photos_dir / item["photo"])


def seed(data_dir: Path, sample_data: Path, public_base_url: str) -> list[str]:
    """Seed (rebuild) all five sample shops; returns the seller links."""
    conn = db.connect(data_dir)
    try:
        links = []
        for slug in SLUGS:
            doc = json.loads((sample_data / f"{slug}.json").read_text())
            assert doc["slug"] == slug, f"slug mismatch in {slug}.json"
            remove_shop(conn, data_dir, slug, sample_data)
            shop_id, token = seed_shop(conn, doc)
            drafts = [_draft_from_sample(raw) for raw in doc["items"]]
            session_id = db.create_session(conn, shop_id, "video")
            version_id = db.approve(conn, session_id, drafts)
            db.set_published(conn, version_id, True)
            copy_photos(doc, data_dir)
            links.append(f"{doc['name']}: {public_base_url}/e/{token}")
        (data_dir / LINKS_FILE).write_text("\n".join(links) + "\n")
        return links
    finally:
        conn.close()


def remove_all(data_dir: Path, sample_data: Path) -> list[str]:
    """Remove every sample shop; returns the slugs that were present."""
    conn = db.connect(data_dir)
    try:
        gone = [slug for slug in SLUGS
                if remove_shop(conn, data_dir, slug, sample_data)]
    finally:
        conn.close()
    (data_dir / LINKS_FILE).unlink(missing_ok=True)
    return gone


def list_seeded(data_dir: Path) -> list[dict]:
    """Seeded sample shops with their published item counts."""
    conn = db.connect(data_dir)
    try:
        out = []
        for slug in SLUGS:
            shop = db.shop_by_slug(conn, slug)
            if shop is None or not shop["is_demo"]:
                continue
            version_id = db.latest_version(conn, shop["id"],
                                           published_only=True)
            out.append({"slug": slug, "name": shop["name"],
                        "items": (len(db.version_items(conn, version_id))
                                  if version_id is not None else 0)})
        return out
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Seed the five labelled sample shops (no API calls).")
    parser.add_argument("--data-dir", default=None,
                        help="DATA_DIR to seed (default: $DATA_DIR or ./data)")
    parser.add_argument("--sample-data", default=str(ROOT / "scripts/sample_data"),
                        help="directory with the <slug>.json pipeline output")
    parser.add_argument("--remove", action="store_true",
                        help="delete the sample shops, leaving no trace")
    parser.add_argument("--list", action="store_true",
                        help="list the seeded sample shops")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv()
    raw_dir = args.data_dir or os.environ.get("DATA_DIR", "./data")
    data_dir = Path(raw_dir)
    sample_data = Path(args.sample_data)
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    if args.list:
        for entry in list_seeded(data_dir):
            print(f"{entry['slug']}: {entry['name']} ({entry['items']} items)")
        return
    if args.remove:
        for slug in remove_all(data_dir, sample_data):
            print(f"removed {slug}")
        return
    links = seed(data_dir, sample_data, base_url)
    for slug in SLUGS:
        print(f"seeded {slug}")
    print(f"seller links written to {data_dir / LINKS_FILE} "
          f"({len(links)} shops)")


if __name__ == "__main__":
    main()
