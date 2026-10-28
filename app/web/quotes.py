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
    CostCapExceeded,
    CostLedger,
)
from app.languages import get_language, shop_bias
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.market.quote import build_quote, wanted_from_photo, wanted_from_text
from app.meta.spark import SparkError
from app.meta.transcribe import transcribe_wav
from app.outputs.quote_pdf import quote_pdf
from app.outputs.time import format_relative
from app.pipeline.media import extract_audio
from app.pipeline.names import keywords_for
from app.pipeline.run import friendly_error_message
from app.web.i18n import get_strings

MAX_QUOTE_PHOTO_BYTES = 10 * 1024 * 1024


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


def _display(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


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
            "per_unit": raw.get("unit") or "",
            "line_total": _fmt_money(raw.get("line_total")),
            "status": status,
            "note": raw.get("note") or "",
        })
    return lines, priced, len(lines) - priced


def _whatsapp_link(shop, raw_lines: list[dict], total: str,
                   quote_url: str) -> str:
    digits = re.sub(r"\D", "", shop["phone"] or "")
    parts = [f"Quote from {shop['name']}"]
    for raw in raw_lines:
        name = _display(raw.get("name_en", ""))
        status = raw.get("status", "")
        if status in ("priced", "needs_qty") and raw.get("line_total"):
            qty = _fmt_money(raw.get("qty", ""))
            unit = raw.get("unit") or ""
            parts.append(
                f"{name} {qty} {unit} - Rs.{_fmt_money(raw['line_total'])}".strip())
        elif status == "sold_out":
            parts.append(f"{name} - sold out")
        else:
            parts.append(f"{name} - not on list")
    parts.append(f"Total: Rs.{_fmt_money(total)}")
    parts.append(f"Quote: {quote_url}")
    return f"https://wa.me/{digits}?text={url_quote(chr(10).join(parts))}"


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
        token = db.create_quote(conn, shop_id=shop_id, quote=quote)
        write_quote_meta(Path(settings.data_dir), session_id, {"token": token})
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
        token = db.create_quote(conn, shop_id=shop_id, quote=quote)
        write_quote_meta(Path(settings.data_dir), session_id, {"token": token})
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
        published_id = db.latest_version(conn, shop["id"], published_only=True)
        if published_id is not None:
            rel = format_relative(db.version_time(conn, published_id),
                                  datetime.now(UTC))
        quote_url = (f"{app.state.settings.public_base_url}/q/{row['token']}")
        return templates.TemplateResponse(request, "quote.html", {
            "shop": shop, "token": row["token"], "lines": lines,
            "total": _fmt_money(row["total"]),
            "priced_count": priced_count, "unpriced_count": unpriced_count,
            "rel": rel, "error": error, "lang": language, "t": strings,
            "shop_lang": shop["language"] or "en",
            "subtitle": strings["quote_subtitle"].format(
                shop=shop["name"], rel=rel),
            "whatsapp_url": _whatsapp_link(shop, raw_lines, row["total"],
                                           quote_url)})

    def _lang_suffix(language: str) -> str:
        return f"?lang={language}" if language != "en" else ""

    def _start_context(request, shop, error=None, lang="en", status=200):
        language = _customer_lang(shop, lang)
        return templates.TemplateResponse(
            request, "quote_start.html",
            {"shop": shop, "error": error, "lang": language,
             "t": get_strings(language)},
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
        form = await request.form()
        items = form.get("items")
        audio = form.get("audio")
        photo = form.get("photo")
        has_audio = audio is not None and hasattr(audio, "file")
        has_photo = photo is not None and hasattr(photo, "file")
        if has_audio:
            return _start_voice_quote(request, shop, audio, conn, lang=language)
        if has_photo:
            return _start_photo_quote(request, shop, photo, conn, lang=language)
        text = str(items or "").strip()
        if not text:
            return _start_context(request, shop, "Tell us what you need first.",
                                  lang=language, status=400)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            wanted = wanted_from_text(text, ledger=ledger,
                                      settings=app.state.settings)
        except (SparkError, CostCapExceeded) as exc:
            message = (BUDGET_EXHAUSTED_MESSAGE
                       if isinstance(exc, CostCapExceeded) else str(exc))
            return _start_context(
                request, shop, message, lang=language,
                status=503 if isinstance(exc, CostCapExceeded) else 502)
        if not wanted:
            return _start_context(request, shop,
                                  "We could not understand that list.",
                                  lang=language, status=400)
        quote = build_quote(conn, shop["id"], wanted)
        token = db.create_quote(conn, shop_id=shop["id"], quote=quote)
        return RedirectResponse(f"/q/{token}{_lang_suffix(language)}",
                                status_code=303)

    def _guarded(request, shop, conn):
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

    def _start_voice_quote(request, shop, audio, conn, lang="en"):
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
        write_quote_meta(data_dir, session_id, {"token": None})
        jobs.submit(run_quote_voice_job, settings, session_id, str(saved))
        return RedirectResponse(
            f"/s/{shop['slug']}/quote/{session_id}{_lang_suffix(lang)}",
            status_code=303)

    def _start_photo_quote(request, shop, photo: UploadFile, conn, lang="en"):
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
        session_id = db.create_session(conn, shop["id"], "quote_photo")
        photo_dir = data_dir / "photos"
        photo_dir.mkdir(parents=True, exist_ok=True)
        saved = photo_dir / f"q{session_id}_{secrets.token_hex(4)}{ext}"
        saved.write_bytes(payload)
        write_quote_meta(data_dir, session_id, {"token": None})
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
                                          progress["stage"])})

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
