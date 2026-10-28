"""Seller photo screens: scan a stock photo, counts overlay, suggestions.

Photos never produce prices; counts are estimates the seller confirms.
"""

import io
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

from app import db, jobs
from app.costs import (
    BUDGET_EXHAUSTED_MESSAGE,
    CostCapExceeded,
    CostLedger,
)
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.market.search import SYNONYMS
from app.outputs.time import format_relative
from app.pipeline.names import CANONICAL_NAMES
from app.pipeline.run import friendly_error_message
from app.pipeline.vision import PhotoReport, analyse_photo

MAX_PHOTO_BYTES = 10 * 1024 * 1024
BOX_COLOURS = 6

_SUGGESTION_BUTTONS = {
    "set_stock": ("tag", "Save stock"),
    "unsold": ("check", "Put back on sale"),
    "voice_update": ("mic", "Say its price"),
}


def photo_meta_path(data_dir: Path, session_id: int) -> Path:
    return Path(data_dir) / "sessions" / str(session_id) / "photo.json"


def read_photo_meta(data_dir: Path, session_id: int) -> dict:
    try:
        return json.loads(photo_meta_path(data_dir, session_id).read_text())
    except (OSError, ValueError):
        return {}


def write_photo_meta(data_dir: Path, session_id: int, payload: dict) -> None:
    path = photo_meta_path(data_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _box_to_dict(box) -> dict:
    return {"x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2,
            "w": box.w, "h": box.h, "confidence": box.confidence}


def report_to_dict(report: PhotoReport, width: int | None,
                   height: int | None) -> dict:
    """Serialise a PhotoReport for the photo_checks table."""
    products = []
    for product in report.products:
        products.append({
            "name_en": product.name_en,
            "name_local": product.name_local,
            "countable": product.countable,
            "count": product.count,
            "count_range": (list(product.count_range)
                            if product.count_range else None),
            "needs_check": product.needs_check,
            "count_spark": product.count_spark,
            "count_sam": product.count_sam,
            "boxes": [_box_to_dict(box) for box in product.boxes],
            "condition": product.condition,
        })
    return {
        "quality": report.quality,
        "image_w": width,
        "image_h": height,
        "products": products,
        "suggestions": [{
            "kind": item.kind, "text": item.text, "item_name": item.item_name,
            "action": item.action, "value": item.value,
        } for item in report.suggestions],
    }


def _shop_or_404(conn, token: str):
    shop = db.shop_by_token(conn, token)
    if shop is None:
        raise HTTPException(404, "unknown shop token")
    return shop


def _check_of_shop(conn, shop_id: int, check_id: int):
    row = conn.execute(
        "SELECT * FROM photo_checks WHERE id = ? AND shop_id = ?",
        (check_id, shop_id)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown photo check")
    return row


def _photo_url(image_path: str | None) -> str | None:
    if not image_path:
        return None
    return "/m/" + Path(image_path).name


def _relative_time(value: str | None, now: datetime) -> str:
    try:
        when = datetime.fromisoformat(value or "")
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return format_relative(when, now)


def _canonical(name: str | None) -> str:
    key = (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def _find_version_item(items, name: str):
    want = _canonical(name)
    for item in items:
        if _canonical(item.name_en) == want:
            return item
    return None


def _find_product(products: list[dict], name: str) -> dict | None:
    want = _canonical(name)
    for product in products:
        if _canonical(product.get("name_en")) == want:
            return product
    return None


def _display(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


def _default_qty(suggestion: dict, products: list[dict]) -> int | None:
    value = suggestion.get("value")
    if isinstance(value, int) and value >= 0:
        return value
    product = _find_product(products, suggestion.get("item_name") or "")
    if product:
        count = product.get("count")
        if isinstance(count, int) and count >= 0:
            return count
        span = product.get("count_range") or []
        if (len(span) == 2 and all(isinstance(v, int) for v in span)):
            spark = product.get("count_spark")
            if isinstance(spark, int) and spark >= 0:
                return spark
            return round((span[0] + span[1]) / 2)
    return None


def _image_size(image: Path) -> tuple[int, int]:
    with Image.open(image) as img:
        img.load()
        return img.size


def process_photo_session(conn, session_id: int, image: Path, *,
                          settings, ledger) -> int | None:
    """Analyse one stock photo; records stages, never raises. Returns check id."""
    image = Path(image)
    try:
        db.set_session_status(conn, session_id, "processing",
                              "Looking at your photo...")
        db.set_stage(conn, session_id, "looking")
        shop_id = conn.execute(
            "SELECT shop_id FROM sessions WHERE id = ?",
            (session_id,)).fetchone()["shop_id"]
        version_id = db.latest_version(conn, shop_id)
        shop_items = []
        if version_id is not None:
            for item in db.version_items(conn, version_id):
                shop_items.append({"name_en": item.name_en,
                                   "sold_out": item.sold_out})
        db.set_stage(conn, session_id, "counting")
        report = analyse_photo(Path(image), shop_items=shop_items,
                               ledger=ledger, settings=settings)
        db.set_stage(conn, session_id, "suggesting")
        width, height = _image_size(Path(image))
        payload = report_to_dict(report, width, height)
        check_id = db.save_photo_check(
            conn, shop_id=shop_id, image_path=str(image),
            report_json=json.dumps(payload), cost=report.cost_usd)
        write_photo_meta(Path(settings.data_dir), session_id,
                         {"image": str(image), "check_id": check_id})
        db.set_stage(conn, session_id, "ready")
        found = len(report.products)
        noun = "product" if found == 1 else "products"
        db.set_session_status(conn, session_id, "review",
                              f"{found} {noun} found")
        return check_id
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
        return None
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="photo"))
        return None


def run_photo_job(settings, session_id: int, image: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_photo_session(conn, session_id, Path(image),
                              settings=settings, ledger=ledger)
    finally:
        conn.close()


def _check_summaries(conn, shop_id: int, now: datetime) -> list[dict]:
    rows = []
    for row in reversed(db.load_photo_checks(conn, shop_id)):
        try:
            report = json.loads(row["report_json"] or "{}")
        except ValueError:
            report = {}
        products = report.get("products") or []
        rows.append({
            "id": row["id"],
            "thumb_url": _photo_url(row["image_path"]),
            "rel": _relative_time(row["created_at"], now),
            "chips": [_display(p.get("name_en", "")) for p in products
                      if p.get("name_en")][:4],
            "count": len(products),
        })
    return rows


def _result_context(report: dict) -> dict:
    products = []
    width = report.get("image_w")
    height = report.get("image_h")
    for index, raw in enumerate(report.get("products") or []):
        name_en = raw.get("name_en") or ""
        boxes = raw.get("boxes") or []
        if (width is None or height is None) and boxes:
            width = width or boxes[0].get("w")
            height = height or boxes[0].get("h")
        count = raw.get("count")
        span = raw.get("count_range")
        needs_check = bool(raw.get("needs_check"))
        if not raw.get("countable"):
            count_text = ""
        elif needs_check and span:
            count_text = (f"Between {span[0]} and {span[1]} - please check")
        elif needs_check and isinstance(count, int):
            count_text = (f"About {count} - some may be hidden, please check")
        elif isinstance(count, int):
            count_text = f"About {count} visible"
        else:
            count_text = ""
        default_qty = None
        if raw.get("countable"):
            if isinstance(count, int):
                default_qty = count
            elif span and len(span) == 2:
                spark = raw.get("count_spark")
                if isinstance(spark, int):
                    default_qty = spark
                else:
                    default_qty = round((span[0] + span[1]) / 2)
        products.append({
            "index": index,
            "colour": index % BOX_COLOURS,
            "name_en": name_en,
            "display": _display(name_en),
            "name_local": (raw.get("name_local")
                           or CANONICAL_NAMES.get(name_en, "")),
            "countable": bool(raw.get("countable")),
            "count": count if isinstance(count, int) else None,
            "needs_check": needs_check,
            "count_text": count_text,
            "default_qty": default_qty,
            "boxes": boxes,
            "condition": raw.get("condition"),
        })
    suggestions = []
    raws = report.get("products") or []
    for index, raw in enumerate(report.get("suggestions") or []):
        action = raw.get("action")
        icon, button = _SUGGESTION_BUTTONS.get(
            action, ("camera", "Retake photo"))
        suggestions.append({
            "index": index,
            "kind": raw.get("kind") or "",
            "text": raw.get("text") or "",
            "item_name": raw.get("item_name") or "",
            "action": action or "",
            "icon": icon,
            "button": button,
            "is_link": action not in _SUGGESTION_BUTTONS,
            "qty": (_default_qty(raw, raws) if action == "set_stock"
                    else None),
        })
    conditions = [(p["display"], p["condition"]) for p in products
                  if p["condition"]]
    return {"products": products, "suggestions": suggestions,
            "conditions": conditions, "width": width or 100,
            "height": height or 100}


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    @app.get("/e/{token}/photos")
    def photos_list(request: Request, token: str, conn: Conn):
        shop = _shop_or_404(conn, token)
        return templates.TemplateResponse(request, "photos.html", {
            "shop": shop, "token": token,
            "checks": _check_summaries(conn, shop["id"], datetime.now(UTC)),
            "max_photo_bytes": MAX_PHOTO_BYTES})

    @app.post("/e/{token}/photos")
    def photos_upload(request: Request, token: str, photo: UploadFile,
                      conn: Conn):
        shop = _shop_or_404(conn, token)
        db.purge_expired(conn, data_dir, datetime.now(UTC))
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
        payload = photo.file.read()
        if not payload:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "No photo chosen",
                 "message": ("Choose a photo of your stock first, then tap"
                             " upload.")},
                status_code=400)
        if len(payload) > MAX_PHOTO_BYTES:
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
                 "message": ("We could not open that file as a photo. Please"
                             " choose a jpeg, png or webp photo (HEIC photos"
                             " need converting to jpeg first).")},
                status_code=400)
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png",
               "webp": ".webp"}.get(photo_format)
        if ext is None:
            given = Path(photo.filename or "").suffix.lower()
            ext = given if given in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        session_id = db.create_session(conn, shop["id"], "photo")
        photo_dir = data_dir / "photos"
        photo_dir.mkdir(parents=True, exist_ok=True)
        saved = photo_dir / f"p{session_id}_{secrets.token_hex(4)}{ext}"
        saved.write_bytes(payload)
        write_photo_meta(data_dir, session_id,
                         {"image": str(saved), "check_id": None})
        jobs.submit(run_photo_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    @app.get("/e/{token}/photos/{check_id}")
    def photo_result(request: Request, token: str, check_id: int, conn: Conn):
        shop = _shop_or_404(conn, token)
        check = _check_of_shop(conn, shop["id"], check_id)
        try:
            report = json.loads(check["report_json"] or "{}")
        except ValueError:
            report = {}
        context = _result_context(report if isinstance(report, dict) else {})
        return templates.TemplateResponse(request, "photo.html", {
            "shop": shop, "token": token, "check": check,
            "rel": _relative_time(check["created_at"], datetime.now(UTC)),
            "image_url": _photo_url(check["image_path"]), **context})

    @app.post("/e/{token}/photos/{check_id}/apply")
    def photo_apply(token: str, check_id: int, conn: Conn,
                    request: Request,
                    action: str = Form(""), item: str = Form(""),
                    qty: str | None = Form(None)):
        shop = _shop_or_404(conn, token)
        check = _check_of_shop(conn, shop["id"], check_id)
        try:
            report = json.loads(check["report_json"] or "{}")
        except ValueError:
            report = {}
        products = (report.get("products") or []
                    if isinstance(report, dict) else [])
        suggestions = (report.get("suggestions") or []
                       if isinstance(report, dict) else [])
        name = (item or "").strip()
        if action == "voice_update":
            if not name:
                return templates.TemplateResponse(
                    request, "error.html",
                    {"title": "Which item?",
                     "message": "Tell us which item needs a price first."},
                    status_code=400)
            return RedirectResponse(
                f"/e/{token}/update?hint={quote(name)}", status_code=303)
        if action not in ("set_stock", "unsold"):
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Unknown action",
                 "message": "That suggestion button did nothing."},
                status_code=400)
        version_id = db.latest_version(conn, shop["id"])
        current = db.version_items(conn, version_id) if version_id else []
        target = _find_version_item(current, name)
        if target is None:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": "Not on your list",
                 "message": (f"{_display(name)} is not on your price list yet."
                             " Say its price first, then save the stock.")},
                status_code=400)
        if action == "unsold":
            db.set_sold_out(conn, target.id, False)
            return RedirectResponse(f"/e/{token}/photos/{check_id}",
                                    status_code=303)
        amount: int | None = None
        if qty is not None and str(qty).strip() != "":
            try:
                amount = int(str(qty).strip())
            except ValueError:
                amount = None
            if amount is None or amount < 0:
                return templates.TemplateResponse(
                    request, "error.html",
                    {"title": "Count does not look right",
                     "message": ("That count is not a whole number. Pick the"
                                 " count with - and +, then save again.")},
                    status_code=400)
        else:
            for raw in suggestions:
                if (raw.get("action") == "set_stock"
                        and _canonical(raw.get("item_name")) == _canonical(name)):
                    amount = _default_qty(raw, products)
                    break
            if amount is None:
                return templates.TemplateResponse(
                    request, "error.html",
                    {"title": "No count yet",
                     "message": ("Pick the count with - and +, then save"
                                 " again.")},
                    status_code=400)
        db.set_stock(conn, target.id, amount, "piece", "photo")
        return RedirectResponse(f"/e/{token}/photos/{check_id}",
                                status_code=303)
