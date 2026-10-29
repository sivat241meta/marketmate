"""Customer quotations: voice, text or photo to a priced quote.

A quote only uses the shop's own published price lines. Items not on the
list are shown as "not on this shop's list", never priced.
"""

import io
import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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
from app.languages import get_language, shop_bias
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.market.order_parse import wanted_local_first
from app.market.quote import (
    WantedLine,
    build_quote,
    wanted_from_photo,
    wanted_from_text,
)
from app.meta.spark import SparkError
from app.meta.transcribe import transcribe_wav
from app.outputs.money import format_money
from app.outputs.quote_pdf import quote_pdf
from app.outputs.time import format_relative
from app.pipeline.media import extract_audio
from app.pipeline.names import display_name_en, display_name_local, keywords_for
from app.pipeline.run import friendly_error_message
from app.web.i18n import get_strings, quote_whatsapp_text

MAX_QUOTE_PHOTO_BYTES = 10 * 1024 * 1024

#: Customer contact rules (Task 60): name required, 1-40 chars; phone
#: optional, a 10-digit Indian mobile or +country digits.
CUSTOMER_NAME_MAX = 40
_PHONE_STRIP_RE = re.compile(r"[\s\-()]+")
_INDIAN_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
_INTL_PHONE_RE = re.compile(r"^\+\d{7,15}$")


def clean_customer_name(raw) -> str:
    return str(raw or "").strip()


def clean_customer_phone(raw) -> str:
    return _PHONE_STRIP_RE.sub("", str(raw or "")).strip()


def customer_name_ok(name: str) -> bool:
    return 1 <= len(name or "") <= CUSTOMER_NAME_MAX


def customer_phone_ok(phone: str) -> bool:
    if not phone:
        return True
    return bool(_INDIAN_MOBILE_RE.match(phone)
                or _INTL_PHONE_RE.match(phone))


def _effective_order_status(status: str) -> str:
    """Customer-facing status: paid reads collected, billed reads new."""
    if status == "paid":
        return "collected"
    if status == "billed":
        return "new"
    return status


def order_steps(status: str, strings) -> list[dict]:
    """Timeline steps for a customer order status."""
    effective = _effective_order_status(status)
    steps = []
    for key in db.ORDER_STEPS:
        steps.append({
            "key": key,
            "label": strings[f"order.step_{key}"],
            "done": (db.ORDER_STEPS.index(effective)
                     >= db.ORDER_STEPS.index(key))
            if effective in db.ORDER_STEPS else False,
            "current": effective == key,
        })
    return steps


def quote_meta_path(data_dir: Path, session_id: int) -> Path:
    return Path(data_dir) / "sessions" / str(session_id) / "quote.json"


def read_quote_meta(data_dir: Path, session_id: int) -> dict:
    try:
        return json.loads(quote_meta_path(data_dir, session_id).read_text())
    except (OSError, ValueError):
        return {}


def write_quote_meta(data_dir: Path, session_id: int, payload: dict) -> None:
    path = quote_meta_path(data_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _shop_or_404(conn, slug: str):
    shop = db.shop_by_slug(conn, slug)
    if shop is None:
        raise HTTPException(404, "unknown shop")
    return shop


def _customer_lang(shop, lang: str | None) -> str:
    """Customer page language: English or the shop language, else English."""
    shop_lang = shop["language"] or "en"
    try:
        get_language(shop_lang)
    except KeyError:
        shop_lang = "en"
    return lang if lang in ("en", shop_lang) else "en"


def _shop_language(conn, shop_id: int) -> str:
    row = conn.execute("SELECT language FROM shops WHERE id = ?",
                       (shop_id,)).fetchone()
    return row["language"] if row and row["language"] else "ta"


def _session_of_shop(conn, shop_id: int, session_id: int):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND shop_id = ?",
        (session_id, shop_id)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown quote request")
    if row["kind"] not in ("quote_voice", "quote_photo"):
        raise HTTPException(404, "unknown quote request")
    return row


def _fmt_money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def _display(name: str, variety: str | None = None) -> str:
    return display_name_en(name, variety)


def _quote_lines_context(raw_lines: list[dict],
                         photos: dict[str, str] | None = None
                         ) -> tuple[list[dict], int, int]:
    lines = []
    priced = 0
    photos = photos or {}
    for index, raw in enumerate(raw_lines):
        status = raw.get("status", "")
        if status == "priced":
            priced += 1
        variety = raw.get("variety") or None
        lines.append({
            "index": index,
            "name_en": raw.get("name_en", ""),
            "variety": variety or "",
            "display": _display(raw.get("name_en", ""), variety),
            "name_local": display_name_local(raw.get("name_local", ""),
                                             variety),
            "photo_url": photos.get(
                str(raw.get("name_en", "")).strip().lower()),
            "qty": _fmt_money(raw.get("qty", "")),
            "unit": raw.get("unit") or "",
            "unit_price": _fmt_money(raw.get("unit_price")),
            "per_amount": _fmt_money(raw.get("per_amount")),
            "per_unit": raw.get("unit") or "",
            "line_total": _fmt_money(raw.get("line_total")),
            "status": status,
            "note": raw.get("note") or "",
        })
    return lines, priced, len(lines) - priced


def _whatsapp_link(shop, raw_lines: list[dict], total: str,
                   quote_url: str, lang: str = "en") -> str:
    digits = re.sub(r"\D", "", shop["phone"] or "")
    text = quote_whatsapp_text(shop, raw_lines, total, quote_url, lang)
    return f"https://wa.me/{digits}?text={url_quote(text)}"


def process_quote_voice_session(conn, session_id: int, audio: Path, *,
                                settings, ledger) -> str | None:
    """Transcribe a spoken list, match it, store the quote. Never raises."""
    try:
        db.set_session_status(conn, session_id, "processing",
                              "Listening to your list...")
        db.set_stage(conn, session_id, "listening")
        shop_id = conn.execute(
            "SELECT shop_id FROM sessions WHERE id = ?",
            (session_id,)).fetchone()["shop_id"]
        session_dir = Path(settings.data_dir) / "sessions" / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        wav = extract_audio(Path(audio), session_dir / "audio.wav")
        shop_lang = _shop_language(conn, shop_id)
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
        meta = read_quote_meta(Path(settings.data_dir), session_id)
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                customer_name=meta.get("customer_name"),
                                customer_phone=meta.get("customer_phone"))
        meta["token"] = token
        write_quote_meta(Path(settings.data_dir), session_id, meta)
        db.set_stage(conn, session_id, "ready")
        db.set_session_status(conn, session_id, "review",
                              f"{len(quote.lines)} lines quoted")
        return token
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
        return None
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="recording"))
        return None


def process_quote_photo_session(conn, session_id: int, image: Path, *,
                                settings, ledger) -> str | None:
    """Read a photo list (or items), match it, store the quote. Never raises."""
    try:
        db.set_session_status(conn, session_id, "processing",
                              "Looking at your photo...")
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
        meta = read_quote_meta(Path(settings.data_dir), session_id)
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                customer_name=meta.get("customer_name"),
                                customer_phone=meta.get("customer_phone"))
        meta["token"] = token
        write_quote_meta(Path(settings.data_dir), session_id, meta)
        db.set_stage(conn, session_id, "ready")
        db.set_session_status(conn, session_id, "review",
                              f"{len(quote.lines)} lines quoted")
        return token
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
        return None
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="photo"))
        return None


def run_quote_voice_job(settings, session_id: int, audio: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_quote_voice_session(conn, session_id, Path(audio),
                                    settings=settings, ledger=ledger)
    finally:
        conn.close()


def run_quote_photo_job(settings, session_id: int, image: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_quote_photo_session(conn, session_id, Path(image),
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

    def _quote_context(request, shop, row, conn, error=None, lang="en"):
        try:
            raw_lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        if not isinstance(raw_lines, list):
            raw_lines = []
        language = _customer_lang(shop, lang)
        strings = get_strings(language)
        from app.web.bills import item_photo_urls

        lines, priced_count, unpriced_count = _quote_lines_context(
            raw_lines, item_photo_urls(conn, shop["id"]))
        rel = ""
        prices_time = ""
        published_id = db.latest_version(conn, shop["id"], published_only=True)
        if published_id is not None:
            when = db.version_time(conn, published_id)
            rel = format_relative(when, datetime.now(UTC))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            prices_time = when.astimezone(IST).strftime("%H:%M")
        quote_url = (f"{app.state.settings.public_base_url}/q/{row['token']}")
        # Paid orders finished the whole flow; show every step done with
        # Collected current. Older accepted rows stuck at "billed" read as
        # "new" (sent, waiting for packing).
        display_status = _effective_order_status(row["status"])
        steps = order_steps(row["status"], strings)
        open_info = _open_info(shop)
        sold_out_any = any(isinstance(entry, dict) and entry.get("sold_out")
                           for entry in raw_lines)
        from app.web.bills import row_not_understood

        return templates.TemplateResponse(request, "quote.html", {
            "shop": shop, "token": row["token"], "order_id": row["id"],
            "lines": lines,
            "total": _fmt_money(row["total"]),
            "total_fmt": format_money(row["total"], shop["currency"] or "INR"),
            "order_date": str(row["created_at"] or "")[:10],
            "status_url": (f"/q/{row['token']}/status.json"
                           f"{_lang_suffix(language)}"),
            "sold_out_any": sold_out_any,
            "priced_count": priced_count, "unpriced_count": unpriced_count,
            "not_understood": row_not_understood(row),
            "rel": rel, "prices_time": prices_time,
            "digits": re.sub(r"\D", "", shop["phone"] or ""),
            "error": error, "lang": language, "t": strings,
            "shop_lang": shop["language"] or "en",
            "ui_lang": language if language in ("ta", "hi", "en") else "en",
            "subtitle": strings["quote_subtitle"].format(
                shop=shop["name"], rel=rel),
            "whatsapp_url": _whatsapp_link(shop, raw_lines, row["total"],
                                           quote_url, language),
            "order_status": display_status,
            "order_steps": steps,
            "open_state": open_info["state"],
            "open_time": open_info["time"]})

    def _lang_suffix(language: str) -> str:
        return f"?lang={language}" if language != "en" else ""

    def _open_info(shop):
        from app.market.hours import shop_open_status

        return shop_open_status(shop)

    def _start_context(request, shop, error=None, lang="en", status=200):
        language = _customer_lang(shop, lang)
        open_info = _open_info(shop)
        return templates.TemplateResponse(
            request, "quote_start.html",
            {"shop": shop, "error": error, "lang": language,
             "t": get_strings(language),
             "open_state": open_info["state"],
             "open_time": open_info["time"],
             "ui_lang": language if language in ("ta", "hi", "en") else "en"},
            status_code=status)

    @app.get("/s/{slug}/quote")
    def quote_start(request: Request, slug: str, conn: Conn, lang: str = "en"):
        shop = _shop_or_404(conn, slug)
        return _start_context(request, shop, lang=lang)

    @app.post("/s/{slug}/quote")
    async def quote_submit(request: Request, slug: str):
        # Own connection: background jobs and sync deps may live elsewhere.
        conn = db.connect(data_dir)
        try:
            return await _quote_submit_impl(request, slug, conn)
        finally:
            conn.close()

    async def _quote_submit_impl(request: Request, slug: str, conn):
        shop = _shop_or_404(conn, slug)
        language = _customer_lang(shop, request.query_params.get("lang"))
        if "application/json" in request.headers.get("content-type", ""):
            return await _quote_submit_cart(request, shop, conn, language)
        form = await request.form()
        items = form.get("items")
        audio = form.get("audio")
        photo = form.get("photo")
        has_audio = audio is not None and hasattr(audio, "file")
        has_photo = photo is not None and hasattr(photo, "file")
        strings = get_strings(language)
        name = clean_customer_name(form.get("customer_name"))
        phone = clean_customer_phone(form.get("customer_phone"))
        if not customer_name_ok(name):
            return _start_context(request, shop,
                                  strings("order.name_required"),
                                  lang=language, status=400)
        if not customer_phone_ok(phone):
            return _start_context(request, shop,
                                  strings("order.phone_invalid"),
                                  lang=language, status=400)
        contact = {"customer_name": name,
                   "customer_phone": phone or None}
        if has_audio:
            return _start_voice_quote(request, shop, audio, conn,
                                      lang=language, contact=contact)
        if has_photo:
            return _start_photo_quote(request, shop, photo, conn,
                                      lang=language, contact=contact)
        text = str(items or "").strip()
        if not text:
            return _start_context(request, shop, "Tell us what you need first.",
                                  lang=language, status=400)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        price_items = (db.version_items(conn, version_id)
                       if version_id is not None else [])
        try:
            wanted, not_understood = wanted_local_first(
                text, price_items, shop["language"] or "ta",
                ledger=ledger, settings=app.state.settings,
                aliases=db.shop_name_aliases(conn, shop["id"]))
        except (SparkError, CostCapExceeded) as exc:
            message = (BUDGET_EXHAUSTED_MESSAGE
                       if isinstance(exc, CostCapExceeded) else str(exc))
            return _start_context(
                request, shop, message, lang=language,
                status=503 if isinstance(exc, CostCapExceeded) else 502)
        except Exception:  # noqa: BLE001 - typed parse failure is a form error
            return _start_context(request, shop,
                                  "We could not understand that list.",
                                  lang=language, status=400)
        if not wanted:
            return _start_context(request, shop,
                                  "We could not understand that list.",
                                  lang=language, status=400)
        quote = build_quote(conn, shop["id"], wanted)
        token = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                not_understood=not_understood,
                                customer_name=name,
                                customer_phone=phone or None)
        return RedirectResponse(f"/q/{token}{_lang_suffix(language)}",
                                status_code=303)

    async def _quote_submit_cart(request: Request, shop, conn, language: str):
        """Cart submit from the shop page: lines only, priced from published.

        The client preview (totals, per-line prices) is ignored entirely;
        build_quote recomputes every price from the published version.
        Every line is validated: finite qty with 0 < qty <= 100, name at
        most 80 characters, unit at most 20, at most 50 lines.
        """
        if not request.app.state.limiter.allow(client_ip(request),
                                               datetime.now(UTC)):
            return JSONResponse({"error": RATE_LIMIT_MESSAGE},
                                status_code=429)
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        raw_lines = payload.get("lines") if isinstance(payload, dict) else None
        if not raw_lines:
            return JSONResponse({"error": "empty cart"}, status_code=400)
        if not isinstance(raw_lines, list):
            return JSONResponse({"error": "cart lines must be a list"},
                                status_code=400)
        if len(raw_lines) > 50:
            return JSONResponse({"error": "too many lines (at most 50)"},
                                status_code=400)
        wanted: list[WantedLine] = []
        for index, entry in enumerate(raw_lines):
            label = f"line {index + 1}"
            if not isinstance(entry, dict):
                return JSONResponse({"error": f"{label} is not valid"},
                                    status_code=400)
            name = str(entry.get("name_en") or "").strip()
            if not name:
                return JSONResponse(
                    {"error": f"{label} has no item name"}, status_code=400)
            if len(name) > 80:
                return JSONResponse(
                    {"error": f"item name on {label} is too long"},
                    status_code=400)
            try:
                qty = Decimal(str(entry.get("qty", "1")))
            except (InvalidOperation, ValueError, TypeError):
                return JSONResponse(
                    {"error": f"quantity on {label} does not look right"},
                    status_code=400)
            if not qty.is_finite() or qty <= 0 or qty > 100:
                return JSONResponse(
                    {"error": (f"quantity on {label} must be more than 0"
                               " and at most 100")},
                    status_code=400)
            unit = entry.get("unit") or None
            if unit is not None:
                unit = str(unit).strip() or None
                if unit is not None and len(unit) > 20:
                    return JSONResponse(
                        {"error": f"unit on {label} is too long"},
                        status_code=400)
            variety = entry.get("variety") or None
            if variety is not None:
                variety = str(variety).strip() or None
                if variety is not None and len(variety) > 40:
                    return JSONResponse(
                        {"error": f"variety on {label} is too long"},
                        status_code=400)
            wanted.append(WantedLine(name_en=name, qty=qty, unit=unit,
                                     source="cart", variety=variety))
        if not wanted:
            return JSONResponse({"error": "empty cart"}, status_code=400)
        strings = get_strings(language)
        name = clean_customer_name(
            payload.get("customer_name") if isinstance(payload, dict)
            else None)
        phone = clean_customer_phone(
            payload.get("customer_phone") if isinstance(payload, dict)
            else None)
        if not customer_name_ok(name):
            return JSONResponse({"error": strings("order.name_required")},
                                status_code=400)
        if not customer_phone_ok(phone):
            return JSONResponse({"error": strings("order.phone_invalid")},
                                status_code=400)
        quote = build_quote(conn, shop["id"], wanted)
        token = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                source="customer", customer_name=name,
                                customer_phone=phone or None)
        url = f"/q/{token}{_lang_suffix(language)}"
        return JSONResponse({"token": token, "url": url})

    def _guarded(request, shop, conn):
        if not request.app.state.limiter.allow(client_ip(request),
                                               datetime.now(UTC)):
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Too many uploads", "message": RATE_LIMIT_MESSAGE,
                 "ui_lang": "en"},
                status_code=429)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            ledger.check()
        except CostCapExceeded:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Demo budget used up",
                 "message": BUDGET_EXHAUSTED_MESSAGE, "ui_lang": "en"},
                status_code=503)
        return None

    def _start_voice_quote(request, shop, audio, conn, lang="en",
                           contact=None):
        denied = _guarded(request, shop, conn)
        if denied is not None:
            return denied
        payload = audio.file.read() if hasattr(audio.file, "read") else b""
        if not payload:
            return _start_context(request, shop, "That recording was empty.",
                                  lang=lang, status=400)
        session_id = db.create_session(conn, shop["id"], "quote_voice")
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(getattr(audio, "filename", "") or "list.webm").name
        saved = uploads / f"q{session_id}_{secrets.token_hex(4)}_{safe_name}"
        saved.write_bytes(payload)
        write_quote_meta(data_dir, session_id, {"token": None,
                                                **(contact or {})})
        jobs.submit(run_quote_voice_job, settings, session_id, str(saved))
        return RedirectResponse(
            f"/s/{shop['slug']}/quote/{session_id}{_lang_suffix(lang)}",
            status_code=303)

    def _start_photo_quote(request, shop, photo: UploadFile, conn, lang="en",
                           contact=None):
        denied = _guarded(request, shop, conn)
        if denied is not None:
            return denied
        payload = photo.file.read()
        if not payload:
            return _start_context(request, shop, "Choose a photo first.",
                                  lang=lang, status=400)
        if len(payload) > MAX_QUOTE_PHOTO_BYTES:
            size_mb = len(payload) / (1024 * 1024)
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Photo too big",
                 "message": (f"That photo is {size_mb:.0f} MB, which is too big"
                             " to upload. Please choose a photo under 10 MB."),
                 "ui_lang": "en"},
                status_code=400)
        try:
            with Image.open(io.BytesIO(payload)) as img:
                img.load()
                photo_format = (img.format or "").lower()
        except Exception:  # noqa: BLE001 - any unreadable file is a 400
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Not a photo",
                 "message": "We could not open that file as a photo.",
                 "ui_lang": "en"},
                status_code=400)
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png",
               "webp": ".webp"}.get(photo_format, ".jpg")
        session_id = db.create_session(conn, shop["id"], "quote_photo")
        photo_dir = data_dir / "photos"
        photo_dir.mkdir(parents=True, exist_ok=True)
        saved = photo_dir / f"q{session_id}_{secrets.token_hex(4)}{ext}"
        saved.write_bytes(payload)
        write_quote_meta(data_dir, session_id, {"token": None,
                                                **(contact or {})})
        jobs.submit(run_quote_photo_job, settings, session_id, str(saved))
        return RedirectResponse(
            f"/s/{shop['slug']}/quote/{session_id}{_lang_suffix(lang)}",
            status_code=303)

    @app.get("/s/{slug}/quote/{session_id}")
    def quote_session_page(request: Request, slug: str, session_id: int,
                           conn: Conn, lang: str = "en"):
        shop = _shop_or_404(conn, slug)
        language = _customer_lang(shop, lang)
        session = _session_of_shop(conn, shop["id"], session_id)
        meta = read_quote_meta(data_dir, session_id)
        if meta.get("token") and session["status"] in ("review", "approved"):
            return RedirectResponse(
                f"/q/{meta['token']}{_lang_suffix(language)}",
                status_code=303)
        progress = db.session_progress(session)
        return templates.TemplateResponse(request, "quote_status.html", {
            "shop": shop, "session": session, "progress": progress,
            "friendly": db.stage_friendly(session["kind"],
                                          progress["stage"]),
            "ui_lang": language if language in ("ta", "hi", "en") else "en"})

    @app.get("/s/{slug}/quote/{session_id}/status")
    def quote_session_status(slug: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, slug)
        session = _session_of_shop(conn, shop["id"], session_id)
        progress = db.session_progress(session)
        meta = read_quote_meta(data_dir, session_id)
        return JSONResponse({
            "status": session["status"], "message": session["message"],
            "stage": progress["stage"], "step": progress["step"],
            "steps": progress["steps"], "detail": progress["detail"],
            "elapsed_s": progress["elapsed_s"],
            "friendly": db.stage_friendly(session["kind"], progress["stage"]),
            "quote_token": meta.get("token"),
        })

    @app.get("/q/{token}")
    def quote_page(request: Request, token: str, conn: Conn, lang: str = "en"):
        row = db.get_quote_by_token(conn, token)
        if row is None:
            raise HTTPException(404, "unknown quote")
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (row["shop_id"],)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown quote")
        return _quote_context(request, shop, row, conn, lang=lang)

    @app.get("/q/{token}/status.json")
    def quote_status_json(token: str, conn: Conn, lang: str = "en"):
        """Live order status for the customer's order page poll."""
        row = db.get_quote_by_token(conn, token)
        if row is None:
            raise HTTPException(404, "unknown quote")
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (row["shop_id"],)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown quote")
        language = _customer_lang(shop, lang)
        strings = get_strings(language)
        try:
            raw_lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        if not isinstance(raw_lines, list):
            raw_lines = []
        sold_out_any = any(isinstance(entry, dict) and entry.get("sold_out")
                           for entry in raw_lines)
        return JSONResponse({
            "status": _effective_order_status(row["status"]),
            "total": _fmt_money(row["total"]),
            "total_fmt": format_money(row["total"],
                                      shop["currency"] or "INR"),
            "steps": order_steps(row["status"], strings),
            "sold_out": sold_out_any,
        })

    @app.post("/q/{token}/lines")
    async def quote_lines_post(request: Request, token: str):
        conn = db.connect(data_dir)
        try:
            return await _quote_lines_impl(request, token, conn)
        finally:
            conn.close()

    async def _quote_lines_impl(request: Request, token: str, conn):
        row = db.get_quote_by_token(conn, token)
        if row is None:
            raise HTTPException(404, "unknown quote")
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (row["shop_id"],)).fetchone()
        try:
            raw_lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        form = await request.form()
        updates = []
        for index, original in enumerate(raw_lines):
            updates.append({
                "name_en": form.get(f"name_en_{index}",
                                    original.get("name_en", "")),
                "qty": form.get(f"qty_{index}", original.get("qty", "1")),
                "unit": form.get(f"unit_{index}", original.get("unit")),
                "variety": form.get(f"variety_{index}",
                                    original.get("variety")),
            })
        language = _customer_lang(shop, request.query_params.get("lang"))
        try:
            db.update_quote_lines(conn, token, updates)
        except (ValueError, TypeError) as exc:
            fresh = db.get_quote_by_token(conn, token)
            return _quote_context(request, shop, fresh, conn, error=str(exc),
                                  lang=language)
        return RedirectResponse(f"/q/{token}{_lang_suffix(language)}",
                                status_code=303)

    @app.get("/q/{token}/pdf")
    def quote_pdf_route(token: str, conn: Conn):
        row = db.get_quote_by_token(conn, token)
        if row is None:
            raise HTTPException(404, "unknown quote")
        shop = conn.execute("SELECT * FROM shops WHERE id = ?",
                            (row["shop_id"],)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown quote")
        try:
            raw_lines = json.loads(row["lines_json"] or "[]")
        except ValueError:
            raw_lines = []
        rel = ""
        published_id = db.latest_version(conn, shop["id"], published_only=True)
        if published_id is not None:
            rel = format_relative(db.version_time(conn, published_id),
                                  datetime.now(UTC))
        prices_note = f"Prices from {shop['name']}'s list, set {rel}" if rel else (
            f"Prices from {shop['name']}'s list")
        pdf = quote_pdf(shop, raw_lines if isinstance(raw_lines, list) else [],
                        row["total"], prices_note,
                        f"{app.state.settings.public_base_url}/q/{token}")
        return Response(pdf, media_type="application/pdf")
