from __future__ import annotations

from decimal import Decimal

from app.models import Item
from app.pipeline.units import convert


def stock_value(items: list[Item]) -> tuple[Decimal, list[str]]:
    """Total stock value plus names left out (no qty, or qty unit converts
    to none of the item's price-line units). Uses the first convertible line."""
    total = Decimal(0)
    left_out: list[str] = []
    for item in items:
        if item.sold_out:
            continue
        if item.qty is None or item.qty_unit is None:
            left_out.append(item.name_en)
            continue
        for line in item.price_lines:
            if (line.price is None or line.per_amount is None
                    or not line.per_amount or line.unit is None):
                continue
            amount = convert(item.qty, item.qty_unit, line.unit)
            if amount is None:
                continue
            total += line.price * amount / line.per_amount
            break
        else:
            left_out.append(item.name_en)
    return (total, left_out)
