from __future__ import annotations

import csv
import io
from datetime import datetime

from app.models import Item

_GENERIC_HEADER = ["name_en", "name_local", "variety", "price", "per_amount",
                   "unit", "qty", "qty_unit", "updated_at"]


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
                item.name_en, item.name_local, _text(item.variety),
                _text(line.price), _text(line.per_amount),
                _text(line.unit), _text(item.qty), _text(item.qty_unit),
                updated_at.isoformat(),
            ])
    return buf.getvalue()


