from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from app.models import DraftItem, Flag, Item, PriceLine, Proof
from app.pipeline.names import repair_local_name

_log = logging.getLogger(__name__)

#: How long SQLite itself waits on a locked database before raising.
BUSY_TIMEOUT_MS = 30000

#: How long pipeline writes keep retrying on "database is locked".
LOCK_RETRY_SECONDS = 60.0
_LOCK_RETRY_FIRST_S = 0.05
_LOCK_RETRY_MAX_S = 2.0

_SESSION_STATUSES = {"uploaded", "processing", "review", "approved", "failed"}
_SESSION_KINDS = {"video", "voice_update", "photo", "quote_voice", "quote_photo",
                  "bill_voice", "bill_photo", "live", "board", "purchase"}

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
QUOTE_VOICE_STAGES = ["received", "listening", "matching", "ready"]
QUOTE_PHOTO_STAGES = ["received", "looking", "matching", "ready"]
QUOTE_STAGE_LABELS = {
    "received": "Request received",
    "listening": "Listening",
    "looking": "Looking",
    "matching": "Matching prices",
    "ready": "Quote ready",
}
QUOTE_STAGE_FRIENDLY = {
    "received": "Your request arrived safely.",
    "listening": "Muse Voice is turning your speech into text.",
    "looking": "Muse Spark is reading your photo.",
    "matching": "Matching each line to the shop's prices.",
    "ready": "Your quote is ready.",
}
LIVE_STAGES = ["listening", "items", "checking", "ready"]
LIVE_STAGE_LABELS = {
    "listening": "Listening live",
    "items": "Finding the items",
    "checking": "Checking every price",
    "ready": "Ready to check",
}
LIVE_STAGE_FRIENDLY = {
    "listening": "Listening live to your prices.",
    "items": "Muse Spark is finding the items and prices you said.",
    "checking": "Checking every price against what you said.",
    "ready": "Ready for you to check.",
}
BOARD_STAGES = ["uploaded", "looking", "items", "checking", "ready"]
BOARD_STAGE_LABELS = {
    "uploaded": "Photo received",
    "looking": "Reading your board",
    "items": "Finding the items",
    "checking": "Checking every price",
    "ready": "Ready to check",
}
BOARD_STAGE_FRIENDLY = {
    "uploaded": "Your board photo arrived safely.",
    "looking": "Muse Spark is reading your price board.",
    "items": "Finding the items and prices on your board.",
    "checking": "Checking every price from your board.",
    "ready": "Ready for you to check.",
}
PURCHASE_STAGES = ["uploaded", "listening", "items", "checking", "ready"]
PURCHASE_STAGE_LABELS = {
    "uploaded": "Recording received",
    "listening": "Listening to your purchases",
    "items": "Finding the items",
    "checking": "Checking every number",
    "ready": "Ready to check",
}
PURCHASE_STAGE_FRIENDLY = {
    "uploaded": "Your recording arrived safely.",
    "listening": "Meta Muse Voice is turning your speech into text.",
    "items": "Muse Spark is finding what you bought.",
    "checking": "Checking every number against what you said.",
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
    if kind in ("quote_voice", "bill_voice"):
        return list(QUOTE_VOICE_STAGES)
    if kind in ("quote_photo", "bill_photo"):
        return list(QUOTE_PHOTO_STAGES)
    if kind == "live":
        return list(LIVE_STAGES)
    if kind == "board":
        return list(BOARD_STAGES)
    if kind == "purchase":
        return list(PURCHASE_STAGES)
    return [key for key, _ in STAGES]


def stage_label(kind: str, key: str) -> str:
    """Stepper label for a stage; photo sessions use their own wording."""
    if kind == "photo":
        return PHOTO_STAGE_LABELS.get(key, key)
    if kind in ("quote_voice", "quote_photo", "bill_voice", "bill_photo"):
        return QUOTE_STAGE_LABELS.get(key, key)
    if kind == "live":
        return LIVE_STAGE_LABELS.get(key, STAGE_LABELS.get(key, key))
    if kind == "board":
        return BOARD_STAGE_LABELS.get(key, STAGE_LABELS.get(key, key))
    if kind == "purchase":
        return PURCHASE_STAGE_LABELS.get(key, STAGE_LABELS.get(key, key))
    return STAGE_LABELS.get(key, key)


def stage_friendly(kind: str, key: str) -> str:
    """One-line explanation under the active step, per session kind."""
    if kind == "photo":
        return PHOTO_STAGE_FRIENDLY.get(key, "")
    if kind in ("quote_voice", "quote_photo", "bill_voice", "bill_photo"):
        return QUOTE_STAGE_FRIENDLY.get(key, "")
    if kind == "live":
        return LIVE_STAGE_FRIENDLY.get(key, STAGE_FRIENDLY.get(key, ""))
    if kind == "board":
        return BOARD_STAGE_FRIENDLY.get(key, STAGE_FRIENDLY.get(key, ""))
    if kind == "purchase":
        return PURCHASE_STAGE_FRIENDLY.get(key, STAGE_FRIENDLY.get(key, ""))
    return STAGE_FRIENDLY.get(key, "")


class ApprovalError(Exception):
    def __init__(self, message: str, needs_confirm=None):
        super().__init__(message)
        self.needs_confirm = needs_confirm or []


def _now() -> str:
    return datetime.now(UTC).isoformat()


def is_locked_error(exc: BaseException) -> bool:
    """True for SQLite's "database is locked" (another connection holds it)."""
    return (isinstance(exc, sqlite3.OperationalError)
            and "database is locked" in str(exc).lower())


def run_with_lock_retry(fn, *, conn=None, timeout_s: float | None = None,
                        label: str = "db write"):
    """Run ``fn()``, retrying on "database is locked" with short backoff.

    Gives up after ``timeout_s`` (default LOCK_RETRY_SECONDS) and re-raises.
    Any other error is re-raised immediately.
    """
    if timeout_s is None:
        timeout_s = LOCK_RETRY_SECONDS
    deadline = time.monotonic() + timeout_s
    delay = _LOCK_RETRY_FIRST_S
    while True:
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not is_locked_error(exc) or time.monotonic() >= deadline:
                raise
            if conn is not None:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
            time.sleep(delay)
            delay = min(delay * 2, _LOCK_RETRY_MAX_S)


def _retry_locked(fn):
    """Retry a ``(conn, ...)`` write on "database is locked" (~60 s)."""

    @functools.wraps(fn)
    def wrapper(conn, *args, **kwargs):
        return run_with_lock_retry(lambda: fn(conn, *args, **kwargs),
                                   conn=conn, label=fn.__name__)

    return wrapper


#: Database paths whose schema this process already created/migrated.
_SCHEMA_DONE: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open the app database, creating the schema on first use.

    Schema creation and migrations run once per process per database
    path; later connections only open and set pragmas, so a plain page
    view never takes the write lock.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    # Each request gets its own connection and uses it sequentially, so this is safe.
    conn = sqlite3.connect(data_dir / "marketmate.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    key = str((data_dir / "marketmate.db").resolve())
    with _SCHEMA_LOCK:
        if key not in _SCHEMA_DONE:
            _init_schema(conn)
            _SCHEMA_DONE.add(key)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and migrate an old database. Runs once per path."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
            area TEXT NOT NULL, language TEXT NOT NULL, currency TEXT NOT NULL,
            type TEXT NOT NULL, edit_token_hash TEXT NOT NULL,
            is_demo INTEGER NOT NULL DEFAULT 0, is_judge INTEGER NOT NULL DEFAULT 0,
            listed INTEGER NOT NULL DEFAULT 0, expires_at TEXT, created_at TEXT NOT NULL,
            upi_id TEXT, upi_payee TEXT, round_bills INTEGER,
            hours_json TEXT, pincode TEXT, lat REAL, lng REAL,
            cover_photo TEXT
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
            created_at TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL REFERENCES versions(id),
            name_local TEXT NOT NULL, name_en TEXT NOT NULL, variety TEXT,
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
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            token TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
            kind TEXT NOT NULL, status TEXT NOT NULL,
            lines_json TEXT NOT NULL, total TEXT NOT NULL,
            customer_note TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, customer_phone TEXT,
            customer_name TEXT,
            payment_mode TEXT, paid_at TEXT, total_exact TEXT,
            bill_token TEXT
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            date TEXT NOT NULL, name_en TEXT NOT NULL,
            name_local TEXT NOT NULL DEFAULT '',
            qty TEXT, unit TEXT, total_cost TEXT,
            source TEXT NOT NULL DEFAULT 'typed',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wastage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            date TEXT NOT NULL, name_en TEXT NOT NULL,
            qty TEXT, unit TEXT
        );
        CREATE TABLE IF NOT EXISTS helpers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS day_closes (
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            date TEXT NOT NULL, closed_at TEXT NOT NULL,
            PRIMARY KEY (shop_id, date)
        );
        CREATE TABLE IF NOT EXISTS credit_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            customer_key TEXT NOT NULL, amount TEXT NOT NULL,
            mode TEXT NOT NULL, at TEXT NOT NULL,
            created_by TEXT
        );
        CREATE TABLE IF NOT EXISTS chosen_names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            match_key TEXT NOT NULL, variety TEXT NOT NULL DEFAULT '',
            name_local TEXT NOT NULL, name_en TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (shop_id, match_key, variety)
        );
        CREATE TABLE IF NOT EXISTS name_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL REFERENCES shops(id),
            item_id INTEGER,
            old_local TEXT NOT NULL, old_en TEXT NOT NULL,
            old_variety TEXT,
            new_local TEXT NOT NULL, new_en TEXT NOT NULL,
            new_variety TEXT,
            created_at TEXT NOT NULL
        );
    """)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    for name, column_type in _STAGE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {column_type}")
    if "base_version_id" not in existing:
        conn.execute("ALTER TABLE sessions ADD COLUMN base_version_id INTEGER")
    if "speak_lang" not in existing:
        conn.execute("ALTER TABLE sessions ADD COLUMN speak_lang TEXT")
    if "lang_retries" not in existing:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN lang_retries INTEGER"
            " NOT NULL DEFAULT 0")
    item_columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "name_ta" in item_columns and "name_local" not in item_columns:
        conn.execute("ALTER TABLE items RENAME COLUMN name_ta TO name_local")
        item_columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    for name in ("stock_qty", "stock_unit", "stock_source"):
        if name not in item_columns:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT")
    if "match_key" not in item_columns:
        conn.execute("ALTER TABLE items ADD COLUMN match_key TEXT")
    conn.execute(
        "UPDATE items SET match_key = name_en"
        " WHERE match_key IS NULL OR match_key = ''")
    for row in conn.execute(
            "SELECT id, data FROM drafts").fetchall():
        try:
            raw = json.loads(row["data"])
        except ValueError:
            continue
        if isinstance(raw, dict) and not raw.get("match_key"):
            raw["match_key"] = raw.get("name_en")
            conn.execute("UPDATE drafts SET data = ? WHERE id = ?",
                         (json.dumps(raw), row["id"]))
    quote_columns = {row[1] for row in conn.execute("PRAGMA table_info(quotes)")}
    if "customer_phone" not in quote_columns:
        conn.execute("ALTER TABLE quotes ADD COLUMN customer_phone TEXT")
    if "customer_name" not in quote_columns:
        conn.execute("ALTER TABLE quotes ADD COLUMN customer_name TEXT")
    for name, column_type in (("payment_mode", "TEXT"),
                              ("paid_at", "TEXT"),
                              ("total_exact", "TEXT"),
                              ("bill_token", "TEXT"),
                              ("client_id", "TEXT"),
                              ("priced_version_id", "INTEGER"),
                              ("price_changed", "INTEGER"),
                              ("created_by", "TEXT"),
                              ("not_understood", "TEXT")):
        if name not in quote_columns:
            conn.execute(f"ALTER TABLE quotes ADD COLUMN {name} {column_type}")
    shop_columns = {row[1] for row in conn.execute("PRAGMA table_info(shops)")}
    for name, column_type in (("upi_id", "TEXT"), ("upi_payee", "TEXT"),
                              ("round_bills", "INTEGER"),
                              ("hours_json", "TEXT"), ("pincode", "TEXT"),
                              ("lat", "REAL"), ("lng", "REAL"),
                              ("cover_photo", "TEXT")):
        if name not in shop_columns:
            conn.execute(f"ALTER TABLE shops ADD COLUMN {name} {column_type}")
    version_columns = {row[1] for row in conn.execute(
        "PRAGMA table_info(versions)")}
    if "source" not in version_columns:
        conn.execute("ALTER TABLE versions ADD COLUMN source TEXT")
    helper_columns = {row[1] for row in conn.execute(
        "PRAGMA table_info(helpers)")}
    if "can_credit" not in helper_columns:
        conn.execute("ALTER TABLE helpers ADD COLUMN can_credit INTEGER"
                     " NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_bill_token"
        " ON quotes(bill_token) WHERE bill_token IS NOT NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_client_id"
        " ON quotes(shop_id, client_id) WHERE client_id IS NOT NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_wastage_shop_date_item"
        " ON wastage(shop_id, date, name_en)")
    _repair_markless_names(conn)
    conn.commit()


def _repair_markless_names(conn) -> int:
    """One-time repair of local names stored without vowel signs.

    Runs inside connect(); each fixed row stops matching, so existing
    rows are repaired once. Names the seller chose with Task 66 — a
    chosen_names entry for the item's key, or a name_changes row for
    the item itself — are never touched, and only Tamil shops are
    repaired, since the canonical list is Tamil.
    """
    try:
        rows = conn.execute(
            "SELECT items.id AS id, items.name_en AS name_en,"
            " items.name_local AS name_local, items.variety AS variety,"
            " items.match_key AS match_key,"
            " versions.shop_id AS shop_id, shops.language AS language"
            " FROM items"
            " JOIN versions ON versions.id = items.version_id"
            " JOIN shops ON shops.id = versions.shop_id").fetchall()
    except sqlite3.Error:
        return 0
    fixed = 0
    for row in rows:
        try:
            language = row["language"]
        except (KeyError, IndexError, TypeError):
            language = None
        if language != "ta":
            continue
        try:
            local = row["name_local"]
            english = row["name_en"]
        except (KeyError, IndexError, TypeError):
            continue
        repaired = repair_local_name(english, local)
        if repaired is None or repaired == local:
            continue
        try:
            variety = row["variety"]
            match_key = row["match_key"]
            shop_id = row["shop_id"]
        except (KeyError, IndexError, TypeError):
            continue
        key = str(match_key or english or "").strip().lower()
        var = str(variety or "").strip().lower()
        try:
            chosen = conn.execute(
                "SELECT 1 FROM chosen_names WHERE shop_id = ?"
                " AND match_key = ? AND variety = ?",
                (shop_id, key, var)).fetchone()
        except sqlite3.Error:
            continue
        if chosen is not None:
            continue
        try:
            renamed = conn.execute(
                "SELECT 1 FROM name_changes WHERE item_id = ?",
                (row["id"],)).fetchone()
        except sqlite3.Error:
            continue
        if renamed is not None:
            continue
        conn.execute("UPDATE items SET name_local = ? WHERE id = ?",
                     (repaired, row["id"]))
        fixed += 1
    return fixed


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
    round_default = 1 if (currency or "").upper() == "INR" else 0
    cursor = conn.execute(
        "INSERT INTO shops (slug, name, phone, area, language, currency, type,"
        " edit_token_hash, is_demo, is_judge, listed, expires_at, created_at,"
        " upi_id, upi_payee, round_bills)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
        (slug, name, phone, area, language, currency, shop_type, digest,
         int(is_demo), int(is_judge), int(listed), expires_at, _now(),
         round_default),
    )
    conn.commit()
    return (cursor.lastrowid, slug, token)


def round_bill_total(exact: Decimal | str) -> tuple[Decimal, Decimal]:
    """Round an exact bill total to the nearest rupee (half up).

    Returns (rounded, round_off) where round_off = rounded - exact, both
    quantized to 2 decimals. E.g. 219.60 -> (220.00, 0.40).
    """
    value = exact if isinstance(exact, Decimal) else Decimal(str(exact))
    rounded = value.quantize(Decimal(1), rounding=ROUND_HALF_UP).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    off = (rounded - value).quantize(Decimal("0.01"),
                                     rounding=ROUND_HALF_UP)
    return rounded, off


def shop_rounding_enabled(shop) -> bool:
    """True when bill totals for this shop round to the nearest rupee.

    Rounding applies to INR shops only. The round_bills flag defaults on
    for INR (NULL from old DBs counts as on).
    """
    try:
        currency = (shop["currency"] or "INR").upper()
    except (KeyError, IndexError, TypeError):
        currency = "INR"
    if currency != "INR":
        return False
    try:
        flag = shop["round_bills"]
    except (KeyError, IndexError, TypeError):
        return True
    if flag is None:
        return True
    return bool(flag)


def shop_upi_id(shop) -> str | None:
    try:
        value = shop["upi_id"]
    except (KeyError, IndexError, TypeError):
        return None
    text = str(value or "").strip()
    return text or None


def shop_upi_payee(shop) -> str:
    """UPI payee name: the configured name, defaulting to the shop name."""
    try:
        payee = str(shop["upi_payee"] or "").strip()
    except (KeyError, IndexError, TypeError):
        payee = ""
    if payee:
        return payee
    try:
        return str(shop["name"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


def bill_display_totals(shop, row) -> dict:
    """Exact, rounded and round-off totals for a bill row.

    exact comes from total_exact (falling back to total for old rows);
    rounded applies shop rounding. All values are Decimals quantized
    to 2 decimals.
    """
    try:
        stored_total = row["total"]
    except (KeyError, IndexError, TypeError):
        stored_total = "0.00"
    try:
        stored_exact = row["total_exact"]
    except (KeyError, IndexError, TypeError):
        stored_exact = None
    try:
        exact = Decimal(str(stored_exact)) if stored_exact not in (
            None, "") else Decimal(str(stored_total))
    except (InvalidOperation, ValueError):
        exact = Decimal("0.00")
    exact = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if shop_rounding_enabled(shop):
        rounded, off = round_bill_total(exact)
        return {"exact": exact, "rounded": rounded, "off": off,
                "enabled": True}
    return {"exact": exact, "rounded": exact,
            "off": Decimal("0.00"), "enabled": False}


def ensure_bill_token(conn, bill_id: int) -> str:
    """Return the bill's public token, minting an unguessable one on first use."""
    row = conn.execute("SELECT id, bill_token FROM quotes WHERE id = ?",
                       (bill_id,)).fetchone()
    if row is None:
        raise ValueError("unknown bill")
    try:
        existing = row["bill_token"]
    except (KeyError, IndexError, TypeError):
        existing = None
    if existing:
        return str(existing)
    for _ in range(5):
        token = secrets.token_urlsafe(12)
        if conn.execute("SELECT 1 FROM quotes WHERE bill_token = ?",
                        (token,)).fetchone() is None:
            break
    else:
        raise ValueError("could not mint a unique bill token")
    conn.execute("UPDATE quotes SET bill_token = ?, updated_at = ? WHERE id = ?",
                 (token, _now(), row["id"]))
    conn.commit()
    return token


def get_quote_by_bill_token(conn, bill_token: str):
    return conn.execute("SELECT * FROM quotes WHERE bill_token = ?",
                        (bill_token,)).fetchone()


_UNCHANGED: object = object()


def update_shop_settings(conn, shop_id: int, *, name: str, area: str,
                         phone: str, language: str, currency: str,
                         shop_type: str, upi_id: str | None,
                         upi_payee: str | None, round_bills: bool,
                         hours_json=_UNCHANGED, pincode=_UNCHANGED,
                         lat=_UNCHANGED, lng=_UNCHANGED,
                         listed=_UNCHANGED) -> None:
    """Update editable shop settings. The slug is never changed.

    ``hours_json``/``pincode``/``lat``/``lng``/``listed`` default to
    _UNCHANGED and are only written when passed; pass None to clear one.
    """
    fields = {"name": name, "area": area, "phone": phone,
              "language": language, "currency": currency,
              "type": shop_type, "upi_id": upi_id,
              "upi_payee": upi_payee, "round_bills": int(bool(round_bills))}
    for key, value in (("hours_json", hours_json),
                       ("pincode", pincode), ("lat", lat), ("lng", lng)):
        if value is not _UNCHANGED:
            fields[key] = value
    if listed is not _UNCHANGED:
        fields["listed"] = int(bool(listed))
    columns = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE shops SET {columns} WHERE id = ?",
                 (*fields.values(), shop_id))
    conn.commit()


def listed_areas(conn, *, include_samples: bool = True) -> list[str]:
    """Distinct areas of listed shops that have a published price list."""
    query = (
        "SELECT DISTINCT s.area FROM shops s"
        " JOIN versions v ON v.shop_id = s.id AND v.published = 1"
        " WHERE s.listed = 1")
    if not include_samples:
        query += " AND s.is_demo = 0"
    rows = conn.execute(query + " ORDER BY s.area").fetchall()
    return [row[0] for row in rows if (row[0] or "").strip()]


def set_shop_cover(conn, shop_id: int, filename: str | None) -> None:
    """Set (or clear with None) a shop's stall cover photo file name."""
    conn.execute("UPDATE shops SET cover_photo = ? WHERE id = ?",
                 (filename, shop_id))
    conn.commit()


def shop_cover(shop) -> str | None:
    """A shop row's cover file name, None when missing (old rows included)."""
    try:
        value = shop["cover_photo"]
    except (KeyError, IndexError, TypeError):
        return None
    return value or None


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
    first = stages_for_kind(kind)[0]
    history = json.dumps([{"key": first, "started_at": now,
                           "ended_at": None}])
    cursor = conn.execute(
        "INSERT INTO sessions (shop_id, kind, status, created_at, stage,"
        " stage_detail, stage_started_at, stages_json)"
        " VALUES (?, ?, 'uploaded', ?, ?, '', ?, ?)",
        (shop_id, kind, now, first, now, history),
    )
    conn.commit()
    return cursor.lastrowid


@_retry_locked
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


@_retry_locked
def set_session_status(conn, session_id: int, status: str, message: str = "") -> None:
    if status not in _SESSION_STATUSES:
        raise ValueError(f"unknown session status: {status}")
    conn.execute("UPDATE sessions SET status = ?, message = ? WHERE id = ?",
                 (status, message, session_id))
    conn.commit()


def note_stage(conn, session_id: int, key: str,
               detail: str | None = None) -> None:
    """Progress-only stage move; a stuck lock is logged and skipped.

    Retries like set_stage first, but never fails the session: a
    "database is locked" that outlasts the retries is dropped.
    """
    try:
        set_stage(conn, session_id, key, detail=detail)
    except sqlite3.OperationalError as exc:
        if not is_locked_error(exc):
            raise
        _log.warning("session %s: dropping progress update (%s): locked",
                     session_id, key)


def note_status(conn, session_id: int, message: str) -> None:
    """Progress-only "processing" message; a stuck lock is logged and skipped."""
    try:
        set_session_status(conn, session_id, "processing", message)
    except sqlite3.OperationalError as exc:
        if not is_locked_error(exc):
            raise
        _log.warning("session %s: dropping progress message: locked",
                     session_id)


def fail_session(conn, session_id: int, message: str) -> None:
    """Record a terminal session failure. Never raises."""
    try:
        set_session_status(conn, session_id, "failed", message)
    except Exception as exc:  # noqa: BLE001 - reporting must not crash jobs
        _log.warning("session %s: could not record failure: %s",
                     session_id, exc)


def report_pipeline_error(conn, session_id: int, exc: BaseException,
                          message: str) -> None:
    """Record a terminal pipeline error; never raises.

    A lock error (after retries) is logged and skipped instead: only
    real pipeline errors fail a session.
    """
    if is_locked_error(exc):
        _log.warning("session %s: database stayed locked; leaving it to retry",
                     session_id)
        return
    fail_session(conn, session_id, message)


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _proof_to_json(proof: Proof) -> dict:
    return {"quote": proof.quote, "turn_ids": proof.turn_ids,
            "start_ms": proof.start_ms, "end_ms": proof.end_ms,
            "frame": proof.frame, "audio_clip": proof.audio_clip,
            "number_check": proof.number_check,
            "source": proof.source}


def _proof_from_json(proof: dict) -> Proof:
    return Proof(quote=proof["quote"], turn_ids=proof["turn_ids"],
                start_ms=proof["start_ms"], end_ms=proof["end_ms"],
                frame=proof.get("frame"), audio_clip=proof.get("audio_clip"),
                number_check=proof.get("number_check"),
                source=proof.get("source"))


def _draft_to_json(item: DraftItem) -> str:
    return json.dumps({
        "name_spoken": item.name_spoken, "name_local": item.name_local,
        "name_en": item.name_en, "variety": item.variety,
        "match_key": getattr(item, "match_key", None) or item.name_en,
        "price_lines": [{"price": _decimal_to_str(line.price),
                         "per_amount": _decimal_to_str(line.per_amount),
                         "unit": line.unit, "said": line.said}
                        for line in item.price_lines],
        "qty": _decimal_to_str(item.qty), "qty_unit": item.qty_unit,
        "proof": _proof_to_json(item.proof),
        "range_said": item.range_said,
        "flags": [{"field": flag.field, "code": flag.code, "message": flag.message,
                   "options": flag.options, "blocking": flag.blocking}
                  for flag in item.flags],
        "photo": item.photo, "photo_candidates": list(item.photo_candidates),
        "condition_hint": item.condition_hint,
        "confirmed": item.confirmed,
    })


def _draft_from_json(data: str) -> DraftItem:
    raw = json.loads(data)
    proof = raw["proof"]
    return DraftItem(
        name_spoken=raw["name_spoken"],
        name_local=raw.get("name_local", raw.get("name_ta", "")),
        name_en=raw["name_en"],
        variety=raw["variety"],
        match_key=raw.get("match_key") or raw["name_en"],
        price_lines=[PriceLine(
            Decimal(line["price"]) if line["price"] is not None else None,
            Decimal(line["per_amount"]) if line["per_amount"] is not None else None,
            line["unit"], line.get("said", "")) for line in raw["price_lines"]],
        qty=Decimal(raw["qty"]) if raw["qty"] is not None else None,
        qty_unit=raw["qty_unit"],
        proof=_proof_from_json(proof),
        range_said=raw["range_said"],
        flags=[Flag(field=f["field"], code=f["code"], message=f["message"],
                    options=f.get("options", []), blocking=f.get("blocking", True))
               for f in raw["flags"]],
        photo=raw["photo"],
        photo_candidates=list(raw.get("photo_candidates") or []),
        condition_hint=raw["condition_hint"],
        confirmed=raw["confirmed"],
    )


@_retry_locked
def save_drafts(conn, session_id: int, items: list[DraftItem]) -> None:
    row = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    if row is not None:
        apply_chosen_names(conn, row["shop_id"], items)
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


def match_key_of(item) -> str:
    """Canonical matching key: the pipeline's name, never the seller's.

    Falls back to name_en for in-memory drafts that predate Task 66.
    """
    key = getattr(item, "match_key", None) or getattr(item, "name_en", "")
    if isinstance(item, dict):
        key = item.get("match_key") or item.get("name_en", "")
    return str(key or "")


def _chosen_variety(variety: str | None) -> str:
    return str(variety or "").strip().lower()


def save_chosen_name(conn, shop_id: int, match_key: str,
                     variety: str | None, name_local: str,
                     name_en: str) -> None:
    """Remember a seller-chosen name for the next price session."""
    key = str(match_key or "").strip().lower()
    if not key:
        return
    conn.execute(
        "INSERT INTO chosen_names (shop_id, match_key, variety, name_local,"
        " name_en, updated_at) VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (shop_id, match_key, variety) DO UPDATE SET"
        " name_local = excluded.name_local, name_en = excluded.name_en,"
        " updated_at = excluded.updated_at",
        (shop_id, key, _chosen_variety(variety), name_local, name_en,
         _now()))
    conn.commit()


def chosen_name_for(conn, shop_id: int, match_key: str,
                    variety: str | None):
    """The seller's chosen names for a (matching key, variety), if any."""
    return conn.execute(
        "SELECT * FROM chosen_names WHERE shop_id = ? AND match_key = ?"
        " AND variety = ?",
        (shop_id, str(match_key or "").strip().lower(),
         _chosen_variety(variety))).fetchone()


def apply_chosen_names(conn, shop_id: int, items: list) -> set[int]:
    """Rewrite draft display names from the seller's chosen names.

    Only the display names change; the matching key, variety, prices and
    proof are untouched. Returns the indices that used a chosen name.
    """
    used: set[int] = set()
    for index, item in enumerate(items or []):
        if isinstance(item, dict):
            variety = item.get("variety")
            if not item.get("match_key"):
                item["match_key"] = item.get("name_en")
        else:
            variety = item.variety
            if not getattr(item, "match_key", None):
                item.match_key = item.name_en
        chosen = chosen_name_for(conn, shop_id, match_key_of(item), variety)
        if chosen is None:
            continue
        if isinstance(item, dict):
            item["name_local"] = chosen["name_local"]
            item["name_en"] = chosen["name_en"]
        else:
            item.name_local = chosen["name_local"]
            item.name_en = chosen["name_en"]
        used.add(index)
    return used


def uses_chosen_name(conn, shop_id: int, item) -> bool:
    """True when a draft's display names equal the seller's chosen names."""
    try:
        variety = item.variety
        local = item.name_local
        english = item.name_en
    except AttributeError:
        if not isinstance(item, dict):
            return False
        variety = item.get("variety")
        local = item.get("name_local")
        english = item.get("name_en")
    chosen = chosen_name_for(conn, shop_id, match_key_of(item), variety)
    return (chosen is not None and chosen["name_local"] == local
            and chosen["name_en"] == english)


def shop_name_aliases(conn, shop_id: int) -> list[tuple[str, str, str | None]]:
    """Seller-chosen (alias text, matching key, variety) for one shop.

    Both the local and the English chosen names match the renamed item
    in voice and typed bills.
    """
    out: list[tuple[str, str, str | None]] = []
    for row in conn.execute(
            "SELECT match_key, variety, name_local, name_en FROM chosen_names"
            " WHERE shop_id = ?", (shop_id,)).fetchall():
        variety = row["variety"] or None
        for text in (row["name_local"], row["name_en"]):
            if str(text or "").strip():
                out.append((str(text), row["match_key"], variety))
    return out


def rename_item(conn, item_id: int, name_local: str, name_en: str,
                variety: str | None) -> tuple[str, str, str | None]:
    """Rename one published item in place; prices stay untouched.

    Returns the old (name_local, name_en, variety). The matching key is
    never changed by a rename.
    """
    row = conn.execute(
        "SELECT name_local, name_en, variety FROM items WHERE id = ?",
        (item_id,)).fetchone()
    if row is None:
        raise ValueError("unknown item")
    old = (row["name_local"], row["name_en"], row["variety"])
    conn.execute(
        "UPDATE items SET name_local = ?, name_en = ?, variety = ?"
        " WHERE id = ?",
        (name_local, name_en, variety, item_id))
    conn.commit()
    return old


def log_name_change(conn, shop_id: int, item_id: int | None,
                    old: tuple[str, str, str | None],
                    new: tuple[str, str, str | None]) -> None:
    """Audit one rename: shop, item, old -> new, time. Never customer-facing."""
    conn.execute(
        "INSERT INTO name_changes (shop_id, item_id, old_local, old_en,"
        " old_variety, new_local, new_en, new_variety, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (shop_id, item_id, old[0], old[1], old[2],
         new[0], new[1], new[2], _now()))
    conn.commit()


def list_name_changes(conn, shop_id: int):
    """This shop's rename audit rows, oldest first."""
    return conn.execute(
        "SELECT * FROM name_changes WHERE shop_id = ? ORDER BY id",
        (shop_id,)).fetchall()


_MERGE_KINDS = {"video", "live", "board"}

#: Session kind -> price-source word stored on each approved version.
_SESSION_SOURCE = {"video": "video", "live": "live", "board": "board",
                   "voice_update": "voice"}


def session_speak_lang(conn, session_id: int) -> str | None:
    """Spoken-language code the seller picked, else None (use the shop)."""
    try:
        row = conn.execute("SELECT speak_lang FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return _row_get(row, "speak_lang")


@_retry_locked
def set_session_speak_lang(conn, session_id: int, code: str | None) -> None:
    conn.execute("UPDATE sessions SET speak_lang = ? WHERE id = ?",
                 (code, session_id))
    conn.commit()


def session_lang_retries(conn, session_id: int) -> int:
    """Voice re-runs used by the language guard (old rows count as 0)."""
    try:
        row = conn.execute("SELECT lang_retries FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    try:
        value = row["lang_retries"]
    except (KeyError, IndexError, TypeError):
        return 0
    return int(value) if value is not None else 0


@_retry_locked
def bump_session_lang_retries(conn, session_id: int) -> int:
    """Count one more guard re-run; returns the new total."""
    total = session_lang_retries(conn, session_id) + 1
    try:
        conn.execute("UPDATE sessions SET lang_retries = ? WHERE id = ?",
                     (total, session_id))
        conn.commit()
    except sqlite3.OperationalError as exc:
        # Old databases lack the column; a lock error retries via the wrapper.
        if "no such column" not in str(exc).lower():
            raise
    return total


def session_base_version(conn, session_id: int) -> int | None:
    """Base version id stored when review started; None for first lists."""
    try:
        row = conn.execute("SELECT base_version_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    try:
        value = row["base_version_id"]
    except (KeyError, IndexError, TypeError):
        return None
    return int(value) if value is not None else None


@_retry_locked
def set_session_base(conn, session_id: int, base_id: int | None) -> None:
    try:
        conn.execute("UPDATE sessions SET base_version_id = ? WHERE id = ?",
                     (base_id, session_id))
        conn.commit()
    except sqlite3.OperationalError as exc:
        # Old databases lack the column; a lock error retries via the wrapper.
        if "no such column" not in str(exc).lower():
            raise


@_retry_locked
def ensure_session_base(conn, session_id: int) -> int | None:
    """Pin the merge base when review starts; two tabs share one base.

    Only for video/live/board sessions. Returns the stored base id, or
    None when the shop has no version yet (first-ever session).
    """
    row = conn.execute("SELECT shop_id, kind FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    if row is None or row["kind"] not in _MERGE_KINDS:
        return None
    existing = session_base_version(conn, session_id)
    if existing is not None:
        return existing
    base = latest_version(conn, row["shop_id"])
    if base is not None:
        set_session_base(conn, session_id, base)
    return base


def session_replaces(session_item, base_item) -> bool:
    """True when a session item replaces a base item.

    Match on the matching key (never the seller's display names); when
    both carry a variety, it must match too.
    """
    sess_name = match_key_of(session_item).strip().lower()
    base_name = match_key_of(base_item).strip().lower()
    if not sess_name or sess_name != base_name:
        return False
    sess_var = str(getattr(session_item, "variety", "") or "").strip().lower()
    base_var = str(getattr(base_item, "variety", "") or "").strip().lower()
    if sess_var and base_var:
        return sess_var == base_var
    return True


def carried_from_base(session_items: list, base_items: list) -> list:
    """Base items not replaced by any session item, in base order."""
    out = []
    for base in base_items:
        if any(session_replaces(sess, base) for sess in session_items):
            continue
        out.append(base)
    return out


def insert_version_item(conn, version_id: int, name_local: str, name_en: str,
                        variety: str | None, qty, qty_unit: str | None,
                        photo: str | None, sold_out: bool, proof: Proof,
                        lines: list, match_key: str | None = None) -> None:
    """Insert one item row plus its price lines.

    Shared copy helper: approve() reuses the same logic as
    app.pipeline.update.apply_changes instead of duplicating it.
    A missing per_amount with a unit is stored as 1, never None.
    """
    fixed = []
    for line in lines:
        per = line.per_amount
        if per is None and line.unit:
            try:
                fixed.append(PriceLine(line.price, Decimal(1), line.unit, line.said))
            except Exception:  # noqa: BLE001 - keep the line as-is on odd types
                fixed.append(line)
        else:
            fixed.append(line)
    lines = fixed
    cursor = conn.execute(
        "INSERT INTO items (version_id, name_local, name_en, variety, qty, qty_unit,"
        " photo, sold_out, proof, match_key)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, name_local, name_en, variety, _decimal_to_str(qty),
         qty_unit, photo, int(bool(sold_out)),
         json.dumps(_proof_to_json(proof)),
         match_key or name_en))
    item_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO price_lines (item_id, price, per_amount, unit, said)"
        " VALUES (?, ?, ?, ?, ?)",
        [(item_id, _decimal_to_str(line.price),
          _decimal_to_str(line.per_amount), line.unit, line.said)
         for line in lines],
    )


def approve(conn, session_id: int, items: list[DraftItem],
            carried_ids: list[int] | None = None) -> int:
    """Freeze approved drafts as a new immutable version; returns version_id.

    For video/live/board sessions with a stored base version, the new
    version is the session's items plus the checked carried items copied
    exactly from the base (names, price lines, photo, proof, sold_out).
    ``carried_ids`` lists the base item ids the seller kept ticked; None
    keeps every carried item (checkboxes default checked). First-ever
    sessions (no base) behave exactly as before.
    """
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
        count_text = (
            "1 item still needs your choice or a tick"
            if len(needs) == 1
            else f"{len(needs)} items still need your choice or a tick")
        raise ApprovalError(
            f"{count_text}. Please check {first['name']}:"
            f" {first['messages'][0]}. Play the clip, then tick I confirm.",
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
    row = conn.execute("SELECT shop_id, kind FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    shop_id = row["shop_id"] if row else None
    kind = row["kind"] if row else "video"
    kept: list = []
    merge_base: int | None = None
    if shop_id is not None and kind in _MERGE_KINDS:
        base_id = session_base_version(conn, session_id)
        if base_id is not None:
            brow = conn.execute("SELECT shop_id FROM versions WHERE id = ?",
                                (base_id,)).fetchone()
            if brow is not None and brow["shop_id"] == shop_id:
                merge_base = base_id
                base_items = version_items(conn, base_id)
                carried = carried_from_base(items, base_items)
                if carried_ids is None:
                    kept = carried
                else:
                    wanted = set()
                    for raw in carried_ids:
                        try:
                            wanted.add(int(raw))
                        except (TypeError, ValueError):
                            continue
                    kept = [it for it in carried if it.id in wanted]
    total = len(items) + len(kept)
    conn.execute("UPDATE sessions SET status = 'approved', message = ? WHERE id = ?",
                   (f"{total} items approved", session_id))
    if shop_id is None:
        shop_id = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                               (session_id,)).fetchone()["shop_id"]
    source = _SESSION_SOURCE.get(kind)
    if kept and source and merge_base is not None:
        base_source = version_source(conn, merge_base)
        if base_source and base_source != source:
            source = "mixed"
    cursor = conn.execute(
        "INSERT INTO versions (shop_id, created_at, published, source)"
        " VALUES (?, ?, 0, ?)",
        (shop_id, _now(), source),
    )
    version_id = cursor.lastrowid
    for item in items:
        priced = [line for line in item.price_lines if line.price is not None]
        insert_version_item(conn, version_id, item.name_local, item.name_en,
                            item.variety, item.qty, item.qty_unit, item.photo,
                            False, item.proof, priced,
                            match_key_of(item))
    for base in kept:
        insert_version_item(conn, version_id, base.name_local, base.name_en,
                            base.variety, base.qty, base.qty_unit, base.photo,
                            base.sold_out, base.proof, list(base.price_lines),
                            match_key_of(base))
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
            name_local=row["name_local"], name_en=row["name_en"],
            variety=row["variety"],
            qty=Decimal(row["qty"]) if row["qty"] is not None else None,
            qty_unit=row["qty_unit"], photo=row["photo"],
            sold_out=bool(row["sold_out"]),
            price_lines=[PriceLine(
                Decimal(line["price"]) if line["price"] is not None else None,
                Decimal(line["per_amount"]) if line["per_amount"] is not None else None,
                line["unit"], line["said"]) for line in line_rows],
            proof=_proof_from_json(proof),
            stock_qty=(Decimal(_row_get(row, "stock_qty"))
                       if _row_get(row, "stock_qty") is not None else None),
            stock_unit=_row_get(row, "stock_unit"),
            stock_source=_row_get(row, "stock_source"),
            match_key=(_row_get(row, "match_key") or row["name_en"]),
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


def set_item_photo(conn, item_id: int, photo: str) -> None:
    """Swap an item's photo in place; prices and versions are untouched."""
    conn.execute("UPDATE items SET photo = ? WHERE id = ?", (photo, item_id))
    conn.commit()


def set_stock(conn, item_id: int, qty: int | str | None, unit: str | None,
              source: str | None) -> None:
    """Store a stock estimate for an item; source is e.g. "photo"."""
    conn.execute(
        "UPDATE items SET stock_qty = ?, stock_unit = ?, stock_source = ?"
        " WHERE id = ?",
        (str(qty) if qty is not None else None, unit, source, item_id))
    conn.commit()


@_retry_locked
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


_QUOTE_SOURCES = {"customer", "seller"}
_QUOTE_KINDS = {"quote", "bill"}
_QUOTE_STATUSES = {"new", "packing", "ready", "collected", "billed", "paid",
                   "cancelled", "credit"}

# Order status for customer orders: new -> packing -> ready -> collected,
# or cancelled from any open state. Accepted orders are kind=bill but keep
# the same flow; "billed" behaves like "new" for customer rows so older
# accepted orders can still move to packing. Walk-in bills keep billed/paid.
ORDER_TRANSITIONS = {
    "new": {"packing", "cancelled"},
    "billed": {"packing", "cancelled"},
    "packing": {"ready", "cancelled"},
    "ready": {"collected", "cancelled"},
    "collected": set(),
    "cancelled": set(),
}
ORDER_STEPS = ("new", "packing", "ready", "collected")


def _quote_line_to_dict(line) -> dict:
    return {
        "name_en": line.name_en,
        "name_local": line.name_local,
        "match_key": getattr(line, "match_key", None),
        "qty": str(line.qty),
        "unit": line.unit,
        "unit_price": str(line.unit_price) if line.unit_price is not None else None,
        "per_amount": str(line.per_amount) if line.per_amount is not None else None,
        "line_total": str(line.line_total) if line.line_total is not None else None,
        "status": line.status,
        "note": line.note,
        "variety": getattr(line, "variety", None),
    }


def _store_totals(conn, shop_id: int, kind: str,
                  exact_total) -> tuple[str, str]:
    """(total, total_exact) strings to store; bills round when enabled."""
    exact = exact_total if isinstance(exact_total, Decimal) else Decimal(
        str(exact_total))
    exact = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if kind != "bill":
        return str(exact), str(exact)
    shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                        (shop_id,)).fetchone()
    if shop is not None and shop_rounding_enabled(shop):
        rounded, _ = round_bill_total(exact)
        return str(rounded), str(exact)
    return str(exact), str(exact)


@_retry_locked
def create_quote(conn, *, shop_id: int, quote, source: str = "customer",
                 kind: str = "quote", status: str = "new",
                 customer_note: str | None = None,
                 created_by: str | None = None,
                 client_id: str | None = None,
                 priced_version_id: int | None = None,
                 price_changed: bool = False,
                 not_understood: str | None = None,
                 customer_name: str | None = None,
                 customer_phone: str | None = None) -> str:
    """Store a priced quote; returns its unguessable public token."""
    if source not in _QUOTE_SOURCES:
        raise ValueError(f"unknown quote source: {source}")
    if kind not in _QUOTE_KINDS:
        raise ValueError(f"unknown quote kind: {kind}")
    if status not in _QUOTE_STATUSES:
        raise ValueError(f"unknown quote status: {status}")
    for _ in range(5):
        token = secrets.token_urlsafe(12)
        if conn.execute("SELECT 1 FROM quotes WHERE token = ?",
                        (token,)).fetchone() is None:
            break
    else:
        raise ValueError("could not mint a unique quote token")
    now = _now()
    total, total_exact = _store_totals(conn, shop_id, kind, quote.total)
    name = (customer_name or "").strip() or None
    phone = (customer_phone or "").strip() or None
    conn.execute(
        "INSERT INTO quotes (shop_id, token, source, kind, status, lines_json,"
        " total, total_exact, customer_note, created_at, updated_at,"
        " created_by, client_id, priced_version_id, price_changed,"
        " not_understood, customer_name, customer_phone)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (shop_id, token, source, kind, status,
         json.dumps([_quote_line_to_dict(line) for line in quote.lines]),
         total, total_exact, customer_note, now, now,
         created_by, client_id, priced_version_id,
         int(bool(price_changed)), not_understood, name, phone),
    )
    conn.commit()
    return token


def set_customer_contact(conn, quote_id: int, *,
                         customer_name: str | None,
                         customer_phone: str | None) -> None:
    """Store the customer contact on an order; blank clears each field."""
    row = get_quote_by_id(conn, quote_id)
    if row is None:
        raise ValueError("unknown order")
    name = (customer_name or "").strip() or None
    phone = (customer_phone or "").strip() or None
    conn.execute("UPDATE quotes SET customer_name = ?, customer_phone = ?,"
                 " updated_at = ? WHERE id = ?",
                 (name, phone, _now(), row["id"]))
    conn.commit()


#: Open customer-order statuses a sold-out flag can land on.
OPEN_ORDER_STATUSES = ("new", "billed", "packing", "ready")


def _line_matches_item(line: dict, name_en: str, variety: str | None,
                       match_key: str | None = None) -> bool:
    if not isinstance(line, dict):
        return False
    want = {(name_en or "").strip().lower(), (match_key or "").strip().lower()}
    want.discard("")
    got = {str(line.get("name_en") or "").strip().lower(),
           str(line.get("match_key") or "").strip().lower()}
    got.discard("")
    if not want or not (want & got):
        return False
    want_var = (variety or "").strip().lower()
    got_var = str(line.get("variety") or "").strip().lower()
    return got_var == want_var


def flag_sold_out_in_open_orders(conn, shop_id: int, name_en: str,
                                 variety: str | None = None,
                                 match_key: str | None = None) -> int:
    """Flag matching lines "sold_out" on every open customer order.

    Only open orders (new/billed/packing/ready) are touched; collected,
    cancelled and paid rows keep their lines. Returns the number of
    orders flagged.
    """
    flagged = 0
    for row in list_quotes(conn, shop_id):
        try:
            source = row["source"]
        except (KeyError, IndexError, TypeError):
            source = None
        if source != "customer":
            continue
        if row["status"] not in OPEN_ORDER_STATUSES:
            continue
        try:
            lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            continue
        if not isinstance(lines, list):
            continue
        changed = False
        for line in lines:
            if (_line_matches_item(line, name_en, variety, match_key)
                    and not line.get("sold_out")):
                line["sold_out"] = True
                changed = True
        if changed:
            conn.execute("UPDATE quotes SET lines_json = ?, updated_at = ?"
                         " WHERE id = ?",
                         (json.dumps(lines), _now(), row["id"]))
            flagged += 1
    conn.commit()
    return flagged


def set_order_status(conn, quote_id: int, new_status: str) -> None:
    """Move a customer order through new -> packing -> ready -> collected.

    Accepted orders (kind=bill, source=customer) keep the same flow;
    walk-in bills never have an order status.

    Raises ValueError for unknown orders, walk-in bills, unknown
    statuses and skipped or backwards transitions.
    """
    row = get_quote_by_id(conn, quote_id)
    if row is None:
        raise ValueError("unknown order")
    try:
        source = row["source"]
    except (KeyError, IndexError, TypeError):
        source = None
    if row["kind"] == "bill" and source != "customer":
        raise ValueError("only customer orders have an order status")
    if row["kind"] not in ("quote", "bill"):
        raise ValueError("only customer orders have an order status")
    if new_status not in ORDER_TRANSITIONS:
        raise ValueError("unknown order status")
    current = row["status"]
    if current not in ORDER_TRANSITIONS:
        raise ValueError("this order can no longer change status")
    if new_status not in ORDER_TRANSITIONS[current]:
        raise ValueError(
            f"cannot move an order from {current} to {new_status}")
    conn.execute("UPDATE quotes SET status = ?, updated_at = ? WHERE id = ?",
                 (new_status, _now(), row["id"]))
    conn.commit()


def get_quote_by_client_id(conn, shop_id: int, client_id: str):
    """Fetch a synced bill by its offline client_id; None when unknown."""
    return conn.execute(
        "SELECT * FROM quotes WHERE shop_id = ? AND client_id = ?",
        (shop_id, client_id)).fetchone()


def create_helper(conn, shop_id: int, name: str) -> tuple[int, str]:
    """Create a billing-only helper; returns (helper_id, token).

    Only the token hash is stored; the token itself is shown once.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("give your helper a name")
    for _ in range(5):
        token = secrets.token_urlsafe(24)
        digest = hashlib.sha256(token.encode()).hexdigest()
        if conn.execute("SELECT 1 FROM helpers WHERE token_hash = ?",
                        (digest,)).fetchone() is None:
            break
    else:
        raise ValueError("could not mint a unique helper token")
    cursor = conn.execute(
        "INSERT INTO helpers (shop_id, name, token_hash, created_at)"
        " VALUES (?, ?, ?, ?)",
        (shop_id, cleaned, digest, _now()))
    conn.commit()
    return cursor.lastrowid, token


def list_helpers(conn, shop_id: int) -> list:
    return conn.execute(
        "SELECT id, shop_id, name, created_at,"
        " COALESCE(can_credit, 0) AS can_credit FROM helpers"
        " WHERE shop_id = ? ORDER BY id", (shop_id,)).fetchall()


def set_helper_credit(conn, shop_id: int, helper_id: int,
                      allowed: bool) -> None:
    """Grant or revoke the credit permission for one helper (default off)."""
    row = conn.execute(
        "SELECT * FROM helpers WHERE id = ? AND shop_id = ?",
        (helper_id, shop_id)).fetchone()
    if row is None:
        raise ValueError("unknown helper")
    conn.execute("UPDATE helpers SET can_credit = ? WHERE id = ?",
                 (int(bool(allowed)), row["id"]))
    conn.commit()


def helper_can_credit(conn, token: str) -> bool:
    """True when a staff token carries the credit permission.

    Owners always pass (caller checks the role first); unknown tokens fail.
    """
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    row = conn.execute("SELECT * FROM helpers WHERE token_hash = ?",
                       (digest,)).fetchone()
    if row is None:
        return False
    try:
        return bool(row["can_credit"])
    except (KeyError, IndexError, TypeError):
        return False


def remove_helper(conn, shop_id: int, helper_id: int) -> None:
    row = conn.execute(
        "SELECT * FROM helpers WHERE id = ? AND shop_id = ?",
        (helper_id, shop_id)).fetchone()
    if row is None:
        raise ValueError("unknown helper")
    conn.execute("DELETE FROM helpers WHERE id = ?", (row["id"],))
    conn.commit()


def resolve_seller_token(conn, token: str):
    """Resolve an owner or helper token.

    Returns (shop_row, role, helper_name) where role is "owner" or
    "staff"; (None, None, None) when the token is unknown.
    """
    shop = shop_by_token(conn, token)
    if shop is not None:
        return shop, "owner", None
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    helper = conn.execute("SELECT * FROM helpers WHERE token_hash = ?",
                          (digest,)).fetchone()
    if helper is None:
        return None, None, None
    shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                        (helper["shop_id"],)).fetchone()
    if shop is None:
        return None, None, None
    return shop, "staff", helper["name"]


def get_quote_by_token(conn, token: str) -> sqlite3.Row | None:
    """Fetch one quote by its public token; None when unknown."""
    return conn.execute("SELECT * FROM quotes WHERE token = ?",
                        (token,)).fetchone()


def update_quote_lines(conn, token: str, lines: list[dict]):
    """Recompute a quote's lines server side; client totals are ignored.

    Each entry supplies name_en/qty/unit; any unit_price/line_total/total
    sent by the client is discarded and rebuilt from the shop's published
    price lines. Returns the rebuilt Quote.
    """
    from app.market.quote import WantedLine, build_quote

    row = get_quote_by_token(conn, token)
    if row is None:
        raise ValueError("unknown quote")
    try:
        original = json.loads(row["lines_json"] or "[]")
    except ValueError:
        original = []
    if not isinstance(original, list):
        original = []
    if len(lines) != len(original):
        raise ValueError("quote lines are out of date; reload and try again")
    wanted: list[WantedLine] = []
    for index, raw in enumerate(lines):
        if not isinstance(raw, dict):
            raise TypeError(f"line {index + 1} is not valid")
        fallback = original[index] if isinstance(original[index], dict) else {}
        name = str(raw.get("name_en") or fallback.get("name_en") or "").strip()
        if not name:
            raise ValueError(f"line {index + 1} has no item name")
        qty_raw = raw.get("qty", fallback.get("qty"))
        try:
            qty = Decimal(str(qty_raw).strip())
        except (InvalidOperation, ValueError, AttributeError):
            raise ValueError(f"quantity for {name} does not look right")
        if not qty.is_finite() or qty <= 0 or qty > 100:
            raise ValueError(f"quantity for {name} does not look right")
        unit = raw.get("unit", fallback.get("unit"))
        if unit is not None:
            unit = str(unit).strip() or None
        variety = raw.get("variety", fallback.get("variety"))
        if variety is not None:
            variety = str(variety).strip() or None
        wanted.append(WantedLine(name_en=name, qty=qty, unit=unit,
                                 source="edit", variety=variety))
    quote = build_quote(conn, row["shop_id"], wanted)
    total, total_exact = _store_totals(conn, row["shop_id"], row["kind"],
                                       quote.total)
    conn.execute(
        "UPDATE quotes SET lines_json = ?, total = ?, total_exact = ?,"
        " updated_at = ? WHERE token = ?",
        (json.dumps([_quote_line_to_dict(line) for line in quote.lines]),
         total, total_exact, _now(), token),
    )
    conn.commit()
    return quote


def list_quotes(conn, shop_id: int, since=None) -> list[sqlite3.Row]:
    """Quotes and bills for a shop since a moment, newest first."""
    if since is None:
        return conn.execute(
            "SELECT * FROM quotes WHERE shop_id = ? ORDER BY id DESC",
            (shop_id,)).fetchall()
    marker = since.isoformat() if isinstance(since, datetime) else str(since)
    return conn.execute(
        "SELECT * FROM quotes WHERE shop_id = ? AND created_at >= ?"
        " ORDER BY id DESC",
        (shop_id, marker)).fetchall()


def get_quote_by_id(conn, quote_id: int) -> sqlite3.Row | None:
    """Fetch one quote or bill by its integer id; None when unknown."""
    try:
        key = int(quote_id)
    except (TypeError, ValueError):
        return None
    return conn.execute("SELECT * FROM quotes WHERE id = ?",
                        (key,)).fetchone()


def _wanted_from_raw(raw: dict, fallback: dict, index: int):
    from app.market.quote import WantedLine

    if not isinstance(raw, dict):
        raise TypeError(f"line {index + 1} is not valid")
    if not isinstance(fallback, dict):
        fallback = {}
    name = str(raw.get("name_en") or fallback.get("name_en") or "").strip()
    if not name:
        raise ValueError(f"line {index + 1} has no item name")
    amount_raw = raw.get("amount", fallback.get("amount"))
    amount_text = str(amount_raw or "").strip() if amount_raw is not None else ""
    variety = raw.get("variety", fallback.get("variety"))
    if variety is not None:
        variety = str(variety).strip() or None
    if amount_text:
        try:
            amount = Decimal(amount_text)
        except (InvalidOperation, ValueError, AttributeError):
            raise ValueError(
                f"amount for {name} does not look right") from None
        if amount.is_nan() or amount <= 0:
            raise ValueError(f"amount for {name} does not look right")
        return WantedLine(name_en=name, qty=None, unit=None, source="edit",
                          amount=amount, variety=variety)
    qty_raw = raw.get("qty", fallback.get("qty"))
    try:
        qty = Decimal(str(qty_raw).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError(f"quantity for {name} does not look right") from None
    if qty.is_nan() or qty <= 0:
        raise ValueError(f"quantity for {name} does not look right")
    unit = raw.get("unit", fallback.get("unit"))
    if unit is not None:
        unit = str(unit).strip() or None
    return WantedLine(name_en=name, qty=qty, unit=unit, source="edit",
                      variety=variety)


PAID_LOCK_MESSAGE = "This bill is paid. Tap 'Change bill' to reopen it."


def _ensure_bill_editable(row) -> None:
    try:
        status = row["status"]
    except (KeyError, IndexError, TypeError):
        return
    if status in ("paid", "credit"):
        raise ValueError(PAID_LOCK_MESSAGE)


def rebuild_bill(conn, bill_id: int, wanted) -> object:
    """Reprice a bill's wanted lines from the shop list; returns the Quote."""
    from app.market.quote import build_quote

    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    _ensure_bill_editable(row)
    quote = build_quote(conn, row["shop_id"], list(wanted))
    total, total_exact = _store_totals(conn, row["shop_id"], "bill",
                                       quote.total)
    conn.execute(
        "UPDATE quotes SET lines_json = ?, total = ?, total_exact = ?,"
        " updated_at = ? WHERE id = ?",
        (json.dumps([_quote_line_to_dict(line) for line in quote.lines]),
         total, total_exact, _now(), row["id"]),
    )
    conn.commit()
    return quote


def update_bill_lines(conn, bill_id: int, lines: list[dict]):
    """Recompute a bill's quantities server side; client totals ignored."""
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    _ensure_bill_editable(row)
    try:
        original = json.loads(row["lines_json"] or "[]")
    except ValueError:
        original = []
    if not isinstance(original, list):
        original = []
    if len(lines) != len(original):
        raise ValueError("bill lines are out of date; reload and try again")
    wanted = [_wanted_from_raw(raw, original[index], index)
              for index, raw in enumerate(lines)]
    return rebuild_bill(conn, row["id"], wanted)


def add_bill_line(conn, bill_id: int, raw: dict):
    """Append one line to a bill, repriced from the shop list."""
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    _ensure_bill_editable(row)
    try:
        original = json.loads(row["lines_json"] or "[]")
    except ValueError:
        original = []
    if not isinstance(original, list):
        original = []
    wanted = [_wanted_from_raw(
        {"name_en": line.get("name_en"), "qty": line.get("qty"),
         "unit": line.get("unit"), "variety": line.get("variety")},
        {}, index) for index, line in enumerate(original)
        if isinstance(line, dict)]
    wanted.append(_wanted_from_raw(raw, {}, len(wanted)))
    return rebuild_bill(conn, row["id"], wanted)


def remove_bill_line(conn, bill_id: int, index: int):
    """Remove one line from a bill by index, repriced from the shop list."""
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    _ensure_bill_editable(row)
    try:
        original = json.loads(row["lines_json"] or "[]")
    except ValueError:
        original = []
    if not isinstance(original, list):
        original = []
    try:
        number = int(index)
    except (TypeError, ValueError):
        raise ValueError("that line does not exist") from None
    if not 0 <= number < len(original):
        raise ValueError("that line does not exist")
    kept = [line for pos, line in enumerate(original) if pos != number]
    wanted = [_wanted_from_raw(
        {"name_en": line.get("name_en"), "qty": line.get("qty"),
         "unit": line.get("unit"), "variety": line.get("variety")},
        {}, pos) for pos, line in enumerate(kept)
        if isinstance(line, dict)]
    return rebuild_bill(conn, row["id"], wanted)


def accept_quote_as_bill(conn, bill_id: int) -> None:
    """Accept a customer order: billable at once, packing flow preserved.

    Customer rows become kind=bill so payment works, but keep their order
    identity: a "new" order moves straight to "packing", otherwise the
    current order status is kept. The seller bill page shows Order #N with
    both the Packing → Ready → Collected buttons and the payment buttons.
    """
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    try:
        exact_raw = row["total_exact"]
    except (KeyError, IndexError, TypeError):
        exact_raw = None
    base = exact_raw if exact_raw not in (None, "") else row["total"]
    total, total_exact = _store_totals(conn, row["shop_id"], "bill", base)
    try:
        current = row["status"]
    except (KeyError, IndexError, TypeError):
        current = "new"
    if current == "new":
        current = "packing"
    conn.execute("UPDATE quotes SET kind = 'bill', status = ?,"
                 " total = ?, total_exact = ?, updated_at = ? WHERE id = ?",
                 (current, total, total_exact, _now(), row["id"]))
    conn.commit()


_PAYMENT_MODES = {"cash", "upi", "card"}


def mark_bill_paid(conn, bill_id: int,
                   payment_mode: str | None = "cash") -> None:
    """Mark a bill paid; only bills can be paid. Stores mode and paid_at."""
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    if row["kind"] != "bill":
        raise ValueError("only bills can be marked paid; accept it first")
    mode = (payment_mode or "cash").strip().lower()
    if mode not in _PAYMENT_MODES:
        raise ValueError("unknown payment mode")
    now = _now()
    conn.execute("UPDATE quotes SET status = 'paid', payment_mode = ?,"
                 " paid_at = ?, updated_at = ? WHERE id = ?",
                 (mode, now, now, row["id"]))
    conn.commit()


def close_day(conn, shop_id: int, day: str) -> str:
    """Record the day as closed now; re-closing updates the time."""
    now = _now()
    conn.execute(
        "INSERT INTO day_closes (shop_id, date, closed_at)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT (shop_id, date) DO UPDATE SET closed_at = ?",
        (shop_id, day, now, now))
    conn.commit()
    return now


def day_closed_at(conn, shop_id: int, day: str) -> str | None:
    """UTC iso timestamp of the recorded close, or None when still open."""
    row = conn.execute(
        "SELECT closed_at FROM day_closes WHERE shop_id = ? AND date = ?",
        (shop_id, day)).fetchone()
    return row["closed_at"] if row is not None else None


def reopen_bill(conn, bill_id: int) -> None:
    """Reopen a paid/credit bill for corrections: billed, payment cleared."""
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    if row["status"] not in ("paid", "credit"):
        raise ValueError("only paid bills can be reopened")
    conn.execute("UPDATE quotes SET status = 'billed', payment_mode = NULL,"
                 " paid_at = NULL, updated_at = ? WHERE id = ?",
                 (_now(), row["id"]))
    conn.commit()


def set_bill_phone(conn, bill_id: int, phone: str | None) -> str | None:
    """Store the bill's customer phone; blank clears it. Returns stored value."""
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    text = (phone or "").strip()
    if not text:
        conn.execute("UPDATE quotes SET customer_phone = NULL,"
                     " updated_at = ? WHERE id = ?",
                     (_now(), row["id"]))
        conn.commit()
        return None
    digits = re.sub(r"\D", "", text)
    if not 7 <= len(digits) <= 15:
        raise ValueError("that phone number does not look right")
    stored = text
    conn.execute("UPDATE quotes SET customer_phone = ?, updated_at = ?"
                 " WHERE id = ?",
                 (stored, _now(), row["id"]))
    conn.commit()
    return stored


_CREDIT_PHONE_STRIP_RE = re.compile(r"[\s\-()]+")


def normalize_credit_phone(raw: str | None) -> str:
    """Normalise a credit phone to 10-digit Indian form or +country digits.

    Raises ValueError when blank or invalid.
    """
    text = _CREDIT_PHONE_STRIP_RE.sub("", str(raw or "")).strip()
    if re.fullmatch(r"[6-9]\d{9}", text):
        return text
    if re.fullmatch(r"\+\d{7,15}", text):
        return text
    raise ValueError("that phone number does not look right")


def clean_credit_name(raw: str | None) -> str:
    return str(raw or "").strip()


def mark_bill_credit(conn, bill_id: int, customer_name: str | None,
                     customer_phone: str | None) -> str:
    """Give a bill on credit (udhaar): status + payment_mode become credit.

    Needs the customer's name (1-40 chars) and a normalised phone. The bill
    locks like a paid bill. Returns the customer_key (normalised phone).
    """
    row = get_quote_by_id(conn, bill_id)
    if row is None:
        raise ValueError("unknown bill")
    if row["kind"] != "bill":
        raise ValueError("only bills can be given on credit; accept it first")
    if row["status"] in ("paid", "credit"):
        raise ValueError(PAID_LOCK_MESSAGE)
    name = clean_credit_name(customer_name)
    if not 1 <= len(name) <= 40:
        raise ValueError("give the customer's name for a credit bill")
    key = normalize_credit_phone(customer_phone)
    now = _now()
    conn.execute(
        "UPDATE quotes SET status = 'credit', payment_mode = 'credit',"
        " paid_at = ?, customer_name = ?, customer_phone = ?,"
        " updated_at = ? WHERE id = ?",
        (now, name, key, now, row["id"]))
    conn.commit()
    return key


def list_credit_payments(conn, shop_id: int,
                         customer_key: str | None = None) -> list:
    """Credit collections for a shop, oldest first (optionally one customer)."""
    if customer_key is None:
        return conn.execute(
            "SELECT * FROM credit_payments WHERE shop_id = ?"
            " ORDER BY id", (shop_id,)).fetchall()
    return conn.execute(
        "SELECT * FROM credit_payments WHERE shop_id = ? AND customer_key = ?"
        " ORDER BY id", (shop_id, customer_key)).fetchall()


def credit_bills_for_customer(conn, shop_id: int,
                              customer_key: str) -> list:
    """Credit bills for one normalised phone, oldest first."""
    out = []
    for row in list_quotes(conn, shop_id):
        if row["kind"] != "bill" or row["status"] != "credit":
            continue
        try:
            phone = str(row["customer_phone"] or "").strip()
        except (KeyError, IndexError, TypeError):
            phone = ""
        if not phone:
            continue
        try:
            normalised = normalize_credit_phone(phone)
        except ValueError:
            if phone != customer_key:
                continue
            normalised = phone
        if normalised == customer_key:
            out.append(row)
    out.sort(key=lambda r: r["id"])
    return out


def _credit_amount(shop, row) -> Decimal:
    try:
        return bill_display_totals(shop, row)["rounded"]
    except (InvalidOperation, ValueError):
        try:
            return Decimal(str(row["total"]))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")


def credit_balance_for(conn, shop, customer_key: str) -> dict:
    """Bills minus payments for one customer; every figure from stored rows."""
    bills = credit_bills_for_customer(conn, shop["id"], customer_key)
    payments = list_credit_payments(conn, shop["id"], customer_key)
    bills_total = sum((_credit_amount(shop, row) for row in bills),
                      Decimal("0.00"))
    paid_total = Decimal("0.00")
    for payment in payments:
        try:
            paid_total += Decimal(str(payment["amount"]))
        except (InvalidOperation, ValueError):
            continue
    balance = (bills_total - paid_total).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    name = ""
    for row in reversed(bills):
        try:
            candidate = str(row["customer_name"] or "").strip()
        except (KeyError, IndexError, TypeError):
            candidate = ""
        if candidate:
            name = candidate
            break
    return {"customer_key": customer_key, "name": name,
            "phone": customer_key, "bills": bills, "payments": payments,
            "bills_total": bills_total.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP),
            "paid_total": paid_total.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP),
            "balance": balance, "bill_count": len(bills)}


def credit_balances(conn, shop) -> list[dict]:
    """Customers with an open balance, largest balance first.

    Each entry carries the credit bills, payments, running balance, the
    last bill date and the oldest unpaid date (ISO strings from stored
    created_at values).
    """
    keys: dict[str, list] = {}
    for row in list_quotes(conn, shop["id"]):
        if row["kind"] != "bill" or row["status"] != "credit":
            continue
        try:
            phone = str(row["customer_phone"] or "").strip()
        except (KeyError, IndexError, TypeError):
            phone = ""
        if not phone:
            continue
        try:
            key = normalize_credit_phone(phone)
        except ValueError:
            continue
        keys.setdefault(key, []).append(row)
    for payment in list_credit_payments(conn, shop["id"]):
        keys.setdefault(str(payment["customer_key"]), [])
    out = []
    for key in keys:
        entry = credit_balance_for(conn, shop, key)
        if entry["balance"] <= 0:
            continue
        stamps = [str(row["created_at"]) for row in entry["bills"]
                  if row["created_at"]]
        entry["last_bill_at"] = max(stamps) if stamps else ""
        entry["oldest_unpaid_at"] = min(stamps) if stamps else ""
        out.append(entry)
    out.sort(key=lambda e: (e["balance"], e["customer_key"]), reverse=True)
    return out


def credit_total_to_collect(conn, shop) -> tuple[Decimal, int]:
    """(total open balance, customer count) from stored credit rows."""
    total = Decimal("0.00")
    entries = credit_balances(conn, shop)
    for entry in entries:
        total += entry["balance"]
    return (total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            len(entries))


def record_credit_payment(conn, shop, customer_key: str, amount_raw,
                          mode_raw, created_by: str | None = None,
                          at: str | None = None) -> int:
    """Record a credit collection; partial allowed, never over the balance.

    Returns the payment id. Raises ValueError for bad amounts, modes or
    overpayments.
    """
    key = normalize_credit_phone(customer_key)
    mode = str(mode_raw or "").strip().lower()
    if mode not in ("cash", "upi"):
        raise ValueError("payment mode must be cash or UPI")
    try:
        amount = Decimal(str(amount_raw).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("that amount does not look right") from None
    if amount.is_nan() or amount <= 0:
        raise ValueError("that amount does not look right")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    entry = credit_balance_for(conn, shop, key)
    if not entry["bills"]:
        raise ValueError("no credit bills for this customer")
    if amount > entry["balance"]:
        raise ValueError("that is more than the balance")
    stamp = at or _now()
    cursor = conn.execute(
        "INSERT INTO credit_payments (shop_id, customer_key, amount, mode,"
        " at, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (shop["id"], key, str(amount), mode, stamp, created_by))
    conn.commit()
    return cursor.lastrowid


def last_prices(conn, shop_id: int) -> dict[str, PriceLine]:
    """name_en -> first price line of the latest approved version.

    Keyed by both the display name and the matching key, so price-jump
    checks keep working after a rename.
    """
    version_id = latest_version(conn, shop_id)
    if version_id is None:
        return {}
    prices: dict[str, PriceLine] = {}
    for item in version_items(conn, version_id):
        if not item.price_lines:
            continue
        if item.name_en not in prices:
            prices[item.name_en] = item.price_lines[0]
        key = match_key_of(item)
        if key and key not in prices:
            prices[key] = item.price_lines[0]
    return prices


def version_time(conn, version_id: int) -> datetime:
    row = conn.execute("SELECT created_at FROM versions WHERE id = ?",
                       (version_id,)).fetchone()
    return datetime.fromisoformat(row["created_at"])


def version_source(conn, version_id: int) -> str | None:
    """Price source of a version: video/live/board/voice/mixed, else None."""
    row = conn.execute("SELECT source FROM versions WHERE id = ?",
                       (version_id,)).fetchone()
    if row is None:
        return None
    try:
        return row["source"]
    except (KeyError, IndexError, TypeError):
        return None


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


def media_path(data_dir: Path, stored: str | None) -> Path | None:
    """Stored media path resolved inside ``data_dir`` (else None).

    Public wrapper around :func:`_media_candidate` for the web layer:
    absolute paths must already sit inside the data dir, relative ones
    are resolved against its parent (the ``data/...`` layout).
    """
    return _media_candidate(data_dir, stored)


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
    conn.execute("DELETE FROM photo_checks WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM quotes WHERE shop_id = ?", (shop_id,))
    conn.execute("DELETE FROM credit_payments WHERE shop_id = ?", (shop_id,))
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
    match = re.match(r"s(\d+)_\d+", name)
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
