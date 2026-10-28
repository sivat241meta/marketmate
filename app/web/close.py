"""Day close page, wastage, day PDF and sales exports."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import db
from app.dayclose import (
    day_tiles,
    item_code,
    items_for_day,
    parse_day,
    resolve_range,
    set_wastage,
    shop_today,
    whatsapp_summary,
)
from app.outputs.day_pdf import day_summary_pdf
from app.outputs.excel import sales_workbook
from app.outputs.money import format_money
from app.outputs.pos_csv import pos_csv, pricelist_csv
from app.pipeline.names import qualified_name
from app.web.auth import owner_or_403, resolve_or_404
from app.web.i18n import get_ui_lang, summary_whatsapp_text


def _shop_or_404(conn, token: str):
    shop, _role, _helper = resolve_or_404(conn, token)
    if shop is None:
        raise HTTPException(404, "unknown shop token")
    return shop


def _fmt(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def _fmt_money(value, currency) -> str:
    if value is None:
        return "—"
    return format_money(value, currency)


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _owner_page(request, conn, token):
        """(shop, None) for owners; (None, friendly 403) for staff."""
        shop, role, _helper = resolve_or_404(conn, token)
        if shop is None:
            raise HTTPException(404, "unknown shop token")
        if role != "owner":
            ui_lang = get_ui_lang(request, shop)
            return None, owner_or_403(request, templates, role, ui_lang)
        return shop, None

    def _close_context(request, shop, token, day):
        ui_lang = get_ui_lang(request, shop)
        conn = db.connect(data_dir)
        try:
            tiles = day_tiles(conn, shop, day)
            items = items_for_day(conn, shop, day)
            if ui_lang in ("ta", "hi"):
                from urllib.parse import quote as url_quote

                currency = shop["currency"] or "INR"
                tiles_fmt = {
                    **tiles,
                    "sales_fmt": _fmt_money(tiles["sales"], currency),
                    "cash_fmt": _fmt_money(tiles["cash"], currency),
                    "upi_fmt": _fmt_money(tiles["upi"], currency),
                    "card_fmt": _fmt_money(tiles["card"], currency),
                    "unpaid_fmt": _fmt_money(tiles["unpaid"], currency),
                    "spent_fmt": _fmt_money(tiles["spent"], currency),
                    "margin_fmt": (_fmt_money(tiles["margin"], currency)
                                   if tiles["margin"] is not None else ""),
                    "currency": currency,
                }
                items_fmt = [{
                    **entry,
                    "sales_amount_fmt": _fmt_money(
                        entry.get("sales_amount"), currency),
                } for entry in items]
                text = summary_whatsapp_text(day, tiles_fmt, items_fmt,
                                             ui_lang)
                url = ("https://wa.me/?text="
                       + url_quote(text))
            else:
                text, url = whatsapp_summary(shop, day, tiles, items)
        finally:
            conn.close()
        currency = shop["currency"] or "INR"
        top_entry = items[0] if items else None
        top_amount = (top_entry.get("sales_amount")
                      if top_entry else None)
        has_top = bool(top_amount is not None and top_amount > 0)
        rows = []
        for entry in items:
            sold = entry["sold_qty"]
            rows.append({
                "name_en": entry["name_en"],
                "variety": entry.get("variety") or "",
                "display": entry["display"],
                "name_local": entry["name_local"],
                "slug": entry["slug"],
                "sold": (f"{_fmt(sold)} {entry['unit']}".strip()
                         if sold is not None else "—"),
                "amount": _fmt_money(entry["sales_amount"], currency),
                "opening": (f"{_fmt(entry['opening'])}"
                            f" {entry['opening_unit']}".strip()
                            if entry["opening"] is not None else "—"),
                "left": (f"{_fmt(entry['stock_left'])}"
                         f" {entry['left_unit']}".strip()
                         if entry["stock_left"] is not None else "—"),
                "wastage": _fmt(entry["wastage_qty"]),
                "unit": entry["unit"] or entry["opening_unit"] or "kg",
            })
        return templates.TemplateResponse(request, "close.html", {
            "shop": shop, "token": token, "day": day,
            "sales": _fmt_money(tiles["sales"], currency),
            "bills_count": tiles["bills_count"],
            "cash": _fmt_money(tiles["cash"], currency),
            "upi": _fmt_money(tiles["upi"], currency),
            "card": _fmt_money(tiles["card"], currency),
            "unpaid": _fmt_money(tiles["unpaid"], currency),
            "spent": _fmt_money(tiles["spent"], currency),
            "margin": _fmt_money(tiles["margin"], currency),
            "margin_known": tiles["margin"] is not None,
            "has_top": has_top,
            "top_display": (top_entry["display"] if has_top else ""),
            "top_amount": (_fmt_money(top_amount, currency)
                           if has_top else ""),
            "rows": rows, "whatsapp_url": url, "whatsapp_text": text,
            "today": shop_today(shop, datetime.now(UTC)),
            "ui_lang": ui_lang,
        })

    @app.get("/e/{token}/close")
    def close_page(request: Request, token: str, conn: Conn,
                   date: str | None = None):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        try:
            day = parse_day(date, shop, datetime.now(UTC))
        except ValueError:
            day = shop_today(shop, datetime.now(UTC))
        return _close_context(request, shop, token, day)

    @app.post("/e/{token}/close/wastage")
    async def close_wastage_post(request: Request, token: str):
        conn = db.connect(data_dir)
        try:
            shop, denied = _owner_page(request, conn, token)
            if denied is not None:
                return denied
            form = await request.form()
            raw_date = str(form.get("date") or "").strip() or None
            try:
                day = parse_day(raw_date, shop, datetime.now(UTC))
            except ValueError:
                raise HTTPException(
                    400, "that date does not look right") from None
            items = items_for_day(conn, shop, day)
            by_slug = {entry["slug"]: entry for entry in items}
            # Also match plain lower names (e.g. wastage_onion).
            for entry in items:
                by_slug.setdefault(entry["name_en"].strip().lower(), entry)
            seen: set[str] = set()
            for key in form:
                if not key.startswith("wastage_"):
                    continue
                suffix = key[len("wastage_"):]
                entry = by_slug.get(suffix) or by_slug.get(
                    suffix.replace("-", " "))
                if entry is None:
                    # Try slugifying the suffix back to an item.
                    for candidate in items:
                        if item_code(suffix.replace("_", " ")) == \
                                candidate["slug"]:
                            entry = candidate
                            break
                if entry is None:
                    continue
                name_en = qualified_name(entry["name_en"],
                                         entry.get("variety"))
                if entry["slug"] in seen:
                    continue
                seen.add(entry["slug"])
                raw_qty = str(form.get(key) or "").strip()
                unit = (str(form.get(f"unit_{suffix}") or "").strip()
                        or entry["unit"] or entry["opening_unit"] or None)
                if raw_qty == "":
                    set_wastage(conn, shop["id"], day, name_en, None,
                                unit)
                    continue
                try:
                    qty = Decimal(raw_qty)
                except InvalidOperation:
                    raise HTTPException(
                        400,
                        f"wastage for {entry['display']}"
                        " does not look right") from None
                if qty.is_nan() or qty < 0:
                    raise HTTPException(
                        400,
                        f"wastage for {entry['display']}"
                        " does not look right")
                if qty == 0:
                    set_wastage(conn, shop["id"], day, name_en, None,
                                unit)
                else:
                    if not unit:
                        raise HTTPException(
                            400,
                            f"wastage for {entry['display']}"
                            " needs a unit")
                    set_wastage(conn, shop["id"], day, name_en, qty,
                                unit)
            return RedirectResponse(f"/e/{token}/close?date={day}",
                                    status_code=303)
        finally:
            conn.close()

    @app.get("/e/{token}/close.pdf")
    def close_pdf(request: Request, token: str, conn: Conn,
                  date: str | None = None):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        try:
            day = parse_day(date, shop, datetime.now(UTC))
        except ValueError:
            day = shop_today(shop, datetime.now(UTC))
        tiles = day_tiles(conn, shop, day)
        items = items_for_day(conn, shop, day)
        pdf = day_summary_pdf(shop, day, tiles, items, lang=ui_lang)
        return Response(pdf, media_type="application/pdf")

    def _range_from_query(request, shop):
        params = request.query_params
        return resolve_range(params.get("range"), params.get("from"),
                             params.get("to"), shop,
                             datetime.now(UTC))

    @app.get("/e/{token}/exports/sales.xlsx")
    def exports_xlsx(request: Request, token: str, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        start, end = _range_from_query(request, shop)
        data = sales_workbook(conn, shop, start, end)
        name = f"sales-{start}-to-{end}.xlsx" if start != end \
            else f"sales-{start}.xlsx"
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument"
                       ".spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/e/{token}/exports/pos.csv")
    def exports_pos(request: Request, token: str, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        start, end = _range_from_query(request, shop)
        data = pos_csv(conn, shop, start, end)
        name = f"pos-{start}-to-{end}.csv" if start != end \
            else f"pos-{start}.csv"
        return Response(data, media_type="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{name}"'})

    @app.get("/e/{token}/exports/pricelist.csv")
    def exports_pricelist(request: Request, token: str, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        data = pricelist_csv(conn, shop)
        return Response(
            data, media_type="text/csv",
            headers={"Content-Disposition":
                     'attachment; filename="pricelist.csv"'})
