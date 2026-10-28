"""Purchases: the morning market run, cost per unit, margin, stock left."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models import Purchase
from app.outputs.money import format_money
from app.pipeline.units import convert


def _decimal_or_none(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, AttributeError):
        return None


def add_purchase(conn: sqlite3.Connection, shop_id: int, date: str,
                 name_en: str, qty: Decimal | str | int | None,
                 unit: str | None, total_cost: Decimal | str | int | None,
                 source: str = "typed", name_local: str = "") -> int:
    """Store one purchase row; returns its id."""
    from datetime import UTC

    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO purchases (shop_id, date, name_en, name_local, qty,"
        " unit, total_cost, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (shop_id, date, (name_en or "").strip().lower(),
         (name_local or "").strip(),
         str(qty) if qty is not None else None, unit,
         str(total_cost) if total_cost is not None else None,
         source, now))
    conn.commit()
    return cursor.lastrowid


def list_purchases(conn: sqlite3.Connection, shop_id: int,
                   date: str) -> list[Purchase]:
    rows = conn.execute(
        "SELECT * FROM purchases WHERE shop_id = ? AND date = ? ORDER BY id",
        (shop_id, date)).fetchall()
    out = []
    for row in rows:
        out.append(Purchase(
            id=row["id"], shop_id=row["shop_id"], date=row["date"],
            name_en=row["name_en"], name_local=row["name_local"] or "",
            qty=_decimal_or_none(row["qty"]),
            unit=row["unit"],
            total_cost=_decimal_or_none(row["total_cost"]),
            source=row["source"]))
    return out


def spent_on(conn: sqlite3.Connection, shop_id: int, date: str) -> Decimal:
    """Total spent on a date (IST date string)."""
    total = Decimal("0.00")
    for purchase in list_purchases(conn, shop_id, date):
        if purchase.total_cost is not None:
            total += purchase.total_cost
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cost_per_unit(qty: Decimal | None, unit: str | None,
                  total_cost: Decimal | None
                  ) -> tuple[Decimal | None, str | None]:
    """Unit cost: total / qty, e.g. 50 kg for 1200 -> (24, kg)."""
    if qty is None or total_cost is None or qty == 0:
        return (None, unit)
    per = (total_cost / qty).quantize(Decimal("0.01"),
                                      rounding=ROUND_HALF_UP)
    # Drop trailing .00 for whole numbers: 24, not 24.00.
    if per == per.to_integral_value():
        per = Decimal(int(per))
    return (per, unit)


def _rounded_pct(margin: Decimal, base: Decimal) -> int:
    if base == 0:
        return 0
    pct = (margin / abs(base) * 100).quantize(Decimal(1),
                                              rounding=ROUND_HALF_UP)
    return int(pct)


def margin_text(buy_per: Decimal | None, buy_unit: str | None,
                sell_per: Decimal | None, sell_unit: str | None,
                currency: str = "INR") -> str:
    """buy/sell line: "buy ₹24/kg · sell ₹40/kg · +₹16 (67%)".

    Units are converted when possible (kg<->g, piece<->dozen); when they
    cannot be compared only the buy part is shown.
    """
    if buy_per is None or sell_per is None:
        return ""
    buy_unit = buy_unit or ""
    sell_unit = sell_unit or ""
    buy_in_sell = buy_per
    if buy_unit != sell_unit:
        converted = convert(Decimal(1), buy_unit, sell_unit)
        if converted is None:
            return f"buy {format_money(buy_per, currency)}/{buy_unit}"
        # 1 buy_unit = N sell_units, so price per sell_unit = buy/N.
        buy_in_sell = (buy_per / converted).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    margin = (sell_per - buy_in_sell).quantize(Decimal("0.01"),
                                               rounding=ROUND_HALF_UP)
    if margin == margin.to_integral_value():
        margin = Decimal(int(margin))
    pct = _rounded_pct(sell_per - buy_in_sell, buy_in_sell)
    sign = "+" if margin >= 0 else ""
    buy_part = f"buy {format_money(buy_per, currency)}/{buy_unit}"
    sell_part = f"sell {format_money(sell_per, currency)}/{sell_unit}"
    return f"{buy_part} · {sell_part} · {sign}{format_money(margin, currency)} ({pct}%)"


def _canonical(name: str | None) -> str:
    from app.market.search import SYNONYMS

    key = (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def _ist_date_of(created_at: str | None):
    from datetime import UTC

    from app.costs import IST

    if not created_at:
        return None
    try:
        when = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(IST).date().isoformat()


def opening_stock(conn: sqlite3.Connection, shop_id: int, name_en: str,
                  date: str) -> tuple[Decimal | None, str | None]:
    """Purchased qty today plus photo stock when the item has one.

    Multiple purchase units are converted to the first purchase unit;
    photo stock (Task 26) is added when present, converted likewise.
    """
    from app import db as _db

    purchases = [p for p in list_purchases(conn, shop_id, date)
                 if _canonical(p.name_en) == _canonical(name_en)
                 and p.qty is not None and p.unit]
    if not purchases:
        base_unit = None
        total: Decimal | None = None
    else:
        base_unit = purchases[0].unit
        total = Decimal(0)
        for purchase in purchases:
            converted = convert(purchase.qty, purchase.unit, base_unit)
            if converted is None:
                continue
            total += converted
    # Photo stock from Task 26, when the latest version carries one.
    version_id = _db.latest_version(conn, shop_id)
    if version_id is not None:
        for item in _db.version_items(conn, version_id):
            if _canonical(item.name_en) != _canonical(name_en):
                continue
            if (item.stock_qty is not None and item.stock_unit
                    and item.stock_source == "photo"):
                if total is None:
                    base_unit = item.stock_unit
                    total = Decimal(item.stock_qty)
                elif base_unit is not None:
                    converted = convert(item.stock_qty, item.stock_unit,
                                        base_unit)
                    if converted is not None:
                        total += converted
            break
    return (total, base_unit)


def sold_qty(conn: sqlite3.Connection, shop_id: int, name_en: str,
             date: str, target_unit: str | None) -> Decimal:
    """Qty sold today in billed/paid bills, converted to target_unit."""
    import json

    from app import db as _db

    if target_unit is None:
        return Decimal(0)
    total = Decimal(0)
    for row in _db.list_quotes(conn, shop_id):
        if row["kind"] != "bill" or row["status"] not in ("billed", "paid"):
            continue
        if _ist_date_of(row["created_at"]) != date:
            continue
        try:
            lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            continue
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            if _canonical(line.get("name_en")) != _canonical(name_en):
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


def stock_left(conn: sqlite3.Connection, shop_id: int, name_en: str,
               date: str) -> tuple[Decimal | None, str | None]:
    """Opening stock minus what today's billed/paid bills sold."""
    opening, unit = opening_stock(conn, shop_id, name_en, date)
    if opening is None or unit is None:
        return (None, None)
    sold = sold_qty(conn, shop_id, name_en, date, unit)
    return (opening - sold, unit)
