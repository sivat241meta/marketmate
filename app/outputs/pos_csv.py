"""General POS CSV exports (UTF-8 with BOM for Excel Tamil)."""

from __future__ import annotations

import csv
import io
import sqlite3
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

POS_HEADER = ["date", "time", "bill_no", "item_code", "item_name",
              "item_name_local", "qty", "unit", "rate", "amount",
              "discount", "tax", "bill_total", "payment_mode",
              "customer_phone"]

PRICELIST_HEADER = ["item_code", "item_name", "item_name_local", "unit",
                    "per_amount", "price", "sold_out"]

__all__ = ["POS_HEADER", "PRICELIST_HEADER", "per_unit_rate", "pos_csv",
           "pricelist_csv"]


def per_unit_rate(unit_price, per_amount) -> Decimal | None:
    """Rate per ONE unit: price ÷ per_amount, to 2 decimals.

    E.g. ₹18 per 0.5 kg -> ₹36 per kg. Amounts stay the bill's own
    line totals; only the rate column is normalised to one unit.
    """
    if unit_price in (None, ""):
        return None
    try:
        price = Decimal(str(unit_price))
    except (InvalidOperation, ValueError, AttributeError):
        return None
    if per_amount in (None, ""):
        return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        per = Decimal(str(per_amount))
    except (InvalidOperation, ValueError, AttributeError):
        return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if per == 0:
        return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (price / per).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
    from app.pipeline.names import display_name_en, qualified_name

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
        if row["status"] == "credit":
            mode = "credit"
        elif row["status"] != "paid":
            mode = "unpaid"
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
            variety = str(line.get("variety") or "").strip() or None
            rate = per_unit_rate(line.get("unit_price"),
                                 line.get("per_amount"))
            item_name = (display_name_en(name_en, variety) if variety
                         else name_en)
            writer.writerow([
                day, clock, row["id"],
                item_code(qualified_name(name_en, variety)),
                item_name,
                str(line.get("name_local") or ""),
                _plain(line.get("qty")), str(line.get("unit") or ""),
                _plain(rate),
                _plain(line.get("line_total")),
                "0", "0", bill_total, mode, phone,
            ])
    from app.dayclose import credit_payments_for_range as _payments_for_range

    for payment in _payments_for_range(conn, shop["id"], start, end, tz):
        when = None
        try:
            when = datetime.fromisoformat(payment["at"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            when = when.astimezone(tz)
        except (ValueError, KeyError, TypeError):
            when = None
        try:
            payday = local_day_of(payment["at"], tz) or ""
        except (KeyError, TypeError):
            payday = ""
        pay_clock = when.strftime("%H:%M") if when else ""
        try:
            collect_mode = str(payment["mode"] or "").strip().lower()
        except (KeyError, IndexError, TypeError):
            collect_mode = ""
        try:
            customer = str(payment["customer_key"] or "").strip()
        except (KeyError, IndexError, TypeError):
            customer = ""
        try:
            collected = _plain(payment["amount"])
        except (KeyError, IndexError, TypeError):
            collected = ""
        writer.writerow([
            payday, pay_clock, "", "credit_payment", "credit_payment",
            "", "1", "", collected, collected,
            "0", "0", collected, collect_mode, customer,
        ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def pricelist_csv(conn: sqlite3.Connection, shop) -> bytes:
    """Today's published items in the general CSV style, BOM + UTF-8."""
    from app import db as _db
    from app.dayclose import item_code
    from app.pipeline.names import display_name_en, qualified_name

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
        variety = (item.variety or "").strip() or None
        item_name = (display_name_en(item.name_en, variety) if variety
                     else item.name_en)
        writer.writerow([
            item_code(qualified_name(item.name_en, variety)), item_name,
            item.name_local,
            line.unit or "", _plain(line.per_amount),
            _plain(line.price),
            "TRUE" if item.sold_out else "FALSE",
        ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
