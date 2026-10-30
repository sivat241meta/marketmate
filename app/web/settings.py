"""Seller settings: shop profile, UPI, language, currency, rounding, helpers."""

import io
import re
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps

from app import db
from app.languages import LANGUAGES, all_currencies
from app.market.hours import (
    has_hours,
    minutes_to_hhmm,
    parse_hours_form,
    parse_hours_json,
    round_coord,
    validate_pincode,
)
from app.outputs.qr import qr_svg
from app.web.auth import owner_or_403, resolve_or_404
from app.web.i18n import get_ui_lang, link_self_whatsapp_url

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")
_UPI_RE = re.compile(r"^[a-zA-Z0-9._\-]{2,}@[a-zA-Z]{2,}[a-zA-Z0-9.\-]*$")
_LANGUAGES = {lang.code for lang in LANGUAGES}
_CURRENCIES = set(all_currencies())

#: Stored shop-type values with translated labels (``set.type_<value>``).
#: The settings form renders these as a select; any other stored value
#: is kept as an extra option so nothing is ever lost.
SHOP_TYPES = ("vegetable",)

#: Shop cover uploads: JPEG/PNG at most this big, resized to 1600px and
#: 800px wide progressive JPEGs with EXIF stripped (no API calls).
MAX_COVER_BYTES = 5 * 1024 * 1024
COVER_WIDTHS = (1600, 800)
COVER_QUALITY = 82


class BadCoverUpload(ValueError):
    """A cover upload that is too big or not a JPEG/PNG image."""


def save_cover(data: bytes, out_stem: Path) -> str:
    """Save a stall cover photo: 1600px + 800px progressive JPEGs.

    Returns the stored 1600px file name. Raises ``BadCoverUpload``
    for oversized or non-JPEG/PNG uploads. Never upscales.
    """
    if len(data) > MAX_COVER_BYTES:
        raise BadCoverUpload("photo is bigger than 5 MB")
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
    except Exception as exc:
        raise BadCoverUpload("not an image") from exc
    try:
        img = Image.open(io.BytesIO(data))
        if (img.format or "").upper() not in ("JPEG", "PNG", "MPO"):
            raise BadCoverUpload("not a JPEG or PNG photo")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except BadCoverUpload:
        raise
    except Exception as exc:
        raise BadCoverUpload("not an image") from exc
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    for width in COVER_WIDTHS:
        frame = img
        if frame.width > width:
            frame = frame.resize((width, round(frame.height * width
                                               / frame.width)),
                                 Image.LANCZOS)
        name = (f"{out_stem.name}.jpg" if width == COVER_WIDTHS[0]
                else f"{out_stem.name}-800.jpg")
        frame.save(out_stem.parent / name, "JPEG", quality=COVER_QUALITY,
                   progressive=True, optimize=True)
    return f"{out_stem.name}.jpg"


def _clean_phone(phone: str) -> str:
    return re.sub(r"[\s\-()]", "", phone or "")


def validate_upi_id(value: str | None) -> str | None:
    """Cleaned UPI ID or None when blank. Raises ValueError when invalid."""
    text = (value or "").strip()
    if not text:
        return None
    if not _UPI_RE.match(text):
        raise ValueError("that UPI ID does not look right (name@bank)")
    return text


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _shop_or_404(conn, token: str):
        shop, _role, _helper = resolve_or_404(conn, token)
        if shop is None:
            raise HTTPException(404, "unknown shop token")
        return shop

    def _owner_page(request, conn, token):
        """(shop, None) for owners; (None, friendly 403) for staff."""
        shop, role, _helper = resolve_or_404(conn, token)
        if shop is None:
            raise HTTPException(404, "unknown shop token")
        if role != "owner":
            ui_lang = get_ui_lang(request, shop)
            return None, owner_or_403(request, templates, role, ui_lang)
        return shop, None

    def _hours_context(shop):
        try:
            raw = shop["hours_json"]
        except (KeyError, IndexError, TypeError):
            raw = None
        try:
            parsed = parse_hours_json(raw)
        except ValueError:
            parsed = {"closed": set(), "slots": {}}
        days = []
        for day in range(7):
            slots = [(minutes_to_hhmm(o), minutes_to_hhmm(c))
                     for o, c in parsed["slots"].get(day, [])]
            while len(slots) < 2:
                slots.append(("", ""))
            days.append({"index": day, "closed": day in parsed["closed"],
                         "slots": [{"open": o, "close": c}
                                   for o, c in slots[:2]]})
        return {"hours_days": days, "has_hours": has_hours(raw)}

    def _context(request, shop, token, error=None, just_created=None,
                 error_field=None, saved=False, cover_saved=False):
        seller_url = f"{app.state.settings.public_base_url}/e/{token}"
        ui_lang = get_ui_lang(request, shop)
        conn = db.connect(data_dir)
        try:
            helpers = db.list_helpers(conn, shop["id"])
        finally:
            conn.close()
        return templates.TemplateResponse(request, "settings.html", {
            "shop": shop, "token": token, "error": error,
            "error_field": error_field, "saved": saved,
            "cover_saved": cover_saved,
            "languages": LANGUAGES, "currencies": all_currencies(),
            "shop_types": SHOP_TYPES,
            "seller_url": seller_url,
            "seller_qr": qr_svg(seller_url),
            "rounding_on": db.shop_rounding_enabled(shop),
            "ui_lang": ui_lang,
            "helpers": helpers,
            "just_created": just_created,
            "self_wa_url": link_self_whatsapp_url(shop, seller_url),
            **_hours_context(shop),
        })

    @app.get("/e/{token}/settings")
    def settings_page(request: Request, token: str, conn: Conn,
                      saved: str | None = None,
                      cover: str | None = None):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        return _context(request, shop, token, saved=bool(saved),
                        cover_saved=bool(cover))

    @app.post("/e/{token}/settings")
    async def settings_post(request: Request, token: str):
        conn = db.connect(data_dir)
        try:
            shop, denied = _owner_page(request, conn, token)
            if denied is not None:
                return denied
            form = await request.form()
            name = str(form.get("name") or "").strip()
            area = str(form.get("area") or "").strip()
            phone = _clean_phone(str(form.get("phone") or ""))
            language = str(form.get("language") or "").strip()
            currency = str(form.get("currency") or "").strip().upper()
            shop_type = str(form.get("type") or "").strip()
            upi_payee_raw = str(form.get("upi_payee") or "").strip()
            error = error_field = None
            if not name or not area or not shop_type:
                error = "name, area and type are required"
                error_field = ("name" if not name else
                               "area" if not area else "type")
            elif not _PHONE_RE.match(phone):
                error = "phone must be 7-15 digits, optional leading +"
                error_field = "phone"
            elif language not in _LANGUAGES:
                error = "unknown language"
                error_field = "language"
            elif currency not in _CURRENCIES:
                error = "unknown currency"
                error_field = "currency"
            try:
                upi_id = validate_upi_id(form.get("upi_id"))
            except ValueError as exc:
                if error is None:
                    error, error_field = str(exc), "upi_id"
                upi_id = None
            try:
                pincode = validate_pincode(form.get("pincode"))
            except ValueError as exc:
                if error is None:
                    error, error_field = str(exc), "pincode"
                pincode = db._UNCHANGED
            try:
                parsed_hours = parse_hours_form(form)
            except ValueError as exc:
                if error is None:
                    error, error_field = str(exc), "hours"
                parsed_hours = ""
            lat = lng = db._UNCHANGED
            if "remove_location" in form:
                lat = lng = None
            elif "lat" in form or "lng" in form:
                try:
                    lat = round_coord(form.get("lat"), kind="lat")
                    lng = round_coord(form.get("lng"), kind="lng")
                except ValueError as exc:
                    if error is None:
                        error, error_field = str(exc), "location"
                    lat = lng = db._UNCHANGED
            if (lat is None) != (lng is None):
                if error is None:
                    error, error_field = "bad location", "location"
                lat = lng = db._UNCHANGED
            # Market listing: the switch is owner-only (helpers get 403
            # above) and judge/test shops always stay unlisted.
            listed = any(
                str(value or "").strip().lower()
                in ("1", "on", "true", "yes")
                for value in form.getlist("listed"))
            if shop["is_judge"]:
                listed = False
            if error is not None:
                fresh = _shop_or_404(conn, token)
                ui_lang = get_ui_lang(request, fresh)
                helpers = db.list_helpers(conn, fresh["id"])
                seller_url = (f"{app.state.settings.public_base_url}"
                              f"/e/{token}")
                return templates.TemplateResponse(
                    request, "settings.html", {
                        "shop": fresh, "token": token, "error": error,
                        "error_field": error_field, "saved": False,
                        "languages": LANGUAGES,
                        "currencies": all_currencies(),
                        "shop_types": SHOP_TYPES,
                        "seller_url": seller_url,
                        "seller_qr": qr_svg(seller_url),
                        "rounding_on": db.shop_rounding_enabled(fresh),
                        "ui_lang": ui_lang,
                        "helpers": helpers,
                        "just_created": None,
                        "self_wa_url": link_self_whatsapp_url(
                            fresh, seller_url),
                        **_hours_context(fresh),
                    }, status_code=400)
            db.update_shop_settings(
                conn, shop["id"], name=name, area=area, phone=phone,
                language=language, currency=currency, shop_type=shop_type,
                upi_id=upi_id, upi_payee=(upi_payee_raw or None),
                round_bills=("round_bills" in form),
                hours_json=(parsed_hours if parsed_hours
                            else db._UNCHANGED),
                pincode=pincode, lat=lat, lng=lng, listed=listed)
            return RedirectResponse(f"/e/{token}/settings?saved=1",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/settings/cover")
    async def cover_post(request: Request, token: str, conn: Conn,
                         cover: UploadFile):
        """Save the seller's stall photo (JPEG/PNG ≤ 5 MB, no API calls)."""
        from app.web.i18n import t_for

        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        try:
            filename = save_cover(
                await cover.read(),
                data_dir / "photos" / f"cover_{shop['id']}")
        except BadCoverUpload:
            return _context(request, shop, token,
                            error=t_for(ui_lang)("set.cover_bad"),
                            error_field="cover")
        db.set_shop_cover(conn, shop["id"], filename)
        return RedirectResponse(f"/e/{token}/settings?cover=1",
                                status_code=303)

    @app.post("/e/{token}/settings/helpers")
    async def helper_add(request: Request, token: str):
        """Create a billing-only helper; the link + QR show once."""
        conn = db.connect(data_dir)
        try:
            shop, denied = _owner_page(request, conn, token)
            if denied is not None:
                return denied
            form = await request.form()
            name = str(form.get("name") or "").strip()
            if not name:
                return _context(request, shop, token,
                                error="give your helper a name")
            _helper_id, helper_token = db.create_helper(
                conn, shop["id"], name)
            helper_url = (f"{app.state.settings.public_base_url}"
                          f"/e/{helper_token}")
            return _context(request, shop, token, just_created={
                "name": name, "url": helper_url,
                "qr": qr_svg(helper_url)})
        finally:
            conn.close()

    @app.post("/e/{token}/settings/helpers/{helper_id}/credit")
    async def helper_credit(request: Request, token: str, helper_id: int):
        """Grant or revoke one helper's credit permission (default off)."""
        conn = db.connect(data_dir)
        try:
            shop, denied = _owner_page(request, conn, token)
            if denied is not None:
                return denied
            form = await request.form()
            try:
                helper_key = int(helper_id)
            except (TypeError, ValueError):
                return _context(request, shop, token,
                                error="unknown helper")
            try:
                db.set_helper_credit(conn, shop["id"], helper_key,
                                     str(form.get("can_credit") or "")
                                     .strip().lower() in ("1", "on",
                                                          "true", "yes"))
            except ValueError as exc:
                return _context(request, shop, token, error=str(exc))
            return RedirectResponse(f"/e/{token}/settings#helpers",
                                    status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/settings/helpers/{helper_id}/remove")
    async def helper_remove(request: Request, token: str, helper_id: int):
        conn = db.connect(data_dir)
        try:
            shop, denied = _owner_page(request, conn, token)
            if denied is not None:
                return denied
            try:
                db.remove_helper(conn, shop["id"], helper_id)
            except ValueError as exc:
                return _context(request, shop, token, error=str(exc))
            return RedirectResponse(f"/e/{token}/settings", status_code=303)
        finally:
            conn.close()
