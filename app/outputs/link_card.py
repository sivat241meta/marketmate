"""Printable "Keep this safe" card with the seller link QR."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.outputs.qr import qr_png

_FONTS_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "fonts").as_uri()
_BRAND_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "brand").as_uri()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"


def link_card_pdf(shop: sqlite3.Row, seller_url: str, lang: str = "en") -> bytes:
    """One-page card: shop name, seller link QR, keep-safe warning."""
    from weasyprint import HTML

    from app.web.i18n import t_for

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    env.globals["t"] = t_for(lang)
    template = env.get_template("link_card.html")
    qr_data_uri = ("data:image/png;base64,"
                   + base64.b64encode(qr_png(seller_url)).decode())
    html = template.render(
        shop=shop, seller_url=seller_url, qr_data_uri=qr_data_uri,
        fonts_uri=_FONTS_URI, brand_uri=_BRAND_URI)
    return HTML(string=html).write_pdf()
