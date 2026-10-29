from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.outputs.money import format_money
from app.pipeline.names import display_name_en, display_name_local

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
_FONTS_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "fonts").as_uri()
_BRAND_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "brand").as_uri()


def _plain(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def quote_pdf(shop: sqlite3.Row | dict, lines: list[dict], total: str,
              prices_note: str, quote_url: str) -> bytes:
    """One-page customer quote: shop header, lines, total, honest footer."""
    from weasyprint import HTML

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    env.filters["money"] = format_money
    template = env.get_template("quote_pdf.html")
    rows = []
    for line in lines:
        variety = line.get("variety") or None
        rows.append({
            "name_en": display_name_en(line.get("name_en", ""), variety),
            "name_local": display_name_local(line.get("name_local", ""),
                                             variety),
            "qty": _plain(line.get("qty", "")),
            "unit": line.get("unit") or "",
            "unit_price": _plain(line.get("unit_price")),
            "per_amount": _plain(line.get("per_amount")),
            "per_unit": line.get("unit") or "",
            "line_total": _plain(line.get("line_total")),
            "status": line.get("status", ""),
            "note": line.get("note") or "",
        })
    html = template.render(
        shop=shop, rows=rows, total=_plain(total),
        prices_note=prices_note, quote_url=quote_url,
        fonts_uri=_FONTS_URI, brand_uri=_BRAND_URI)
    return HTML(string=html).write_pdf()
