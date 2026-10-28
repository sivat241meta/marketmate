"""Day close: sales, cash split, margin, stock left, wastage, ranges."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

from app.costs import IST

__all__ = [
    "bills_for_day",
    "bills_for_range",
    "day_tiles",
    "get_wastage",
    "item_code",
    "items_for_day",
    "list_days",
    "opening_for_day",
    "parse_day",
    "resolve_range",
    "set_wastage",
    "shop_today",
    "shop_tz",
    "stock_left_for_day",
    "whatsapp_summary",
]


def _row_get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def shop_tz(shop) -> ZoneInfo:
    """Shop's local timezone: timezone column when present, else IST for INR."""
    raw = _row_get(shop, "timezone", None)
    if raw:
        try:
            return ZoneInfo(str(raw).strip())
        except Exception:  # noqa: BLE001 - fall through to currency default
            raw = None
    currency = str(_row_get(shop, "currency", "INR") or "INR").upper()
    if currency == "INR":
        return IST
    return ZoneInfo("UTC")


def _ensure_utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(UTC)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def shop_today(shop, now: datetime | None = None) -> str:
    return _ensure_utc(now).astimezone(shop_tz(shop)).date().isoformat()


def parse_day(value: str | None, shop, now: datetime | None = None) -> str:
    """Validate YYYY-MM-DD, defaulting to the shop's today."""
    if not value:
        return shop_today(shop, now)
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError("that date does not look right") from None


def _parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when


def local_day_of(created_at: str | None, tz: ZoneInfo) -> str | None:
    when = _parse_moment(created_at)
    if when is None:
        return None
    return when.astimezone(tz).date().isoformat()


def _bills_all(conn: sqlite3.Connection, shop_id: int):
    from app import db as _db

    return _db.list_quotes(conn, shop_id)


def bills_for_day(conn, shop_id: int, day: str, tz: ZoneInfo) -> list:
    out = []
    for row in _bills_all(conn, shop_id):
        if row["kind"] != "bill" or row["status"] not in ("billed", "paid"):
            continue
        if local_day_of(row["created_at"], tz) != day:
            continue
        out.append(row)
    out.sort(key=lambda r: r["id"])
    return out


def bills_for_range(conn, shop_id: int, start: str, end: str,
                    tz: ZoneInfo) -> list:
    out = []
    for row in _bills_all(conn, shop_id):
        if row["kind"] != "bill" or row["status"] not in ("billed", "paid"):
            continue
        day = local_day_of(row["created_at"], tz)
        if day is None or not (start <= day <= end):
            continue
        out.append(row)
    out.sort(key=lambda r: r["id"])
    return out


def _canonical(name: str | None) -> str:
    from app.market.search import SYNONYMS

    key = (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def _decimal_or_none(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _quantize_money(value: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP

    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _cost_map_for_day(conn, shop_id: int,
                      day: str) -> dict[str, tuple[Decimal, str]]:
    """Canonical item -> (avg cost per base unit, base unit) for one day."""
    from app import purchases as pur
    from app.pipeline.units import convert

    groups: dict[str, list] = {}
    for purchase in pur.list_purchases(conn, shop_id, day):
        if (purchase.qty is None or purchase.unit is None
                or purchase.total_cost is None):
            continue
        if purchase.qty == 0:
            continue
        key = _canonical(purchase.name_en)
        groups.setdefault(key, []).append(purchase)
    out: dict[str, tuple[Decimal, str]] = {}
    for key, rows in groups.items():
        base_unit = rows[0].unit
        total_qty = Decimal(0)
        total_cost = Decimal(0)
        for row in rows:
            converted = convert(row.qty, row.unit, base_unit)
            if converted is None:
                continue
            total_qty += converted
            total_cost += row.total_cost
        if total_qty > 0:
            out[key] = (total_cost / total_qty, base_unit)
    return out


def day_tiles(conn, shop, day: str) -> dict:
    """Rounded sales, counts, cash split, spend and gross margin for a day."""
    from decimal import ROUND_HALF_UP

    from app import db as _db
    from app import purchases as pur
    from app.pipeline.units import convert

    tz = shop_tz(shop)
    shop_id = shop["id"]
    bills = bills_for_day(conn, shop_id, day, tz)
    sales = Decimal("0.00")
    cash = Decimal("0.00")
    upi = Decimal("0.00")
    card = Decimal("0.00")
    unpaid = Decimal("0.00")
    for row in bills:
        try:
            amount = _db.bill_display_totals(shop, row)["rounded"]
        except (InvalidOperation, ValueError):
            continue
        sales += amount
        if row["status"] == "paid":
            mode = str(_row_get(row, "payment_mode", "") or "").lower()
            if mode == "cash":
                cash += amount
            elif mode == "upi":
                upi += amount
            elif mode == "card":
                card += amount
        else:
            unpaid += amount
    spent = pur.spent_on(conn, shop_id, day)
    # Gross margin: sales minus sold qty * purchase cost per unit.
    costs = _cost_map_for_day(conn, shop_id, day)
    cogs = Decimal("0.00")
    sold_any = False
    margin_known = True
    import json

    for row in bills:
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
            qty = _decimal_or_none(line.get("qty"))
            unit = (line.get("unit") or "").strip() or None
            if qty is None or unit is None or qty <= 0:
                continue
            sold_any = True
            found = costs.get(_canonical(line.get("name_en")))
            if found is None:
                margin_known = False
                break
            cost_per, cost_unit = found
            converted = convert(qty, unit, cost_unit)
            if converted is None:
                margin_known = False
                break
            cogs += cost_per * converted
        if not margin_known:
            break
    if not sold_any:
        margin_known = False
    if margin_known:
        cogs = cogs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        margin = (sales - cogs).quantize(Decimal("0.01"),
                                         rounding=ROUND_HALF_UP)
    else:
        margin = None
        cogs = None
    return {
        "day": day,
        "sales": _quantize_money(sales),
        "bills_count": len(bills),
        "cash": _quantize_money(cash),
        "upi": _quantize_money(upi),
        "card": _quantize_money(card),
        "unpaid": _quantize_money(unpaid),
        "spent": _quantize_money(spent),
        "margin": margin,
        "cogs": cogs,
    }


def get_wastage(conn, shop_id: int, day: str,
                name_en: str) -> tuple[Decimal | None, str | None]:
    key = _canonical(name_en)
    # Stored as canonical lower; fall back to exact lower for old rows.
    for candidate in (key, (name_en or "").strip().lower()):
        row = conn.execute(
            "SELECT qty, unit FROM wastage WHERE shop_id = ? AND date = ?"
            " AND name_en = ?",
            (shop_id, day, candidate)).fetchone()
        if row is not None:
            return (_decimal_or_none(row["qty"]), row["unit"])
    return (None, None)


def set_wastage(conn, shop_id: int, day: str, name_en: str,
                qty: Decimal | None, unit: str | None) -> None:
    key = _canonical(name_en)
    conn.execute("DELETE FROM wastage WHERE shop_id = ? AND date = ?"
                 " AND name_en IN (?, ?)",
                 (shop_id, day, key, (name_en or "").strip().lower()))
    if qty is not None and qty > 0 and unit:
        conn.execute(
            "INSERT INTO wastage (shop_id, date, name_en, qty, unit)"
            " VALUES (?, ?, ?, ?, ?)",
            (shop_id, day, key, str(qty), unit))
    conn.commit()


def _sold_qty_on(conn, shop_id: int, canonical: str, day: str,
                 target_unit: str, tz: ZoneInfo) -> Decimal:
    import json

    from app.pipeline.units import convert

    total = Decimal(0)
    for row in bills_for_day(conn, shop_id, day, tz):
        try:
            lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            continue
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            if _canonical(line.get("name_en")) != canonical:
                continue
            if line.get("status") not in ("priced", "needs_qty"):
                continue
            qty = _decimal_or_none(line.get("qty"))
            unit = (line.get("unit") or "").strip() or None
            if qty is None or unit is None:
                continue
            converted = convert(qty, unit, target_unit)
            if converted is None:
                continue
            total += converted
    return total


def _purchases_total(conn, shop_id: int, canonical: str,
                     day: str) -> tuple[Decimal | None, str | None]:
    from app import purchases as pur
    from app.pipeline.units import convert

    rows = [p for p in pur.list_purchases(conn, shop_id, day)
            if _canonical(p.name_en) == canonical
            and p.qty is not None and p.unit]
    if not rows:
        return (None, None)
    base_unit = rows[0].unit
    total = Decimal(0)
    for row in rows:
        converted = convert(row.qty, row.unit, base_unit)
        if converted is None:
            continue
        total += converted
    return (total, base_unit)


def opening_for_day(conn, shop, canonical: str,
                    day: str) -> tuple[Decimal | None, str | None]:
    """Purchases today plus yesterday's stock left (carry-over)."""
    from datetime import timedelta

    from app.pipeline.units import convert

    shop_id = shop["id"]
    bought, bought_unit = _purchases_total(conn, shop_id, canonical, day)
    try:
        prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    except ValueError:
        prev = None
    carry, carry_unit = (None, None)
    if prev is not None:
        carry, carry_unit = stock_left_for_day(conn, shop, canonical, prev,
                                               _depth=1)
    if bought is not None and carry is not None:
        converted = convert(carry, carry_unit, bought_unit)
        if converted is not None:
            return (bought + converted, bought_unit)
        return (bought, bought_unit)
    if bought is not None:
        return (bought, bought_unit)
    if carry is not None:
        return (carry, carry_unit)
    return (None, None)


def stock_left_for_day(conn, shop, canonical: str, day: str,
                       _depth: int = 0
                       ) -> tuple[Decimal | None, str | None]:
    """Opening minus sold minus wastage; None when opening is unknown."""
    from app.pipeline.units import convert

    if _depth > 30:
        return (None, None)
    shop_id = shop["id"]
    tz = shop_tz(shop)
    # Inline opening to control recursion depth.
    bought, bought_unit = _purchases_total(conn, shop_id, canonical, day)
    carry, carry_unit = (None, None)
    if _depth < 30:
        try:
            import datetime as _dt

            prev = (date.fromisoformat(day) - _dt.timedelta(days=1)
                    ).isoformat()
        except ValueError:
            prev = None
        if prev is not None:
            carry, carry_unit = stock_left_for_day(conn, shop, canonical,
                                                   prev, _depth + 1)
    opening, unit = (None, None)
    if bought is not None and carry is not None:
        converted = convert(carry, carry_unit, bought_unit)
        opening = (bought + converted if converted is not None
                   else bought)
        unit = bought_unit
    elif bought is not None:
        opening, unit = bought, bought_unit
    elif carry is not None:
        opening, unit = carry, carry_unit
    else:
        return (None, None)
    sold = _sold_qty_on(conn, shop_id, canonical, day, unit, tz)
    waste_qty, waste_unit = get_wastage(conn, shop_id, day, canonical)
    waste = Decimal(0)
    if waste_qty is not None and waste_unit:
        converted = convert(waste_qty, waste_unit, unit)
        if converted is not None:
            waste = converted
    return (opening - sold - waste, unit)


def items_for_day(conn, shop, day: str) -> list[dict]:
    """Per-item sold qty, sales, opening, stock left and wastage for a day."""
    import json

    from app.pipeline.units import convert

    tz = shop_tz(shop)
    shop_id = shop["id"]
    bills = bills_for_day(conn, shop_id, day, tz)
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for row in bills:
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
            raw_name = str(line.get("name_en") or "").strip()
            if not raw_name:
                continue
            key = _canonical(raw_name)
            qty = _decimal_or_none(line.get("qty"))
            unit = (line.get("unit") or "").strip() or None
            amount = _decimal_or_none(line.get("line_total"))
            if amount is None:
                continue
            local = str(line.get("name_local") or "").strip()
            entry = grouped.get(key)
            if entry is None:
                entry = {"name_en": key, "display": key[:1].upper() + key[1:],
                         "name_local": local, "sold_qty": Decimal(0),
                         "unit": unit, "sales_amount": Decimal("0.00")}
                grouped[key] = entry
                order.append(key)
            if not entry["name_local"] and local:
                entry["name_local"] = local
            entry["sales_amount"] += amount
            if qty is None or unit is None:
                continue
            if entry["unit"] is None:
                entry["unit"] = unit
                entry["sold_qty"] += qty
            elif unit == entry["unit"]:
                entry["sold_qty"] += qty
            else:
                converted = convert(qty, unit, entry["unit"])
                if converted is not None:
                    entry["sold_qty"] += converted
                # Incompatible units: keep sales, leave qty in base unit.
    # Include purchased-but-unsold items so wastage can be entered.
    from app import purchases as pur

    for purchase in pur.list_purchases(conn, shop_id, day):
        key = _canonical(purchase.name_en)
        if key not in grouped:
            grouped[key] = {
                "name_en": key, "display": key[:1].upper() + key[1:],
                "name_local": (purchase.name_local or "").strip(),
                "sold_qty": Decimal(0), "unit": purchase.unit,
                "sales_amount": Decimal("0.00")}
            order.append(key)
    rows = []
    for key in sorted(order):
        entry = grouped[key]
        opening, opening_unit = opening_for_day(conn, shop, key, day)
        _left, left_unit = stock_left_for_day(conn, shop, key, day)
        # stock_left_for_day recomputes opening; reuse its unit for display.
        left, _ = (stock_left_for_day(conn, shop, key, day)
                   if opening is not None else (None, None))
        # Prefer the opening unit for the row; fall back to sold unit.
        unit = opening_unit or entry["unit"]
        sold_qty = entry["sold_qty"]
        if unit is not None and entry["unit"] is not None \
                and entry["unit"] != unit:
            converted = convert(entry["sold_qty"], entry["unit"], unit)
            if converted is not None:
                sold_qty = converted
        waste_qty, waste_unit = get_wastage(conn, shop_id, day, key)
        rows.append({
            "name_en": entry["name_en"],
            "display": entry["display"],
            "name_local": entry["name_local"],
            "slug": item_code(entry["name_en"]),
            "sold_qty": sold_qty,
            "unit": unit or "",
            "sales_amount": _quantize_money(entry["sales_amount"]),
            "opening": opening,
            "opening_unit": opening_unit or "",
            "stock_left": left,
            "left_unit": (left_unit or opening_unit or ""),
            "wastage_qty": waste_qty,
            "wastage_unit": waste_unit or "",
        })
    rows.sort(key=lambda r: r["sales_amount"], reverse=True)
    return rows


def item_code(name_en: str) -> str:
    """Stable slug of the English name: "Small Onion" -> "small-onion"."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name_en or "").strip().lower())
    return slug.strip("-")


def resolve_range(range_key: str | None, from_raw: str | None,
                  to_raw: str | None, shop,
                  now: datetime | None = None) -> tuple[str, str]:
    """(start_day, end_day) inclusive for the export range picker."""
    from datetime import timedelta

    today = shop_today(shop, now)
    key = (range_key or "today").strip().lower()
    if key == "yesterday":
        day = date.fromisoformat(today) - timedelta(days=1)
        iso = day.isoformat()
        return (iso, iso)
    if key in ("week", "last 7 days", "last-7-days", "7days"):
        start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
        return (start, today)
    if key in ("month", "this month", "this-month"):
        first = date.fromisoformat(today).replace(day=1).isoformat()
        return (first, today)
    if key == "custom":
        try:
            start = date.fromisoformat((from_raw or "").strip()).isoformat()
        except ValueError:
            start = today
        try:
            end = date.fromisoformat((to_raw or "").strip()).isoformat()
        except ValueError:
            end = today
        if start > end:
            start, end = end, start
        return (start, end)
    return (today, today)


def list_days(start: str, end: str) -> list[str]:
    from datetime import timedelta

    out = []
    day = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while day <= last:
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def whatsapp_summary(shop, day: str, tiles: dict,
                     items: list[dict]) -> tuple[str, str]:
    """(text, wa.me URL) to the shop's own number; link only, never sent."""
    from app.outputs.money import format_money

    currency = str(_row_get(shop, "currency", "INR") or "INR")
    try:
        short = datetime.strptime(day, "%Y-%m-%d").strftime("%d %b")
    except ValueError:
        short = day
    sales = format_money(tiles.get("sales", 0), currency)
    cash = format_money(tiles.get("cash", 0), currency)
    upi = format_money(tiles.get("upi", 0), currency)
    bills = tiles.get("bills_count", 0)
    top = sorted(items, key=lambda r: r.get("sales_amount", Decimal(0)),
                 reverse=True)[:3]
    parts = []
    for entry in top:
        qty = entry.get("sold_qty")
        unit = entry.get("unit") or ""
        amount = format_money(entry.get("sales_amount", 0), currency)
        if qty is None:
            qty_text = ""
        else:
            try:
                qty_text = format(Decimal(qty).normalize(), "f")
            except (InvalidOperation, ValueError, AttributeError):
                qty_text = str(qty)
        label = entry.get("display") or entry.get("name_en", "")
        if qty_text:
            parts.append(f"{label} {qty_text}{unit} ({amount})".strip())
        else:
            parts.append(f"{label} ({amount})")
    text = (f"{short}: Sales {sales} (Cash {cash}, UPI {upi}),"
            f" {bills} bills.")
    if parts:
        text += " Top: " + ", ".join(parts) + "."
    margin = tiles.get("margin")
    if margin is not None:
        text += f" Margin {format_money(margin, currency)}."
    digits = re.sub(r"\D", "", str(_row_get(shop, "phone", "") or ""))
    base = f"https://wa.me/{digits}" if digits else "https://wa.me/"
    return (text, f"{base}?text={url_quote(text)}")
