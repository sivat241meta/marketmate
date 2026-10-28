"""Seller settings: shop profile, UPI, language, currency, rounding, helpers."""

import re
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.languages import LANGUAGES, all_currencies
from app.outputs.qr import qr_svg
from app.web.auth import owner_or_403, resolve_or_404
from app.web.i18n import get_ui_lang, link_self_whatsapp_url

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")
_UPI_RE = re.compile(r"^[a-zA-Z0-9._\-]{2,}@[a-zA-Z]{2,}[a-zA-Z0-9.\-]*$")
_LANGUAGES = {lang.code for lang in LANGUAGES}
_CURRENCIES = set(all_currencies())


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

    def _context(request, shop, token, error=None, just_created=None):
        seller_url = f"{app.state.settings.public_base_url}/e/{token}"
        ui_lang = get_ui_lang(request, shop)
        conn = db.connect(data_dir)
        try:
            helpers = db.list_helpers(conn, shop["id"])
        finally:
            conn.close()
        return templates.TemplateResponse(request, "settings.html", {
            "shop": shop, "token": token, "error": error,
            "languages": LANGUAGES, "currencies": all_currencies(),
            "seller_url": seller_url,
            "seller_qr": qr_svg(seller_url),
            "rounding_on": db.shop_rounding_enabled(shop),
            "ui_lang": ui_lang,
            "helpers": helpers,
            "just_created": just_created,
            "self_wa_url": link_self_whatsapp_url(shop, seller_url),
        })

    @app.get("/e/{token}/settings")
    def settings_page(request: Request, token: str, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        return _context(request, shop, token)

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
            error = None
            if not name or not area or not shop_type:
                error = "name, area and type are required"
            elif not _PHONE_RE.match(phone):
                error = "phone must be 7-15 digits, optional leading +"
            elif language not in _LANGUAGES:
                error = "unknown language"
            elif currency not in _CURRENCIES:
                error = "unknown currency"
            try:
                upi_id = validate_upi_id(form.get("upi_id"))
            except ValueError as exc:
                error = error or str(exc)
                upi_id = None
            if error is not None:
                fresh = _shop_or_404(conn, token)
                ui_lang = get_ui_lang(request, fresh)
                helpers = db.list_helpers(conn, fresh["id"])
                seller_url = (f"{app.state.settings.public_base_url}"
                              f"/e/{token}")
                return templates.TemplateResponse(
                    request, "settings.html", {
                        "shop": fresh, "token": token, "error": error,
                        "languages": LANGUAGES,
                        "currencies": all_currencies(),
                        "seller_url": seller_url,
                        "seller_qr": qr_svg(seller_url),
                        "rounding_on": db.shop_rounding_enabled(fresh),
                        "ui_lang": ui_lang,
                        "helpers": helpers,
                        "just_created": None,
                        "self_wa_url": link_self_whatsapp_url(
                            fresh, seller_url),
                    }, status_code=400)
            db.update_shop_settings(
                conn, shop["id"], name=name, area=area, phone=phone,
                language=language, currency=currency, shop_type=shop_type,
                upi_id=upi_id, upi_payee=(upi_payee_raw or None),
                round_bills=("round_bills" in form))
            return RedirectResponse(f"/e/{token}/settings", status_code=303)
        finally:
            conn.close()

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
