"""General POS CSV exports (UTF-8 with BOM for Excel Tamil)."""

from __future__ import annotations

import csv
import io
import sqlite3
from decimal import Decimal, InvalidOperation

POS_HEADER = ["date", "time", "bill_no", "item_code", "item_name",
              "item_name_local", "qty", "unit", "rate", "amount",
              "discount", "tax", "bill_total", "payment_mode",
              "customer_phone"]

PRICELIST_HEADER = ["item_code", "item_name", "item_name_local", "unit",
                    "per_amount", "price", "sold_out"]

__all__ = ["POS_HEADER", "PRICELIST_HEADER", "pos_csv", "pricelist_csv"]


def _plain(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError, AttributeError):
        return str(value)


def pos_csv(conn: sqlite3.Connection, shop, start: str, end: str) -> bytes:
    """One row per priced bill line in the range, BOM + UTF-8."""
    import json
    from datetime import UTC, datetime

    from app import db as _db
    from app.dayclose import bills_for_range, item_code, local_day_of, shop_tz

    tz = shop_tz(shop)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(POS_HEADER)
    for row in bills_for_range(conn, shop["id"], start, end, tz):
        when = None
        try:
            when = datetime.fromisoformat(row["created_at"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            when = when.astimezone(tz)
        except ValueError:
            when = None
        day = local_day_of(row["created_at"], tz) or ""
        clock = when.strftime("%H:%M") if when else ""
        try:
            totals = _db.bill_display_totals(shop, row)
            bill_total = format(totals["rounded"].normalize(), "f")
        except (InvalidOperation, ValueError):
            bill_total = _plain(row["total"])
        try:
            mode = str(row["payment_mode"] or "").strip().lower()
        except (KeyError, IndexError, TypeError):
            mode = ""
        if row["status"] != "paid":
            mode = ""
        try:
            phone = str(row["customer_phone"] or "").strip()
        except (KeyError, IndexError, TypeError):
            phone = ""
        try:
            lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            continue
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            if line.get("status") not in ("priced", "needs_qty"):
                continue
            if line.get("line_total") is None:
                continue
            name_en = str(line.get("name_en") or "").strip()
            if not name_en:
                continue
            writer.writerow([
                day, clock, row["id"], item_code(name_en), name_en,
                str(line.get("name_local") or ""),
                _plain(line.get("qty")), str(line.get("unit") or ""),
                _plain(line.get("unit_price")),
                _plain(line.get("line_total")),
                "0", "0", bill_total, mode, phone,
            ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def pricelist_csv(conn: sqlite3.Connection, shop) -> bytes:
    """Today's published items in the general CSV style, BOM + UTF-8."""
    from app import db as _db
    from app.dayclose import item_code

    version_id = _db.latest_version(conn, shop["id"], published_only=True)
    items = _db.version_items(conn, version_id) if version_id else []
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(PRICELIST_HEADER)
    for item in items:
        line = next((ln for ln in item.price_lines
                     if ln.price is not None), None)
        if line is None:
            continue
        writer.writerow([
            item_code(item.name_en), item.name_en, item.name_local,
            line.unit or "", _plain(line.per_amount),
            _plain(line.price),
            "TRUE" if item.sold_out else "FALSE",
        ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
