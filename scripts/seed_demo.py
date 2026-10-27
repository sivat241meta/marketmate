"""Seed a listed demo shop from a pipeline run JSON.

Usage: .venv/bin/python scripts/seed_demo.py eval/out/<clip>.json
    --name "Demo Stall" --area "Koyambedu"

Creates a listed demo shop, approves the run's drafts unchanged (only when
none carries a blocking flag) and publishes. With blocking flags it stops
and lists them instead. Never prints secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.config import load_settings


def load_run_items(run_path: Path) -> list:
    """DraftItems from a run_clip.py output file, unchanged."""
    raw = json.loads(run_path.read_text())
    return [db._draft_from_json(json.dumps(entry))
            for entry in raw.get("items", [])]


def blocking_lines(items: list) -> list[str]:
    """One line per blocking flag: item, code, field and message."""
    lines = []
    for item in items:
        for flag in item.flags:
            if flag.blocking:
                lines.append(f"{item.name_en}: [{flag.code}] {flag.field}: "
                             f"{flag.message}")
        if not any(line.price is not None for line in item.price_lines):
            lines.append(f"{item.name_en}: [NO_PRICE] price: no price heard")
    return lines


def seed(run_path: Path, name: str, area: str, settings) -> tuple[str, int]:
    """Create, approve and publish the demo shop; returns (slug, version_id)."""
    items = load_run_items(run_path)
    conn = db.connect(Path(settings.data_dir))
    try:
        shop_id, slug, _ = db.create_shop(
            conn, name=name, phone="", area=area, language="ta",
            currency="INR", shop_type="vegetable",
            is_demo=True, listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        db.save_drafts(conn, session_id, items)
        version_id = db.approve(conn, session_id, items)
        db.set_published(conn, version_id, True)
    finally:
        conn.close()
    return slug, version_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed a listed demo shop from eval/out/<clip>.json")
    parser.add_argument("run_json", help="run_clip.py output file")
    parser.add_argument("--name", required=True, help="demo shop name")
    parser.add_argument("--area", required=True, help="market area text")
    args = parser.parse_args(argv)
    settings = load_settings()
    items = load_run_items(Path(args.run_json))
    if not items:
        print("Nothing to seed: no items in the run file.")
        return 1
    problems = blocking_lines(items)
    if problems:
        print("Refusing to seed: these flags need a seller decision:")
        for line in problems:
            print(f"  - {line}")
        return 1
    slug, version_id = seed(Path(args.run_json), args.name, args.area,
                            settings)
    print(f"Seeded demo shop '{args.name}' slug={slug} "
          f"version={version_id} items={len(items)}")
    print(f"Shop page: {settings.public_base_url}/s/{slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
