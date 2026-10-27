from __future__ import annotations

import base64
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.models import Item
from app.outputs.qr import qr_png

_FONTS_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "fonts").as_uri()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"


def _plain(value) -> str:
    """Decimal without scientific notation: 40, not 4E+1."""
    return format(value.normalize(), "f")


def _rows(items: list[Item]) -> list[dict]:
    rows = []
    for item in items:
        for line in item.price_lines:
            if line.price is None:
                continue
            amount = line.per_amount if line.per_amount is not None else ""
            rows.append({
                "name_ta": item.name_ta,
                "name_en": item.name_en,
                "variety": item.variety,
                "price": _plain(line.price),
                "per": f"{amount} {line.unit or ''}".strip(),
            })
    return rows


def price_board_pdf(shop: sqlite3.Row, items: list[Item], at: datetime,
                    shop_url: str) -> bytes:
    """A4 price board with big prices, Tamil names and a shop QR code."""
    from weasyprint import HTML

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    template = env.get_template("board.html")
    qr_data_uri = ("data:image/png;base64,"
                   + base64.b64encode(qr_png(shop_url)).decode())
    html = template.render(
        shop=shop, rows=_rows(items), at=at.strftime("%d %b %Y, %H:%M"),
        shop_url=shop_url, qr_data_uri=qr_data_uri, fonts_uri=_FONTS_URI)
    return HTML(string=html).write_pdf()
