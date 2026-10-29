"""Board photo to price list: read the seller's own board, every price confirmed.

Third allowed price source (build-plan-3). The pipeline reads only what is
written on the board and never guesses; every readable price carries a
blocking BOARD_CONFIRM flag until the seller taps it.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.meta.spark import chat_json, image_part
from app.models import DraftItem, Flag, PriceLine, Proof
from app.pipeline.names import (
    CANONICAL_NAMES,
    correct_draft_from_variety,
    repair_variety_local_name,
)
from app.pipeline.units import normalize_unit

BOARD_CONFIRM_MESSAGE = "read from your board – tap to confirm"
NOT_READ_MESSAGE = "could not be read from your board – type the price"

BOARD_INSTRUCTION = (
    "Look at this photo of the seller's own price board. It may be "
    "handwritten or printed, in Tamil, English or both. Read only what is "
    "written on the board and never guess: copy each item line exactly as "
    "written. For each line give: name_as_written (the item name exactly as "
    "written), name_en (the common English name, lower case), name_local "
    "(the local name, or null unless it is obvious), price (the number as "
    "digits, or null when unreadable), read (the exact characters read for "
    "the price, or null when unreadable), per_amount (the number before the "
    "unit, default 1 when the board shows only a unit word), unit (the unit "
    "word as written, or null). Never invent a price, amount or unit that "
    "is not written. A photo of vegetables never gives a price; only this "
    "board does."
)

BOARD_CONTRACT = (
    '{"lines": [{"name_as_written": "thakkali", "name_en": "tomato", '
    '"name_local": "தக்காளி", "price": 40, "read": "40", '
    '"per_amount": 1, "unit": "kg"}]}'
)

BOARD_JSON_EXAMPLE = {
    "lines": [
        {"name_as_written": "thakkali", "name_en": "tomato",
         "name_local": "தக்காளி", "price": 40, "read": "40",
         "per_amount": 1, "unit": "kg"},
    ],
}


def build_board_messages(image: Path) -> list[dict]:
    """Vision prompt: the board photo plus the read-only-what-is-written rules."""
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    return [{"role": "user", "content": [
        {"type": "text", "text": (
            f"{BOARD_INSTRUCTION}\n\nCanonical names: {canonical}\n\n"
            f"Return only JSON shaped like: {BOARD_CONTRACT}")},
        image_part(Path(image)),
    ]}]


def _decimal_or_none(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _canonical_name(raw: str | None, fallback: str) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return (fallback or "").strip().lower() or "other"
    return key


def _local_name(raw: dict, name_en: str, spoken: str, *,
                language: str = "ta") -> str:
    said = raw.get("name_local")
    if isinstance(said, str) and said.strip():
        local = said.strip()
        return (repair_variety_local_name(name_en, local, language=language)
                or local)
    if name_en in CANONICAL_NAMES:
        return CANONICAL_NAMES[name_en]
    return spoken


def parse_board_json(data: dict, image_path: Path | str, *,
                     language: str = "ta") -> list[DraftItem]:
    """Build DraftItems from board vision JSON. Missing prices stay None."""
    image_str = str(image_path)
    raw_lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(raw_lines, list):
        return []
    items: list[DraftItem] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        spoken = str(raw.get("name_as_written") or "").strip()
        name_en = _canonical_name(raw.get("name_en"), spoken)
        price = _decimal_or_none(raw.get("price"))
        read = raw.get("read")
        read_text = str(read).strip() if read is not None else ""
        if price is None:
            read_text = ""
        per_amount = _decimal_or_none(raw.get("per_amount"))
        unit_raw = raw.get("unit")
        unit: str | None = None
        if isinstance(unit_raw, str) and unit_raw.strip():
            canonical, factor = normalize_unit(unit_raw)
            if canonical is not None:
                unit = canonical
                if factor != 1 and per_amount is not None:
                    per_amount = per_amount * factor
            else:
                unit = unit_raw.strip()
        elif unit_raw is not None and price is not None:
            unit = None
        # Default amount when the board shows only a unit word.
        if price is not None and per_amount is None and unit is not None:
            per_amount = Decimal(1)
        quote = f"{spoken} {read_text}".strip() if spoken else read_text
        flags: list[Flag] = []
        if price is None:
            flags.append(Flag(
                field="price", code="NOT_READ",
                message=f"{spoken or 'this line'} {NOT_READ_MESSAGE}".strip(),
                options=[], blocking=True))
        else:
            flags.append(Flag(
                field="price", code="BOARD_CONFIRM",
                message=f"{price} {BOARD_CONFIRM_MESSAGE}".strip()
                if False else BOARD_CONFIRM_MESSAGE,
                options=[str(price)], blocking=True))
            # Message must read "read from your board – tap to confirm".
            flags[-1].message = BOARD_CONFIRM_MESSAGE
        line = PriceLine(price=price, per_amount=per_amount, unit=unit,
                         said=read_text)
        items.append(DraftItem(
            name_spoken=spoken or name_en,
            name_local=_local_name(raw, name_en, spoken or name_en,
                                   language=language),
            name_en=name_en,
            variety=None,
            match_key=name_en,
            price_lines=[line],
            qty=None,
            qty_unit=None,
            proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0,
                        frame=image_str, audio_clip=None, source="board_photo"),
            flags=flags,
        ))
    return items


def _board_summary(data: dict) -> str:
    found = data.get("items")
    count = len(found) if isinstance(found, list) else 0
    noun = "item" if count == 1 else "items"
    return f"{count} {noun} on board"


def read_board(image: Path, *, ledger, settings,
               language: str = "ta") -> list[DraftItem]:
    """One low-reasoning Spark vision call reading the board into drafts."""
    data = chat_json(build_board_messages(Path(image)), ledger=ledger,
                     settings=settings, reasoning_effort="low",
                     step="read board", summary=_board_summary)
    if not isinstance(data, dict):
        return []
    return parse_board_json(data, Path(image), language=language)


def board_meta_path(data_dir: Path, session_id: int) -> Path:
    return Path(data_dir) / "sessions" / str(session_id) / "board.json"


def read_board_meta(data_dir: Path, session_id: int) -> dict:
    try:
        return json.loads(board_meta_path(data_dir, session_id).read_text())
    except (OSError, ValueError):
        return {}


def write_board_meta(data_dir: Path, session_id: int, payload: dict) -> None:
    path = board_meta_path(data_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def process_board_session(conn, session_id: int, image: Path, *,
                          settings, ledger) -> None:
    """Read one board photo into drafts; records stages, never raises."""
    from app import db
    from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded
    from app.pipeline.checks import check_item
    from app.pipeline.run import friendly_error_message

    image = Path(image)
    try:
        db.set_session_status(conn, session_id, "processing",
                              "Reading your board...")
        db.set_stage(conn, session_id, "looking")
        row = conn.execute(
            "SELECT shop_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        shop_id = row["shop_id"]
        ledger.bind(shop_id=shop_id, session_id=session_id)
        shop_row = conn.execute("SELECT language FROM shops WHERE id = ?",
                                (shop_id,)).fetchone()
        language = shop_row["language"] if shop_row else "ta"
        db.set_stage(conn, session_id, "items")
        items = read_board(Path(image), ledger=ledger, settings=settings,
                            language=language)
        for item in items:
            # A known variety decides the item (Task 97); items
            # carrying a seller-chosen name are never touched.
            if db.chosen_name_for(conn, shop_id, db.match_key_of(item),
                                  item.variety) is None:
                correct_draft_from_variety(item, language=language)
        db.set_stage(conn, session_id, "checking")
        previous = db.last_prices(conn, shop_id)
        for item in items:
            for flag in check_item(item, previous, language=language,
                                   ledger=ledger, settings=settings):
                # Board prices are confirmed by tapping, not by re-hearing:
                # keep jump/unit/duplicate checks, drop voice-hearing flags
                # that would double the blocking BOARD_CONFIRM/NOT_READ.
                if flag.code in ("NOT_HEARD", "NO_PRICE", "UNIT_MISSING",
                                  "RANGE", "NUMBER_CHECK", "UNCLEAR_NUMBER"):
                    continue
                item.flags.append(flag)
        db.save_drafts(conn, session_id, items)
        write_board_meta(Path(settings.data_dir), session_id,
                         {"image": str(image)})
        db.set_stage(conn, session_id, "ready")
        db.ensure_session_base(conn, session_id)
        noun = "item" if len(items) == 1 else "items"
        db.set_session_status(conn, session_id, "review",
                              f"{len(items)} {noun} read from your board")
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="photo"))


def run_board_job(settings, session_id: int, image: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    from app import db
    from app.costs import CostLedger

    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_board_session(conn, session_id, Path(image),
                              settings=settings, ledger=ledger)
    finally:
        conn.close()
