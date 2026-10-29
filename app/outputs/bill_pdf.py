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


def bill_pdf(shop: sqlite3.Row | dict, bill_id: int, lines: list[dict],
             total: str, created_label: str,
             customer_phone: str | None = None, lang: str = "en",
             round_off: str | None = None,
             paid_mode: str | None = None) -> bytes:
    """Receipt-style seller bill: shop header, lines, round-off, total, paid."""
    from weasyprint import HTML

    from app.web.i18n import t_for

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    env.filters["money"] = format_money
    env.globals["t"] = t_for(lang)
    template = env.get_template("bill_pdf.html")
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
            "line_total": _plain(line.get("line_total")),
            "status": line.get("status", ""),
        })
    html = template.render(
        shop=shop, bill_id=bill_id, rows=rows, total=_plain(total),
        created_label=created_label, customer_phone=customer_phone or "",
        round_off=round_off or "", paid_mode=paid_mode or "",
        fonts_uri=_FONTS_URI, brand_uri=_BRAND_URI)
    return HTML(string=html).write_pdf()
