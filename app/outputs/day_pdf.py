"""Day-close summary PDF (WeasyPrint, Tamil font)."""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.outputs.money import format_money

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
_FONTS_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "fonts").as_uri()

__all__ = ["day_summary_pdf"]


def _plain(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def day_summary_pdf(shop: sqlite3.Row | dict, day: str, tiles: dict,
                    items: list[dict]) -> bytes:
    """One-page day summary: tiles plus per-item sales and stock left."""
    from weasyprint import HTML

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    env.filters["money"] = format_money
    template = env.get_template("close_pdf.html")
    rows = []
    for entry in items:
        sold = entry.get("sold_qty")
        opening = entry.get("opening")
        left = entry.get("stock_left")
        rows.append({
            "display": entry.get("display") or entry.get("name_en", ""),
            "name_local": entry.get("name_local") or "",
            "sold": (f"{_plain(sold)} {entry.get('unit') or ''}".strip()
                     if sold is not None else "—"),
            "amount": _plain(entry.get("sales_amount")),
            "opening": (f"{_plain(opening)}"
                        f" {entry.get('opening_unit') or ''}".strip()
                        if opening is not None else "—"),
            "left": (f"{_plain(left)} {entry.get('left_unit') or ''}".strip()
                     if left is not None else "—"),
        })
    html = template.render(
        shop=shop, day=day, tiles=tiles, rows=rows,
        fonts_uri=_FONTS_URI)
    return HTML(string=html).write_pdf()
