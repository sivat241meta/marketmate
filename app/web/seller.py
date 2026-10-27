import json
import re
import sqlite3
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
from app.costs import IST, CostLedger
from app.outputs.csv_export import generic_csv, posapp_pos_csv
from app.outputs.pdf import price_board_pdf
from app.outputs.value import stock_value
from app.pipeline.checks import check_item
from app.pipeline.run import process_video_session, reprocess

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
        if versions:
            total, left_out = stock_value(
                db.version_items(conn, versions[0]["id"]))
            stock = {"total": total, "left_out": left_out,
                     "version_id": versions[0]["id"]}
        return templates.TemplateResponse(
            request,
            "seller.html",
            {"shop": shop, "sessions": sessions, "versions": versions,
             "notice": NOTICE, "stock": stock, "token": token},
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

    @app.post("/e/{token}/upload")
    def upload(request: Request, token: str, video: UploadFile, conn: Conn):
        shop = _shop_or_404(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(video.filename or "clip.mp4").name
        saved = uploads / f"{session_id}_{safe_name}"
        saved.write_bytes(video.file.read())
        jobs.submit(_run_session_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    @app.get("/e/{token}/s/{session_id}")
    def session_page(request: Request, token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        context = {"shop": shop, "session": session, "token": token}
        if session["status"] == "review":
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
                    }
                )
            context["cards"] = cards
            return templates.TemplateResponse(request, "review.html", context)
        return templates.TemplateResponse(request, "session.html", context)

    @app.get("/e/{token}/s/{session_id}/status")
    def session_status(token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        return JSONResponse({"status": session["status"], "message": session["message"]})

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
        items = []
        for index, raw in enumerate(raw_items):
            merged = dict(defaults, **raw)
            merged["proof"] = dict(defaults["proof"], **(raw.get("proof") or {}))
            item = db._draft_from_json(json.dumps(merged))
            item.flags = check_item(item, previous)
            item.confirmed = index in confirmed
            items.append(item)
        try:
            db.approve(conn, session_id, items)
        except db.ApprovalError as exc:
            raise HTTPException(400, str(exc))
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/s/{session_id}/retry")
    def retry_session(token: str, session_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
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
            "shop": shop, "rows": rows, "rel": rel, "digits": digits})

    @app.get("/m/{path:path}")
    def public_photo(path: str):
        base = (data_dir / "photos").resolve()
        target = (base / path).resolve()
        if base not in target.parents and target != base or not target.is_file():
            raise HTTPException(404, "no such photo")
        suffix = target.suffix.lower()
        media_type = "image/png" if suffix == ".png" else "image/jpeg"
        return FileResponse(target, media_type=media_type)
