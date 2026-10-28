import html as html_lib
import json
import re
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

from app import db, jobs
from app.costs import (
    BUDGET_EXHAUSTED_MESSAGE,
    IST,
    CostCapExceeded,
    CostLedger,
)
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.meta.spark import SparkError
from app.meta.transcribe import TranscribeError, transcribe_wav
from app.outputs.csv_export import generic_csv, posapp_pos_csv
from app.outputs.pdf import price_board_pdf
from app.outputs.qr import qr_png
from app.outputs.value import stock_value
from app.pipeline.checks import check_item
from app.pipeline.media import extract_audio
from app.pipeline.names import CANONICAL_NAMES, PRODUCE_KEYWORDS
from app.pipeline.numbers import parse_number
from app.pipeline.run import (
    friendly_error_message,
    process_video_session,
    reprocess,
)
from app.pipeline.update import (
    apply_changes,
    change_from_dict,
    change_to_dict,
    flags_for_change,
    parse_update,
)
from app.web.photos import (
    process_photo_session,
    read_photo_meta,
)

NOTICE = "Your voice recording is sent to Meta's AI service to be transcribed."

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")
_LANGUAGES = {"ta", "en"}
_CURRENCIES = {"INR"}


def _clean_phone(phone: str) -> str:
    return re.sub(r"[\s\-()]", "", phone or "")


def _shop_or_404(conn, token: str):
    shop = db.shop_by_token(conn, token)
    if shop is None:
        raise HTTPException(404, "unknown shop token")
    return shop


def _session_of_shop(conn, shop_id: int, session_id: int):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND shop_id = ?", (session_id, shop_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown session")
    return row


def _run_session_job(settings, session_id: int, video: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db", settings.daily_budget_usd)
        process_video_session(conn, session_id, Path(video), settings=settings, ledger=ledger)
    finally:
        conn.close()


def _photo_url(photo: str | None) -> str | None:
    if not photo:
        return None
    return "/m/" + Path(photo).name


def _draft_from_client(raw: dict):
    """Parse one review-form item, filling fields the form never edits."""
    defaults = {
        "name_spoken": "",
        "name_ta": "",
        "variety": None,
        "qty": None,
        "qty_unit": None,
        "range_said": False,
        "flags": [],
        "photo": None,
        "condition_hint": None,
        "confirmed": False,
        "proof": {
            "quote": "",
            "turn_ids": [],
            "start_ms": 0,
            "end_ms": 0,
            "frame": None,
            "audio_clip": None,
        },
    }
    merged = dict(defaults, **raw)
    merged["proof"] = dict(defaults["proof"], **(raw.get("proof") or {}))
    return db._draft_from_json(json.dumps(merged))


def _update_path(data_dir: Path, session_id: int) -> Path:
    return data_dir / "sessions" / str(session_id) / "update.json"


_ACTION_LABELS = {
    "set_price": "New price",
    "sold_out": "Sold out",
    "in_stock": "Back in stock",
    "set_qty": "New quantity",
}


def _relative_time(when, now) -> str:
    seconds = max(0, int((now - when).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours ago"
    return f"{hours // 24} days ago"


def _highlight_quote(quote: str) -> str:
    """Escape the proof quote and wrap heard numbers in <mark>."""
    parts = re.split(r"(\s+)", quote or "")
    out = []
    for part in parts:
        if not part or part.isspace():
            out.append(html_lib.escape(part))
            continue
        stripped = part.strip(".,;:!?\"'()[]{}₹")
        if stripped and parse_number(stripped) is not None:
            out.append(f"<mark>{html_lib.escape(part)}</mark>")
        else:
            out.append(html_lib.escape(part))
    return "".join(out)


def _needs_decision(item) -> bool:
    return any(flag.options or flag.blocking for flag in item.flags)


def _price_summary(item) -> str:
    for line in item.price_lines:
        if line.price is not None:
            if line.per_amount is not None and line.unit:
                return f"₹{line.price} / {line.per_amount} {line.unit}"
            if line.unit:
                return f"₹{line.price} / {line.unit}"
            return f"₹{line.price}"
    return "no price yet"


def _mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.0f}"


def _too_big_message(size_bytes: int, limit_bytes: int) -> str:
    return (f"That file is {_mb(size_bytes)} MB, which is too big to upload. "
            f"Please choose a file under {_mb(limit_bytes)} MB.")


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    @app.get("/new")
    def new_shop(request: Request):
        return templates.TemplateResponse(request, "new_shop.html", {})

    @app.post("/new")
    def create_shop_post(
        request: Request,
        conn: Conn,
        name: str = Form(...),
        phone: str = Form(...),
        area: str = Form(...),
        language: str = Form(...),
        currency: str = Form(...),
        type: str = Form(...),
    ):
        if not name.strip() or not area.strip() or not type.strip():
            raise HTTPException(422, "name, area and type are required")
        if not _PHONE_RE.match(_clean_phone(phone)):
            raise HTTPException(422, "phone must be 7-15 digits, optional leading +")
        if language not in _LANGUAGES:
            raise HTTPException(422, "language must be ta or en")
        if currency not in _CURRENCIES:
            raise HTTPException(422, "currency must be INR")
        _, _, token = db.create_shop(
            conn,
            name=name.strip(),
            phone=_clean_phone(phone),
            area=area.strip(),
            language=language,
            currency=currency,
            shop_type=type.strip(),
        )
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.get("/e/{token}")
    def seller_home(request: Request, token: str, conn: Conn):
        shop = _shop_or_404(conn, token)
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE shop_id = ? ORDER BY id DESC", (shop["id"],)
        ).fetchall()
        versions = conn.execute(
            "SELECT * FROM versions WHERE shop_id = ? ORDER BY id DESC", (shop["id"],)
        ).fetchall()
        stock = None
        items = []
        if versions:
            latest_items = db.version_items(conn, versions[0]["id"])
            total, left_out = stock_value(latest_items)
            stock = {"total": total, "left_out": left_out,
                     "version_id": versions[0]["id"]}
            for item in latest_items:
                stock_line = None
                if item.stock_qty is not None and item.stock_source:
                    stock_line = (f"Stock: about {item.stock_qty}"
                                  f" ({item.stock_source})")
                items.append({
                    "id": item.id,
                    "name_ta": item.name_ta,
                    "name_en": item.name_en,
                    "variety": item.variety,
                    "photo_url": _photo_url(item.photo),
                    "sold_out": item.sold_out,
                    "stock_line": stock_line,
                    "lines": [{"price": str(line.price),
                               "per": f"{line.per_amount} {line.unit}"}
                              for line in item.price_lines],
                })
        live = False
        live_count = 0
        published_id = db.latest_version(conn, shop["id"], published_only=True)
        if published_id is not None:
            live = True
            live_count = sum(
                len(item.price_lines)
                for item in db.version_items(conn, published_id))
        from app.web.bills import bills_tiles

        bills = bills_tiles(conn, shop["id"])
        return templates.TemplateResponse(
            request,
            "seller.html",
            {"shop": shop, "sessions": sessions, "versions": versions,
             "notice": NOTICE, "stock": stock, "token": token,
             "items": items, "live": live, "live_count": live_count,
             "shop_url": f"/s/{shop['slug']}",
             "max_upload_bytes": app.state.settings.max_upload_bytes,
             "bills": bills},
        )

    def _version_of_shop(conn, shop_id: int, version_id: int):
        row = conn.execute(
            "SELECT * FROM versions WHERE id = ? AND shop_id = ?",
            (version_id, shop_id)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown version")
        return row

    def _version_items(conn, token: str, version_id: int):
        shop = _shop_or_404(conn, token)
        _version_of_shop(conn, shop["id"], version_id)
        return shop, db.version_items(conn, version_id)

    @app.get("/e/{token}/v/{version_id}/board.pdf")
    def version_board(token: str, version_id: int, conn: Conn):
        shop, items = _version_items(conn, token, version_id)
        pdf = price_board_pdf(
            shop, items, datetime.now(IST),
            f"{app.state.settings.public_base_url}/s/{shop['slug']}")
        return Response(pdf, media_type="application/pdf")

    @app.get("/e/{token}/v/{version_id}/export.csv")
    def version_csv(token: str, version_id: int, conn: Conn):
        _, items = _version_items(conn, token, version_id)
        return Response(generic_csv(items, datetime.now(IST)),
                        media_type="text/csv")

    @app.get("/e/{token}/v/{version_id}/posapp.csv")
    def version_posapp(token: str, version_id: int, conn: Conn):
        _, items = _version_items(conn, token, version_id)
        return Response(posapp_pos_csv(items), media_type="text/csv")

    @app.get("/try")
    def try_judge(conn: Conn):
        _, _, token = db.create_shop(
            conn, name="Judge Test Shop", phone="+910000000000",
            area="Judge trial", language="en", currency="INR",
            shop_type="vegetable", is_judge=True, listed=False)
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/upload")
    def upload(request: Request, token: str, video: UploadFile, conn: Conn):
        shop = _shop_or_404(conn, token)
        db.purge_expired(conn, data_dir, datetime.now(UTC))
        limiter = request.app.state.limiter
        ip = client_ip(request)
        if not limiter.allow(ip, datetime.now(UTC)):
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
        payload = video.file.read()
        limit = app.state.settings.max_upload_bytes
        if len(payload) > limit:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "File too big",
                 "message": _too_big_message(len(payload), limit)},
                status_code=413)
        session_id = db.create_session(conn, shop["id"], "video")
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(video.filename or "clip.mp4").name
        saved = uploads / f"{session_id}_{safe_name}"
        saved.write_bytes(payload)
        jobs.submit(_run_session_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    @app.get("/e/{token}/s/{session_id}")
    def session_page(request: Request, token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        if session["kind"] == "photo" and session["status"] == "review":
            meta = read_photo_meta(data_dir, session_id)
            if meta.get("check_id") is not None:
                return RedirectResponse(
                    f"/e/{token}/photos/{meta['check_id']}", status_code=303)
        progress = db.session_progress(session)
        context = {"shop": shop, "session": session, "token": token,
                   "progress": progress,
                   "friendly": db.stage_friendly(session["kind"],
                                                progress["stage"])}
        if session["status"] == "review" and session["kind"] == "video":
            items = db.load_drafts(conn, session_id)
            cards = []
            for index, item in enumerate(items):
                proof = {
                    "quote": item.proof.quote,
                    "turn_ids": item.proof.turn_ids,
                    "start_ms": item.proof.start_ms,
                    "end_ms": item.proof.end_ms,
                    "frame": item.proof.frame,
                    "audio_clip": item.proof.audio_clip,
                }
                cards.append(
                    {
                        "index": index,
                        "item": item,
                        "photo_url": _photo_url(item.photo),
                        "clip_url": (
                            f"/e/{token}/s/{session_id}/clip/{index}"
                            if item.proof.audio_clip
                            else None
                        ),
                        "proof_json": json.dumps(proof),
                        "needs_decision": _needs_decision(item),
                        "quote_html": _highlight_quote(item.proof.quote),
                        "price_summary": _price_summary(item),
                    }
                )
            cards.sort(key=lambda c: (not c["needs_decision"], c["index"]))
            need_count = sum(1 for c in cards if c["needs_decision"])
            context["cards"] = cards
            context["total"] = len(cards)
            context["need_count"] = need_count
            context["ok_count"] = len(cards) - need_count
            return templates.TemplateResponse(request, "review.html", context)
        return templates.TemplateResponse(request, "session.html", context)

    @app.get("/e/{token}/s/{session_id}/status")
    def session_status(token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        progress = db.session_progress(session)
        return JSONResponse({
            "status": session["status"], "message": session["message"],
            "stage": progress["stage"], "step": progress["step"],
            "steps": progress["steps"], "detail": progress["detail"],
            "elapsed_s": progress["elapsed_s"],
            "friendly": db.stage_friendly(session["kind"], progress["stage"]),
        })

    @app.get("/e/{token}/s/{session_id}/clip/{index}")
    def session_clip(token: str, session_id: int, index: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
        items = db.load_drafts(conn, session_id)
        if not 0 <= index < len(items) or not items[index].proof.audio_clip:
            raise HTTPException(404, "no such clip")
        return FileResponse(items[index].proof.audio_clip, media_type="audio/mp4")

    @app.post("/e/{token}/s/{session_id}/approve")
    def approve(token: str, session_id: int, body: dict, conn: Conn):
        shop = _shop_or_404(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
        raw_items = body.get("items", [])
        confirmed = set(body.get("confirmed", []))
        previous = db.last_prices(conn, shop["id"])
        items = []
        for index, raw in enumerate(raw_items):
            item = _draft_from_client(raw)
            item.flags = check_item(item, previous)
            item.confirmed = index in confirmed
            items.append(item)
        try:
            db.approve(conn, session_id, items)
        except db.ApprovalError as exc:
            if exc.needs_confirm:
                return JSONResponse(
                    status_code=400,
                    content={"detail": str(exc),
                             "needs_confirm": exc.needs_confirm},
                )
            raise HTTPException(400, str(exc))
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/s/{session_id}/retry")
    def retry_session(token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        if session["kind"] == "photo":
            meta = read_photo_meta(data_dir, session_id)
            if not meta.get("image"):
                raise HTTPException(400, "this photo is gone; scan it again")
            process_photo_session(
                conn, session_id, Path(meta["image"]),
                settings=app.state.settings,
                ledger=CostLedger(data_dir / "costs.db",
                                  app.state.settings.daily_budget_usd))
            return RedirectResponse(f"/e/{token}/s/{session_id}",
                                    status_code=303)
        try:
            reprocess(
                conn,
                session_id,
                settings=app.state.settings,
                ledger=CostLedger(data_dir / "costs.db", app.state.settings.daily_budget_usd),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    def _update_cards(token: str, changes, current_map: dict) -> list[dict]:
        cards = []
        for index, change in enumerate(changes):
            current = current_map.get(change.name_en)
            if current is not None and current.price_lines:
                summary = ", ".join(
                    f"₹{line.price} per {line.per_amount} {line.unit}"
                    for line in current.price_lines)
            else:
                summary = ""
            cards.append({
                "index": index,
                "name_en": change.name_en,
                "name_ta": CANONICAL_NAMES.get(change.name_en, change.name_en),
                "action": change.action,
                "action_label": _ACTION_LABELS.get(change.action, change.action),
                "lines": change.price_lines,
                "qty": change.qty,
                "quote": change.proof.quote,
                "flags": change.flags,
                "photo_url": _photo_url(current.photo) if current else None,
                "current_summary": summary,
                "need_confirm": any(
                    flag.blocking and not flag.options for flag in change.flags),
                "proof_json": json.dumps({
                    "quote": change.proof.quote,
                    "turn_ids": change.proof.turn_ids,
                    "start_ms": change.proof.start_ms,
                    "end_ms": change.proof.end_ms,
                    "frame": change.proof.frame,
                    "audio_clip": change.proof.audio_clip,
                }),
            })
        return cards

    @app.get("/e/{token}/update")
    def update_page(request: Request, token: str, conn: Conn,
                    hint: str | None = None):
        shop = _shop_or_404(conn, token)
        version_id = db.latest_version(conn, shop["id"])
        items = db.version_items(conn, version_id) if version_id else []
        return templates.TemplateResponse(request, "update.html", {
            "shop": shop, "token": token, "mode": "record", "items": items,
            "notice": NOTICE, "error": None, "hint": (hint or "").strip(),
            "max_upload_bytes": app.state.settings.max_upload_bytes})

    @app.post("/e/{token}/update")
    async def update_post(request: Request, token: str):
        # Own connection: the sync request dependency may live on another thread.
        conn = db.connect(data_dir)
        try:
            return await _update_post_impl(request, token, conn)
        finally:
            conn.close()

    async def _update_post_impl(request: Request, token: str, conn):
        shop = _shop_or_404(conn, token)
        base_version_id = db.latest_version(conn, shop["id"])
        if base_version_id is None:
            raise HTTPException(400, "approve a price list first, then update it")
        form = await request.form()
        upload = form.get("audio") or form.get("file") or form.get("video")
        if upload is None or not hasattr(upload, "file"):
            raise HTTPException(422, "an audio recording is required")
        payload = await upload.read()
        limit = app.state.settings.max_upload_bytes
        if len(payload) > limit:
            items = db.version_items(conn, base_version_id)
            return templates.TemplateResponse(request, "update.html", {
                "shop": shop, "token": token, "mode": "record", "items": items,
                "notice": NOTICE, "error": _too_big_message(len(payload), limit),
                "max_upload_bytes": limit})
        session_id = db.create_session(conn, shop["id"], "voice_update")
        session_dir = data_dir / "sessions" / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(getattr(upload, "filename", "") or "update.webm").name
        saved = uploads / f"{session_id}_{safe_name}"
        saved.write_bytes(payload)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            db.set_session_status(conn, session_id, "processing",
                                  "Listening to the update...")
            db.set_stage(conn, session_id, "listening")
            wav = extract_audio(saved, session_dir / "audio.wav")
            transcript = transcribe_wav(
                wav, keywords=PRODUCE_KEYWORDS, ledger=ledger,
                settings=app.state.settings)
            db.set_stage(conn, session_id, "items")
            current = db.version_items(conn, base_version_id)
            changes = parse_update(transcript, current,
                                   ledger=ledger, settings=app.state.settings)
            db.set_stage(conn, session_id, "checking")
        except (TranscribeError, SparkError, CostCapExceeded,
                subprocess.CalledProcessError, OSError) as exc:
            message = friendly_error_message(exc, media="recording")
            db.set_session_status(conn, session_id, "failed", message)
            items = db.version_items(conn, base_version_id)
            return templates.TemplateResponse(request, "update.html", {
                "shop": shop, "token": token, "mode": "record", "items": items,
                "notice": NOTICE, "error": message,
                "max_upload_bytes": limit})
        finally:
            saved.unlink(missing_ok=True)
        _update_path(data_dir, session_id).write_text(json.dumps({
            "base_version_id": base_version_id,
            "changes": [change_to_dict(change) for change in changes]}))
        db.set_stage(conn, session_id, "ready")
        db.set_session_status(conn, session_id, "review",
                              f"{len(changes)} changes heard")
        current_map = {item.name_en: item for item in current}
        return templates.TemplateResponse(request, "update.html", {
            "shop": shop, "token": token, "mode": "confirm",
            "session_id": session_id,
            "cards": _update_cards(token, changes, current_map),
            "transcript": transcript.text})

    @app.post("/e/{token}/update/{session_id}/confirm")
    async def update_confirm(request: Request, token: str, session_id: int):
        # Own connection: the sync request dependency may live on another thread.
        conn = db.connect(data_dir)
        try:
            return await _update_confirm_impl(request, token, session_id, conn)
        finally:
            conn.close()

    async def _update_confirm_impl(request: Request, token: str, session_id: int,
                                   conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        if session["kind"] != "voice_update":
            raise HTTPException(400, "not a voice update session")
        if session["status"] == "approved":
            return RedirectResponse(f"/e/{token}", status_code=303)
        if session["status"] != "review":
            raise HTTPException(400, "this update is not ready to confirm")
        stored_path = _update_path(data_dir, session_id)
        if not stored_path.is_file():
            raise HTTPException(400, "no pending update; record again")
        stored = json.loads(stored_path.read_text())
        base_version_id = stored["base_version_id"]
        changes = [change_from_dict(raw) for raw in stored["changes"]]
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            raw_items = body.get("items", [])
            confirmed = set(body.get("confirmed", []))
            if len(raw_items) != len(changes):
                raise HTTPException(400, "confirm form is out of date; record again")
            current = db.version_items(conn, base_version_id)
            current_map = {item.name_en: item for item in current}
            previous = {item.name_en: item.price_lines[0] for item in current
                        if item.price_lines}
            for index, (change, raw) in enumerate(zip(changes, raw_items)):
                draft = _draft_from_client(raw)
                if change.action == "set_price":
                    change.price_lines = list(draft.price_lines)
                    change.qty = draft.qty
                    if draft.qty_unit is not None:
                        change.qty_unit = draft.qty_unit
                elif change.action == "set_qty" and draft.qty is not None:
                    change.qty = draft.qty
                    if draft.qty_unit is not None:
                        change.qty_unit = draft.qty_unit
                change.flags = flags_for_change(change, current_map, previous)
                if (any(flag.blocking for flag in change.flags)
                        and index not in confirmed):
                    raise HTTPException(
                        400, f"unconfirmed change on {change.name_en}")
        else:
            form = await request.form()
            confirmed: set[int] = set()
            for value in form.getlist("confirmed"):
                try:
                    confirmed.add(int(value))
                except (TypeError, ValueError):
                    continue
            current = db.version_items(conn, base_version_id)
            current_map = {item.name_en: item for item in current}
            previous = {item.name_en: item.price_lines[0] for item in current
                        if item.price_lines}
            for index, change in enumerate(changes):
                change.flags = flags_for_change(change, current_map, previous)
                if (any(flag.blocking for flag in change.flags)
                        and index not in confirmed):
                    raise HTTPException(
                        400, f"unconfirmed change on {change.name_en}")
        new_version_id = apply_changes(conn, shop["id"], base_version_id, changes)
        db.set_published(conn, new_version_id, True)
        db.set_session_status(conn, session_id, "approved",
                              f"{len(changes)} changes published")
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/v/{version_id}/publish")
    def publish_version(token: str, version_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        _version_of_shop(conn, shop["id"], version_id)
        db.set_published(conn, version_id, True)
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/v/{version_id}/unpublish")
    def unpublish_version(token: str, version_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        _version_of_shop(conn, shop["id"], version_id)
        db.set_published(conn, version_id, False)
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/item/{item_id}/soldout")
    def toggle_soldout(token: str, item_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        row = conn.execute(
            "SELECT items.sold_out, versions.shop_id FROM items"
            " JOIN versions ON versions.id = items.version_id"
            " WHERE items.id = ?", (item_id,)).fetchone()
        if row is None or row["shop_id"] != shop["id"]:
            raise HTTPException(404, "unknown item")
        db.set_sold_out(conn, item_id, not bool(row["sold_out"]))
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.get("/s/{slug}")
    def public_shop(request: Request, conn: Conn, slug: str, lang: str = "en"):
        shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                            (slug,)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown shop")
        language = lang if lang in ("ta", "en") else "en"
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        rows = []
        rel = ""
        if version_id is not None:
            for item in db.version_items(conn, version_id):
                name = item.name_ta if language == "ta" else item.name_en
                rows.append({
                    "name": f"{name} ({item.variety})" if item.variety else name,
                    "name_ta": item.name_ta,
                    "name_en": item.name_en,
                    "variety": item.variety,
                    "photo_url": _photo_url(item.photo),
                    "sold_out": item.sold_out,
                    "lines": [{"price": str(line.price),
                               "per": f"{line.per_amount} {line.unit}"}
                              for line in item.price_lines],
                })
            rel = _relative_time(db.version_time(conn, version_id),
                                 datetime.now(UTC))
        digits = re.sub(r"\D", "", shop["phone"] or "")
        return templates.TemplateResponse(request, "shop.html", {
            "shop": shop, "rows": rows, "rel": rel, "digits": digits,
            "lang": language})

    @app.get("/s/{slug}/qr.png")
    def shop_qr(slug: str, conn: Conn):
        shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                            (slug,)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown shop")
        png = qr_png(f"{app.state.settings.public_base_url}/s/{slug}")
        return Response(png, media_type="image/png")

    @app.get("/m/{path:path}")
    def public_photo(path: str):
        base = (data_dir / "photos").resolve()
        target = (base / path).resolve()
        if base not in target.parents and target != base or not target.is_file():
            raise HTTPException(404, "no such photo")
        suffix = target.suffix.lower()
        media_type = {".png": "image/png", ".webp": "image/webp"}.get(
            suffix, "image/jpeg")
        return FileResponse(target, media_type=media_type)
