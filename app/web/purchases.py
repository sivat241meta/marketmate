"""Seller purchases: the morning market run, cost, margin and stock left."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db, jobs
from app.costs import (
    BUDGET_EXHAUSTED_MESSAGE,
    IST,
    CostCapExceeded,
    CostLedger,
)
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.models import UNITS
from app.outputs.money import format_money
from app.pipeline.purchase import (
    _draft_from_dict,
    read_purchase_meta,
    run_purchase_job,
)
from app.web.i18n import get_ui_lang, t_for


def _today_ist() -> str:
    return datetime.now(UTC).astimezone(IST).date().isoformat()


def _shop_or_404(conn, token: str):
    shop = db.shop_by_token(conn, token)
    if shop is None:
        raise HTTPException(404, "unknown shop token")
    return shop


def _session_of_shop(conn, shop_id: int, session_id: int):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND shop_id = ?",
        (session_id, shop_id)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown purchase")
    if row["kind"] != "purchase":
        raise HTTPException(404, "unknown purchase")
    return row


def _canonical(name: str | None) -> str:
    from app.market.search import SYNONYMS

    key = (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def _sell_per_unit(item):
    """(price per 1 unit, unit) for the first priced line, or (None, None)."""
    for line in item.price_lines:
        if (line.price is not None and line.per_amount
                and line.per_amount != 0 and line.unit):
            per = (line.price / line.per_amount).quantize(
                Decimal("0.01"))
            if per == per.to_integral_value():
                per = Decimal(int(per))
            return (per, line.unit)
    return (None, None)


def purchase_rows(conn, shop_id: int, date: str, currency: str,
                  lang: str = "en") -> list[dict]:
    """One row per purchase today with cost, margin and stock left."""
    from app import purchases as pur

    t = t_for(lang)
    version_id = db.latest_version(conn, shop_id, published_only=True)
    sell_map: dict[str, object] = {}
    if version_id is not None:
        for item in db.version_items(conn, version_id):
            key = _canonical(item.name_en)
            if key not in sell_map:
                sell_map[key] = item
    rows = []
    for purchase in pur.list_purchases(conn, shop_id, date):
        buy_per, buy_unit = pur.cost_per_unit(purchase.qty, purchase.unit,
                                              purchase.total_cost)
        sell_per, sell_unit = (None, None)
        margin = ""
        item = sell_map.get(_canonical(purchase.name_en))
        if item is not None and not item.sold_out:
            sell_per, sell_unit = _sell_per_unit(item)
            if buy_per is not None and sell_per is not None:
                margin = pur.margin_text(buy_per, buy_unit, sell_per,
                                         sell_unit, currency=currency,
                                         lang=lang)
        left, left_unit = pur.stock_left(conn, shop_id, purchase.name_en,
                                         date)
        total_fmt = (format_money(purchase.total_cost, currency)
                     if purchase.total_cost is not None else "")
        cost_fmt = (f"{format_money(buy_per, currency)}/{buy_unit}"
                    if buy_per is not None else "")
        rows.append({
            "id": purchase.id,
            "name_en": purchase.name_en,
            "display": (purchase.name_en[:1].upper() + purchase.name_en[1:]
                        if purchase.name_en else ""),
            "name_local": purchase.name_local,
            "qty": (format(purchase.qty.normalize(), "f")
                    if purchase.qty is not None else ""),
            "unit": purchase.unit or "",
            "total": total_fmt,
            "cost_per": cost_fmt,
            "paid_cost": t("pur.paid_cost", total=total_fmt, cost=cost_fmt),
            "sell_per": (f"{format_money(sell_per, currency)}/{sell_unit}"
                         if sell_per is not None else ""),
            "margin": margin,
            "stock_left": (f"{format(left.normalize(), 'f')} {left_unit}"
                           if left is not None else ""),
            "source": purchase.source,
        })
    return rows


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    @app.get("/e/{token}/purchases")
    def purchases_page(request: Request, token: str, conn: Conn):
        from app import purchases as pur

        shop = _shop_or_404(conn, token)
        ui_lang = get_ui_lang(request, shop)
        today = _today_ist()
        currency = shop["currency"] or "INR"
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE shop_id = ? AND kind = 'purchase'"
            " ORDER BY id DESC LIMIT 5", (shop["id"],)).fetchall()
        return templates.TemplateResponse(request, "purchases.html", {
            "shop": shop, "token": token, "today": today,
            "rows": purchase_rows(conn, shop["id"], today, currency,
                                  ui_lang),
            "spent": pur.spent_on(conn, shop["id"], today),
            "currency": currency, "sessions": sessions, "error": None,
            "units": list(UNITS),
            "notice": "Your voice recording is sent to Meta's AI service"
                      " to be transcribed.",
            "ui_lang": ui_lang,
        })

    @app.post("/e/{token}/purchases/voice")
    def purchases_voice(request: Request, token: str, audio: UploadFile,
                        conn: Conn):
        shop = _shop_or_404(conn, token)
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        db.purge_expired(conn, data_dir, datetime.now(UTC))
        if not request.app.state.limiter.allow(client_ip(request),
                                               datetime.now(UTC)):
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.too_many_title"),
                 "message": RATE_LIMIT_MESSAGE, "token": token,
                 "ui_lang": ui_lang},
                status_code=429)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            ledger.check()
        except CostCapExceeded:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.budget_title"),
                 "message": BUDGET_EXHAUSTED_MESSAGE, "token": token,
                 "ui_lang": ui_lang},
                status_code=503)
        payload = audio.file.read()
        if not payload:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.empty_rec_title"),
                 "message": "That recording was empty. Try again.",
                 "token": token, "ui_lang": ui_lang},
                status_code=400)
        session_id = db.create_session(conn, shop["id"], "purchase")
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(getattr(audio, "filename", "") or "buy.webm").name
        saved = uploads / f"p{session_id}_{safe_name}"
        saved.write_bytes(payload)
        jobs.submit(run_purchase_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/purchases/{session_id}",
                                status_code=303)

    @app.get("/e/{token}/purchases/{session_id}")
    def purchase_review(request: Request, token: str, session_id: int,
                        conn: Conn):
        shop = _shop_or_404(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        if session["status"] != "review":
            return RedirectResponse(f"/e/{token}/s/{session_id}",
                                    status_code=303)
        meta = read_purchase_meta(data_dir, session_id)
        drafts = [_draft_from_dict(raw) for raw in meta.get("drafts") or []]
        cards = []
        for index, draft in enumerate(drafts):
            cards.append({
                "index": index,
                "name_en": draft.name_en,
                "name_local": draft.name_local,
                "qty": (format(draft.qty.normalize(), "f")
                        if draft.qty is not None else ""),
                "unit": draft.unit or "",
                "total_cost": (format(draft.total_cost.normalize(), "f")
                               if draft.total_cost is not None else ""),
                "quote": draft.proof.quote,
                "flags": draft.flags,
                "need_confirm": any(f.blocking for f in draft.flags),
            })
        return templates.TemplateResponse(request, "purchase_review.html", {
            "shop": shop, "token": token, "session": session,
            "cards": cards, "transcript": meta.get("transcript", ""),
            "currency": shop["currency"] or "INR", "ui_lang": ui_lang})

    @app.post("/e/{token}/purchases/{session_id}/confirm")
    async def purchase_confirm(request: Request, token: str, session_id: int):
        from app import purchases as pur

        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            session = _session_of_shop(conn, shop["id"], session_id)
            if session["status"] == "approved":
                return RedirectResponse(f"/e/{token}/purchases",
                                        status_code=303)
            if session["status"] != "review":
                raise HTTPException(400, "these purchases are not ready")
            meta = read_purchase_meta(data_dir, session_id)
            drafts = [_draft_from_dict(raw) for raw in meta.get("drafts") or []]
            form = await request.form()
            confirmed: set[int] = set()
            for value in form.getlist("confirmed"):
                try:
                    confirmed.add(int(value))
                except (TypeError, ValueError):
                    continue
            # A single "confirmed=on" ticks every card (one-item voice note).
            if form.get("confirmed") == "on":
                confirmed = set(range(len(drafts)))
            for index, draft in enumerate(drafts):
                if (any(f.blocking for f in draft.flags)
                        and index not in confirmed):
                    raise HTTPException(
                        400, f"unconfirmed purchase on {draft.name_en}")
            today = _today_ist()
            for draft in drafts:
                pur.add_purchase(
                    conn, shop["id"], today, draft.name_en, draft.qty,
                    draft.unit, draft.total_cost, source="voice",
                    name_local=draft.name_local)
            db.set_session_status(conn, session_id, "approved",
                                  f"{len(drafts)} purchases saved")
            return RedirectResponse(f"/e/{token}/purchases", status_code=303)
        finally:
            conn.close()

    @app.post("/e/{token}/purchases/add")
    async def purchases_add(request: Request, token: str):
        from app import purchases as pur
        from app.pipeline.names import CANONICAL_NAMES

        conn = db.connect(data_dir)
        try:
            shop = _shop_or_404(conn, token)
            form = await request.form()
            name = str(form.get("item") or "").strip()
            qty_raw = str(form.get("quantity") or "").strip()
            unit = str(form.get("unit") or "").strip() or None
            total_raw = str(form.get("total_paid") or "").strip()
            if not name:
                raise HTTPException(400, "tell us what you bought")
            try:
                qty = Decimal(qty_raw)
            except (InvalidOperation, ValueError, AttributeError):
                raise HTTPException(
                    400, "that quantity does not look right") from None
            if qty.is_nan() or qty <= 0:
                raise HTTPException(
                    400, "that quantity does not look right")
            if unit is not None and unit not in UNITS:
                raise HTTPException(400, "that unit does not look right")
            try:
                total = Decimal(total_raw)
            except (InvalidOperation, ValueError, AttributeError):
                raise HTTPException(
                    400, "that total does not look right") from None
            if total.is_nan() or total <= 0:
                raise HTTPException(
                    400, "that total does not look right")
            name_en = name.lower()
            pur.add_purchase(
                conn, shop["id"], _today_ist(), name_en, qty, unit, total,
                source="typed",
                name_local=CANONICAL_NAMES.get(name_en, ""))
            return RedirectResponse(f"/e/{token}/purchases", status_code=303)
        finally:
            conn.close()
