"""Seller bills dashboard: quotes waiting, bills, receipts.

Bills reuse the customer quote engine (app.market.quote) with source
"seller" and kind "bill". Every price comes from the shop's published
price lines; client totals are always recomputed server side.
"""

import io
import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import quote as url_quote
from urllib.parse import urlencode as url_encode

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image

from app import db, jobs
from app.costs import (
    BUDGET_EXHAUSTED_MESSAGE,
    IST,
    CostCapExceeded,
    CostLedger,
)
from app.languages import shop_bias
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.market.quote import (
    WantedLine,
    build_quote,
    wanted_from_photo,
    wanted_from_text,
)
from app.meta.spark import SparkError
from app.meta.transcribe import transcribe_wav
from app.outputs.bill_pdf import bill_pdf
from app.outputs.money import format_money
from app.pipeline.media import extract_audio
from app.pipeline.names import keywords_for
from app.pipeline.run import friendly_error_message
from app.pipeline.units import convert
from app.web.i18n import (
    bill_whatsapp_text,
    get_ui_lang,
    stage_friendly,
    stage_label,
    t_for,
)

MAX_BILL_PHOTO_BYTES = 10 * 1024 * 1024

# Re-exported for templates/tests; the canonical math lives in app.db.
round_bill_total = db.round_bill_total


def build_upi_url(upi_id: str, payee: str, amount: Decimal | str,
                  bill_id: int, shop_name: str) -> str:
    """UPI collect URL for the exact bill amount, URL-encoded.

    amount is formatted with 2 decimals; callers pass the rounded total
    when rounding is on.
    """
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    params = url_encode({
        "pa": (upi_id or "").strip(),
        "pn": (payee or shop_name or "").strip(),
        "am": format(value, "f"),
        "cu": "INR",
        "tn": f"Bill {bill_id}, {shop_name}",
    }, quote_via=url_quote)
    return f"upi://pay?{params}"


def _row_mode(row) -> str | None:
    try:
        value = row["payment_mode"]
    except (KeyError, IndexError, TypeError):
        return None
    text = str(value or "").strip().lower()
    return text or None


def _mode_label(mode: str | None, lang: str = "en") -> str:
    t = t_for(lang)
    return {"cash": t("bills.cash"), "upi": t("bills.upi"),
            "card": t("bills.card")}.get((mode or "").lower(), "")


def bill_meta_path(data_dir: Path, session_id: int) -> Path:
    return Path(data_dir) / "sessions" / str(session_id) / "bill.json"


def read_bill_meta(data_dir: Path, session_id: int) -> dict:
    try:
        return json.loads(bill_meta_path(data_dir, session_id).read_text())
    except (OSError, ValueError):
        return {}


def write_bill_meta(data_dir: Path, session_id: int, payload: dict) -> None:
    path = bill_meta_path(data_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _shop_or_404(conn, token: str):
    shop = db.shop_by_token(conn, token)
    if shop is None:
        raise HTTPException(404, "unknown shop token")
    return shop


def _bill_of_shop(conn, shop_id: int, bill_id: int):
    try:
        key = int(bill_id)
    except (TypeError, ValueError):
        raise HTTPException(404, "unknown bill") from None
    row = db.get_quote_by_id(conn, key)
    if row is None or row["shop_id"] != shop_id:
        raise HTTPException(404, "unknown bill")
    return row


def _session_of_shop(conn, shop_id: int, session_id: int):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND shop_id = ?",
        (session_id, shop_id)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown bill request")
    if row["kind"] not in ("bill_voice", "bill_photo"):
        raise HTTPException(404, "unknown bill request")
    return row


def _parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when


def _ist_date(value: str | None):
    when = _parse_moment(value)
    if when is None:
        return None
    return when.astimezone(IST).date()


def bills_tiles(conn, shop_id: int, *, now: datetime | None = None) -> dict:
    """Today's tiles: bill count, sales, quotes waiting, average bill.

    Bills today counts kind=bill rows with status billed/paid created
    today (IST). Sales today sums their rounded display totals. Quotes
    waiting counts customer quotes with status new (all time). Average
    is sales / bills. Cash/UPI/Card split paid bills today by mode.
    """
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    today = moment.astimezone(IST).date()
    shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                        (shop_id,)).fetchone()
    bills_today = 0
    sales = Decimal("0.00")
    cash = Decimal("0.00")
    upi = Decimal("0.00")
    card = Decimal("0.00")
    waiting = 0
    for row in db.list_quotes(conn, shop_id):
        if (row["source"] == "customer" and row["kind"] == "quote"
                and row["status"] == "new"):
            waiting += 1
        if (row["kind"] == "bill" and row["status"] in ("billed", "paid")
                and _ist_date(row["created_at"]) == today):
            bills_today += 1
            try:
                if shop is None:
                    amount = Decimal(str(row["total"]))
                else:
                    amount = db.bill_display_totals(shop, row)["rounded"]
            except (InvalidOperation, ValueError):
                continue
            sales += amount
            if row["status"] == "paid":
                mode = _row_mode(row)
                if mode == "cash":
                    cash += amount
                elif mode == "upi":
                    upi += amount
                elif mode == "card":
                    card += amount
    def _q(value: Decimal) -> Decimal:
        if value == 0:
            return Decimal("0.00")
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sales = _q(sales)
    cash = _q(cash)
    upi = _q(upi)
    card = _q(card)
    average = (sales / bills_today).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP) if bills_today else Decimal(
            "0.00")
    return {"bills_today": bills_today, "sales_today": sales,
            "quotes_waiting": waiting, "average_bill": average,
            "sales_cash": cash, "sales_upi": upi, "sales_card": card}


def top_items(conn, shop_id: int, *, now: datetime | None = None,
              limit: int = 5) -> list[dict]:
    """Top items today from billed + paid bills: name, qty, amount."""
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    today = moment.astimezone(IST).date()
    totals: dict[str, dict] = {}
    for row in db.list_quotes(conn, shop_id):
        if row["kind"] != "bill" or row["status"] not in ("billed", "paid"):
            continue
        if _ist_date(row["created_at"]) != today:
            continue
        try:
            lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            continue
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            if line.get("status") not in ("priced", "needs_qty"):
                continue
            if line.get("line_total") is None:
                continue
            name = str(line.get("name_en") or "").strip()
            if not name:
                continue
            try:
                qty = Decimal(str(line.get("qty", "0")))
                amount = Decimal(str(line["line_total"]))
            except (InvalidOperation, ValueError):
                continue
            line_unit = str(line.get("unit") or "").strip() or None
            entry = totals.setdefault(
                name, {"qty": Decimal(0), "unit": line_unit,
                       "amount": Decimal("0.00")})
            if entry["unit"] is None:
                entry["unit"] = line_unit
            adding = qty
            if (line_unit and entry["unit"] and line_unit != entry["unit"]):
                converted = convert(qty, line_unit, entry["unit"])
                if converted is not None:
                    adding = converted
            entry["qty"] += adding
            entry["amount"] += amount
    ranked = sorted(totals.items(),
                    key=lambda kv: (kv[1]["amount"], kv[1]["qty"]),
                    reverse=True)[:max(0, limit)]
    peak = ranked[0][1]["amount"] if ranked else Decimal(0)
    out = []
    for name, entry in ranked:
        width = 0
        if peak and peak > 0:
            width = int((entry["amount"] / peak * 100).to_integral_value(
                rounding=ROUND_HALF_UP))
            width = max(4, min(100, width))
        out.append({
            "name_en": name,
            "display": name[:1].upper() + name[1:] if name else name,
            "qty": format(entry["qty"].normalize(), "f"),
            "unit": _qty_unit_display(entry["unit"], entry["qty"]),
            "amount": format(entry["amount"].quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP).normalize(), "f"),
            "width": width,
        })
    return out


def _qty_unit_display(unit: str | None, qty: Decimal) -> str:
    """Unit shown after a top-item quantity: "kg", "pcs", "dozen"."""
    if not unit:
        return ""
    if unit == "piece":
        return "pc" if qty == 1 else "pcs"
    return unit


def _fmt_money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def _display(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


def _row_phone(row) -> str | None:
    try:
        value = row["customer_phone"]
    except (KeyError, IndexError, TypeError):
        value = None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _customer_label(row, lang: str = "en") -> str:
    return _row_phone(row) or t_for(lang)("bills.walk_in")


def _row_time(row, *, now: datetime | None = None, lang: str = "en") -> str:
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    today = moment.astimezone(IST).date()
    when = _parse_moment(row["created_at"])
    if when is None:
        return ""
    local = when.astimezone(IST)
    clock = local.strftime("%H:%M")
    day = local.date()
    if day == today:
        return clock
    delta = (today - day).days
    if delta == 1:
        return t_for(lang)("bills.time_yesterday", clock=clock)
    return local.strftime("%d %b, ") + clock


def _status_pill(row, lang: str = "en") -> tuple[str, str]:
    t = t_for(lang)
    if row["kind"] == "quote" and row["status"] == "new":
        return (t("bills.pill_quote"), "quote")
    if row["status"] == "billed":
        return (t("bills.pill_billed"), "billed")
    if row["status"] == "paid":
        return (t("bills.pill_paid"), "paid")
    if row["status"] == "cancelled":
        return (t("bills.pill_cancelled"), "info")
    return (str(row["status"]).title(), "info")


def item_photo_urls(conn, shop_id: int) -> dict[str, str]:
    """Map lower-cased item name to its public photo URL (display only)."""
    urls: dict[str, str] = {}
    version_id = db.latest_version(conn, shop_id, published_only=True)
    if version_id is None:
        return urls
    for item in db.version_items(conn, version_id):
        if item.photo and item.name_en:
            urls[item.name_en.strip().lower()] = (
                "/m/" + Path(item.photo).name)
    return urls


def _bill_lines(raw_lines, photos: dict[str, str] | None = None
                ) -> tuple[list[dict], int]:
    lines = []
    photos = photos or {}
    for index, raw in enumerate(raw_lines if isinstance(raw_lines, list)
                               else []):
        if not isinstance(raw, dict):
            continue
        lines.append({
            "index": index,
            "name_en": raw.get("name_en", ""),
            "display": _display(raw.get("name_en", "")),
            "name_local": raw.get("name_local", ""),
            "photo_url": photos.get(
                str(raw.get("name_en", "")).strip().lower()),
            "qty": _fmt_money(raw.get("qty", "")),
            "unit": raw.get("unit") or "",
            "unit_price": _fmt_money(raw.get("unit_price")),
            "per_amount": _fmt_money(raw.get("per_amount")),
            "line_total": _fmt_money(raw.get("line_total")),
            "status": raw.get("status", ""),
            "note": raw.get("note") or "",
        })
    return lines, len(lines)


def _bill_text(shop, bill_id: int, raw_lines: list[dict], total: str,
               lang: str = "en") -> str:
    return bill_whatsapp_text(shop, bill_id, raw_lines, total, lang)


def _whatsapp_link(phone: str | None, text: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    base = f"https://wa.me/{digits}" if digits else "https://wa.me/"
    return f"{base}?text={url_quote(text)}"


def _price_items(conn, shop_id: int, lang: str = "en") -> list[dict]:
    version_id = db.latest_version(conn, shop_id, published_only=True)
    if version_id is None:
        return []
    shop = conn.execute("SELECT currency FROM shops WHERE id = ?",
                        (shop_id,)).fetchone()
    currency = (shop["currency"] if shop else None) or "INR"
    t = t_for(lang)
    items = []
    for index, item in enumerate(db.version_items(conn, version_id)):
        first = item.price_lines[0] if item.price_lines else None
        if item.sold_out:
            summary = t("bill.sold_out")
        elif first is not None and first.price is not None:
            amount = first.per_amount if first.per_amount is not None else ""
            per = f"{amount} {first.unit or ''}".strip()
            price = format_money(first.price, currency)
            if per:
                summary = f"{price} per {per}" if lang == "en" else f"{price} / {per}"
            else:
                summary = price
        else:
            summary = t("bill.no_price_yet")
        items.append({
            "index": index,
            "name_en": item.name_en,
            "display": _display(item.name_en),
            "name_local": item.name_local,
            "unit": first.unit if first is not None else "",
            "summary": summary,
            "sold_out": item.sold_out,
            # Display only: live totals in JS, server recomputes on post.
            "unit_price": _fmt_money(first.price) if first is not None else "",
            "per_amount": _fmt_money(first.per_amount)
            if first is not None else "",
            "photo_url": ("/m/" + Path(item.photo).name
                          if item.photo else None),
        })
    return items


def process_bill_voice_session(conn, session_id: int, audio: Path, *,
                               settings, ledger) -> int | None:
    """Transcribe a spoken order, price it, store a seller bill. Never raises."""
    try:
        db.set_session_status(conn, session_id, "processing",
                              "Listening to the order...")
        db.set_stage(conn, session_id, "listening")
        shop_id = conn.execute(
            "SELECT shop_id FROM sessions WHERE id = ?",
            (session_id,)).fetchone()["shop_id"]
        shop_row = conn.execute("SELECT language FROM shops WHERE id = ?",
                                (shop_id,)).fetchone()
        shop_lang = shop_row["language"] if shop_row else "ta"
        session_dir = Path(settings.data_dir) / "sessions" / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        wav = extract_audio(Path(audio), session_dir / "audio.wav")
        transcript = transcribe_wav(
            wav, keywords=keywords_for(shop_lang), ledger=ledger,
            settings=settings, languages=shop_bias(shop_lang))
        db.set_stage(conn, session_id, "matching")
        wanted = wanted_from_text(transcript.text, ledger=ledger,
                                  settings=settings)
        for line in wanted:
            line.source = "voice"
        if not wanted:
            db.set_session_status(conn, session_id, "failed",
                                  "We could not hear any items. Please try again.")
            return None
        quote = build_quote(conn, shop_id, wanted)
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, token)["id"]
        write_bill_meta(Path(settings.data_dir), session_id, {"bill_id": bill_id})
        db.set_stage(conn, session_id, "ready")
        db.set_session_status(conn, session_id, "review",
                              f"{len(quote.lines)} lines billed")
        return bill_id
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
        return None
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="recording"))
        return None


def process_bill_photo_session(conn, session_id: int, image: Path, *,
                               settings, ledger) -> int | None:
    """Read a basket photo, price it, store a seller bill. Never raises."""
    try:
        db.set_session_status(conn, session_id, "processing",
                              "Looking at the basket...")
        db.set_stage(conn, session_id, "looking")
        shop_id = conn.execute(
            "SELECT shop_id FROM sessions WHERE id = ?",
            (session_id,)).fetchone()["shop_id"]
        db.set_stage(conn, session_id, "matching")
        wanted = wanted_from_photo(Path(image), ledger=ledger,
                                   settings=settings)
        if not wanted:
            db.set_session_status(conn, session_id, "failed",
                                  "We could not read that photo. Please try again.")
            return None
        quote = build_quote(conn, shop_id, wanted)
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, token)["id"]
        write_bill_meta(Path(settings.data_dir), session_id, {"bill_id": bill_id})
        db.set_stage(conn, session_id, "ready")
        db.set_session_status(conn, session_id, "review",
                              f"{len(quote.lines)} lines billed")
        return bill_id
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
        return None
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="photo"))
        return None


def run_bill_voice_job(settings, session_id: int, audio: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_bill_voice_session(conn, session_id, Path(audio),
                                   settings=settings, ledger=ledger)
    finally:
        conn.close()


def run_bill_photo_job(settings, session_id: int, image: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_bill_photo_session(conn, session_id, Path(image),
                                   settings=settings, ledger=ledger)
    finally:
        conn.close()


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _filtered(conn, shop_id: int, range_key: str, status_key: str,
                  now: datetime) -> list:
        today = now.astimezone(IST).date()
        rows = []
        for row in db.list_quotes(conn, shop_id):
            day = _ist_date(row["created_at"])
            if range_key == "today" and day != today:
                continue
            if range_key == "yesterday" and (
                    day is None or (today - day).days != 1):
                continue
            if range_key == "week" and (
                    day is None or not 0 <= (today - day).days <= 6):
                continue
            if status_key == "waiting" and not (
                    row["kind"] == "quote" and row["status"] == "new"):
                continue
            if status_key == "billed" and not (
                    row["kind"] == "bill" and row["status"] == "billed"):
                continue
            if status_key == "paid" and row["status"] != "paid":
                continue
            rows.append(row)
        return rows

    def _list_context(request, shop, token, range_key, status_key):
        conn = db.connect(data_dir)
        try:
            now = datetime.now(UTC)
            ui_lang = get_ui_lang(request, shop)
            tiles = bills_tiles(conn, shop["id"], now=now)
            rows = _filtered(conn, shop["id"], range_key, status_key, now)
            items = []
            for row in rows:
                try:
                    raw = json.loads(row["lines_json"] or "[]")
                except ValueError:
                    raw = []
                count = len(raw) if isinstance(raw, list) else 0
                text, kind = _status_pill(row, ui_lang)
                names = [_display(str(entry.get("name_en", "")))
                         for entry in raw
                         if isinstance(entry, dict) and entry.get("name_en")]
                try:
                    display_total = db.bill_display_totals(
                        shop, row)["rounded"]
                except (InvalidOperation, ValueError):
                    display_total = row["total"]
                items.append({
                    "id": row["id"],
                    "label": _customer_label(row, ui_lang),
                    "time": _row_time(row, now=now, lang=ui_lang),
                    "count": count,
                    "names": names,
                    "total": _fmt_money(display_total),
                    "pill_text": text,
                    "pill_kind": kind,
                    "mode": _mode_label(_row_mode(row), ui_lang),
                })
            return templates.TemplateResponse(request, "bills.html", {
                "shop": shop, "token": token, "range": range_key,
                "status": status_key, "rows": items,
                "bills_today": tiles["bills_today"],
                "sales_today": _fmt_money(tiles["sales_today"]),
                "sales_cash": _fmt_money(tiles["sales_cash"]),
                "sales_upi": _fmt_money(tiles["sales_upi"]),
                "sales_card": _fmt_money(tiles["sales_card"]),
                "quotes_waiting": tiles["quotes_waiting"],
                "average_bill": _fmt_money(tiles["average_bill"]),
                "top": top_items(conn, shop["id"], now=now),
                "ui_lang": ui_lang,
            })
        finally:
            conn.close()

    def _bill_context(request, shop, token, bill, conn, error=None,
                      status_code=200):
        from app.outputs.qr import qr_svg

        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        try:
            raw_lines = json.loads(bill["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        if not isinstance(raw_lines, list):
            raw_lines = []
        lines, _ = _bill_lines(
            raw_lines, item_photo_urls(conn, shop["id"]))
        text, kind = _status_pill(bill, ui_lang)
        when = _parse_moment(bill["created_at"])
        created_label = when.astimezone(IST).strftime(
            "%d %b %Y, %H:%M") if when else ""
        phone = _row_phone(bill)
        totals = db.bill_display_totals(shop, bill)
        exact = totals["exact"]
        rounded = totals["rounded"]
        off = totals["off"]
        show_round = bool(totals["enabled"] and off != 0)
        currency = (shop["currency"] or "INR").upper()
        is_inr = currency == "INR"
        upi_id = db.shop_upi_id(shop)
        upi_url = None
        upi_qr = None
        if is_inr and upi_id and bill["kind"] == "bill":
            upi_url = build_upi_url(upi_id, db.shop_upi_payee(shop),
                                    rounded, bill["id"], shop["name"])
            upi_qr = qr_svg(upi_url)
        bill_token = db.ensure_bill_token(conn, bill["id"])
        public_url = (
            f"{request.app.state.settings.public_base_url}/b/{bill_token}")
        mode = _row_mode(bill)
        try:
            paid_at = bill["paid_at"]
        except (KeyError, IndexError, TypeError):
            paid_at = None
        pay_modes = (("cash", t("bill.paid_cash")), ("upi", t("bill.paid_upi"))
                     ) if is_inr else (("cash", t("bill.paid_cash")),
                                       ("card", t("bill.paid_card")))
        return templates.TemplateResponse(request, "bill.html", {
            "shop": shop, "token": token, "bill": bill, "lines": lines,
            "total": _fmt_money(rounded),
            "total_exact": _fmt_money(exact),
            "round_off": f"{off:+.2f}" if show_round else "",
            "show_round": show_round,
            "pill_text": text, "pill_kind": kind,
            "created_label": created_label, "phone": phone or "",
            "label": _customer_label(bill, ui_lang), "error": error,
            "price_items": _price_items(conn, shop["id"], ui_lang),
            "whatsapp_url": _whatsapp_link(
                phone, _bill_text(shop, bill["id"], raw_lines,
                                  str(rounded), ui_lang)),
            "is_quote": bill["kind"] == "quote" and bill["status"] == "new",
            "is_billed": bill["kind"] == "bill" and bill["status"] == "billed",
            "is_paid": bill["status"] == "paid",
            "is_inr": is_inr, "upi_id": upi_id, "upi_url": upi_url,
            "upi_qr": upi_qr, "pay_modes": pay_modes,
            "mode_label": _mode_label(mode, ui_lang),
            "paid_at": paid_at or "",
            "bill_token": bill_token, "public_url": public_url,
            "public_qr": qr_svg(public_url), "ui_lang": ui_lang,
        }, status_code=status_code)

    @app.get("/e/{token}/bills")
    def bills_list(request: Request, token: str, conn: Conn,
                   range: str = "today", status: str = "all"):
        shop = _shop_or_404(conn, token)
        range_key = range if range in ("today", "yesterday", "week") else "today"
        status_key = (status if status in ("all", "waiting", "billed", "paid")
                      else "all")
        return _list_context(request, shop, token, range_key, status_key)

    @app.get("/e/{token}/bills/new")
    def bills_new_page(request: Request, token: str, conn: Conn):
        shop = _shop_or_404(conn, token)
        ui_lang = get_ui_lang(request, shop)
        return templates.TemplateResponse(request, "bills_new.html", {
            "shop": shop, "token": token,
            "price_items": _price_items(conn, shop["id"], ui_lang),
            "error": None, "ui_lang": ui_lang})

    @app.post("/e/{token}/bills/new")
    async def bills_new_post(request: Request, token: str):
        conn = db.connect(data_dir)
        try:
            return await _bills_new_impl(request, token, conn)
        finally:
            conn.close()

    async def _bills_new_impl(request: Request, token: str, conn):
        shop = _shop_or_404(conn, token)
        form = await request.form()
        audio = form.get("audio")
        photo = form.get("photo")
        has_audio = audio is not None and hasattr(audio, "file")
        has_photo = photo is not None and hasattr(photo, "file")
        if has_audio:
            return _start_voice_bill(request, shop, token, audio, conn)
        if has_photo:
            return _start_photo_bill(request, shop, token, photo, conn)
        text = str(form.get("items") or "").strip()
        if text:
            return _type_bill(request, shop, token, text, conn)
        return _tap_bill(request, shop, token, form, conn)

    def _guarded(request, shop, token=None):
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        ctx = {"token": token, "ui_lang": ui_lang} if token else {"ui_lang": ui_lang}
        if not request.app.state.limiter.allow(client_ip(request),
                                               datetime.now(UTC)):
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.too_many_title"),
                 "message": RATE_LIMIT_MESSAGE, **ctx},
                status_code=429)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            ledger.check()
        except CostCapExceeded:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.budget_title"),
                 "message": BUDGET_EXHAUSTED_MESSAGE, **ctx},
                status_code=503)
        return None

    def _new_error(request, shop, token, conn, message, status_code=400):
        ui_lang = get_ui_lang(request, shop)
        return templates.TemplateResponse(request, "bills_new.html", {
            "shop": shop, "token": token,
            "price_items": _price_items(conn, shop["id"], ui_lang),
            "error": message, "ui_lang": ui_lang},
            status_code=status_code)

    def _start_voice_bill(request, shop, token, audio, conn):
        denied = _guarded(request, shop, token)
        if denied is not None:
            return denied
        payload = audio.file.read() if hasattr(audio.file, "read") else b""
        if not payload:
            return _new_error(request, shop, token, conn,
                              "That recording was empty.")
        session_id = db.create_session(conn, shop["id"], "bill_voice")
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(getattr(audio, "filename", "") or "order.webm").name
        saved = uploads / f"b{session_id}_{secrets.token_hex(4)}_{safe_name}"
        saved.write_bytes(payload)
        write_bill_meta(data_dir, session_id, {"bill_id": None})
        jobs.submit(run_bill_voice_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/bills/new/{session_id}",
                                status_code=303)

    def _start_photo_bill(request, shop, token, photo: UploadFile, conn):
        denied = _guarded(request, shop, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        payload = photo.file.read()
        if not payload:
            return _new_error(request, shop, token, conn,
                              "Choose a photo first.")
        if len(payload) > MAX_BILL_PHOTO_BYTES:
            size_mb = len(payload) / (1024 * 1024)
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.photo_big_title"),
                 "message": (f"That photo is {size_mb:.0f} MB, which is too big"
                             " to upload. Please choose a photo under 10 MB."),
                 "token": token, "ui_lang": ui_lang},
                status_code=400)
        try:
            with Image.open(io.BytesIO(payload)) as img:
                img.load()
                photo_format = (img.format or "").lower()
        except Exception:  # noqa: BLE001 - any unreadable file is a 400
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.not_photo_title"),
                 "message": "We could not open that file as a photo.",
                 "token": token, "ui_lang": ui_lang},
                status_code=400)
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png",
               "webp": ".webp"}.get(photo_format, ".jpg")
        session_id = db.create_session(conn, shop["id"], "bill_photo")
        photo_dir = data_dir / "photos"
        photo_dir.mkdir(parents=True, exist_ok=True)
        saved = photo_dir / f"b{session_id}_{secrets.token_hex(4)}{ext}"
        saved.write_bytes(payload)
        write_bill_meta(data_dir, session_id, {"bill_id": None})
        jobs.submit(run_bill_photo_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/bills/new/{session_id}",
                                status_code=303)

    def _type_bill(request, shop, token, text, conn):
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            wanted = wanted_from_text(text, ledger=ledger,
                                      settings=app.state.settings)
        except CostCapExceeded:
            return _new_error(request, shop, token, conn,
                              BUDGET_EXHAUSTED_MESSAGE, 503)
        except SparkError as exc:
            return _new_error(request, shop, token, conn, str(exc), 502)
        if not wanted:
            return _new_error(request, shop, token, conn,
                              "We could not understand that list.")
        quote = build_quote(conn, shop["id"], wanted)
        quote_token = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                      source="seller", kind="bill",
                                      status="billed")
        bill_id = db.get_quote_by_token(conn, quote_token)["id"]
        return RedirectResponse(f"/e/{token}/bills/{bill_id}", status_code=303)

    def _tap_bill(request, shop, token, form, conn):
        indices: list[int] = []
        for key in form:
            for prefix in ("qty_", "amount_"):
                if key.startswith(prefix):
                    try:
                        indices.append(int(key[len(prefix):]))
                    except ValueError:
                        continue
        wanted: list[WantedLine] = []
        for index in sorted(set(indices)):
            name = str(form.get(f"name_en_{index}") or "").strip()
            if not name:
                continue
            raw_amount = str(form.get(f"amount_{index}") or "").strip()
            if raw_amount:
                try:
                    amount = Decimal(raw_amount)
                except InvalidOperation:
                    return _new_error(
                        request, shop, token, conn,
                        f"Amount for {name} does not look right.")
                if amount.is_nan() or amount <= 0:
                    return _new_error(
                        request, shop, token, conn,
                        f"Amount for {name} does not look right.")
                wanted.append(WantedLine(name_en=name, qty=None, unit=None,
                                         source="tap", amount=amount))
                continue
            raw_qty = str(form.get(f"qty_{index}") or "").strip()
            if raw_qty == "":
                continue
            try:
                qty = Decimal(raw_qty)
            except InvalidOperation:
                return _new_error(
                    request, shop, token, conn,
                    f"Quantity for {name} does not look right.")
            if qty.is_nan() or qty < 0:
                return _new_error(
                    request, shop, token, conn,
                    f"Quantity for {name} does not look right.")
            if qty == 0:
                continue
            unit = str(form.get(f"unit_{index}") or "").strip() or None
            wanted.append(WantedLine(name_en=name, qty=qty, unit=unit,
                                     source="tap"))
        if not wanted:
            return _new_error(request, shop, token, conn,
                              "Pick at least one item with + first.")
        quote = build_quote(conn, shop["id"], wanted)
        quote_token = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                      source="seller", kind="bill",
                                      status="billed")
        bill_id = db.get_quote_by_token(conn, quote_token)["id"]
        return RedirectResponse(f"/e/{token}/bills/{bill_id}", status_code=303)

    @app.get("/e/{token}/bills/new/{session_id}")
    def bills_new_status_page(request: Request, token: str, session_id: int,
                              conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        meta = read_bill_meta(data_dir, session_id)
        if meta.get("bill_id") and session["status"] in ("review", "approved"):
            return RedirectResponse(f"/e/{token}/bills/{meta['bill_id']}",
                                    status_code=303)
        raw = db.session_progress(session)
        kind = session["kind"]
        steps = [{**step, "label": stage_label(kind, step.get("key", ""),
                                               ui_lang)}
                 for step in raw.get("steps", [])]
        progress = {**raw, "steps": steps}
        friendly = stage_friendly(kind, raw.get("stage", ""), ui_lang)
        return templates.TemplateResponse(request, "bills_status.html", {
            "shop": shop, "token": token, "session": session,
            "progress": progress, "friendly": friendly,
            "ui_lang": ui_lang})

    @app.get("/e/{token}/bills/new/{session_id}/status")
    def bills_new_status_json(request: Request, token: str, session_id: int,
                              conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        raw = db.session_progress(session)
        kind = session["kind"]
        steps = [{**step, "label": stage_label(kind, step.get("key", ""),
                                               ui_lang)}
                 for step in raw.get("steps", [])]
        meta = read_bill_meta(data_dir, session_id)
        return JSONResponse({
            "status": session["status"], "message": session["message"],
            "stage": raw["stage"], "step": raw["step"],
            "steps": steps, "detail": raw["detail"],
            "elapsed_s": raw["elapsed_s"],
            "friendly": stage_friendly(kind, raw.get("stage", ""), ui_lang),
            "bill_id": meta.get("bill_id"),
        })

    @app.get("/e/{token}/bills/{bill_id}")
    def bill_page(request: Request, token: str, bill_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        bill = _bill_of_shop(conn, shop["id"], bill_id)
        return _bill_context(request, shop, token, bill, conn)

    @app.post("/e/{token}/bills/{bill_id}/lines")
    async def bill_lines_post(request: Request, token: str, bill_id: int):
        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            bill = _bill_of_shop(conn, shop["id"], bill_id)
            try:
                original = json.loads(bill["lines_json"] or "[]")
            except ValueError:
                original = []
            if not isinstance(original, list):
                original = []
            form = await request.form()
            updates = []
            for index, line in enumerate(original):
                fallback = line if isinstance(line, dict) else {}
                updates.append({
                    "name_en": form.get(f"name_en_{index}",
                                        fallback.get("name_en", "")),
                    "qty": form.get(f"qty_{index}", fallback.get("qty", "1")),
                    "unit": form.get(f"unit_{index}", fallback.get("unit")),
                    "amount": form.get(f"amount_{index}", ""),
                })
            try:
                db.update_bill_lines(conn, bill["id"], updates)
            except (ValueError, TypeError) as exc:
                fresh = _bill_of_shop(conn, shop["id"], bill_id)
                return _bill_context(request, shop, token, fresh, conn,
                                     error=str(exc))
            return RedirectResponse(f"/e/{token}/bills/{bill_id}",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/bills/{bill_id}/add")
    async def bill_add_post(request: Request, token: str, bill_id: int):
        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            bill = _bill_of_shop(conn, shop["id"], bill_id)
            form = await request.form()
            try:
                db.add_bill_line(conn, bill["id"], {
                    "name_en": form.get("name_en", ""),
                    "qty": form.get("qty", ""),
                    "unit": form.get("unit"),
                })
            except (ValueError, TypeError) as exc:
                fresh = _bill_of_shop(conn, shop["id"], bill_id)
                return _bill_context(request, shop, token, fresh, conn,
                                     error=str(exc))
            return RedirectResponse(f"/e/{token}/bills/{bill_id}",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/bills/{bill_id}/remove")
    async def bill_remove_post(request: Request, token: str, bill_id: int):
        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            bill = _bill_of_shop(conn, shop["id"], bill_id)
            form = await request.form()
            try:
                db.remove_bill_line(conn, bill["id"], form.get("index", ""))
            except (ValueError, TypeError) as exc:
                fresh = _bill_of_shop(conn, shop["id"], bill_id)
                return _bill_context(request, shop, token, fresh, conn,
                                     error=str(exc))
            return RedirectResponse(f"/e/{token}/bills/{bill_id}",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/bills/{bill_id}/phone")
    async def bill_phone_post(request: Request, token: str, bill_id: int):
        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            bill = _bill_of_shop(conn, shop["id"], bill_id)
            form = await request.form()
            try:
                db.set_bill_phone(conn, bill["id"],
                                  form.get("customer_phone", ""))
            except ValueError as exc:
                fresh = _bill_of_shop(conn, shop["id"], bill_id)
                return _bill_context(request, shop, token, fresh, conn,
                                     error=str(exc))
            return RedirectResponse(f"/e/{token}/bills/{bill_id}",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/bills/{bill_id}/paid")
    async def bill_paid_post(request: Request, token: str, bill_id: int):
        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            bill = _bill_of_shop(conn, shop["id"], bill_id)
            form = await request.form()
            mode = str(form.get("mode") or "cash").strip().lower() or "cash"
            currency = (shop["currency"] or "INR").upper()
            allowed = ({"cash", "upi"} if currency == "INR"
                       else {"cash", "card"})
            if mode not in allowed:
                fresh = _bill_of_shop(conn, shop["id"], bill_id)
                return _bill_context(request, shop, token, fresh, conn,
                                     error="that payment mode is not available"
                                     " for this shop",
                                     status_code=400)
            try:
                db.mark_bill_paid(conn, bill["id"], mode)
            except ValueError as exc:
                fresh = _bill_of_shop(conn, shop["id"], bill_id)
                return _bill_context(request, shop, token, fresh, conn,
                                     error=str(exc))
            return RedirectResponse(f"/e/{token}/bills/{bill_id}",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/bills/{bill_id}/accept")
    def bill_accept_post(request: Request, token: str, bill_id: int,
                         conn: Conn):
        shop = _shop_or_404(conn, token)
        bill = _bill_of_shop(conn, shop["id"], bill_id)
        try:
            db.accept_quote_as_bill(conn, bill["id"])
        except ValueError as exc:
            fresh = _bill_of_shop(conn, shop["id"], bill_id)
            return _bill_context(request, shop, token, fresh, conn,
                                 error=str(exc))
        return RedirectResponse(f"/e/{token}/bills/{bill_id}", status_code=303)

    @app.get("/e/{token}/bills/{bill_id}/pdf")
    def bill_pdf_route(request: Request, token: str, bill_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        bill = _bill_of_shop(conn, shop["id"], bill_id)
        ui_lang = get_ui_lang(request, shop)
        try:
            raw_lines = json.loads(bill["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        when = _parse_moment(bill["created_at"])
        created_label = when.astimezone(IST).strftime(
            "%d %b %Y, %H:%M") if when else ""
        totals = db.bill_display_totals(shop, bill)
        pdf = bill_pdf(shop, bill["id"],
                       raw_lines if isinstance(raw_lines, list) else [],
                       str(totals["rounded"]), created_label,
                       _row_phone(bill), lang=ui_lang)
        return Response(pdf, media_type="application/pdf")

    @app.get("/b/{bill_token}")
    def public_bill_page(request: Request, bill_token: str, conn: Conn):
        bill = db.get_quote_by_bill_token(conn, bill_token)
        if bill is None:
            raise HTTPException(404, "unknown bill")
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (bill["shop_id"],)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown bill")
        try:
            raw_lines = json.loads(bill["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        if not isinstance(raw_lines, list):
            raw_lines = []
        lines, _ = _bill_lines(raw_lines, None)
        totals = db.bill_display_totals(shop, bill)
        when = _parse_moment(bill["created_at"])
        created_label = when.astimezone(IST).strftime(
            "%d %b %Y, %H:%M") if when else ""
        shop_lang = (shop["language"] or "en").strip().lower()
        ui_lang = shop_lang if shop_lang in ("ta", "hi") else "en"
        text, kind = _status_pill(bill, ui_lang)
        return templates.TemplateResponse(request, "bill_public.html", {
            "shop": shop, "bill": bill, "lines": lines,
            "total": _fmt_money(totals["rounded"]),
            "total_exact": _fmt_money(totals["exact"]),
            "round_off": (f"{totals['off']:+.2f}"
                          if totals["enabled"] and totals["off"] != 0
                          else ""),
            "show_round": bool(totals["enabled"] and totals["off"] != 0),
            "pill_text": text, "pill_kind": kind,
            "created_label": created_label,
            "mode_label": _mode_label(_row_mode(bill), ui_lang),
            "ui_lang": ui_lang,
        })
