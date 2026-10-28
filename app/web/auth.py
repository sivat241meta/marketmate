"""Seller-token auth shared by route modules: owner vs billing-only staff."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from app import db
from app.web.i18n import t_for


def resolve_or_404(conn: sqlite3.Connection, token: str):
    """Resolve an owner or helper token; 404 when unknown.

    Returns (shop_row, role, helper_name) with role "owner" or "staff".
    """
    shop, role, helper = db.resolve_seller_token(conn, token)
    if shop is None:
        raise HTTPException(404, "unknown shop token")
    return shop, role, helper


def owner_or_403(request: Request, templates: Jinja2Templates,
                 role: str, ui_lang: str = "en"):
    """None for owners; a friendly 403 page for billing-only helpers."""
    if role == "owner":
        return None
    t = t_for(ui_lang)
    return templates.TemplateResponse(
        request, "error.html",
        {"title": t("error.helper_title"),
         "message": t("error.helper_message"),
         "ui_lang": ui_lang},
        status_code=403)


def created_by_for(role: str, helper_name: str | None) -> str:
    """created_by value for a new bill: helper name or "owner"."""
    if role == "staff" and helper_name:
        return helper_name
    return "owner"
