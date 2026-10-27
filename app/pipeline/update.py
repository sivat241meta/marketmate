from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app import db
from app.meta.spark import chat_json
from app.models import DraftItem, Flag, Item, PriceLine, Proof, Transcript
from app.pipeline.checks import check_item
from app.pipeline.names import CANONICAL_NAMES

ACTIONS = ("set_price", "sold_out", "in_stock", "set_qty")

_SYSTEM_PROMPT = (
    "You parse a produce seller's next-day voice price update into JSON. "
    "Rules: use only what was said, null when it wasn't said; "
    "quote must be copied exactly from one or more turn texts; "
    "name_en must be a key of the canonical list, or \"other\"; "
    "action is set_price when a new price is said, sold_out when the item ran "
    "out, in_stock when it is available again, set_qty when only a quantity "
    "is said; never estimate quantities."
)

_CONTRACT = (
    '{"changes":[{"name_en":"tomato","action":"set_price",'
    '"prices":[{"said":"22","price":22,"per_amount":1,"unit":"kg"}],'
    '"qty":null,"qty_unit":null,"turn_ids":[1],"quote":"thakkali 22 today"}]}'
)


@dataclass
class Change:
    name_en: str
    action: str
    price_lines: list[PriceLine]
    qty: Decimal | None
    qty_unit: str | None
    proof: Proof
    flags: list[Flag] = field(default_factory=list)


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _proof_times(quote: str, turn_ids: list, transcript: Transcript) -> tuple[int, int]:
    by_id = {turn.id: turn for turn in transcript.turns}
    known = [by_id[tid] for tid in turn_ids if tid in by_id]
    if known:
        return (min(t.start_ms for t in known), max(t.end_ms for t in known))
    if quote:
        hit = next((t for t in transcript.turns if quote in t.text), None)
        if hit is not None:
            return (hit.start_ms, hit.end_ms)
    return (0, 0)


def build_update_messages(transcript: Transcript, current: list[Item]) -> list[dict]:
    """Prompt messages: current price list plus transcript turns as [id] text."""
    stock = []
    for item in current:
        if item.sold_out:
            stock.append(f"- {item.name_en} ({item.name_ta}): sold out")
            continue
        lines = ", ".join(f"₹{line.price} per {line.per_amount} {line.unit}"
                          for line in item.price_lines)
        stock.append(f"- {item.name_en} ({item.name_ta}): {lines or 'no price'}")
    lines = "\n".join(f"[{turn.id}] {turn.text}" for turn in transcript.turns)
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    user_content = (
        f"{_SYSTEM_PROMPT}\n\nCanonical names: {canonical}\n\n"
        f"Current price list:\n" + "\n".join(stock) + "\n\n"
        f"Transcript (one line per turn as [id] text):\n{lines}\n\n"
        f"Return only JSON shaped like: {_CONTRACT}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _as_draft(change: Change) -> DraftItem:
    """Convert a change so the video-flow checks can run on it unchanged."""
    return DraftItem(
        name_spoken=change.name_en,
        name_ta=CANONICAL_NAMES.get(change.name_en, change.name_en),
        name_en=change.name_en,
        variety=None,
        price_lines=change.price_lines,
        qty=change.qty,
        qty_unit=change.qty_unit,
        proof=change.proof,
    )


def flags_for_change(change: Change, current_map: dict[str, Item],
                     previous: dict[str, PriceLine]) -> list[Flag]:
    """Honesty flags for one change, reusing the video-flow checks."""
    inherited = False
    if change.action == "set_price":
        current_item = current_map.get(change.name_en)
        first = (current_item.price_lines[0]
                 if current_item is not None and current_item.price_lines
                 else None)
        if (first is not None and first.per_amount is not None
                and first.unit is not None):
            for line in change.price_lines:
                if (line.price is not None and line.per_amount is None
                        and line.unit is None):
                    line.per_amount = first.per_amount
                    line.unit = first.unit
                    inherited = True
    flags: list[Flag] = []
    if change.name_en not in current_map:
        flags.append(Flag(
            field="name", code="NEW_ITEM",
            message=f"{change.name_en} is not in the current price list"))
    if change.action == "set_price":
        flags.extend(check_item(_as_draft(change), previous))
    elif change.action == "set_qty":
        flags.extend(flag for flag in check_item(_as_draft(change), previous)
                     if flag.field in ("qty", "quote"))
    elif change.action in ("sold_out", "in_stock"):
        flags.extend(flag for flag in check_item(_as_draft(change), previous)
                     if flag.code == "CORRECTION_SAID")
    flags = [flag for flag in flags if flag.code != "QTY_MISSING"]
    if inherited:
        flags.append(Flag(
            field="unit", code="UNIT_FROM_EARLIER",
            message="unit was taken from the current price",
            blocking=False))
    return flags


def parse_update_json(data: dict, transcript: Transcript,
                      current: list[Item]) -> list[Change]:
    """Build flagged changes from model JSON; unknown turns fall back to quotes."""
    current_map = {item.name_en: item for item in current}
    previous = {item.name_en: item.price_lines[0] for item in current
                if item.price_lines}
    changes: list[Change] = []
    for raw in data.get("changes", []):
        name_en = raw.get("name_en", "other")
        action = raw.get("action", "set_price")
        if action not in ACTIONS:
            action = "set_price"
        price_lines = [
            PriceLine(
                price=_decimal_or_none(line.get("price")),
                per_amount=_decimal_or_none(line.get("per_amount")),
                unit=line.get("unit"),
                said=line.get("said", ""),
            )
            for line in raw.get("prices", [])
        ]
        quote = raw.get("quote", "")
        turn_ids = list(raw.get("turn_ids", []))
        start_ms, end_ms = _proof_times(quote, turn_ids, transcript)
        change = Change(
            name_en=name_en,
            action=action,
            price_lines=price_lines,
            qty=_decimal_or_none(raw.get("qty")),
            qty_unit=raw.get("qty_unit"),
            proof=Proof(quote=quote, turn_ids=turn_ids,
                        start_ms=start_ms, end_ms=end_ms),
        )
        change.flags = flags_for_change(change, current_map, previous)
        changes.append(change)
    return changes


def parse_update(transcript: Transcript, current: list[Item], *,
                 ledger, settings) -> list[Change]:
    """One low-reasoning Spark call turning an update transcript into changes."""
    data = chat_json(build_update_messages(transcript, current),
                     ledger=ledger, settings=settings, reasoning_effort="low")
    return parse_update_json(data, transcript, current)


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def change_to_dict(change: Change) -> dict:
    return {
        "name_en": change.name_en, "action": change.action,
        "price_lines": [{"price": _decimal_to_str(line.price),
                         "per_amount": _decimal_to_str(line.per_amount),
                         "unit": line.unit, "said": line.said}
                        for line in change.price_lines],
        "qty": _decimal_to_str(change.qty), "qty_unit": change.qty_unit,
        "proof": {"quote": change.proof.quote, "turn_ids": change.proof.turn_ids,
                  "start_ms": change.proof.start_ms, "end_ms": change.proof.end_ms,
                  "frame": change.proof.frame,
                  "audio_clip": change.proof.audio_clip},
        "flags": [{"field": flag.field, "code": flag.code, "message": flag.message,
                   "options": flag.options, "blocking": flag.blocking}
                  for flag in change.flags],
    }


def change_from_dict(raw: dict) -> Change:
    proof = raw["proof"]
    return Change(
        name_en=raw["name_en"], action=raw["action"],
        price_lines=[PriceLine(
            _decimal_or_none(line["price"]),
            _decimal_or_none(line["per_amount"]),
            line["unit"], line.get("said", "")) for line in raw["price_lines"]],
        qty=_decimal_or_none(raw["qty"]), qty_unit=raw["qty_unit"],
        proof=Proof(quote=proof["quote"], turn_ids=proof["turn_ids"],
                    start_ms=proof["start_ms"], end_ms=proof["end_ms"],
                    frame=proof.get("frame"), audio_clip=proof.get("audio_clip")),
        flags=[Flag(field=f["field"], code=f["code"], message=f["message"],
                    options=f.get("options", []), blocking=f.get("blocking", True))
               for f in raw["flags"]],
    )


def _insert_item(conn, version_id: int, name_ta: str, name_en: str,
                 variety: str | None, qty: Decimal | None, qty_unit: str | None,
                 photo: str | None, sold_out: bool, proof: Proof,
                 lines: list[PriceLine]) -> None:
    cursor = conn.execute(
        "INSERT INTO items (version_id, name_ta, name_en, variety, qty, qty_unit,"
        " photo, sold_out, proof) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, name_ta, name_en, variety, _decimal_to_str(qty), qty_unit,
         photo, int(sold_out),
         json.dumps({"quote": proof.quote, "turn_ids": proof.turn_ids,
                     "start_ms": proof.start_ms, "end_ms": proof.end_ms,
                     "frame": proof.frame,
                     "audio_clip": proof.audio_clip})))
    item_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO price_lines (item_id, price, per_amount, unit, said)"
        " VALUES (?, ?, ?, ?, ?)",
        [(item_id, _decimal_to_str(line.price), _decimal_to_str(line.per_amount),
          line.unit, line.said) for line in lines],
    )


def apply_changes(conn, shop_id: int, base_version_id: int,
                  changes: list[Change]) -> int:
    """Copy the base version, apply the changes, return the new version id.

    The new version is unpublished; the caller publishes after the seller
    confirms. A new price clears sold-out; untouched items keep everything.
    """
    row = conn.execute("SELECT shop_id FROM versions WHERE id = ?",
                       (base_version_id,)).fetchone()
    if row is None or row["shop_id"] != shop_id:
        raise ValueError("unknown base version")
    working: list[dict] = []
    for item in db.version_items(conn, base_version_id):
        working.append({
            "name_ta": item.name_ta, "name_en": item.name_en,
            "variety": item.variety, "qty": item.qty, "qty_unit": item.qty_unit,
            "photo": item.photo, "sold_out": item.sold_out,
            "proof": item.proof, "lines": list(item.price_lines),
        })
    index = {entry["name_en"]: entry for entry in working}
    for change in changes:
        entry = index.get(change.name_en)
        if entry is None:
            entry = {
                "name_ta": CANONICAL_NAMES.get(change.name_en, change.name_en),
                "name_en": change.name_en, "variety": None,
                "qty": None, "qty_unit": None, "photo": None,
                "sold_out": False, "proof": change.proof, "lines": [],
            }
            working.append(entry)
            index[change.name_en] = entry
        entry["proof"] = change.proof
        if change.action == "set_price":
            priced = [line for line in change.price_lines if line.price is not None]
            if priced:
                entry["lines"] = priced
            entry["sold_out"] = False
            if change.qty is not None:
                entry["qty"], entry["qty_unit"] = change.qty, change.qty_unit
        elif change.action == "sold_out":
            entry["sold_out"] = True
        elif change.action == "in_stock":
            entry["sold_out"] = False
        elif change.action == "set_qty" and change.qty is not None:
            entry["qty"], entry["qty_unit"] = change.qty, change.qty_unit
    cursor = conn.execute(
        "INSERT INTO versions (shop_id, created_at, published) VALUES (?, ?, 0)",
        (shop_id, datetime.now(UTC).isoformat()),
    )
    new_id = cursor.lastrowid
    for entry in working:
        _insert_item(conn, new_id, entry["name_ta"], entry["name_en"],
                     entry["variety"], entry["qty"], entry["qty_unit"],
                     entry["photo"], entry["sold_out"], entry["proof"],
                     entry["lines"])
    conn.commit()
    return new_id
