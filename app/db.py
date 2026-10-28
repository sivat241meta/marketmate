from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, Flag, Item, PriceLine, Proof

_SESSION_STATUSES = {"uploaded", "processing", "review", "approved", "failed"}
_SESSION_KINDS = {"video", "voice_update", "photo"}

STAGES: list[tuple[str, str]] = [
    ("uploaded", "Video received"),
    ("audio", "Getting the sound out"),
    ("listening", "Listening to your prices"),
    ("items", "Finding the items"),
    ("photos", "Picking a photo for each item"),
    ("checking", "Checking every price"),
    ("ready", "Ready to check"),
]
STAGE_LABELS = dict(STAGES)
VOICE_STAGES = ["uploaded", "listening", "items", "checking", "ready"]
PHOTO_STAGES = ["uploaded", "looking", "counting", "suggesting", "ready"]
PHOTO_STAGE_LABELS = {
    "uploaded": "Photo received",
    "looking": "Looking at your photo",
    "counting": "Counting each item",
    "suggesting": "Preparing suggestions",
    "ready": "Ready to check",
}
STAGE_FRIENDLY = {
    "uploaded": "Your recording arrived safely.",
    "audio": "Getting the sound out of your video.",
    "listening": "Meta Muse Voice is turning your speech into text.",
    "items": "Muse Spark is finding the items and prices you said.",
    "photos": "Picking a photo for each item.",
    "checking": "Checking every price against what you said.",
    "ready": "Ready for you to check.",
}
PHOTO_STAGE_FRIENDLY = {
    "uploaded": "Your photo arrived safely.",
    "looking": "Muse Spark is looking at your photo.",
    "counting": "Counting each item in the photo.",
    "suggesting": "Preparing suggestions for you.",
    "ready": "Ready for you to check.",
}
_STAGE_COLUMNS = (
    ("stage", "TEXT"),
    ("stage_detail", "TEXT"),
    ("stage_started_at", "TEXT"),
    ("stages_json", "TEXT"),
)


def stages_for_kind(kind: str) -> list[str]:
    """Stage keys for a session kind; voice updates skip audio and photos."""
    if kind == "voice_update":
        return list(VOICE_STAGES)
    if kind == "photo":
        return list(PHOTO_STAGES)
    return [key for key, _ in STAGES]


def stage_label(kind: str, key: str) -> str:
    """Stepper label for a stage; photo sessions use their own wording."""
    if kind == "photo":
        return PHOTO_STAGE_LABELS.get(key, key)
    return STAGE_LABELS.get(key, key)


def stage_friendly(kind: str, key: str) -> str:
    """One-line explanation under the active step, per session kind."""
    if kind == "photo":
        return PHOTO_STAGE_FRIENDLY.get(key, "")
    return STAGE_FRIENDLY.get(key, "")


class ApprovalError(Exception):
    def __init__(self, message: str, needs_confirm=None):
        super().__init__(message)
        self.needs_confirm = needs_confirm or []


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open the app database, creating the schema on first use."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "marketmate.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
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
        CREATE TABLE IF NOT EXISTS photo_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            created_at TEXT NOT NULL, image_path TEXT NOT NULL,
            report_json TEXT NOT NULL, cost REAL NOT NULL DEFAULT 0
        );
    """)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    for name, column_type in _STAGE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {column_type}")
    item_columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    for name in ("stock_qty", "stock_unit", "stock_source"):
        if name not in item_columns:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT")
    conn.commit()
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
    now = _now()
    history = json.dumps([{"key": "uploaded", "started_at": now,
                           "ended_at": None}])
    cursor = conn.execute(
        "INSERT INTO sessions (shop_id, kind, status, created_at, stage,"
        " stage_detail, stage_started_at, stages_json)"
        " VALUES (?, ?, 'uploaded', ?, 'uploaded', '', ?, ?)",
        (shop_id, kind, now, now, history),
    )
    conn.commit()
    return cursor.lastrowid


def set_stage(conn, session_id: int, key: str, detail: str | None = None) -> None:
    """Move a session to a stage, closing the previous history entry.

    Re-setting the current stage only refreshes its detail line, so callers
    can report "item 3 of 5" without rewriting the history.
    """
    row = conn.execute("SELECT stage, stages_json FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown session: {session_id}")
    now = _now()
    history = json.loads(row["stages_json"]) if row["stages_json"] else []
    if row["stage"] == key and history:
        conn.execute("UPDATE sessions SET stage_detail = ? WHERE id = ?",
                     (detail or "", session_id))
    else:
        if history and history[-1].get("ended_at") is None:
            history[-1]["ended_at"] = now
        history.append({"key": key, "started_at": now, "ended_at": None})
        conn.execute(
            "UPDATE sessions SET stage = ?, stage_detail = ?,"
            " stage_started_at = ?, stages_json = ? WHERE id = ?",
            (key, detail or "", now, json.dumps(history), session_id))
    conn.commit()


def _parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _row_get(row, key: str, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def session_progress(row, *, now: datetime | None = None) -> dict:
    """Stepper state for a session row: stage, 1-based step, per-step states."""
    moment = _as_utc(now) if now is not None else datetime.now(UTC)
    keys = stages_for_kind(_row_get(row, "kind", "video"))
    stage = _row_get(row, "stage") or (
        "ready" if _row_get(row, "status") in ("review", "approved")
        else "uploaded")
    position = keys.index(stage) if stage in keys else 0
    history = json.loads(_row_get(row, "stages_json") or "[]")
    last_by_key = {entry["key"]: entry for entry in history}
    steps = []
    for index, key in enumerate(keys):
        state = ("done" if index < position
                 else "active" if index == position else "todo")
        seconds = 0.0
        entry = last_by_key.get(key)
        if entry is not None and state != "todo":
            start = _parse_moment(entry.get("started_at"))
            end = _parse_moment(entry.get("ended_at"))
            if end is None and state == "active":
                end = moment
            if start is not None and end is not None:
                seconds = max(0.0, (end - start).total_seconds())
        steps.append({"key": key,
                      "label": stage_label(_row_get(row, "kind", "video"), key),
                      "state": state, "seconds": round(seconds, 1)})
    elapsed = 0.0
    created = _parse_moment(_row_get(row, "created_at"))
    if created is not None:
        elapsed = max(0.0, (moment - created).total_seconds())
    return {"stage": stage, "step": position + 1, "steps": steps,
            "detail": _row_get(row, "stage_detail", "") or "",
            "elapsed_s": round(elapsed, 1)}


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
    needs: list[dict] = []
    for index, item in enumerate(items):
        blocking = [flag for flag in item.flags if flag.blocking]
        if blocking and not item.confirmed:
            needs.append({
                "index": index,
                "name": item.name_en,
                "messages": [flag.message for flag in blocking],
            })
    if needs:
        first = needs[0]
        raise ApprovalError(
            f"Please check {first['name']}: {first['messages'][0]}."
            " Play the clip, then tick I confirm.",
            needs_confirm=needs,
        )
    for item in items:
        priced = [line for line in item.price_lines if line.price is not None]
        if not priced:
            raise ApprovalError(f"no priced line for {item.name_en}")
        seen_amounts: set[tuple] = set()
        for line in priced:
            key = (line.per_amount, line.unit)
            if key in seen_amounts:
                raise ApprovalError(
                    f"two prices for the same amount on {item.name_en}: pick one")
            seen_amounts.add(key)
    conn.execute("UPDATE sessions SET status = 'approved', message = ? WHERE id = ?",
                   (f"{len(items)} items approved", session_id))
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
        priced = [line for line in item.price_lines if line.price is not None]
        conn.executemany(
            "INSERT INTO price_lines (item_id, price, per_amount, unit, said)"
            " VALUES (?, ?, ?, ?, ?)",
            [(item_id, _decimal_to_str(line.price), _decimal_to_str(line.per_amount),
              line.unit, line.said) for line in priced],
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
            stock_qty=(Decimal(_row_get(row, "stock_qty"))
                       if _row_get(row, "stock_qty") is not None else None),
            stock_unit=_row_get(row, "stock_unit"),
            stock_source=_row_get(row, "stock_source"),
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


def set_stock(conn, item_id: int, qty: int | str | None, unit: str | None,
              source: str | None) -> None:
    """Store a stock estimate for an item; source is e.g. "photo"."""
    conn.execute(
        "UPDATE items SET stock_qty = ?, stock_unit = ?, stock_source = ?"
        " WHERE id = ?",
        (str(qty) if qty is not None else None, unit, source, item_id))
    conn.commit()


def save_photo_check(conn, *, shop_id: int, image_path: str | Path,
                     report_json: str | dict, cost: float) -> int:
    """Store a photo analysis report; returns the check id."""
    if not isinstance(report_json, str):
        report_json = json.dumps(report_json)
    cursor = conn.execute(
        "INSERT INTO photo_checks (shop_id, created_at, image_path,"
        " report_json, cost) VALUES (?, ?, ?, ?, ?)",
        (shop_id, _now(), str(image_path), report_json, float(cost)),
    )
    conn.commit()
    return cursor.lastrowid


def load_photo_checks(conn, shop_id: int) -> list[sqlite3.Row]:
    """All photo checks for a shop, oldest first."""
    return conn.execute(
        "SELECT * FROM photo_checks WHERE shop_id = ? ORDER BY id",
        (shop_id,)).fetchall()


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


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _inside(data_dir: Path, candidate: Path) -> Path | None:
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(data_dir.resolve())
    except ValueError:
        return None
    return resolved


def _media_candidate(data_dir: Path, stored: str | None) -> Path | None:
    if not stored:
        return None
    raw = Path(stored)
    if raw.is_absolute():
        return _inside(data_dir, raw)
    return _inside(data_dir, data_dir.parent / raw)


def _unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
    except OSError:
        pass


def _rmtree_quietly(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
    except OSError:
        pass


def _delete_shop_rows(conn, shop_id: int) -> None:
    session_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM sessions WHERE shop_id = ?", (shop_id,))]
    version_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM versions WHERE shop_id = ?", (shop_id,))]
    for session_id in session_ids:
        conn.execute("DELETE FROM drafts WHERE session_id = ?", (session_id,))
    for version_id in version_ids:
        item_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM items WHERE version_id = ?", (version_id,))]
        for item_id in item_ids:
            conn.execute("DELETE FROM price_lines WHERE item_id = ?",
                         (item_id,))
        conn.execute("DELETE FROM items WHERE version_id = ?", (version_id,))
    conn.execute("DELETE FROM sessions WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM versions WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM shops WHERE id = ?", (shop_id,))


def _delete_shop_files(conn, data_dir: Path, shop_id: int) -> None:
    session_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM sessions WHERE shop_id = ?", (shop_id,))]
    version_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM versions WHERE shop_id = ?", (shop_id,))]
    for session_id in session_ids:
        for row in conn.execute("SELECT data FROM drafts WHERE session_id = ?",
                                (session_id,)):
            item = _draft_from_json(row["data"])
            _unlink_quietly(_media_candidate(data_dir, item.photo))
            _unlink_quietly(_media_candidate(data_dir, item.proof.frame))
            _unlink_quietly(_media_candidate(data_dir, item.proof.audio_clip))
        for photo in (data_dir / "photos").glob(f"s{session_id}_*"):
            _unlink_quietly(_inside(data_dir, photo))
        for upload in (data_dir / "uploads").glob(f"{session_id}_*"):
            _unlink_quietly(_inside(data_dir, upload))
        _rmtree_quietly(data_dir / "sessions" / str(session_id))
    for version_id in version_ids:
        for item in version_items(conn, version_id):
            _unlink_quietly(_media_candidate(data_dir, item.photo))


def _session_id_of_photo(name: str) -> int | None:
    match = re.match(r"s(\d+)_\d+\.", name)
    return int(match.group(1)) if match else None


def _session_id_of_upload(name: str) -> int | None:
    match = re.match(r"(\d+)_", name)
    return int(match.group(1)) if match else None


def _dir_newest_mtime(path: Path) -> float | None:
    """Newest mtime of the files inside; the dir's own mtime is entry churn."""
    try:
        children = list(path.rglob("*"))
    except OSError:
        return None
    newest: float | None = None
    for child in children:
        try:
            if child.is_file():
                stamp = child.stat().st_mtime
                newest = stamp if newest is None else max(newest, stamp)
        except OSError:
            continue
    if newest is None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None
    return newest


def _purge_old_media(conn, data_dir: Path, now: datetime) -> None:
    cutoff = _as_utc(now).timestamp() - 30 * 86400
    demo_shops = {row["id"] for row in
                  conn.execute("SELECT id FROM shops WHERE is_demo = 1")}
    demo_sessions = {row["id"] for row in
                     conn.execute("SELECT id, shop_id FROM sessions")
                     if row["shop_id"] in demo_shops}
    protected: set[Path] = set()
    for row in conn.execute(
            "SELECT sessions.shop_id AS shop_id, drafts.data AS data"
            " FROM drafts JOIN sessions ON sessions.id = drafts.session_id"):
        if row["shop_id"] not in demo_shops:
            continue
        item = _draft_from_json(row["data"])
        for stored in (item.photo, item.proof.frame, item.proof.audio_clip):
            candidate = _media_candidate(data_dir, stored)
            if candidate is not None:
                protected.add(candidate)
    photos = data_dir / "photos"
    if photos.is_dir():
        for path in photos.iterdir():
            if not path.is_file() or path.resolve() in protected:
                continue
            if _session_id_of_photo(path.name) in demo_sessions:
                continue
            try:
                old = path.stat().st_mtime < cutoff
            except OSError:
                continue
            if old:
                _unlink_quietly(path)
    sessions = data_dir / "sessions"
    if sessions.is_dir():
        for path in sessions.iterdir():
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                session_id = int(path.name)
            except ValueError:
                continue
            if session_id in demo_sessions:
                continue
            newest = _dir_newest_mtime(path)
            if newest is not None and newest < cutoff:
                _rmtree_quietly(path)
    uploads = data_dir / "uploads"
    if uploads.is_dir():
        for path in uploads.iterdir():
            if not path.is_file():
                continue
            if _session_id_of_upload(path.name) in demo_sessions:
                continue
            try:
                old = path.stat().st_mtime < cutoff
            except OSError:
                continue
            if old:
                _unlink_quietly(path)


def purge_expired(conn, data_dir: Path, now: datetime) -> int:
    """Delete expired judge shops with their files, plus old non-demo media.

    Media (photos, session dirs, uploads) older than 30 days is removed for
    non-demo shops; demo shops keep theirs forever. Returns the number of
    shops removed.
    """
    data_dir = Path(data_dir)
    now = _as_utc(now)
    removed = 0
    for shop in conn.execute("SELECT * FROM shops WHERE is_judge = 1"):
        if shop["expires_at"] is None:
            continue
        try:
            expires = _as_utc(datetime.fromisoformat(shop["expires_at"]))
        except ValueError:
            continue
        if expires > now:
            continue
        _delete_shop_files(conn, data_dir, shop["id"])
        _delete_shop_rows(conn, shop["id"])
        removed += 1
    conn.commit()
    _purge_old_media(conn, data_dir, now)
    return removed
