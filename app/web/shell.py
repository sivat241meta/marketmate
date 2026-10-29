"""Fresh Green shell data (Task 51): the announcement-bar status line.

Every page shows a forest announcement bar with one short status line:
seller pages show shop status + last-prices time + review count from real
data; customer shop pages show the published-prices time + area.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC
from pathlib import Path

from app import db
from app.costs import IST
from app.languages import get_language

# Price sessions sitting in "review" are what "N lists to check" counts.
_PRICE_REVIEW_KINDS = ("video", "live", "board", "voice_update")

_SKIP_SUFFIXES = (".pdf", ".csv", ".png", ".json", ".webmanifest", ".js")
_SKIP_PARTS = ("/live/ws", "/clip/")


def prices_hhmm(conn: sqlite3.Connection, shop_id: int) -> str | None:
    """IST HH:MM of the published price list, else None."""
    version_id = db.latest_version(conn, shop_id, published_only=True)
    if version_id is None:
        return None
    when = db.version_time(conn, version_id)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(IST).strftime("%H:%M")


def review_count(conn: sqlite3.Connection, shop_id: int) -> int:
    """Price sessions waiting for a review tap."""
    placeholders = ",".join("?" for _ in _PRICE_REVIEW_KINDS)
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM sessions WHERE shop_id = ?"
        f" AND status = 'review' AND kind IN ({placeholders})",
        (shop_id, *_PRICE_REVIEW_KINDS)).fetchone()
    return int(row["n"]) if row else 0


def shop_native_name(shop_lang: str) -> str:
    try:
        return get_language(shop_lang).native_name
    except KeyError:
        return "English"


def _seller_ann(conn: sqlite3.Connection, token: str) -> dict | None:
    shop, _role, _helper = db.resolve_seller_token(conn, token)
    if shop is None:
        return None
    return {
        "kind": "seller",
        "prices_time": prices_hhmm(conn, shop["id"]),
        "need": review_count(conn, shop["id"]),
        "area": shop["area"] or "",
        "slug": shop["slug"],
        "shop_lang": shop["language"] or "en",
        "shop_native": shop_native_name(shop["language"] or "en"),
    }


def _shop_row(conn: sqlite3.Connection, shop_id: int):
    return conn.execute("SELECT * FROM shops WHERE id = ?",
                        (shop_id,)).fetchone()


def _customer_ann(conn: sqlite3.Connection, shop) -> dict | None:
    if shop is None:
        return None
    return {
        "kind": "customer",
        "prices_time": prices_hhmm(conn, shop["id"]),
        "need": 0,
        "area": shop["area"] or "",
        "slug": shop["slug"],
        "shop_lang": shop["language"] or "en",
        "shop_native": shop_native_name(shop["language"] or "en"),
    }


def ann_for_path(data_dir: Path, path: str) -> dict | None:
    """Announcement data for a page path; None when it needs no lookup."""
    if not path or path.startswith("/static/"):
        return None
    if path.endswith(_SKIP_SUFFIXES) or any(p in path for p in _SKIP_PARTS):
        return None
    parts = [p for p in path.split("/") if p]
    if not parts or parts[0] not in ("e", "s", "q", "b") or len(parts) < 2:
        return None
    try:
        conn = db.connect(data_dir)
    except Exception:  # noqa: BLE001 - shell must never break the page
        return None
    try:
        head, key = parts[0], parts[1]
        if head == "e":
            return _seller_ann(conn, key)
        if head == "s":
            shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                                (key,)).fetchone()
            return _customer_ann(conn, shop)
        if head == "q":
            row = db.get_quote_by_token(conn, key)
            return _customer_ann(conn, _shop_row(conn, row["shop_id"])) if row else None
        if head == "b":
            row = db.get_quote_by_bill_token(conn, key)
            return _customer_ann(conn, _shop_row(conn, row["shop_id"])) if row else None
        return None
    except Exception:  # noqa: BLE001 - shell must never break the page
        return None
    finally:
        conn.close()
