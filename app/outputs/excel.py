"""Excel exports (.xlsx) via openpyxl: sales workbook + price-list sheet."""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

BILLS_HEADER = ["Bill no", "Date", "Time", "Customer", "Payment mode",
                "Items count", "Total", "Round off", "Status"]
LINES_HEADER = ["Bill no", "Date", "Item (English)", "Item (local)", "Qty",
                "Unit", "Rate", "Amount"]
ITEMS_HEADER = ["Item", "Qty sold", "Amount"]
SUMMARY_HEADER = ["Date", "Bills", "Sales", "Cash", "UPI", "Card", "Unpaid",
                  "Spent", "Margin"]

_MONEY_FMT = "0.00"

PRICELIST_HEADER = ["Item code", "Item (English)", "Item (local)",
                    "Unit", "Per", "Price", "Sold out"]

__all__ = [
    "BILLS_HEADER",
    "ITEMS_HEADER",
    "LINES_HEADER",
    "PRICELIST_HEADER",
    "SUMMARY_HEADER",
    "pricelist_workbook",
    "sales_workbook",
]


def _decimal(value, default="0.00") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal(default)


def _style_header(cell):
    from openpyxl.styles import Font

    cell.font = Font(bold=True)


def _money(cell, value: Decimal | None):
    if value is None:
        cell.value = None
        return
    cell.value = float(value)
    cell.number_format = _MONEY_FMT


def _number(cell, value: Decimal | None):
    if value is None:
        cell.value = None
        return
    cell.value = float(value)


def sales_workbook(conn: sqlite3.Connection, shop, start: str,
                   end: str) -> bytes:
    """Build the 4-sheet workbook for the inclusive date range."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    from app import db as _db
    from app.dayclose import bills_for_range, day_tiles, list_days, local_day_of, shop_tz
    from app.pipeline.names import english_title

    tz = shop_tz(shop)
    book = Workbook()
    bills_ws = book.active
    bills_ws.title = "Bills"
    lines_ws = book.create_sheet("Lines")
    items_ws = book.create_sheet("Items")
    summary_ws = book.create_sheet("Summary")

    for ws, header in ((bills_ws, BILLS_HEADER), (lines_ws, LINES_HEADER),
                       (items_ws, ITEMS_HEADER),
                       (summary_ws, SUMMARY_HEADER)):
        ws.append(header)
        for cell in ws[1]:
            _style_header(cell)
        ws.freeze_panes = "A2"

    bills = bills_for_range(conn, shop["id"], start, end, tz)
    # Bills + Lines.
    for row in bills:
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
        except (InvalidOperation, ValueError):
            totals = None
        try:
            raw_lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        if not isinstance(raw_lines, list):
            raw_lines = []
        try:
            phone = str(row["customer_phone"] or "").strip()
        except (KeyError, IndexError, TypeError):
            phone = ""
        customer = phone or "Walk-in"
        try:
            mode_raw = str(row["payment_mode"] or "").strip().lower()
        except (KeyError, IndexError, TypeError):
            mode_raw = ""
        mode = {"cash": "Cash", "upi": "UPI", "card": "Card"}.get(
            mode_raw, "")
        if row["status"] == "credit":
            mode = "credit"
        elif row["status"] != "paid":
            mode = "unpaid"
        bill_row = bills_ws.max_row + 1
        bills_ws.cell(row=bill_row, column=1, value=row["id"])
        bills_ws.cell(row=bill_row, column=2, value=day)
        bills_ws.cell(row=bill_row, column=3, value=clock)
        bills_ws.cell(row=bill_row, column=4, value=customer)
        bills_ws.cell(row=bill_row, column=5, value=mode)
        bills_ws.cell(row=bill_row, column=6, value=len(raw_lines))
        if totals is not None:
            _money(bills_ws.cell(row=bill_row, column=7),
                   totals["rounded"])
            _money(bills_ws.cell(row=bill_row, column=8), totals["off"])
        else:
            _money(bills_ws.cell(row=bill_row, column=7),
                   _decimal(row["total"]))
            _money(bills_ws.cell(row=bill_row, column=8), Decimal("0.00"))
        bills_ws.cell(row=bill_row, column=9, value=row["status"])
        for line in raw_lines:
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
            item_name = (english_title(name_en, variety) if variety
                         else name_en)
            line_row = lines_ws.max_row + 1
            lines_ws.cell(row=line_row, column=1, value=row["id"])
            lines_ws.cell(row=line_row, column=2, value=day)
            lines_ws.cell(row=line_row, column=3, value=item_name)
            # Tamil kept as text.
            lines_ws.cell(row=line_row, column=4,
                          value=str(line.get("name_local") or ""))
            _number(lines_ws.cell(row=line_row, column=5),
                    _decimal(line.get("qty"), "0"))
            lines_ws.cell(row=line_row, column=6,
                          value=str(line.get("unit") or ""))
            from app.outputs.pos_csv import per_unit_rate

            rate = per_unit_rate(line.get("unit_price"),
                                 line.get("per_amount"))
            _money(lines_ws.cell(row=line_row, column=7),
                   rate if rate is not None else Decimal("0.00"))
            _money(lines_ws.cell(row=line_row, column=8),
                   _decimal(line.get("line_total"), "0"))

    # Credit collections as their own Bills rows (type credit_payment).
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
            day = local_day_of(payment["at"], tz) or ""
        except (KeyError, TypeError):
            day = ""
        clock = when.strftime("%H:%M") if when else ""
        try:
            collect_mode = str(payment["mode"] or "").strip().lower()
        except (KeyError, IndexError, TypeError):
            collect_mode = ""
        mode_label = {"cash": "Cash", "upi": "UPI"}.get(collect_mode,
                                                        collect_mode)
        try:
            customer = str(payment["customer_key"] or "").strip()
        except (KeyError, IndexError, TypeError):
            customer = ""
        bill_row = bills_ws.max_row + 1
        bills_ws.cell(row=bill_row, column=1, value=None)
        bills_ws.cell(row=bill_row, column=2, value=day)
        bills_ws.cell(row=bill_row, column=3, value=clock)
        bills_ws.cell(row=bill_row, column=4, value=customer)
        bills_ws.cell(row=bill_row, column=5, value=mode_label)
        bills_ws.cell(row=bill_row, column=6, value=0)
        try:
            collected = Decimal(str(payment["amount"]))
        except (InvalidOperation, ValueError, KeyError, TypeError,
                AttributeError):
            collected = Decimal("0.00")
        _money(bills_ws.cell(row=bill_row, column=7), collected)
        _money(bills_ws.cell(row=bill_row, column=8), Decimal("0.00"))
        bills_ws.cell(row=bill_row, column=9, value="credit_payment")

    # Items: aggregate qty + amount across the range.
    agg: dict[str, dict] = {}
    for row in bills:
        try:
            raw_lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            continue
        if not isinstance(raw_lines, list):
            continue
        for line in raw_lines:
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
            key = (name_en.lower(), (variety or "").lower())
            entry = agg.setdefault(key, {"name": name_en,
                                         "variety": variety,
                                         "qty": Decimal(0),
                                         "amount": Decimal("0.00"),
                                         "unit": line.get("unit")})
            if entry["unit"] is None:
                entry["unit"] = line.get("unit")
            qty = _decimal(line.get("qty"), "0")
            unit = str(line.get("unit") or "")
            if unit and entry["unit"] and unit != entry["unit"]:
                from app.pipeline.units import convert

                converted = convert(qty, unit, entry["unit"])
                if converted is not None:
                    qty = converted
                else:
                    qty = Decimal(0)
            entry["qty"] += qty
            entry["amount"] += _decimal(line.get("line_total"), "0")
    for key in sorted(agg):
        entry = agg[key]
        if entry["variety"]:
            display = english_title(entry["name"], entry["variety"])
        else:
            display = entry["name"][:1].upper() + entry["name"][1:]
        row_no = items_ws.max_row + 1
        items_ws.cell(row=row_no, column=1, value=display)
        _number(items_ws.cell(row=row_no, column=2), entry["qty"])
        _money(items_ws.cell(row=row_no, column=3), entry["amount"])

    # Summary: day-close tiles per day.
    for day in list_days(start, end):
        tiles = day_tiles(conn, shop, day)
        row_no = summary_ws.max_row + 1
        summary_ws.cell(row=row_no, column=1, value=day)
        summary_ws.cell(row=row_no, column=2, value=tiles["bills_count"])
        _money(summary_ws.cell(row=row_no, column=3), tiles["sales"])
        _money(summary_ws.cell(row=row_no, column=4), tiles["cash"])
        _money(summary_ws.cell(row=row_no, column=5), tiles["upi"])
        _money(summary_ws.cell(row=row_no, column=6), tiles["card"])
        _money(summary_ws.cell(row=row_no, column=7), tiles["unpaid"])
        _money(summary_ws.cell(row=row_no, column=8), tiles["spent"])
        _money(summary_ws.cell(row=row_no, column=9), tiles["margin"])

    widths = {
        "Bills": [10, 12, 8, 16, 13, 12, 12, 10, 10],
        "Lines": [10, 12, 16, 16, 10, 8, 10, 12],
        "Items": [20, 12, 12],
        "Summary": [12, 8, 12, 12, 12, 10, 12, 12, 12],
    }
    for ws in (bills_ws, lines_ws, items_ws, summary_ws):
        for index, width in enumerate(widths[ws.title], start=1):
            ws.column_dimensions[get_column_letter(index)].width = width

    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def pricelist_workbook(conn: sqlite3.Connection, shop) -> bytes:
    """Today's published price list as a one-sheet Excel workbook."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    from app import db as _db
    from app.dayclose import item_code
    from app.pipeline.names import english_title, qualified_name

    book = Workbook()
    ws = book.active
    ws.title = "Pricelist"
    ws.append(PRICELIST_HEADER)
    for cell in ws[1]:
        _style_header(cell)
    ws.freeze_panes = "A2"

    version_id = _db.latest_version(conn, shop["id"], published_only=True)
    items = _db.version_items(conn, version_id) if version_id else []
    for item in items:
        line = next((ln for ln in item.price_lines
                     if ln.price is not None), None)
        if line is None:
            continue
        variety = (item.variety or "").strip() or None
        item_name = (english_title(item.name_en, variety) if variety
                     else item.name_en)
        row_no = ws.max_row + 1
        ws.cell(row=row_no, column=1,
                value=item_code(qualified_name(item.name_en, variety)))
        ws.cell(row=row_no, column=2, value=item_name)
        ws.cell(row=row_no, column=3, value=item.name_local or "")
        ws.cell(row=row_no, column=4, value=line.unit or "")
        _number(ws.cell(row=row_no, column=5),
                _decimal(line.per_amount, "0") if line.per_amount is not None
                else None)
        _money(ws.cell(row=row_no, column=6), line.price)
        ws.cell(row=row_no, column=7,
                value="TRUE" if item.sold_out else "FALSE")

    for index, width in enumerate([16, 20, 20, 8, 8, 12, 10], start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()
