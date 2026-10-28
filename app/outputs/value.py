from __future__ import annotations

from decimal import Decimal

from app.models import Item
from app.pipeline.units import convert


def _valued_line(lines, qty: Decimal, unit: str):
    """First price line the quantity converts to, or None."""
    for line in lines:
        if (line.price is None or line.per_amount is None
                or not line.per_amount or line.unit is None):
            continue
        amount = convert(qty, unit, line.unit)
        if amount is None:
            continue
        return line, amount
    return None


def stock_value(items: list[Item]) -> tuple[Decimal, list[str]]:
    """Total stock value plus names left out (no qty, or qty unit converts
    to none of the item's price-line units). Uses the first convertible line.

    A photo stock estimate wins when it converts to a price line; otherwise
    the spoken quantity is used exactly as before.
    """
    total = Decimal(0)
    left_out: list[str] = []
    for item in items:
        if item.sold_out:
            continue
        stock_qty = getattr(item, "stock_qty", None)
        stock_unit = getattr(item, "stock_unit", None)
        if stock_qty is not None and stock_unit:
            found = _valued_line(item.price_lines, stock_qty, stock_unit)
            if found is not None:
                line, amount = found
                total += line.price * amount / line.per_amount
                continue
        if item.qty is None or item.qty_unit is None:
            left_out.append(item.name_en)
            continue
        found = _valued_line(item.price_lines, item.qty, item.qty_unit)
        if found is None:
            left_out.append(item.name_en)
            continue
        line, amount = found
        total += line.price * amount / line.per_amount
    return (total, left_out)
