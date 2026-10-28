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
from app.pipeline.media import extract_audio
from app.pipeline.names import PRODUCE_KEYWORDS
from app.pipeline.run import friendly_error_message

MAX_BILL_PHOTO_BYTES = 10 * 1024 * 1024


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
    today (IST). Sales today sums their totals. Quotes waiting counts
    customer quotes with status new (all time). Average is sales / bills.
    """
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    today = moment.astimezone(IST).date()
    bills_today = 0
    sales = Decimal("0.00")
    waiting = 0
    for row in db.list_quotes(conn, shop_id):
        if (row["source"] == "customer" and row["kind"] == "quote"
                and row["status"] == "new"):
            waiting += 1
        if (row["kind"] == "bill" and row["status"] in ("billed", "paid")
                and _ist_date(row["created_at"]) == today):
            bills_today += 1
            try:
                sales += Decimal(str(row["total"]))
            except (InvalidOperation, ValueError):
                continue
    if sales == 0:
        sales = Decimal("0.00")
    else:
        sales = sales.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    average = (sales / bills_today).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP) if bills_today else Decimal(
            "0.00")
    return {"bills_today": bills_today, "sales_today": sales,
            "quotes_waiting": waiting, "average_bill": average}


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
            entry = totals.setdefault(
                name, {"qty": Decimal(0), "amount": Decimal("0.00")})
            entry["qty"] += qty
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
            "amount": format(entry["amount"].quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP).normalize(), "f"),
            "width": width,
        })
    return out


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


def _customer_label(row) -> str:
    return _row_phone(row) or "Walk-in"


def _row_time(row, *, now: datetime | None = None) -> str:
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
        return f"Yesterday {clock}"
    return local.strftime("%d %b, ") + clock


def _status_pill(row) -> tuple[str, str]:
    if row["kind"] == "quote" and row["status"] == "new":
        return ("Quote", "quote")
    if row["status"] == "billed":
        return ("Billed", "billed")
    if row["status"] == "paid":
        return ("Paid", "paid")
    if row["status"] == "cancelled":
        return ("Cancelled", "info")
    return (str(row["status"]).title(), "info")


def _bill_lines(raw_lines) -> tuple[list[dict], int]:
    lines = []
    for index, raw in enumerate(raw_lines if isinstance(raw_lines, list)
                               else []):
        if not isinstance(raw, dict):
            continue
        lines.append({
            "index": index,
            "name_en": raw.get("name_en", ""),
            "display": _display(raw.get("name_en", "")),
            "name_local": raw.get("name_local", ""),
            "qty": _fmt_money(raw.get("qty", "")),
            "unit": raw.get("unit") or "",
            "unit_price": _fmt_money(raw.get("unit_price")),
            "per_amount": _fmt_money(raw.get("per_amount")),
            "line_total": _fmt_money(raw.get("line_total")),
            "status": raw.get("status", ""),
            "note": raw.get("note") or "",
        })
    return lines, len(lines)


def _bill_text(shop, bill_id: int, raw_lines: list[dict], total: str) -> str:
    parts = [f"Bill {bill_id} from {shop['name']}"]
    for raw in raw_lines:
        name = _display(raw.get("name_en", ""))
        status = raw.get("status", "")
        if status in ("priced", "needs_qty") and raw.get("line_total"):
            qty = _fmt_money(raw.get("qty", ""))
            unit = raw.get("unit") or ""
            parts.append(
                f"{name} {qty} {unit} - Rs.{_fmt_money(raw['line_total'])}"
                .strip())
        elif status == "sold_out":
            parts.append(f"{name} - sold out")
        else:
            parts.append(f"{name} - not on list")
    parts.append(f"Total: Rs.{_fmt_money(total)}")
    return "\n".join(parts)


def _whatsapp_link(phone: str | None, text: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    base = f"https://wa.me/{digits}" if digits else "https://wa.me/"
    return f"{base}?text={url_quote(text)}"


def _price_items(conn, shop_id: int) -> list[dict]:
    version_id = db.latest_version(conn, shop_id, published_only=True)
    if version_id is None:
        return []
    items = []
    for index, item in enumerate(db.version_items(conn, version_id)):
        first = item.price_lines[0] if item.price_lines else None
        if item.sold_out:
            summary = "Sold out"
        elif first is not None and first.price is not None:
            amount = first.per_amount if first.per_amount is not None else ""
            summary = f"Rs.{_fmt_money(first.price)} per {amount} {first.unit or ''}".strip()
        else:
            summary = "No price yet"
        items.append({
            "index": index,
            "name_en": item.name_en,
            "display": _display(item.name_en),
            "name_local": item.name_local,
            "unit": first.unit if first is not None else "",
            "summary": summary,
            "sold_out": item.sold_out,
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
            wav, keywords=PRODUCE_KEYWORDS, ledger=ledger, settings=settings,
            languages=shop_bias(shop_lang))
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

    def _currency(shop) -> str:
        return "Rs." if (shop["currency"] or "INR") != "INR" else "₹"

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
            tiles = bills_tiles(conn, shop["id"], now=now)
            rows = _filtered(conn, shop["id"], range_key, status_key, now)
            items = []
            for row in rows:
                try:
                    raw = json.loads(row["lines_json"] or "[]")
                except ValueError:
                    raw = []
                count = len(raw) if isinstance(raw, list) else 0
                text, kind = _status_pill(row)
                items.append({
                    "id": row["id"],
                    "label": _customer_label(row),
                    "time": _row_time(row, now=now),
                    "count": count,
                    "total": _fmt_money(row["total"]),
                    "pill_text": text,
                    "pill_kind": kind,
                })
            symbol = _currency(shop)
            return templates.TemplateResponse(request, "bills.html", {
                "shop": shop, "token": token, "range": range_key,
                "status": status_key, "rows": items,
                "symbol": symbol,
                "bills_today": tiles["bills_today"],
                "sales_today": _fmt_money(tiles["sales_today"]),
                "quotes_waiting": tiles["quotes_waiting"],
                "average_bill": _fmt_money(tiles["average_bill"]),
                "top": top_items(conn, shop["id"], now=now),
            })
        finally:
            conn.close()

    def _bill_context(request, shop, token, bill, conn, error=None):
        try:
            raw_lines = json.loads(bill["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        if not isinstance(raw_lines, list):
            raw_lines = []
        lines, _ = _bill_lines(raw_lines)
        text, kind = _status_pill(bill)
        when = _parse_moment(bill["created_at"])
        created_label = when.astimezone(IST).strftime(
            "%d %b %Y, %H:%M") if when else ""
        phone = _row_phone(bill)
        return templates.TemplateResponse(request, "bill.html", {
            "shop": shop, "token": token, "bill": bill, "lines": lines,
            "total": _fmt_money(bill["total"]),
            "pill_text": text, "pill_kind": kind,
            "created_label": created_label, "phone": phone or "",
            "label": _customer_label(bill), "error": error,
            "symbol": _currency(shop),
            "price_items": _price_items(conn, shop["id"]),
            "whatsapp_url": _whatsapp_link(
                phone, _bill_text(shop, bill["id"], raw_lines,
                                  bill["total"])),
            "is_quote": bill["kind"] == "quote" and bill["status"] == "new",
            "is_billed": bill["kind"] == "bill" and bill["status"] == "billed",
            "is_paid": bill["status"] == "paid",
        })

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
        return templates.TemplateResponse(request, "bills_new.html", {
            "shop": shop, "token": token,
            "price_items": _price_items(conn, shop["id"]), "error": None})

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

    def _guarded(request, shop):
        if not request.app.state.limiter.allow(client_ip(request),
                                               datetime.now(UTC)):
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Too many uploads", "message": RATE_LIMIT_MESSAGE},
                status_code=429)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            ledger.check()
        except CostCapExceeded:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Demo budget used up",
                 "message": BUDGET_EXHAUSTED_MESSAGE},
                status_code=503)
        return None

    def _new_error(request, shop, token, conn, message, status_code=400):
        return templates.TemplateResponse(request, "bills_new.html", {
            "shop": shop, "token": token,
            "price_items": _price_items(conn, shop["id"]), "error": message},
            status_code=status_code)

    def _start_voice_bill(request, shop, token, audio, conn):
        denied = _guarded(request, shop)
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
        denied = _guarded(request, shop)
        if denied is not None:
            return denied
        payload = photo.file.read()
        if not payload:
            return _new_error(request, shop, token, conn,
                              "Choose a photo first.")
        if len(payload) > MAX_BILL_PHOTO_BYTES:
            size_mb = len(payload) / (1024 * 1024)
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Photo too big",
                 "message": (f"That photo is {size_mb:.0f} MB, which is too big"
                             " to upload. Please choose a photo under 10 MB.")},
                status_code=400)
        try:
            with Image.open(io.BytesIO(payload)) as img:
                img.load()
                photo_format = (img.format or "").lower()
        except Exception:  # noqa: BLE001 - any unreadable file is a 400
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Not a photo",
                 "message": "We could not open that file as a photo."},
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
            if key.startswith("qty_"):
                try:
                    indices.append(int(key[len("qty_"):]))
                except ValueError:
                    continue
        wanted: list[WantedLine] = []
        for index in sorted(set(indices)):
            name = str(form.get(f"name_en_{index}") or "").strip()
            if not name:
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
        meta = read_bill_meta(data_dir, session_id)
        if meta.get("bill_id") and session["status"] in ("review", "approved"):
            return RedirectResponse(f"/e/{token}/bills/{meta['bill_id']}",
                                    status_code=303)
        progress = db.session_progress(session)
        return templates.TemplateResponse(request, "bills_status.html", {
            "shop": shop, "token": token, "session": session,
            "progress": progress,
            "friendly": db.stage_friendly(session["kind"],
                                          progress["stage"])})

    @app.get("/e/{token}/bills/new/{session_id}/status")
    def bills_new_status_json(token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        progress = db.session_progress(session)
        meta = read_bill_meta(data_dir, session_id)
        return JSONResponse({
            "status": session["status"], "message": session["message"],
            "stage": progress["stage"], "step": progress["step"],
            "steps": progress["steps"], "detail": progress["detail"],
            "elapsed_s": progress["elapsed_s"],
            "friendly": db.stage_friendly(session["kind"], progress["stage"]),
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
    def bill_paid_post(request: Request, token: str, bill_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        bill = _bill_of_shop(conn, shop["id"], bill_id)
        try:
            db.mark_bill_paid(conn, bill["id"])
        except ValueError as exc:
            fresh = _bill_of_shop(conn, shop["id"], bill_id)
            return _bill_context(request, shop, token, fresh, conn,
                                 error=str(exc))
        return RedirectResponse(f"/e/{token}/bills/{bill_id}", status_code=303)

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
    def bill_pdf_route(token: str, bill_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        bill = _bill_of_shop(conn, shop["id"], bill_id)
        try:
            raw_lines = json.loads(bill["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        when = _parse_moment(bill["created_at"])
        created_label = when.astimezone(IST).strftime(
            "%d %b %Y, %H:%M") if when else ""
        pdf = bill_pdf(shop, bill["id"],
                       raw_lines if isinstance(raw_lines, list) else [],
                       bill["total"], created_label, _row_phone(bill))
        return Response(pdf, media_type="application/pdf")
