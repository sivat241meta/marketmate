"""Credit (udhaar) pages: open balances, customer ledger, collections."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import quote as url_quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.dayclose import shop_tz
from app.outputs.money import format_money
from app.web.auth import created_by_for, credit_or_403, resolve_or_404
from app.web.i18n import (
    credit_reminder_whatsapp_text,
    get_ui_lang,
    t_for,
    wa_chat_number,
)


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


def _fmt_day(shop, value: str | None) -> str:
    when = _parse_moment(value)
    if when is None:
        return ""
    return when.astimezone(shop_tz(shop)).strftime("%d %b %Y")


def _fmt_clock(shop, value: str | None) -> str:
    when = _parse_moment(value)
    if when is None:
        return ""
    local = when.astimezone(shop_tz(shop))
    return local.strftime("%d %b, %H:%M")


def _fmt_plain(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def _bill_amount(shop, row) -> Decimal:
    try:
        return db.bill_display_totals(shop, row)["rounded"]
    except (InvalidOperation, ValueError):
        try:
            return Decimal(str(row["total"]))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _actor(request, conn, token):
        shop, role, helper = resolve_or_404(conn, token)
        ui_lang = get_ui_lang(request, shop)
        denied = credit_or_403(request, templates, role, token, conn,
                               ui_lang)
        return shop, role, helper, ui_lang, denied

    def _is_staff(role: str) -> bool:
        return role == "staff"

    @app.get("/e/{token}/credit")
    def credit_list(request: Request, token: str, conn: Conn):
        shop, role, _helper, ui_lang, denied = _actor(request, conn, token)
        if denied is not None:
            return denied
        t = t_for(ui_lang)
        entries = db.credit_balances(conn, shop)
        currency = shop["currency"] or "INR"
        total = sum((entry["balance"] for entry in entries),
                    Decimal("0.00"))
        if len(entries) == 1:
            headline = t("credit.to_collect_one",
                         total=format_money(total, currency))
        else:
            headline = t("credit.to_collect",
                         total=format_money(total, currency), n=len(entries))
        rows = []
        for entry in entries:
            rows.append({
                "key": entry["customer_key"],
                "key_quoted": url_quote(entry["customer_key"], safe=""),
                "name": entry["name"] or entry["phone"],
                "phone": entry["phone"],
                "balance": format_money(entry["balance"], currency),
                "bill_count": entry["bill_count"],
                "last_bill": _fmt_day(shop, entry.get("last_bill_at")),
                "oldest": _fmt_day(shop, entry.get("oldest_unpaid_at")),
            })
        return templates.TemplateResponse(request, "credit.html", {
            "shop": shop, "token": token, "ui_lang": ui_lang,
            "is_staff": _is_staff(role), "entries": rows,
            "headline": headline, "count": len(entries),
        })

    def _detail_context(request, shop, token, key: str, conn, ui_lang: str,
                        error=None, status_code=200, is_staff=False):
        currency = shop["currency"] or "INR"
        try:
            norm = db.normalize_credit_phone(key)
        except ValueError:
            raise HTTPException(404, "unknown customer") from None
        entry = db.credit_balance_for(conn, shop, norm)
        if not entry["bills"] and not entry["payments"]:
            raise HTTPException(404, "unknown customer")
        bills = []
        for row in entry["bills"]:
            bill_token = db.ensure_bill_token(conn, row["id"])
            amount = _bill_amount(shop, row)
            bills.append({
                "id": row["id"],
                "day": _fmt_day(shop, row["created_at"]),
                "clock": _fmt_clock(shop, row["created_at"]),
                "amount": format_money(amount, currency),
                "receipt_url": f"/b/{bill_token}",
                "at": str(row["created_at"] or ""),
            })
        payments = []
        for payment in entry["payments"]:
            try:
                amount = Decimal(str(payment["amount"]))
            except (InvalidOperation, ValueError):
                amount = Decimal("0.00")
            try:
                mode = str(payment["mode"] or "").strip().lower()
            except (KeyError, IndexError, TypeError):
                mode = ""
            payments.append({
                "id": payment["id"],
                "day": _fmt_day(shop, payment["at"]),
                "clock": _fmt_clock(shop, payment["at"]),
                "amount": format_money(amount, currency),
                "mode": mode,
                "at": str(payment["at"] or ""),
            })
        # Running ledger: bills add, payments subtract, in stored order.
        events: list[tuple[str, int, str, dict]] = []
        for order, row in enumerate(entry["bills"]):
            events.append((str(row["created_at"] or ""), order, "bill",
                           row))
        for order, payment in enumerate(entry["payments"]):
            events.append((str(payment["at"] or ""), order, "payment",
                           payment))
        events.sort(key=lambda item: (item[0], item[1]))
        running = Decimal("0.00")
        ledger = []
        for _stamp, _order, kind, ref in events:
            if kind == "bill":
                running += _bill_amount(shop, ref)
                ledger.append({
                    "kind": "bill",
                    "label": f"#{ref['id']}",
                    "day": _fmt_day(shop, ref["created_at"]),
                    "amount": format_money(_bill_amount(shop, ref),
                                           currency),
                    "running": format_money(running, currency),
                })
            else:
                try:
                    paid = Decimal(str(ref["amount"]))
                except (InvalidOperation, ValueError):
                    paid = Decimal("0.00")
                running -= paid
                ledger.append({
                    "kind": "payment",
                    "label": "",
                    "day": _fmt_day(shop, ref["at"]),
                    "amount": format_money(-paid, currency),
                    "running": format_money(running, currency),
                })
        stamps = [str(row["created_at"]) for row in entry["bills"]
                  if row["created_at"]]
        oldest = _fmt_day(shop, min(stamps)) if stamps else ""
        shop_url = (f"{request.app.state.settings.public_base_url}"
                    f"/s/{shop['slug']}")
        balance_text = format_money(entry["balance"], currency)
        text = credit_reminder_whatsapp_text(
            shop, balance_text, entry["bill_count"], oldest, shop_url)
        digits = wa_chat_number(norm)
        reminder_url = (f"https://wa.me/{digits}?text={url_quote(text)}"
                        if digits else f"https://wa.me/?text={url_quote(text)}")
        return templates.TemplateResponse(request, "credit_customer.html", {
            "shop": shop, "token": token, "ui_lang": ui_lang,
            "is_staff": is_staff,
            "key": norm, "key_quoted": url_quote(norm, safe=""),
            "name": entry["name"] or norm, "phone": norm,
            "bills": bills, "payments": payments, "ledger": ledger,
            "bills_total": format_money(entry["bills_total"], currency),
            "paid_total": format_money(entry["paid_total"], currency),
            "balance": balance_text,
            "balance_plain": _fmt_plain(entry["balance"]),
            "bill_count": entry["bill_count"],
            "oldest": oldest, "reminder_url": reminder_url,
            "reminder_text": text, "error": error,
        }, status_code=status_code)

    @app.get("/e/{token}/credit/{customer_key}")
    def credit_detail(request: Request, token: str, customer_key: str,
                      conn: Conn):
        shop, role, _helper, ui_lang, denied = _actor(
            request, conn, token)
        if denied is not None:
            return denied
        return _detail_context(request, shop, token, customer_key, conn,
                               ui_lang,
                               is_staff=_is_staff(role))

    @app.post("/e/{token}/credit/{customer_key}/pay")
    async def credit_pay_post(request: Request, token: str,
                              customer_key: str):
        conn = db.connect(data_dir)
        try:
            shop, role, helper, ui_lang, denied = _actor(
                request, conn, token)
            if denied is not None:
                return denied
            form = await request.form()
            try:
                norm = db.normalize_credit_phone(customer_key)
            except ValueError:
                raise HTTPException(404, "unknown customer") from None
            try:
                db.record_credit_payment(
                    conn, shop, norm, form.get("amount", ""),
                    form.get("mode", ""),
                    created_by_for(role, helper))
            except ValueError as exc:
                return _detail_context(request, shop, token, norm, conn,
                                       ui_lang, error=str(exc),
                                       status_code=400,
                                       is_staff=_is_staff(role))
            return RedirectResponse(
                f"/e/{token}/credit/{url_quote(norm, safe='')}?saved=1",
                status_code=303)
        finally:
            conn.close()
