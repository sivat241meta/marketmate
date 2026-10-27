from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, Flag, Item, PriceLine, Proof

_SESSION_STATUSES = {"uploaded", "processing", "review", "approved", "failed"}
_SESSION_KINDS = {"video", "voice_update"}


class ApprovalError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open the app database, creating the schema on first use."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "marketmate.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
            area TEXT NOT NULL, language TEXT NOT NULL, currency TEXT NOT NULL,
            type TEXT NOT NULL, edit_token_hash TEXT NOT NULL,
            is_demo INTEGER NOT NULL DEFAULT 0, is_judge INTEGER NOT NULL DEFAULT 0,
            listed INTEGER NOT NULL DEFAULT 0, expires_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            kind TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
            cost REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            item_index INTEGER NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            created_at TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL REFERENCES versions(id),
            name_ta TEXT NOT NULL, name_en TEXT NOT NULL, variety TEXT,
            qty TEXT, qty_unit TEXT, photo TEXT,
            sold_out INTEGER NOT NULL DEFAULT 0, proof TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES items(id),
            price TEXT, per_amount TEXT, unit TEXT, said TEXT NOT NULL DEFAULT ''
        );
    """)
    return conn


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "shop"


def create_shop(conn, *, name: str, phone: str, area: str, language: str,
                currency: str, shop_type: str, is_demo: bool = False,
                is_judge: bool = False, listed: bool = False) -> tuple[int, str, str]:
    """Create a shop; returns (shop_id, slug, edit_token). Only a hash is stored."""
    token = secrets.token_urlsafe(24)
    digest = hashlib.sha256(token.encode()).hexdigest()
    slug = _slugify(name)
    n = 2
    while conn.execute("SELECT 1 FROM shops WHERE slug = ?", (slug,)).fetchone():
        slug = f"{_slugify(name)}-{n}"
        n += 1
    expires_at = (_now_plus_days(7) if is_judge else None)
    cursor = conn.execute(
        "INSERT INTO shops (slug, name, phone, area, language, currency, type,"
        " edit_token_hash, is_demo, is_judge, listed, expires_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, name, phone, area, language, currency, shop_type, digest,
         int(is_demo), int(is_judge), int(listed), expires_at, _now()),
    )
    conn.commit()
    return (cursor.lastrowid, slug, token)


def _now_plus_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def shop_by_token(conn, token: str) -> sqlite3.Row | None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return conn.execute("SELECT * FROM shops WHERE edit_token_hash = ?",
                        (digest,)).fetchone()


def shop_by_slug(conn, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM shops WHERE slug = ?", (slug,)).fetchone()


def create_session(conn, shop_id: int, kind: str) -> int:
    if kind not in _SESSION_KINDS:
        raise ValueError(f"unknown session kind: {kind}")
    cursor = conn.execute(
        "INSERT INTO sessions (shop_id, kind, status, created_at)"
        " VALUES (?, ?, 'uploaded', ?)",
        (shop_id, kind, _now()),
    )
    conn.commit()
    return cursor.lastrowid


def set_session_status(conn, session_id: int, status: str, message: str = "") -> None:
    if status not in _SESSION_STATUSES:
        raise ValueError(f"unknown session status: {status}")
    conn.execute("UPDATE sessions SET status = ?, message = ? WHERE id = ?",
                 (status, message, session_id))
    conn.commit()


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _draft_to_json(item: DraftItem) -> str:
    return json.dumps({
        "name_spoken": item.name_spoken, "name_ta": item.name_ta,
        "name_en": item.name_en, "variety": item.variety,
        "price_lines": [{"price": _decimal_to_str(line.price),
                         "per_amount": _decimal_to_str(line.per_amount),
                         "unit": line.unit, "said": line.said}
                        for line in item.price_lines],
        "qty": _decimal_to_str(item.qty), "qty_unit": item.qty_unit,
        "proof": {"quote": item.proof.quote, "turn_ids": item.proof.turn_ids,
                  "start_ms": item.proof.start_ms, "end_ms": item.proof.end_ms,
                  "frame": item.proof.frame, "audio_clip": item.proof.audio_clip},
        "range_said": item.range_said,
        "flags": [{"field": flag.field, "code": flag.code, "message": flag.message,
                   "options": flag.options, "blocking": flag.blocking}
                  for flag in item.flags],
        "photo": item.photo, "condition_hint": item.condition_hint,
        "confirmed": item.confirmed,
    })


def _draft_from_json(data: str) -> DraftItem:
    raw = json.loads(data)
    proof = raw["proof"]
    return DraftItem(
        name_spoken=raw["name_spoken"], name_ta=raw["name_ta"], name_en=raw["name_en"],
        variety=raw["variety"],
        price_lines=[PriceLine(
            Decimal(line["price"]) if line["price"] is not None else None,
            Decimal(line["per_amount"]) if line["per_amount"] is not None else None,
            line["unit"], line.get("said", "")) for line in raw["price_lines"]],
        qty=Decimal(raw["qty"]) if raw["qty"] is not None else None,
        qty_unit=raw["qty_unit"],
        proof=Proof(quote=proof["quote"], turn_ids=proof["turn_ids"],
                    start_ms=proof["start_ms"], end_ms=proof["end_ms"],
                    frame=proof.get("frame"), audio_clip=proof.get("audio_clip")),
        range_said=raw["range_said"],
        flags=[Flag(field=f["field"], code=f["code"], message=f["message"],
                    options=f.get("options", []), blocking=f.get("blocking", True))
               for f in raw["flags"]],
        photo=raw["photo"], condition_hint=raw["condition_hint"],
        confirmed=raw["confirmed"],
    )


def save_drafts(conn, session_id: int, items: list[DraftItem]) -> None:
    conn.execute("DELETE FROM drafts WHERE session_id = ?", (session_id,))
    conn.executemany(
        "INSERT INTO drafts (session_id, item_index, data) VALUES (?, ?, ?)",
        [(session_id, index, _draft_to_json(item)) for index, item in enumerate(items)],
    )
    conn.commit()


def load_drafts(conn, session_id: int) -> list[DraftItem]:
    rows = conn.execute(
        "SELECT data FROM drafts WHERE session_id = ? ORDER BY item_index",
        (session_id,)).fetchall()
    return [_draft_from_json(row["data"]) for row in rows]


def approve(conn, session_id: int, items: list[DraftItem]) -> int:
    """Freeze approved drafts as a new immutable version; returns version_id."""
    for item in items:
        if any(flag.blocking for flag in item.flags) and not item.confirmed:
            raise ApprovalError(f"unconfirmed blocking flag on {item.name_en}")
        if not any(line.price is not None for line in item.price_lines):
            raise ApprovalError(f"no priced line for {item.name_en}")
    shop_id = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()["shop_id"]
    cursor = conn.execute(
        "INSERT INTO versions (shop_id, created_at, published) VALUES (?, ?, 0)",
        (shop_id, _now()),
    )
    version_id = cursor.lastrowid
    for item in items:
        item_cursor = conn.execute(
            "INSERT INTO items (version_id, name_ta, name_en, variety, qty, qty_unit,"
            " photo, sold_out, proof) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (version_id, item.name_ta, item.name_en, item.variety,
             _decimal_to_str(item.qty), item.qty_unit, item.photo,
             json.dumps({"quote": item.proof.quote, "turn_ids": item.proof.turn_ids,
                         "start_ms": item.proof.start_ms, "end_ms": item.proof.end_ms,
                         "frame": item.proof.frame,
                         "audio_clip": item.proof.audio_clip})),
        )
        item_id = item_cursor.lastrowid
        conn.executemany(
            "INSERT INTO price_lines (item_id, price, per_amount, unit, said)"
            " VALUES (?, ?, ?, ?, ?)",
            [(item_id, _decimal_to_str(line.price), _decimal_to_str(line.per_amount),
              line.unit, line.said) for line in item.price_lines],
        )
    conn.commit()
    return version_id


def latest_version(conn, shop_id: int, published_only: bool = False) -> int | None:
    query = "SELECT MAX(id) FROM versions WHERE shop_id = ?"
    params: tuple = (shop_id,)
    if published_only:
        query += " AND published = 1"
    row = conn.execute(query, params).fetchone()
    return row[0] if row[0] is not None else None


def version_items(conn, version_id: int) -> list[Item]:
    item_rows = conn.execute(
        "SELECT * FROM items WHERE version_id = ? ORDER BY id", (version_id,)).fetchall()
    items: list[Item] = []
    for row in item_rows:
        line_rows = conn.execute(
            "SELECT * FROM price_lines WHERE item_id = ? ORDER BY id",
            (row["id"],)).fetchall()
        proof = json.loads(row["proof"])
        items.append(Item(
            id=row["id"], version_id=version_id,
            name_ta=row["name_ta"], name_en=row["name_en"], variety=row["variety"],
            qty=Decimal(row["qty"]) if row["qty"] is not None else None,
            qty_unit=row["qty_unit"], photo=row["photo"],
            sold_out=bool(row["sold_out"]),
            price_lines=[PriceLine(
                Decimal(line["price"]) if line["price"] is not None else None,
                Decimal(line["per_amount"]) if line["per_amount"] is not None else None,
                line["unit"], line["said"]) for line in line_rows],
            proof=Proof(quote=proof["quote"], turn_ids=proof["turn_ids"],
                        start_ms=proof["start_ms"], end_ms=proof["end_ms"],
                        frame=proof.get("frame"), audio_clip=proof.get("audio_clip")),
        ))
    return items


def set_published(conn, version_id: int, published: bool) -> None:
    shop_id = conn.execute("SELECT shop_id FROM versions WHERE id = ?",
                           (version_id,)).fetchone()["shop_id"]
    if published:
        conn.execute("UPDATE versions SET published = 0 WHERE shop_id = ? AND id != ?",
                     (shop_id, version_id))
    conn.execute("UPDATE versions SET published = ? WHERE id = ?",
                 (int(published), version_id))
    conn.commit()


def set_sold_out(conn, item_id: int, sold_out: bool) -> None:
    conn.execute("UPDATE items SET sold_out = ? WHERE id = ?",
                 (int(sold_out), item_id))
    conn.commit()


def last_prices(conn, shop_id: int) -> dict[str, PriceLine]:
    """name_en -> first price line of the latest approved version."""
    version_id = latest_version(conn, shop_id)
    if version_id is None:
        return {}
    prices: dict[str, PriceLine] = {}
    for item in version_items(conn, version_id):
        if item.price_lines and item.name_en not in prices:
            prices[item.name_en] = item.price_lines[0]
    return prices


def version_time(conn, version_id: int) -> datetime:
    row = conn.execute("SELECT created_at FROM versions WHERE id = ?",
                       (version_id,)).fetchone()
    return datetime.fromisoformat(row["created_at"])
