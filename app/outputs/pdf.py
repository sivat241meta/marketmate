from __future__ import annotations

import base64
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.models import Item
from app.outputs.money import format_money
from app.outputs.qr import qr_png
from app.pipeline.names import english_title, local_title

_FONTS_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "fonts").as_uri()
_BRAND_URI = (Path(__file__).resolve().parent.parent
              / "web" / "static" / "brand").as_uri()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"


def _plain(value) -> str:
    """Decimal without scientific notation: 40, not 4E+1."""
    return format(value.normalize(), "f")


_PHOTO_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _photo_data_uri(path) -> str | None:
    """Embed the SAM cut-out thumbnail; None when the item has no photo."""
    if not path:
        return None
    file = Path(path)
    if not file.is_file():
        return None
    mime = _PHOTO_MIME.get(file.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode()


def _shop_lang(shop) -> str:
    try:
        lang = shop["language"]
    except (KeyError, IndexError, TypeError):
        return "en"
    return lang or "en"


def _rows(items: list[Item], language: str = "en") -> list[dict]:
    rows = []
    for item in items:
        photo = _photo_data_uri(item.photo)
        titles = {
            "name_local": item.name_local, "name_en": item.name_en,
            "variety": item.variety,
            "title_local": local_title(item.name_local, item.variety,
                                       item.name_en, language),
            "title_en": english_title(item.name_en, item.variety),
        }
        if item.sold_out:
            rows.append({
                **titles, "photo": photo, "sold_out": True,
                "price": "", "per": "",
            })
            continue
        for line in item.price_lines:
            if line.price is None:
                continue
            amount = line.per_amount if line.per_amount is not None else ""
            rows.append({
                **titles,
                "photo": photo,
                "sold_out": False,
                "price": _plain(line.price),
                "per": f"{amount} {line.unit or ''}".strip(),
            })
    return rows


def price_board_pdf(shop: sqlite3.Row, items: list[Item], at: datetime,
                    shop_url: str, lang: str = "en") -> bytes:
    """A4 price board with big prices, Tamil names and a shop QR code."""
    from weasyprint import HTML

    from app.web.i18n import t_for

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    env.filters["money"] = format_money
    env.globals["t"] = t_for(lang)
    template = env.get_template("board.html")
    qr_data_uri = ("data:image/png;base64,"
                   + base64.b64encode(qr_png(shop_url)).decode())
    html = template.render(
        shop=shop, rows=_rows(items, _shop_lang(shop)),
        at=at.strftime("%d %b %Y, %H:%M"),
        shop_url=shop_url, qr_data_uri=qr_data_uri, fonts_uri=_FONTS_URI,
        brand_uri=_BRAND_URI)
    return HTML(string=html).write_pdf()


def _tags(items: list[Item], language: str = "en") -> list[dict]:
    """One tag per published item; sold-out items are skipped."""
    tags = []
    for item in items:
        if item.sold_out:
            continue
        line = next((line for line in item.price_lines
                     if line.price is not None), None)
        if line is None:
            continue
        amount = line.per_amount if line.per_amount is not None else ""
        per = f"{amount} {line.unit or ''}".strip() or (line.unit or "")
        tags.append({
            "name_local": item.name_local,
            "name_en": item.name_en,
            "variety": item.variety,
            "title_local": local_title(item.name_local, item.variety,
                                       item.name_en, language),
            "title_en": english_title(item.name_en, item.variety),
            "price": _plain(line.price),
            "per": per,
        })
    return tags


def price_tags_pdf(shop: sqlite3.Row, items: list[Item], at: datetime,
                   shop_url: str, lang: str = "en") -> bytes:
    """A4 sheet of per-item price tags, 2 columns x 4 rows (8 per page)."""
    from weasyprint import HTML

    from app.web.i18n import t_for

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)),
                      autoescape=True)
    env.filters["money"] = format_money
    env.globals["t"] = t_for(lang)
    template = env.get_template("tags.html")
    qr_data_uri = ("data:image/png;base64,"
                   + base64.b64encode(qr_png(shop_url)).decode())
    tags = _tags(items, _shop_lang(shop))
    pages = [tags[index:index + 8] for index in range(0, len(tags), 8)] or [[]]
    html = template.render(
        shop=shop, pages=pages, at=at.strftime("%d %b %Y"),
        shop_url=shop_url, qr_data_uri=qr_data_uri, fonts_uri=_FONTS_URI,
        brand_uri=_BRAND_URI)
    return HTML(string=html).write_pdf()
