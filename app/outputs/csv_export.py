from __future__ import annotations

import csv
import io
from datetime import datetime

from app.models import Item

_GENERIC_HEADER = ["name_en", "name_ta", "variety", "price", "per_amount",
                   "unit", "qty", "qty_unit", "updated_at"]
_POSAPP_HEADER = ["Item Name", "Selling Price", "Unit", "Description"]


def _text(value) -> str:
    return "" if value is None else str(value)


def generic_csv(items: list[Item], updated_at: datetime) -> str:
    """One row per price line with the item's qty and the export time."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_GENERIC_HEADER)
    for item in items:
        for line in item.price_lines:
            writer.writerow([
                item.name_en, item.name_ta, _text(item.variety),
                _text(line.price), _text(line.per_amount),
                _text(line.unit), _text(item.qty), _text(item.qty_unit),
                updated_at.isoformat(),
            ])
    return buf.getvalue()


def _display_name(item: Item) -> str:
    name = item.name_en.strip().title()
    if item.variety and item.variety.strip():
        return f"{name} ({item.variety.strip().title()})"
    return name


def posapp_pos_csv(items: list[Item]) -> str:
    """POS app import: first priced line per item, Tamil name as description."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_POSAPP_HEADER)
    for item in items:
        line = next((ln for ln in item.price_lines if ln.price is not None), None)
        if line is None:
            continue
        writer.writerow([_display_name(item), str(line.price),
                         _text(line.unit), item.name_ta])
    return buf.getvalue()
