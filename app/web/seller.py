import html as html_lib
import json
import os
import re
import sqlite3
import subprocess
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import quote as url_quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

from app import db, jobs
from app.config import (
    SAM_MODEL,
    SPARK_MODEL,
    SPARK_OPEN_MODEL,
    VOICE_MODEL,
    sample_shops_enabled,
)
from app.costs import (
    BUDGET_EXHAUSTED_MESSAGE,
    IST,
    VISION_STEPS,
    CostCapExceeded,
    CostLedger,
)
from app.languages import (
    LANGUAGES,
    all_currencies,
    get_language,
    shop_bias,
    shop_form_languages,
)
from app.limits import RATE_LIMIT_MESSAGE, client_ip
from app.market.search import category_of
from app.meta.sam import SamError
from app.meta.spark import SparkError
from app.meta.transcribe import TranscribeError, transcribe_wav
from app.outputs.csv_export import generic_csv
from app.outputs.money import format_money
from app.outputs.pdf import price_board_pdf, price_tags_pdf
from app.outputs.qr import qr_png
from app.outputs.time import format_relative
from app.outputs.value import stock_left_out_display, stock_value
from app.pipeline.checks import check_item
from app.pipeline.media import extract_audio
from app.pipeline.names import (
    CANONICAL_NAMES,
    QUALIFIER_VARIETIES,
    display_name_en,
    english_title,
    keywords_for,
    local_title,
)
from app.pipeline.numbers import parse_number
from app.pipeline.photos import (
    BadPhotoUpload,
    is_cutout_photo,
    photo_kind,
    save_retake,
)
from app.pipeline.run import (
    apply_spoken_language,
    friendly_error_message,
    process_video_session,
    reprocess,
    spoken_language,
)
from app.pipeline.update import (
    apply_changes,
    change_from_dict,
    change_to_dict,
    flags_for_change,
    parse_update,
)
from app.web.auth import owner_or_403, resolve_or_404
from app.web.home_data import v13_cutout_url
from app.web.i18n import (
    SAMPLE_TIME,
    first_grapheme,
    get_strings,
    get_ui_lang,
    link_self_whatsapp_url,
    local_date_label,
    stage_friendly,
    stage_label,
    t_for,
    tile_variety,
)
from app.web.photos import read_photo_meta, run_photo_job

NOTICE = "Your voice recording is sent to Meta's AI service to be transcribed."


def _voice_notice(ui_lang: str) -> str:
    return t_for(ui_lang)("notice.voice")

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")
_LANGUAGES = {lang.code for lang in LANGUAGES}
_CURRENCIES = set(all_currencies())
#: Version source -> customer notice phrase; unknown sources read as mixed.
_SRC_KEYS = {"video": "shop.src_video", "voice": "shop.src_voice",
             "live": "shop.src_live", "board": "shop.src_board",
             "mixed": "shop.src_mixed"}


def _clean_phone(phone: str) -> str:
    return re.sub(r"[\s\-()]", "", phone or "")


def _shop_or_404(conn, token: str):
    shop, _role, _helper = resolve_or_404(conn, token)
    return shop


def _owner_or_403_exc(conn, token: str):
    """Owner shop lookup for non-HTML routes; staff get a plain 403."""
    shop, role, _helper = resolve_or_404(conn, token)
    if role != "owner":
        raise HTTPException(403, "Helpers can only make bills")
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


def _retry_video_job(settings, session_id: int) -> None:
    """Background video retry: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db", settings.daily_budget_usd)
        reprocess(conn, session_id, settings=settings, ledger=ledger)
    finally:
        conn.close()


def _retry_language_job(settings, session_id: int, speak_lang: str) -> None:
    """Background guard re-run: opens its own connection, never the request's."""
    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db", settings.daily_budget_usd)
        apply_spoken_language(conn, session_id, speak_lang,
                              settings=settings, ledger=ledger)
    finally:
        conn.close()


def _photo_url(photo: str | None) -> str | None:
    if not photo:
        return None
    return "/m/" + Path(photo).name


def _draft_from_client(raw: dict, stored=None):
    """Parse one review-form item.

    Seller-editable fields (names, price lines, qty) come from the client.
    Everything the form never edits — photo, proof, name_spoken, variety,
    qty_unit, range_said, condition_hint — comes from the STORED draft so a
    client-sent null or a smuggled path can never wipe or forge them.
    """
    defaults = {
        "name_spoken": "",
        "name_local": "",
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
            "source": None,
        },
    }
    merged = dict(defaults, **raw)
    merged["proof"] = dict(defaults["proof"], **(raw.get("proof") or {}))
    item = db._draft_from_json(json.dumps(merged))
    if stored is None:
        return item
    # Stored truth wins for everything the form does not edit. Never trust
    # a client-sent photo or clip path.
    item.name_spoken = stored.name_spoken
    if not (item.name_local or "").strip():
        item.name_local = stored.name_local
    if not (item.name_en or "").strip():
        item.name_en = stored.name_en
    # Renames may change the variety; empty keeps the stored value.
    if not (item.variety or "").strip():
        item.variety = stored.variety
    else:
        item.variety = item.variety.strip()
    # A rename never changes the matching key.
    item.match_key = db.match_key_of(stored) or stored.name_en
    item.qty_unit = stored.qty_unit
    item.range_said = stored.range_said
    item.photo = stored.photo
    item.photo_candidates = list(stored.photo_candidates)
    item.proof = stored.proof
    item.condition_hint = stored.condition_hint
    # Keep the heard "said" text per line; the client only edits numbers.
    for pos, line in enumerate(item.price_lines):
        if pos < len(stored.price_lines) and not (line.said or "").strip():
            line.said = stored.price_lines[pos].said
        # Missing per with a unit means 1 (never "per None kg").
        if line.per_amount is None and line.unit:
            line.per_amount = Decimal(1)
    return item


def _board_flags(item):
    """Blocking flags for a board-photo draft: confirm or type the price."""
    from app.pipeline.board import BOARD_CONFIRM_MESSAGE, NOT_READ_MESSAGE

    flags = []
    for line in item.price_lines:
        if line.price is None:
            flags.append(db.Flag(
                field="price", code="NOT_READ",
                message=f"{item.name_en} {NOT_READ_MESSAGE}".strip(),
                options=[], blocking=True))
        else:
            flags.append(db.Flag(
                field="price", code="BOARD_CONFIRM",
                message=BOARD_CONFIRM_MESSAGE,
                options=[str(line.price)], blocking=True))
    return flags


def _update_path(data_dir: Path, session_id: int) -> Path:
    return data_dir / "sessions" / str(session_id) / "update.json"


_ACTION_LABELS = {
    "set_price": "New price",
    "sold_out": "Sold out",
    "in_stock": "Back in stock",
    "set_qty": "New quantity",
}

#: Task 78: ledger step value -> i18n label key for the Meta AI calls page.
_AI_STEP_KEYS = {
    "transcribe": "ai.step_transcribe",
    "extract prices": "ai.step_extract_prices",
    "check prices": "ai.step_check_prices",
    "find product frames": "ai.step_find_product_frames",
    "cut-out mask": "ai.step_cut_out_mask",
    "face check": "ai.step_face_check",
    "verify photo": "ai.step_verify_photo",
    "read board": "ai.step_read_board",
    "scan photo": "ai.step_scan_photo",
    "count items": "ai.step_count_items",
    "name items": "ai.step_name_items",
    "voice order": "ai.step_voice_order",
    "note purchases": "ai.step_note_purchases",
    "market search": "ai.step_market_search",
    "typed bill": "ai.step_typed_bill",
}

_AI_KINDS = ("all", "voice", "spark", "sam")

_AI_HONESTY_URL = ("https://github.com/sivat241meta/marketmate"
                   "/blob/main/README.md#honesty-by-design")


def _ai_kind_of(row: dict) -> str:
    """Filter kind for a ledger row: voice, spark, sam or other."""
    if row["provider"] == "baseten" or row["model"] in (
            SPARK_MODEL, SPARK_OPEN_MODEL):
        return "spark"
    if row["model"] == VOICE_MODEL:
        return "voice"
    if row["model"] == SAM_MODEL:
        return "sam"
    return "other"


def _ai_row_time(created_at: str | None) -> str:
    try:
        return datetime.fromisoformat(created_at or "").strftime("%H:%M")
    except ValueError:
        return (created_at or "")[:5]


def _ai_row_view(row: dict, t) -> dict:
    """One ledger row as the page/JSON needs it (translated step label)."""
    step = row["step"] or ""
    key = _AI_STEP_KEYS.get(step)
    kind = _ai_kind_of(row)
    usd = float(row["usd"] or 0.0)
    latency = row["latency_ms"]
    return {
        "id": row["id"],
        "time": _ai_row_time(row["created_at"]),
        "model": row["model"],
        "kind": kind,
        "spark_kind": ("vision" if step in VISION_STEPS else "text"
                       if kind == "spark" else None),
        "step": step,
        "step_label": t(key) if key else step,
        "summary": row["summary"],
        "latency_ms": latency,
        "latency": f"{latency} ms" if latency is not None else None,
        "usd": usd,
        "cost": f"${usd:.4f}",
        "ok": None if row["ok"] is None else bool(row["ok"]),
        "session_id": row["session_id"],
        "session_title": (t("sess.title", id=row["session_id"])
                          if row["session_id"] is not None
                          else t("ai.other_calls")),
    }


def _ai_groups(views: list[dict]) -> list[dict]:
    """Newest-first views grouped by session, order kept."""
    groups: list[dict] = []
    by_session: dict = {}
    for view in views:
        key = view["session_id"]
        if key not in by_session:
            by_session[key] = {"session_id": key,
                               "title": view["session_title"], "rows": []}
            groups.append(by_session[key])
        by_session[key]["rows"].append(view)
    return groups


def _ai_processing(conn, shop_id: int, session_id: int | None) -> bool:
    if session_id is not None:
        row = conn.execute(
            "SELECT status FROM sessions WHERE id = ? AND shop_id = ?",
            (session_id, shop_id)).fetchone()
        return row is not None and row["status"] == "processing"
    return conn.execute(
        "SELECT 1 FROM sessions WHERE shop_id = ? AND status = 'processing'"
        " LIMIT 1", (shop_id,)).fetchone() is not None


def _ai_session_param(raw: str | None) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None

_ACTION_LABEL_KEYS = {
    "set_price": "upd.action_set_price",
    "sold_out": "upd.action_sold_out",
    "in_stock": "upd.action_in_stock",
    "set_qty": "upd.action_set_qty",
}


def _action_label(action: str, lang: str = "en") -> str:
    key = _ACTION_LABEL_KEYS.get(action)
    if key is None:
        return _ACTION_LABELS.get(action, action)
    return t_for(lang)(key)


def _current_map(current: list):
    """Current items by matching key and display name (renames keep both)."""
    mapping = {}
    for item in current or []:
        mapping.setdefault(db.match_key_of(item), item)
        mapping.setdefault(item.name_en, item)
    return mapping


_FIELD_KEYS = {"local": "rename.field_local", "en": "rename.field_en",
               "variety": "rename.field_variety"}


def _rename_error(ui_lang: str, exc) -> str:
    """Translated rename rejection from a NameValidationError."""
    t = t_for(ui_lang)
    params = dict(exc.params or {})
    field = params.get("field")
    if field in _FIELD_KEYS:
        params["field"] = t(_FIELD_KEYS[field])
    return t(exc.key, **params)


_ITEM_COUNTER_RE = re.compile(r"item (\d+) of (\d+)$")


def _translated_progress(session, lang: str = "en") -> tuple[dict, str]:
    """session_progress with stepper labels + friendly line in ``lang``.

    Task 140: the active step's label carries the photo counter, so the
    status JSON (and the upload bubble polling it) reads "Picking a photo
    for each item (7 of 21)" while the step runs.
    """
    progress = db.session_progress(session)
    kind = session["kind"]
    counter = ""
    match = _ITEM_COUNTER_RE.match(progress.get("detail") or "")
    if match:
        counter = f" ({match.group(1)} of {match.group(2)})"
    steps = []
    for step in progress.get("steps", []):
        key = step.get("key", "")
        label = stage_label(kind, key, lang)
        if counter and key == progress.get("stage"):
            label = f"{label}{counter}"
        steps.append({**step, "label": label})
    progress = {**progress, "steps": steps}
    friendly = stage_friendly(kind, progress.get("stage", ""), lang)
    return progress, friendly


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


def _board_only(item) -> bool:
    """True when every blocking flag is a board-price tap confirm."""
    blocking = [flag for flag in item.flags if flag.blocking]
    return bool(blocking) and all(
        flag.code == "BOARD_CONFIRM" for flag in blocking)


def _per_text(per_amount, unit) -> str:
    """Display text for a price line's per-amount; never 'None'."""
    if per_amount is not None and unit:
        return f"{per_amount} {unit}"
    if unit:
        return str(unit)
    if per_amount is not None:
        return str(per_amount)
    return ""


def _price_summary(item, currency: str = "INR", lang: str = "en") -> str:
    # Task 143: a price under a blocking flag is shown as uncertain; the
    # card header pairs this with the "Needs you" pill, never the green tick.
    uncertain = any(getattr(flag, "blocking", False)
                    for flag in getattr(item, "flags", None) or [])
    mark = " ?" if uncertain else ""
    for line in item.price_lines:
        if line.price is not None:
            price = format_money(line.price, currency)
            if line.per_amount is not None and line.unit:
                return f"{price} / {line.per_amount} {line.unit}{mark}"
            if line.unit:
                return f"{price} / {line.unit}{mark}"
            return f"{price}{mark}"
    return t_for(lang)("review.no_price")


def _home_extras(conn, shop, ui_lang: str) -> dict:
    """Fresh Green home data: greeting, tap notice, orders, week numbers.

    Every figure comes from existing rows: today's tiles, sessions in
    review, waiting customer quotes and the last 7 day-close tiles.
    """
    from datetime import date as date_cls
    from datetime import timedelta

    from app.dayclose import day_tiles, shop_today

    t = t_for(ui_lang)
    now = datetime.now(UTC)
    local = now.astimezone(IST)
    hour = local.hour
    if hour < 12:
        greet_key = "sh.greet_morning"
    elif hour < 17:
        greet_key = "sh.greet_afternoon"
    else:
        greet_key = "sh.greet_evening"
    today_label = local_date_label(ui_lang, local)

    taps = []
    taps_total = 0
    for session in conn.execute(
            "SELECT * FROM sessions WHERE shop_id = ? AND status = 'review'"
            " AND kind IN ('video', 'live', 'board', 'voice_update')"
            " ORDER BY id DESC", (shop["id"],)).fetchall():
        try:
            drafts = db.load_drafts(conn, session["id"])
        except Exception:  # noqa: BLE001 - unreadable drafts count as none
            drafts = []
        need = sum(1 for draft in drafts if _needs_decision(draft))
        taps.append({"id": session["id"], "need": need})
        taps_total += need

    _OPEN_NEXT = {
        "new": ("packing", "bill.start_packing", "bills.pill_new", "quote"),
        "packing": ("ready", "bill.mark_ready", "bills.pill_packing",
                    "packing"),
        "ready": ("collected", "bill.mark_collected", "bills.pill_ready",
                  "ready"),
    }
    open_orders = []
    week_orders = 0
    count_new = 0
    count_packing = 0
    count_ready = 0
    unpaid_count = 0
    base = date_cls.fromisoformat(shop_today(shop, now))
    week_start = base - timedelta(days=6)
    currency = shop["currency"] or "INR"
    for row in db.list_quotes(conn, shop["id"]):
        try:
            when = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            local_day = when.astimezone(IST).date()
        else:
            local_day = None
        if (row["kind"] == "quote" and local_day is not None
                and week_start <= local_day <= base):
            week_orders += 1
        status = row["status"]
        customer = row["source"] == "customer"
        if customer and status == "new" and row["kind"] == "quote":
            # Same filter as pending.json, so the live badge matches.
            count_new += 1
        if customer and status == "packing":
            count_packing += 1
        if customer and status == "ready":
            count_ready += 1
        if row["kind"] == "bill" and status == "billed":
            unpaid_count += 1
        if not (customer and status in _OPEN_NEXT):
            continue
        try:
            raw = json.loads(row["lines_json"] or "[]")
        except ValueError:
            raw = []
        names = [
            display_name_en(str(entry.get("name_en") or ""),
                            entry.get("variety"))
            for entry in raw
            if isinstance(entry, dict) and entry.get("name_en")]
        try:
            total = db.bill_display_totals(shop, row)["rounded"]
        except (ValueError, ArithmeticError):
            total = row["total"]
        try:
            phone = (row["customer_phone"] or "").strip() or None
        except (KeyError, IndexError, TypeError):
            phone = None
        try:
            customer_name = (row["customer_name"] or "").strip() or None
        except (KeyError, IndexError, TypeError):
            customer_name = None
        order_num = t("bills.order_num", id=row["id"])
        if customer_name:
            order_label = f"{order_num} · {customer_name}"
        elif phone:
            order_label = f"{order_num} · {phone}"
        else:
            order_label = order_num
        next_status, next_key, pill_key, pill_kind = _OPEN_NEXT[status]
        av_name = (customer_name or phone or f"#{row['id']}").strip()
        open_orders.append({
            "id": row["id"],
            "label": order_label,
            "avatar_initial": av_name[:1].upper() or "#",
            "avatar_idx": sum(av_name.encode("utf-8")) % 5,
            "names": names,
            "count": len(raw) if isinstance(raw, list) else 0,
            "total": format_money(total, currency),
            "time": (when.astimezone(IST).strftime("%H:%M")
                     if when else ""),
            "pill": t(pill_key),
            "pill_kind": pill_kind,
            "next_status": next_status,
            "next_label": t(next_key),
        })
    open_orders.sort(key=lambda entry: entry["id"], reverse=True)

    sales_week = Decimal("0.00")
    bills_week = 0
    margin_week = Decimal("0.00")
    margin_known = True
    for back in range(7):
        day = (base - timedelta(days=back)).isoformat()
        tiles = day_tiles(conn, shop, day)
        sales_week += tiles["sales"]
        bills_week += tiles["bills_count"]
        if tiles["bills_count"]:
            if tiles["margin"] is None:
                margin_known = False
            else:
                margin_week += tiles["margin"]
    week_known = margin_known and bills_week > 0
    return {
        "today_label": today_label,
        "greet_key": greet_key,
        "greet_word_key": {
            "sh.greet_morning": "t68.greet_morning",
            "sh.greet_afternoon": "t68.greet_afternoon",
            "sh.greet_evening": "t68.greet_evening",
        }.get(greet_key, "t68.greet_afternoon"),
        "taps": taps,
        "taps_total": taps_total,
        "taps_first": next((entry["id"] for entry in taps
                            if entry["need"]),
                           taps[0]["id"] if taps else None),
        "count_new": count_new,
        "count_packing": count_packing,
        "count_ready": count_ready,
        "unpaid_count": unpaid_count,
        "open_orders": open_orders[:3],
        "week": {
            "sales": format_money(sales_week, currency),
            "bills": bills_week,
            "orders": week_orders,
            "margin": (format_money(margin_week, currency)
                       if week_known else None),
            "margin_known": week_known,
        },
    }


def _mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.0f}"


def _too_big_message(size_bytes: int, limit_bytes: int) -> str:
    return (f"That file is {_mb(size_bytes)} MB, which is too big to upload. "
            f"Please choose a file under {_mb(limit_bytes)} MB.")


PRICE_MESSAGE_MAX_ITEMS = 60
PRICE_MESSAGE_MAX_CHARS = 3500


def _fmt_amount(value) -> str:
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (ArithmeticError, ValueError):
        return str(value)


def build_price_message(conn, shop, lang, base_url: str | None = None) -> str:
    """Plain-text price list for WhatsApp from the latest PUBLISHED version.

    Only seller-confirmed prices are shared: drafts and newer unpublished
    versions never appear, and items without a price are left out. Sold-out
    items are named once at the end. Returns "" when nothing is published.
    """
    t = t_for(lang)
    if base_url is None:
        base_url = os.environ.get("PUBLIC_BASE_URL",
                                  "http://127.0.0.1:8000")
    base_url = str(base_url).rstrip("/") or "http://127.0.0.1:8000"
    version_id = db.latest_version(conn, shop["id"], published_only=True)
    if version_id is None:
        return ""
    when = db.version_time(conn, version_id)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    day = when.astimezone(IST).strftime("%d %b %Y")
    currency = shop["currency"] or "INR"
    first = f"{shop['name']} · {t('wa.today_prices')} · {day}"
    lines: list[str] = []
    sold_names: list[str] = []
    shop_lang = shop["language"] or "en"
    for item in db.version_items(conn, version_id):
        local = (item.name_local or "").strip() or item.name_en
        variety = (item.variety or "").strip()
        is_qualifier = (bool(variety)
                        and variety.lower() in QUALIFIER_VARIETIES)
        if item.sold_out:
            sold_names.append(
                local_title(local, item.variety, item.name_en, shop_lang)
                if is_qualifier else local)
            continue
        priced = [line for line in item.price_lines
                  if line.price is not None]
        if not priced:
            continue
        if is_qualifier:
            head = (f"{local_title(local, item.variety, item.name_en, shop_lang)}"
                    f" ({english_title(item.name_en, item.variety)})")
        else:
            head = f"{local} ({item.name_en}"
            if variety:
                head += f", {variety}"
            head += ")"
        bits = []
        for line in priced:
            money = format_money(line.price, currency)
            if line.unit and line.per_amount not in (None, Decimal(1)):
                bits.append(f"{money}/{_fmt_amount(line.per_amount)}"
                            f" {line.unit}")
            elif line.unit:
                bits.append(f"{money}/{line.unit}")
            else:
                bits.append(money)
        lines.append(f"{head} {', '.join(bits)}")
    shown = lines[:PRICE_MESSAGE_MAX_ITEMS]
    hidden = len(lines) - len(shown)
    order_line = t("wa.order_here", url=f"{base_url}/s/{shop['slug']}")

    def _assemble() -> str:
        parts = [first, *shown]
        if hidden:
            parts.append(t("wa.more", n=hidden))
        if sold_names:
            parts.append(t("wa.sold_out_list",
                           items=", ".join(sold_names)))
        parts.append(order_line)
        return "\n".join(parts)

    text = _assemble()
    while len(text) > PRICE_MESSAGE_MAX_CHARS and shown:
        shown = shown[:-1]
        hidden += 1
        text = _assemble()
    while len(text) > PRICE_MESSAGE_MAX_CHARS and sold_names:
        sold_names = sold_names[:-1]
        hidden += 1
        text = _assemble()
    return text


def _price_share(conn, shop, lang: str,
                 base_url: str) -> tuple[str | None, str | None]:
    """(wa.me URL, text) for today's prices, or (None, None) unpublished."""
    text = build_price_message(conn, shop, lang, base_url=base_url)
    if not text:
        return None, None
    return "https://wa.me/?text=" + url_quote(text), text


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _owner_page(request, conn, token):
        """(shop, None) for owners; (None, friendly 403) for staff."""
        shop, role, _helper = resolve_or_404(conn, token)
        if role != "owner":
            ui_lang = get_ui_lang(request, shop)
            return None, owner_or_403(request, templates, role, ui_lang)
        return shop, None

    def _new_shop_page(request, *, error=None, error_field=None,
                       values=None, status_code=200):
        visitor = get_ui_lang(request, None)
        default_lang = visitor if visitor in ("ta", "hi") else "en"
        try:
            default_currency = get_language(default_lang).default_currency
        except KeyError:
            default_currency = "INR"
        picked = values or {}
        return templates.TemplateResponse(request, "new_shop.html", {
            "languages": shop_form_languages(),
            "currencies": all_currencies(),
            "default_currency": {lang.code: lang.default_currency
                                 for lang in LANGUAGES},
            "default_lang": default_lang,
            "selected_currency": default_currency,
            "ui_lang": visitor if visitor in ("ta", "hi", "en") else "en",
            "error": error,
            "error_field": error_field,
            "values": picked,
        }, status_code=status_code)

    @app.get("/new")
    def new_shop(request: Request):
        return _new_shop_page(request)

    @app.post("/new")
    async def create_shop_post(request: Request, conn: Conn):
        from app.web.settings import validate_upi_id

        form = await request.form()
        name = str(form.get("name") or "").strip()
        phone = _clean_phone(str(form.get("phone") or ""))
        area = str(form.get("area") or "").strip()
        language = str(form.get("language") or "").strip()
        currency = str(form.get("currency") or "").strip()
        shop_type = str(form.get("type") or "").strip()
        values = {"name": str(form.get("name") or ""),
                  "phone": str(form.get("phone") or ""),
                  "area": str(form.get("area") or ""),
                  "language": language,
                  "currency": currency,
                  "type": str(form.get("type") or ""),
                  "upi_id": str(form.get("upi_id") or ""),
                  "listed": form.getlist("listed"),
                  "listed_on": True if not form.getlist("listed") else any(
                      str(value or "").strip().lower()
                      in ("1", "on", "true", "yes")
                      for value in form.getlist("listed"))}
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
        if error is None:
            if not currency:
                try:
                    currency = get_language(language).default_currency
                except KeyError:
                    currency = "INR"
            if currency not in _CURRENCIES:
                error = "unknown currency"
                error_field = "currency"
        try:
            upi_id = validate_upi_id(form.get("upi_id"))
        except ValueError as exc:
            if error is None:
                error = str(exc)
                error_field = "upi_id"
            upi_id = None
        if error is not None:
            return _new_shop_page(request, error=error,
                                  error_field=error_field, values=values,
                                  status_code=422)
        # The "Show my shop" box is on by default; the form always sends
        # listed=0 plus listed=1 when ticked, so read every value. A post
        # without the field (old clients) stays listed by default.
        picked = form.getlist("listed")
        listed = True if not picked else any(
            str(value or "").strip().lower() in ("1", "on", "true", "yes")
            for value in picked)
        shop_id, _, token = db.create_shop(
            conn,
            name=name,
            phone=phone,
            area=area.strip(),
            language=language,
            currency=currency,
            shop_type=shop_type,
            listed=listed,
        )
        if upi_id:
            conn.execute("UPDATE shops SET upi_id = ? WHERE id = ?",
                         (upi_id, shop_id))
            conn.commit()
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.get("/e/{token}")
    def seller_home(request: Request, token: str, conn: Conn):
        shop, role, helper_name = resolve_or_404(conn, token)
        if shop is None:
            raise HTTPException(404, "unknown shop token")
        is_staff = role == "staff"
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
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
            total, _left_out = stock_value(latest_items)
            stock = {"total": total,
                     "left_out": stock_left_out_display(latest_items),
                     "version_id": versions[0]["id"],
                     "counted": any(
                         ((item.stock_qty is not None
                           and item.stock_source)
                          or (item.qty is not None and item.qty_unit))
                         for item in latest_items
                         if not item.sold_out)}
            for item in latest_items:
                stock_line = None
                if item.stock_qty is not None and item.stock_source:
                    stock_line = t("dash.stock_line", qty=item.stock_qty,
                                   source=item.stock_source)
                items.append({
                    "id": item.id,
                    "name_local": item.name_local,
                    "name_en": item.name_en,
                    "tile": first_grapheme(item.name_local or
                                           item.name_en),
                    "tile_var": tile_variety(item.variety),
                    "variety": item.variety,
                    "photo_url": _photo_url(item.photo),
                    "photo_cutout": is_cutout_photo(item.photo),
                    "sold_out": item.sold_out,
                    "stock_line": stock_line,
                    "lines": [{"price": str(line.price),
                               "per": _per_text(line.per_amount, line.unit)}
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
        has_bills = any(row["kind"] == "bill"
                        for row in db.list_quotes(conn, shop["id"]))
        gs_prices_done = any(session["kind"] in (
            "video", "live", "board", "voice_update") for session in sessions)
        from app import purchases as pur

        today = datetime.now(UTC).astimezone(IST).date().isoformat()
        spent = pur.spent_on(conn, shop["id"], today)
        currency = shop["currency"] or "INR"
        buy_map: dict[str, object] = {}
        for purchase in pur.list_purchases(conn, shop["id"], today):
            key = purchase.name_en.strip().lower()
            if key and key not in buy_map:
                buy_map[key] = purchase
        for entry, item in zip(items, db.version_items(conn, versions[0]["id"])
                               if versions else []):
            margin_chip = ""
            purchase = buy_map.get(item.name_en.strip().lower())
            if purchase is not None and item.price_lines:
                buy_per, buy_unit = pur.cost_per_unit(
                    purchase.qty, purchase.unit, purchase.total_cost)
                line = next((line for line in item.price_lines
                             if line.price is not None and line.per_amount
                             and line.unit), None)
                if buy_per is not None and line is not None:
                    sell_per = (line.price / line.per_amount).quantize(
                        Decimal("0.01"))
                    margin_chip = pur.margin_text(
                        buy_per, buy_unit, sell_per, line.unit,
                        currency=currency, lang=ui_lang)
            entry["margin_chip"] = margin_chip
        seller_url = f"{app.state.settings.public_base_url}/e/{token}"
        try:
            shop_native = get_language(shop["language"]).native_name
        except KeyError:
            shop_native = shop["language"]
        home = _home_extras(conn, shop, ui_lang)
        wa_url, wa_text = _price_share(
            conn, shop, ui_lang, app.state.settings.public_base_url)
        from app.dayclose import day_tiles

        now_local = datetime.now(UTC).astimezone(IST)
        published_today = False
        live_since = ""
        if published_id is not None:
            when = db.version_time(conn, published_id)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            local_when = when.astimezone(IST)
            published_today = local_when.date().isoformat() == today
            live_since = local_when.strftime("%H:%M")
        tiles = day_tiles(conn, shop, today)
        from app.market.hours import has_hours as _has_hours

        try:
            _hours_raw = shop["hours_json"]
        except (KeyError, IndexError, TypeError):
            _hours_raw = None
        credit_total, credit_count = db.credit_total_to_collect(conn, shop)
        can_credit = (not is_staff) or db.helper_can_credit(conn, token)
        closed_raw = db.day_closed_at(conn, shop["id"], today)
        closed_at = ""
        if closed_raw:
            try:
                moment = datetime.fromisoformat(closed_raw)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=UTC)
                closed_at = moment.astimezone(IST).strftime("%H:%M")
            except ValueError:
                closed_at = ""
        return templates.TemplateResponse(
            request,
            "seller.html",
            {"shop": shop, "sessions": sessions, "versions": versions,
             "notice": _voice_notice(ui_lang), "stock": stock, "token": token,
             "items": items, "live": live, "live_count": live_count,
             "published_today": published_today, "live_since": live_since,
             "wa_url": wa_url, "wa_text": wa_text,
             "shop_url": f"/s/{shop['slug']}",
             "max_upload_bytes": app.state.settings.max_upload_bytes,
             "bills": bills, "shop_lang": shop["language"],
             "shop_native": shop_native,
             "languages": LANGUAGES,
             "spent_today": spent, "ui_lang": ui_lang,
             "is_staff": is_staff, "helper_name": helper_name,
             "seller_url": seller_url,
             "self_wa_url": (link_self_whatsapp_url(shop, seller_url)
                             if not is_staff else None),
             "today_label": home["today_label"],
             "greet_key": home["greet_key"],
             "greet_word_key": home["greet_word_key"],
             "taps": home["taps"], "taps_total": home["taps_total"],
             "taps_first": home["taps_first"],
             "count_new": home["count_new"],
             "count_packing": home["count_packing"],
             "count_ready": home["count_ready"],
             "unpaid_count": home["unpaid_count"],
             "open_orders": home["open_orders"],
             "week": home["week"],
             "close_preview": {
                 "sales": format_money(tiles["sales"], currency),
                 "bills": tiles["bills_count"],
                 "cash": format_money(tiles["cash"], currency),
                 "upi": format_money(tiles["upi"], currency),
             },
             "close_is_dark": now_local.hour >= 18,
             "closed_at": closed_at,
             "first_run": published_id is None and not is_staff,
             "has_bills": has_bills, "gs_prices_done": gs_prices_done,
             "credit_total": format_money(credit_total, currency),
             "credit_count": credit_count,
             "renamed": request.query_params.get("renamed") == "1",
             "can_credit": can_credit,
             "show_hours_nudge": (not is_staff
                                  and not _has_hours(_hours_raw))},
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
    def version_board(request: Request, token: str, version_id: int, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        shop, items = _version_items(conn, token, version_id)
        ui_lang = get_ui_lang(request, shop)
        pdf = price_board_pdf(
            shop, items, datetime.now(IST),
            f"{app.state.settings.public_base_url}/s/{shop['slug']}",
            lang=ui_lang)
        return Response(pdf, media_type="application/pdf")

    @app.get("/e/{token}/tags.pdf")
    def shop_tags(request: Request, token: str, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        if version_id is None:
            raise HTTPException(404, "no published price list yet")
        items = db.version_items(conn, version_id)
        pdf = price_tags_pdf(
            shop, items, datetime.now(IST),
            f"{app.state.settings.public_base_url}/s/{shop['slug']}",
            lang=ui_lang)
        return Response(pdf, media_type="application/pdf")

    @app.get("/e/{token}/v/{version_id}/export.csv")
    def version_csv(request: Request, token: str, version_id: int, conn: Conn):
        _shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        _, items = _version_items(conn, token, version_id)
        return Response(generic_csv(items, datetime.now(IST)),
                        media_type="text/csv")

    @app.get("/e/{token}/link-card.pdf")
    def link_card(request: Request, token: str, conn: Conn):
        """Printable "Keep this safe" card with the seller link QR."""
        from app.outputs.link_card import link_card_pdf

        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        seller_url = f"{app.state.settings.public_base_url}/e/{token}"
        pdf = link_card_pdf(shop, seller_url, lang=ui_lang)
        return Response(pdf, media_type="application/pdf")

    @app.get("/try")
    def try_judge(conn: Conn):
        _, _, token = db.create_shop(
            conn, name="Judge Test Shop", phone="+910000000000",
            area="Judge trial", language="en", currency="INR",
            shop_type="vegetable", is_judge=True, listed=False)
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/upload")
    def upload(request: Request, token: str, video: UploadFile, conn: Conn,
               speak_lang: str = Form("")):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        db.purge_expired(conn, data_dir, datetime.now(UTC))
        limiter = request.app.state.limiter
        ip = client_ip(request)
        if not limiter.allow(ip, datetime.now(UTC)):
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
        payload = video.file.read()
        limit = app.state.settings.max_upload_bytes
        if len(payload) > limit:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.file_big_title"),
                 "message": _too_big_message(len(payload), limit),
                 "token": token, "ui_lang": ui_lang},
                status_code=413)
        session_id = db.create_session(conn, shop["id"], "video")
        if speak_lang in _LANGUAGES:
            db.set_session_speak_lang(conn, session_id, speak_lang)
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(video.filename or "clip.mp4").name
        saved = uploads / f"{session_id}_{safe_name}"
        saved.write_bytes(payload)
        jobs.submit(_run_session_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    @app.post("/e/{token}/board")
    def board_upload(request: Request, token: str, photo: UploadFile,
                     conn: Conn):
        import io
        import secrets

        from PIL import Image

        from app.pipeline.board import run_board_job, write_board_meta

        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
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
        payload = photo.file.read()
        if not payload:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.no_photo_title"),
                 "message": "Choose a photo of your price board first.",
                 "token": token, "ui_lang": ui_lang},
                status_code=400)
        if len(payload) > 10 * 1024 * 1024:
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.photo_big_title"),
                 "message": "That photo is too big. Choose one under 10 MB.",
                 "token": token, "ui_lang": ui_lang},
                status_code=400)
        try:
            with Image.open(io.BytesIO(payload)) as img:
                img.load()
                photo_format = (img.format or "").lower()
        except Exception:  # noqa: BLE001 - any unreadable file is a 400
            return templates.TemplateResponse(
                request, "error.html",
                {"title": t("error.not_photo_title"),
                 "message": "We could not open that file as a photo.",
                 "token": token, "ui_lang": ui_lang},
                status_code=400)
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png",
               "webp": ".webp"}.get(photo_format, ".jpg")
        session_id = db.create_session(conn, shop["id"], "board")
        photo_dir = data_dir / "photos"
        photo_dir.mkdir(parents=True, exist_ok=True)
        saved = photo_dir / f"b{session_id}_{secrets.token_hex(4)}{ext}"
        saved.write_bytes(payload)
        write_board_meta(data_dir, session_id, {"image": str(saved)})
        jobs.submit(run_board_job, settings, session_id, str(saved))
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    def _transcript_snippet(session_id: int) -> str:
        """First 120 chars of a session transcript, else "" (never raises)."""
        try:
            saved = json.loads((data_dir / "sessions" / str(session_id)
                                / "transcript.json").read_text())
            return str(saved.get("text", ""))[:120]
        except (OSError, ValueError):
            return ""

    def _language_check_page(request, conn, token, shop, session,
                             ui_lang):
        """Task 53: ask which language was spoken after a script mismatch."""
        t = t_for(ui_lang)
        quote = _transcript_snippet(session["id"])
        script = session["stage_detail"] or "other"
        try:
            set_name = get_language(
                spoken_language(conn, session["id"])).native_name
        except KeyError:
            set_name = "English"
        if script == "other":
            heard = t("langcheck.heard_other", language=set_name)
        else:
            heard = t("langcheck.heard", script=script, language=set_name)
        order = [shop["language"], "ta", "hi", "kn", "te", "ml", "bn", "en"]
        chips = []
        seen = set()
        for code in order:
            if code in seen:
                continue
            try:
                lang = get_language(code)
            except KeyError:
                continue
            seen.add(code)
            chips.append({"code": code, "native": lang.native_name})
        rest = [{"code": lang.code, "native": lang.native_name}
                for lang in LANGUAGES if lang.code not in seen]
        return templates.TemplateResponse(request, "language_check.html", {
            "shop": shop, "session": session, "token": token,
            "ui_lang": ui_lang, "shop_lang": shop["language"],
            "heard": heard, "quote": quote, "chips": chips, "rest": rest,
        })

    @app.get("/e/{token}/s/{session_id}")
    def session_page(request: Request, token: str, session_id: int, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        session = _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        if session["stage"] == "language_check":
            return _language_check_page(request, conn, token, shop,
                                        session, ui_lang)
        if session["kind"] == "photo" and session["status"] == "review":
            meta = read_photo_meta(data_dir, session_id)
            if meta.get("check_id") is not None:
                return RedirectResponse(
                    f"/e/{token}/photos/{meta['check_id']}", status_code=303)
        if session["kind"] == "purchase" and session["status"] == "review":
            return RedirectResponse(f"/e/{token}/purchases/{session_id}",
                                    status_code=303)
        progress, friendly = _translated_progress(session, ui_lang)
        from app.web.live import STOPPED_MESSAGE

        stopped = (session["message"] == STOPPED_MESSAGE
                   if session["message"] else False)
        try:
            shop_native = get_language(shop["language"]).native_name
        except KeyError:
            shop_native = shop["language"]
        context = {"shop": shop, "session": session, "token": token,
                   "progress": progress, "shop_lang": shop["language"],
                   "shop_native": shop_native,
                   "friendly": friendly, "ui_lang": ui_lang,
                   "stopped_note": STOPPED_MESSAGE if stopped else None}
        if session["status"] == "approved":
            wa_url, wa_text = _price_share(
                conn, shop, ui_lang, app.state.settings.public_base_url)
            context["wa_url"] = wa_url
            context["wa_text"] = wa_text
        if session["status"] == "review" and session["kind"] in (
                "video", "live", "board"):
            items = db.load_drafts(conn, session_id)
            base_id = db.ensure_session_base(conn, session_id)
            carried = []
            if base_id is not None:
                try:
                    base_items = db.version_items(conn, base_id)
                except Exception:  # noqa: BLE001 - unreadable base means no carried
                    base_items = []
                review_lang = shop["language"] or "en"
                for base in db.carried_from_base(items, base_items):
                    carried.append({
                        "id": base.id,
                        "name_local": base.name_local,
                        "name_en": base.name_en,
                        "variety": base.variety,
                        "title_local": local_title(
                            base.name_local, base.variety, base.name_en,
                            review_lang),
                        "title_en": english_title(base.name_en,
                                                  base.variety),
                        "photo_url": _photo_url(base.photo),
                        "photo_cutout": is_cutout_photo(base.photo),
                        "sold_out": base.sold_out,
                        "price_summary": _price_summary(
                            base, shop["currency"] or "INR", ui_lang),
                    })
            context["carried"] = carried
            context["base_version_id"] = base_id
            page_t = t_for(ui_lang)
            kind_labels = {"cutout": page_t("review.cutout"),
                           "original": page_t("review.original")}
            cards = []
            for index, item in enumerate(items):
                proof = {
                    "quote": item.proof.quote,
                    "turn_ids": item.proof.turn_ids,
                    "start_ms": item.proof.start_ms,
                    "end_ms": item.proof.end_ms,
                    "frame": item.proof.frame,
                    "audio_clip": item.proof.audio_clip,
                    "source": item.proof.source,
                }
                is_board = item.proof.source == "board_photo"
                candidates = []
                for path in item.photo_candidates or []:
                    url = _photo_url(path)
                    if not url:
                        continue
                    kind = photo_kind(path)
                    candidates.append({
                        "url": url,
                        "label": kind_labels.get(kind),
                        "cutout": kind == "cutout",
                    })
                cards.append(
                    {
                        "index": index,
                        "item": item,
                        "title_local": local_title(
                            item.name_local, item.variety, item.name_en,
                            shop["language"] or "en"),
                        "title_en": english_title(item.name_en,
                                                  item.variety),
                        "photo_url": _photo_url(item.photo),
                        "photo_cutout": is_cutout_photo(item.photo),
                        "candidates": candidates,
                        "board_thumb_url": (
                            _photo_url(item.proof.frame) if is_board else None
                        ),
                        "is_board": is_board,
                        "clip_url": (
                            f"/e/{token}/s/{session_id}/clip/{index}"
                            if item.proof.audio_clip
                            else None
                        ),
                        "proof_json": json.dumps(proof),
                        "needs_decision": _needs_decision(item),
                        "own_name": db.uses_chosen_name(conn, shop["id"],
                                                        item),
                        "board_only": _board_only(item),
                        "quote_html": _highlight_quote(item.proof.quote),
                        "price_summary": _price_summary(
                            item, shop["currency"] or "INR", ui_lang),
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
    def session_status(request: Request, token: str, session_id: int,
                       conn: Conn):
        shop = _owner_or_403_exc(conn, token)
        session = _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        progress, friendly = _translated_progress(session, ui_lang)
        needs_action = session["stage"] == "language_check"
        return JSONResponse({
            "status": session["status"], "message": session["message"],
            "stage": progress["stage"], "step": progress["step"],
            "steps": progress["steps"], "detail": progress["detail"],
            "elapsed_s": progress["elapsed_s"],
            "friendly": friendly,
            # Task 131: the composer stops polling on needs_action and
            # shows the question with this transcript snippet inline.
            "needs_action": needs_action,
            "quote": (_transcript_snippet(session_id)
                      if needs_action else ""),
            "language_url": (f"/e/{token}/s/{session_id}/language"
                             if needs_action else None),
        })

    @app.get("/e/{token}/ai")
    def ai_calls_page(request: Request, token: str, conn: Conn,
                      show: str | None = None, session: str | None = None):
        """Owner-only log of every Meta model call for this shop."""
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        kind = show if show in _AI_KINDS else "all"
        session_id = _ai_session_param(session)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        stats = ledger.today_stats(shop["id"])
        rows = ledger.rows_for_shop(
            shop["id"], session_id=session_id,
            kind=kind if kind != "all" else None)
        views = [_ai_row_view(row, t) for row in rows]
        avg = stats["avg_latency_ms"]
        return templates.TemplateResponse(request, "ai.html", {
            "shop": shop, "token": token, "ui_lang": ui_lang,
            "shop_lang": shop["language"],
            "stats": stats, "cost_text": f"${stats['cost_usd']:.4f}",
            "avg_text": f"{avg} ms" if avg is not None else "—",
            "groups": _ai_groups(views),
            "max_id": max((view["id"] for view in views), default=0),
            "kind": kind, "session_id": session_id,
            "processing": _ai_processing(conn, shop["id"], session_id),
            "honesty_url": _AI_HONESTY_URL,
        })

    @app.get("/e/{token}/ai.json")
    def ai_calls_json(request: Request, token: str, conn: Conn,
                      since_id: int = 0, show: str | None = None,
                      session: str | None = None):
        """Polling endpoint for the AI calls page; same owner auth."""
        shop = _owner_or_403_exc(conn, token)
        ui_lang = get_ui_lang(request, shop)
        t = t_for(ui_lang)
        kind = show if show in _AI_KINDS else "all"
        session_id = _ai_session_param(session)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        stats = ledger.today_stats(shop["id"])
        rows = ledger.rows_for_shop(
            shop["id"], session_id=session_id, since_id=max(since_id, 0),
            kind=kind if kind != "all" else None)
        views = [_ai_row_view(row, t) for row in rows]
        avg = stats["avg_latency_ms"]
        latest = max([since_id] + [view["id"] for view in views])
        return JSONResponse({
            "rows": views, "max_id": latest, "stats": stats,
            "cost_text": f"${stats['cost_usd']:.4f}",
            "avg_text": f"{avg} ms" if avg is not None else "—",
            "processing": _ai_processing(conn, shop["id"], session_id),
        })

    @app.get("/e/{token}/s/{session_id}/clip/{index}")
    def session_clip(token: str, session_id: int, index: int, conn: Conn):
        shop = _owner_or_403_exc(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
        items = db.load_drafts(conn, session_id)
        if not 0 <= index < len(items) or not items[index].proof.audio_clip:
            raise HTTPException(404, "no such clip")
        return FileResponse(items[index].proof.audio_clip, media_type="audio/mp4")

    @app.post("/e/{token}/s/{session_id}/photo/{index}")
    def pick_candidate(token: str, session_id: int, index: int, body: dict,
                       conn: Conn):
        """Make candidate ``index`` the draft photo. Index only, never a path."""
        shop = _owner_or_403_exc(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
        items = db.load_drafts(conn, session_id)
        if not 0 <= index < len(items):
            raise HTTPException(404, "no such item")
        candidates = items[index].photo_candidates or []
        want = body.get("index")
        if (not isinstance(want, int) or isinstance(want, bool)
                or not 0 <= want < len(candidates)):
            raise HTTPException(400, "unknown photo choice")
        items[index].photo = candidates[want]
        db.save_drafts(conn, session_id, items)
        return JSONResponse({"photo_url": _photo_url(items[index].photo),
                             "cutout": is_cutout_photo(items[index].photo)})

    @app.post("/e/{token}/s/{session_id}/photo/{index}/upload")
    async def upload_draft_photo(request: Request, token: str, session_id: int,
                                 index: int, photo: UploadFile, conn: Conn):
        """Seller retake for a draft: verified, face-blurred, EXIF-free 4:3."""
        shop = _owner_or_403_exc(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
        items = db.load_drafts(conn, session_id)
        if not 0 <= index < len(items):
            raise HTTPException(404, "no such item")
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        ledger.bind(shop_id=shop["id"], session_id=session_id)
        try:
            out = save_retake(
                await photo.read(),
                data_dir / "photos" / f"s{session_id}_{index}_retake.jpg",
                ledger=ledger, settings=app.state.settings)
        except BadPhotoUpload as exc:
            raise HTTPException(400, str(exc))
        except CostCapExceeded:
            raise HTTPException(503, BUDGET_EXHAUSTED_MESSAGE)
        except SamError:
            raise HTTPException(502, "The photo check failed. Please try again.")
        items[index].photo = str(out)
        db.save_drafts(conn, session_id, items)
        return JSONResponse({"photo_url": _photo_url(items[index].photo),
                             "cutout": False})

    @app.post("/e/{token}/item/{item_id}/photo")
    async def upload_item_photo(request: Request, token: str, item_id: int,
                                photo: UploadFile, conn: Conn):
        """Change a published item's photo in place: same prices, same version."""
        shop = _owner_or_403_exc(conn, token)
        row = conn.execute(
            "SELECT items.id AS id FROM items"
            " JOIN versions ON versions.id = items.version_id"
            " WHERE items.id = ? AND versions.shop_id = ?",
            (item_id, shop["id"])).fetchone()
        if row is None:
            raise HTTPException(404, "no such item")
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        ledger.bind(shop_id=shop["id"])
        try:
            out = save_retake(
                await photo.read(),
                data_dir / "photos" / f"item_{item_id}.jpg",
                ledger=ledger, settings=app.state.settings)
        except BadPhotoUpload as exc:
            raise HTTPException(400, str(exc))
        except CostCapExceeded:
            raise HTTPException(503, BUDGET_EXHAUSTED_MESSAGE)
        except SamError:
            raise HTTPException(502, "The photo check failed. Please try again.")
        db.set_item_photo(conn, item_id, str(out))
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/e/{token}", status_code=303)
        return JSONResponse({"photo_url": _photo_url(str(out)),
                             "cutout": False})

    @app.post("/e/{token}/s/{session_id}/approve")
    def approve(request: Request, token: str, session_id: int, body: dict,
                conn: Conn):
        shop = _owner_or_403_exc(conn, token)
        _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        raw_items = body.get("items", [])
        confirmed = set(body.get("confirmed", []))
        carried_raw = body.get("carried", None)
        carried_ids = None
        if carried_raw is not None:
            carried_ids = []
            for raw_id in carried_raw or []:
                try:
                    carried_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
        previous = db.last_prices(conn, shop["id"])
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        ledger.bind(shop_id=shop["id"], session_id=session_id)
        try:
            saved_drafts = db.load_drafts(conn, session_id)
        except Exception:  # noqa: BLE001 - missing drafts keep variety empty
            saved_drafts = []
        from app.pipeline.namecheck import (
            NameValidationError,
            validate_names,
        )

        items = []
        for index, raw in enumerate(raw_items):
            stored = saved_drafts[index] if index < len(saved_drafts) else None
            item = _draft_from_client(raw, stored)
            if stored is not None and (
                    item.name_local != stored.name_local
                    or item.name_en != stored.name_en
                    or (item.variety or None) != (stored.variety or None)):
                try:
                    local, english, variety = validate_names(
                        item.name_local, item.name_en, item.variety,
                        shop["language"])
                except NameValidationError as exc:
                    raise HTTPException(
                        400, _rename_error(ui_lang, exc))
                item.name_local, item.name_en = local, english
                item.variety = variety or stored.variety
            if item.proof.source == "board_photo":
                kept = [
                    flag for flag in check_item(
                        item, previous,
                        language=spoken_language(conn, session_id),
                        ledger=ledger, settings=app.state.settings)
                    if flag.code not in ("NOT_HEARD", "NO_PRICE",
                                          "UNIT_MISSING", "NUMBER_CHECK",
                                          "UNCLEAR_NUMBER")]
                item.flags = kept + _board_flags(item)
            else:
                item.flags = check_item(
                    item, previous,
                    language=spoken_language(conn, session_id),
                    ledger=ledger, settings=app.state.settings)
            item.confirmed = index in confirmed
            items.append(item)
        try:
            version_id = db.approve(conn, session_id, items,
                                    carried_ids=carried_ids)
        except db.ApprovalError as exc:
            if exc.needs_confirm:
                return JSONResponse(
                    status_code=400,
                    content={"detail": str(exc),
                             "needs_confirm": exc.needs_confirm},
                )
            raise HTTPException(400, str(exc))
        try:
            new_items = db.version_items(conn, version_id)
        except Exception:  # noqa: BLE001 - audit is best effort
            new_items = []
        for index, item in enumerate(items):
            stored = saved_drafts[index] if index < len(saved_drafts) else None
            if stored is None:
                continue
            if (item.name_local == stored.name_local
                    and item.name_en == stored.name_en
                    and (item.variety or None) == (stored.variety or None)):
                continue
            db.save_chosen_name(conn, shop["id"], db.match_key_of(item),
                                item.variety, item.name_local, item.name_en)
            fresh_id = (new_items[index].id
                        if index < len(new_items) else None)
            db.log_name_change(
                conn, shop["id"], fresh_id,
                (stored.name_local, stored.name_en, stored.variety),
                (item.name_local, item.name_en, item.variety))
        db.set_published(conn, version_id, True)
        return RedirectResponse(f"/e/{token}/s/{session_id}/live",
                                status_code=303)

    @app.get("/e/{token}/s/{session_id}/live")
    def prices_live(request: Request, token: str, session_id: int, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        _session_of_shop(conn, shop["id"], session_id)
        ui_lang = get_ui_lang(request, shop)
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        if version_id is None:
            return RedirectResponse(f"/e/{token}", status_code=303)
        wa_url, _wa_text = _price_share(
            conn, shop, ui_lang, app.state.settings.public_base_url)
        shop_path = f"/s/{shop['slug']}"
        return templates.TemplateResponse(request, "prices_live.html", {
            "shop": shop, "token": token, "session_id": session_id,
            "version_id": version_id, "wa_url": wa_url,
            "shop_path": shop_path,
            "shop_url": f"{app.state.settings.public_base_url}{shop_path}",
            "qr_url": f"{shop_path}/qr.png",
            "ui_lang": ui_lang})

    @app.post("/e/{token}/s/{session_id}/retry")
    def retry_session(request: Request, token: str, session_id: int,
                      conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        session = _session_of_shop(conn, shop["id"], session_id)
        if session["kind"] == "photo":
            meta = read_photo_meta(data_dir, session_id)
            if not meta.get("image"):
                raise HTTPException(400, "this photo is gone; scan it again")
            db.set_session_status(conn, session_id, "processing",
                                  "Trying again...")
            jobs.submit(run_photo_job, settings, session_id,
                        str(meta["image"]))
            return RedirectResponse(f"/e/{token}/s/{session_id}",
                                    status_code=303)
        if session["kind"] == "board":
            from app.pipeline.board import read_board_meta, run_board_job

            meta = read_board_meta(data_dir, session_id)
            if not meta.get("image"):
                raise HTTPException(400, "this photo is gone; take it again")
            db.set_session_status(conn, session_id, "processing",
                                  "Trying again...")
            jobs.submit(run_board_job, settings, session_id,
                        str(meta["image"]))
            return RedirectResponse(f"/e/{token}/s/{session_id}",
                                    status_code=303)
        if session["status"] not in ("failed", "review"):
            raise HTTPException(
                400, "reprocess is only for failed or review sessions")
        db.set_session_status(conn, session_id, "processing", "Trying again...")
        jobs.submit(_retry_video_job, settings, session_id)
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    @app.post("/e/{token}/s/{session_id}/language")
    def choose_language(request: Request, token: str, session_id: int,
                        conn: Conn, speak_lang: str = Form(...)):
        """Task 53: seller's spoken-language answer; re-runs transcription."""
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        session = _session_of_shop(conn, shop["id"], session_id)
        if session["stage"] != "language_check":
            return RedirectResponse(f"/e/{token}/s/{session_id}",
                                    status_code=303)
        if speak_lang not in _LANGUAGES:
            raise HTTPException(422, "unknown language")
        db.set_session_status(conn, session_id, "processing",
                              "Trying your language...")
        jobs.submit(_retry_language_job, settings, session_id, speak_lang)
        if "application/json" in request.headers.get("accept", ""):
            # Task 131: the composer's inline language buttons resume
            # polling off this answer instead of following a redirect.
            return JSONResponse({"status": "processing",
                                 "stage": "listening",
                                 "speak_lang": speak_lang})
        return RedirectResponse(f"/e/{token}/s/{session_id}", status_code=303)

    def _update_cards(token: str, changes, current_map: dict,
                      currency: str = "INR", lang: str = "en") -> list[dict]:
        t = t_for(lang)
        cards = []
        for index, change in enumerate(changes):
            current = current_map.get(change.name_en)
            if current is not None and current.price_lines:
                summary = ", ".join(
                    t("upd.price_line", price=format_money(line.price, currency),
                      amount=line.per_amount, unit=line.unit)
                    for line in current.price_lines)
            else:
                summary = ""
            cards.append({
                "index": index,
                "name_en": change.name_en,
                "name_local": CANONICAL_NAMES.get(change.name_en, change.name_en),
                "action": change.action,
                "action_label": _action_label(change.action, lang),
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
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        version_id = db.latest_version(conn, shop["id"])
        items = db.version_items(conn, version_id) if version_id else []
        return templates.TemplateResponse(request, "update.html", {
            "shop": shop, "token": token, "mode": "record", "items": items,
            "notice": _voice_notice(ui_lang), "error": None,
            "hint": (hint or "").strip(),
            "shop_lang": shop["language"], "ui_lang": ui_lang,
            "languages": LANGUAGES,
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
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
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
                "notice": _voice_notice(ui_lang),
                "error": _too_big_message(len(payload), limit),
                "shop_lang": shop["language"], "ui_lang": ui_lang,
                "languages": LANGUAGES,
                "max_upload_bytes": limit})
        session_id = db.create_session(conn, shop["id"], "voice_update")
        speak_lang = str(form.get("speak_lang") or "")
        if speak_lang in _LANGUAGES:
            db.set_session_speak_lang(conn, session_id, speak_lang)
        session_dir = data_dir / "sessions" / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(getattr(upload, "filename", "") or "update.webm").name
        saved = uploads / f"{session_id}_{safe_name}"
        saved.write_bytes(payload)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        ledger.bind(shop_id=shop["id"], session_id=session_id)
        try:
            db.set_session_status(conn, session_id, "processing",
                                  "Listening to the update...")
            db.set_stage(conn, session_id, "listening")
            wav = extract_audio(saved, session_dir / "audio.wav")
            transcript = transcribe_wav(
                wav, keywords=keywords_for(shop["language"]), ledger=ledger,
                settings=app.state.settings,
                languages=shop_bias(shop["language"]))
            db.set_stage(conn, session_id, "items")
            current = db.version_items(conn, base_version_id)
            changes = parse_update(transcript, current,
                                   ledger=ledger, settings=app.state.settings,
                                   language=shop["language"])
            db.set_stage(conn, session_id, "checking")
        except (TranscribeError, SparkError, CostCapExceeded,
                subprocess.CalledProcessError, OSError) as exc:
            message = friendly_error_message(exc, media="recording")
            db.set_session_status(conn, session_id, "failed", message)
            items = db.version_items(conn, base_version_id)
            return templates.TemplateResponse(request, "update.html", {
                "shop": shop, "token": token, "mode": "record", "items": items,
                "notice": _voice_notice(ui_lang), "error": message,
                "shop_lang": shop["language"], "ui_lang": ui_lang,
                "languages": LANGUAGES,
                "max_upload_bytes": limit})
        finally:
            saved.unlink(missing_ok=True)
        _update_path(data_dir, session_id).write_text(json.dumps({
            "base_version_id": base_version_id,
            "changes": [change_to_dict(change) for change in changes]}))
        db.set_stage(conn, session_id, "ready")
        db.set_session_status(conn, session_id, "review",
                              f"{len(changes)} changes heard")
        current_map = _current_map(current)
        return templates.TemplateResponse(request, "update.html", {
            "shop": shop, "token": token, "mode": "confirm",
            "session_id": session_id,
            "cards": _update_cards(token, changes, current_map,
                                   shop["currency"] or "INR", ui_lang),
            "shop_lang": shop["language"], "ui_lang": ui_lang,
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
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
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
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        ledger.bind(shop_id=shop["id"], session_id=session_id)
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            raw_items = body.get("items", [])
            confirmed = set(body.get("confirmed", []))
            if len(raw_items) != len(changes):
                raise HTTPException(400, "confirm form is out of date; record again")
            current = db.version_items(conn, base_version_id)
            current_map = _current_map(current)
            previous = {}
            for _item in current:
                if _item.price_lines:
                    previous.setdefault(db.match_key_of(_item),
                                        _item.price_lines[0])
                    previous.setdefault(_item.name_en,
                                        _item.price_lines[0])
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
                change.flags = flags_for_change(
                    change, current_map, previous, language=shop["language"],
                    ledger=ledger, settings=app.state.settings)
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
            current_map = _current_map(current)
            previous = {}
            for _item in current:
                if _item.price_lines:
                    previous.setdefault(db.match_key_of(_item),
                                        _item.price_lines[0])
                    previous.setdefault(_item.name_en,
                                        _item.price_lines[0])
            for index, change in enumerate(changes):
                change.flags = flags_for_change(
                    change, current_map, previous, language=shop["language"],
                    ledger=ledger, settings=app.state.settings)
                if (any(flag.blocking for flag in change.flags)
                        and index not in confirmed):
                    raise HTTPException(
                        400, f"unconfirmed change on {change.name_en}")
        new_version_id = apply_changes(conn, shop["id"], base_version_id, changes)
        db.set_published(conn, new_version_id, True)
        sold_names = {change.name_en for change in changes
                      if change.action == "sold_out"}
        if sold_names:
            for item in db.version_items(conn, new_version_id):
                if item.sold_out and db.match_key_of(item) in sold_names:
                    db.flag_sold_out_in_open_orders(conn, shop["id"],
                                                    item.name_en,
                                                    item.variety,
                                                    db.match_key_of(item))
        db.set_session_status(conn, session_id, "approved",
                              f"{len(changes)} changes published")
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/v/{version_id}/publish")
    def publish_version(request: Request, token: str, version_id: int,
                        conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        _version_of_shop(conn, shop["id"], version_id)
        db.set_published(conn, version_id, True)
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/v/{version_id}/unpublish")
    def unpublish_version(request: Request, token: str, version_id: int,
                          conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        _version_of_shop(conn, shop["id"], version_id)
        db.set_published(conn, version_id, False)
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.post("/e/{token}/item/{item_id}/name")
    async def rename_live_item(request: Request, token: str, item_id: int,
                               conn: Conn):
        """Rename one live-list item in place: names only, never prices.

        Owner only, like price edits. Works as a plain form post (303
        back with a "Name changed" notice) and as JSON for the sheet.
        """
        from app.pipeline.namecheck import (
            NameValidationError,
            validate_names,
        )

        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        ui_lang = get_ui_lang(request, shop)
        row = conn.execute(
            "SELECT items.id, items.name_local, items.name_en,"
            " items.variety, items.match_key, versions.shop_id FROM items"
            " JOIN versions ON versions.id = items.version_id"
            " WHERE items.id = ?", (item_id,)).fetchone()
        if row is None or row["shop_id"] != shop["id"]:
            raise HTTPException(404, "unknown item")
        if request.headers.get("content-type", "").startswith(
                "application/json"):
            body = await request.json()
            raw_local = body.get("name_local", "")
            raw_en = body.get("name_en", "")
            raw_variety = body.get("variety", "")
        else:
            form = await request.form()
            raw_local = form.get("name_local", "")
            raw_en = form.get("name_en", "")
            raw_variety = form.get("variety", "")
        wants_json = "application/json" in request.headers.get("accept", "")
        try:
            local, english, variety = validate_names(
                raw_local, raw_en, raw_variety or None, shop["language"])
        except NameValidationError as exc:
            message = _rename_error(ui_lang, exc)
            if wants_json:
                return JSONResponse({"detail": message}, status_code=400)
            raise HTTPException(400, message)
        old = db.rename_item(conn, item_id, local, english, variety)
        try:
            match_key = row["match_key"]
        except (KeyError, IndexError, TypeError):
            match_key = None
        db.save_chosen_name(conn, shop["id"], match_key or row["name_en"],
                            variety, local, english)
        db.log_name_change(conn, shop["id"], item_id, old,
                           (local, english, variety))
        if wants_json:
            return JSONResponse({
                "ok": True, "name_local": local, "name_en": english,
                "variety": variety,
                "notice": t_for(ui_lang)("rename.done"),
            })
        return RedirectResponse(f"/e/{token}?renamed=1", status_code=303)

    @app.post("/e/{token}/item/{item_id}/soldout")
    def toggle_soldout(request: Request, token: str, item_id: int, conn: Conn):
        shop, denied = _owner_page(request, conn, token)
        if denied is not None:
            return denied
        row = conn.execute(
            "SELECT items.sold_out, items.name_en, items.variety,"
            " items.match_key, versions.shop_id FROM items"
            " JOIN versions ON versions.id = items.version_id"
            " WHERE items.id = ?", (item_id,)).fetchone()
        if row is None or row["shop_id"] != shop["id"]:
            raise HTTPException(404, "unknown item")
        now_out = not bool(row["sold_out"])
        db.set_sold_out(conn, item_id, now_out)
        if now_out:
            try:
                match_key = row["match_key"]
            except (KeyError, IndexError, TypeError):
                match_key = None
            db.flag_sold_out_in_open_orders(conn, shop["id"], row["name_en"],
                                            row["variety"],
                                            match_key or row["name_en"])
        return RedirectResponse(f"/e/{token}", status_code=303)

    @app.get("/s/{slug}")
    def public_shop(request: Request, conn: Conn, slug: str, lang: str = "en"):
        shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                            (slug,)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown shop")
        if shop["is_demo"] and not sample_shops_enabled(
                app.state.settings):
            raise HTTPException(404, "unknown shop")
        shop_lang = shop["language"] or "en"
        try:
            shop_native = get_language(shop_lang).native_name
        except KeyError:
            shop_lang, shop_native = "en", "English"
        language = lang if lang in ("en", shop_lang) else "en"
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        rows = []
        rel = ""
        prices_time = ""
        hero_photo = None
        min_price: Decimal | None = None
        max_price: Decimal | None = None
        quotes_ok = True
        if version_id is not None:
            for item in db.version_items(conn, version_id):
                name = item.name_local if language == shop_lang else item.name_en
                named_cutout = v13_cutout_url(item.name_en)
                photo_url = named_cutout or _photo_url(item.photo)
                photo_cutout = bool(named_cutout) or is_cutout_photo(item.photo)
                if photo_url and hero_photo is None and not item.sold_out:
                    hero_photo = photo_url
                first = item.price_lines[0] if item.price_lines else None
                unit = (first.unit or "") if first else ""
                price = first.price if first else None
                per_amount = first.per_amount if first else None
                if price is not None and not item.sold_out:
                    if min_price is None or price < min_price:
                        min_price = price
                    if max_price is None or price > max_price:
                        max_price = price
                clip_file = (db.media_path(data_dir, item.proof.audio_clip)
                             if item.proof else None)
                has_clip = bool(clip_file is not None and clip_file.is_file())
                quote = (item.proof.quote if item.proof else "") or ""
                if not quote.strip():
                    quotes_ok = False
                rows.append({
                    "name": f"{name} ({item.variety})" if item.variety else name,
                    "name_local": item.name_local,
                    "name_en": item.name_en,
                    "title_local": local_title(
                        item.name_local, item.variety, item.name_en,
                        shop_lang),
                    "title_en": english_title(item.name_en, item.variety),
                    "has_clip": has_clip,
                    "clip_url": (f"/s/{shop['slug']}/voice/{item.id}"
                                 if has_clip else ""),
                    # The price's own transcript span ("said" words);
                    # the full proof quote never leaves the server.
                    "said": (first.said or "") if first else "",
                    "cat": category_of(item.name_en),
                    "tile": first_grapheme(item.name_local or name),
                    "tile_var": tile_variety(item.variety),
                    "variety": item.variety,
                    "photo_url": photo_url,
                    "photo_cutout": photo_cutout,
                    "sold_out": item.sold_out,
                    "unit": unit,
                    "price": str(price) if price is not None else "",
                    "per_amount": (str(per_amount)
                                   if per_amount is not None else ""),
                    "lines": [{"price": str(line.price),
                               "per": _per_text(line.per_amount, line.unit)}
                              for line in item.price_lines],
                })
            when = db.version_time(conn, version_id)
            rel = format_relative(when, datetime.now(UTC))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            prices_time = when.astimezone(IST).strftime("%H:%M")
        if hero_photo is None:
            for row in rows:
                if row["photo_url"]:
                    hero_photo = row["photo_url"]
                    break
        from app.market.hours import has_hours, shop_open_status

        open_info = shop_open_status(shop)
        currency = shop["currency"] or "INR"
        summary_min = format_money(min_price, currency) if min_price else ""
        summary_max = format_money(max_price, currency) if max_price else ""
        digits = re.sub(r"\D", "", shop["phone"] or "")
        shop_link = f"{app.state.settings.public_base_url}/s/{shop['slug']}"
        share_text = f"{shop['name']}\n{shop_link}"
        share_url = "https://wa.me/?text=" + url_quote(share_text)
        strings = get_strings(language)
        # Sample shops never read "said today": the SAMPLE_TIME marker
        # makes t() render the sample wording in the page language.
        if shop["is_demo"] and version_id is not None:
            prices_time = SAMPLE_TIME
            rel = strings("hp.said_sample")
        price_source = ""
        if version_id is not None:
            raw_source = db.version_source(conn, version_id)
            price_source = strings(
                _SRC_KEYS.get(raw_source or "", "shop.src_mixed"))
        try:
            hours_raw = shop["hours_json"]
        except (KeyError, IndexError, TypeError):
            hours_raw = None
        nearby = []
        if (shop["area"] or "").strip():
            candidates = conn.execute(
                "SELECT * FROM shops WHERE listed = 1 AND area = ?"
                " AND id != ? ORDER BY id LIMIT 12",
                (shop["area"], shop["id"])).fetchall()
            if not sample_shops_enabled(app.state.settings):
                candidates = [row for row in candidates
                              if not row["is_demo"]]
            # Sample shops sort after real shops.
            candidates = sorted(candidates,
                                key=lambda row: bool(row["is_demo"]))
            for other in candidates:
                if len(nearby) >= 4:
                    break
                other_version = db.latest_version(
                    conn, other["id"], published_only=True)
                if other_version is None:
                    continue
                other_open = shop_open_status(other)
                nearby.append({
                    "name": other["name"], "slug": other["slug"],
                    "area": other["area"] or "",
                    "tile": first_grapheme(other["name"]),
                    "n_prices": len(db.version_items(conn, other_version)),
                    "open_state": other_open["state"],
                    "open_time": other_open["time"],
                    "is_demo": bool(other["is_demo"]),
                    "cover_url": _photo_url(db.shop_cover(other)),
                })
        cover = db.shop_cover(shop)
        try:
            priced = [row for row in rows
                      if row["price"] and not row["sold_out"]]
            best_rows = sorted(
                priced, key=lambda row: Decimal(row["price"]))[:5]
        except (InvalidOperation, ValueError):
            best_rows = [row for row in rows if row["price"]][:5]
        # --- v13 shop page facts (Task 127): every caption below is
        # computed, never invented. "Lowest in <market>" compares the
        # same item + unit across today's live lists in this area;
        # "less than yesterday" needs the previous published version
        # from yesterday with a higher price for the same item.
        from app.web import home_data as home_data_mod

        now_utc = datetime.now(UTC)
        today_ist = now_utc.astimezone(IST).date()
        area_min: dict[tuple[str, str], Decimal] = {}
        for live in home_data_mod.live_shops(conn, now_utc,
                                             settings=app.state.settings):
            if (live["shop"]["area"] or "") != (shop["area"] or ""):
                continue
            for live_item in live["items"]:
                for live_line in live_item.price_lines:
                    if live_line.price is None:
                        continue
                    key = ((live_item.name_en or "").strip().lower(),
                           (live_line.unit or "").strip().lower())
                    prev = area_min.get(key)
                    if prev is None or live_line.price < prev:
                        area_min[key] = live_line.price
        prev_prices: dict[tuple[str, str], Decimal] = {}
        prev_yesterday = False
        if version_id is not None:
            prev_row = conn.execute(
                "SELECT id FROM versions WHERE shop_id = ?"
                " AND published = 1 AND id < ?"
                " ORDER BY id DESC LIMIT 1",
                (shop["id"], version_id)).fetchone()
            if prev_row is not None:
                prev_when = db.version_time(conn, prev_row["id"])
                if prev_when.tzinfo is None:
                    prev_when = prev_when.replace(tzinfo=UTC)
                prev_yesterday = (
                    (today_ist - prev_when.astimezone(IST).date()).days
                    == 1)
                for prev_item in db.version_items(conn, prev_row["id"]):
                    if prev_item.sold_out or not prev_item.price_lines:
                        continue
                    first_prev = prev_item.price_lines[0]
                    if first_prev.price is None:
                        continue
                    prev_prices[((prev_item.name_en or "").strip().lower(),
                                 (prev_item.variety or "").strip().lower())] \
                        = first_prev.price
        best_cards = []
        for row in best_rows:
            caption = ""
            try:
                amount = Decimal(row["price"])
            except (InvalidOperation, ValueError):
                amount = None
            if amount is not None:
                floor = area_min.get(
                    ((row["name_en"] or "").strip().lower(),
                     (row["unit"] or "").strip().lower()))
                if floor is not None and amount <= floor:
                    caption = strings("v13.lowest_in",
                                      market=(shop["area"] or ""))
            if not caption and amount is not None and prev_yesterday:
                was = prev_prices.get(
                    ((row["name_en"] or "").strip().lower(),
                     (row["variety"] or "").strip().lower()))
                if was is not None and was > amount:
                    diff = format((was - amount).normalize(), "f")
                    caption = strings("v13.less_yday", n=diff)
            if not caption:
                caption = (strings("hp.said_sample") if shop["is_demo"]
                           else strings("v13.said_today"))
            best_cards.append({
                "name": row["name_local"],
                "price": format_money(amount, currency)
                if amount is not None else "",
                "per": (row["lines"][0]["per"] if row["lines"] else ""),
                "photo_url": row["photo_url"],
                "caption": caption,
            })
        area_parts = [(part.strip()) for part in
                      (shop["area"] or "").split(",") if part.strip()]
        if len(area_parts) > 1:
            crumb_market, crumb_city = area_parts[0], area_parts[-1]
        elif area_parts:
            crumb_market, crumb_city = area_parts[0], ""
        else:
            crumb_market, crumb_city = "", ""
        first_clip = next((row["clip_url"] for row in rows
                           if row["has_clip"]), "")
        said_today = False
        if version_id is not None and not shop["is_demo"]:
            said_when = db.version_time(conn, version_id)
            if said_when.tzinfo is None:
                said_when = said_when.replace(tzinfo=UTC)
            said_today = said_when.astimezone(IST).date() == today_ist
        return templates.TemplateResponse(request, "shop.html", {
            "shop": shop, "rows": rows, "best_rows": best_rows,
            "best_cards": best_cards,
            "rel": rel, "digits": digits,
            "share_url": share_url,
            "lang": language, "shop_lang": shop_lang,
            "shop_native": shop_native, "t": strings,
            "prices_time": prices_time, "price_source": price_source,
            "hero_photo": hero_photo,
            "shop_cover_url": _photo_url(cover),
            "summary_min": summary_min, "summary_max": summary_max,
            "has_upi": bool(db.shop_upi_id(shop)),
            "open_state": open_info["state"],
            "open_time": open_info["time"],
            "has_hours": has_hours(hours_raw),
            "nearby": nearby,
            "voice_checked": bool(rows) and quotes_ok,
            "said_today": said_today,
            "n_prices": len(priced),
            "crumb_market": crumb_market, "crumb_city": crumb_city,
            "first_clip_url": first_clip,
            "ui_lang": language if language in ("ta", "hi", "en") else "en"})

    @app.get("/s/{slug}/voice/{item_id}")
    def public_voice_clip(slug: str, item_id: int, conn: Conn):
        """One price's voice proof, from the published list only."""
        shop = conn.execute("SELECT * FROM shops WHERE slug = ?",
                            (slug,)).fetchone()
        if shop is None:
            raise HTTPException(404, "unknown shop")
        if shop["is_demo"] and not sample_shops_enabled(
                app.state.settings):
            raise HTTPException(404, "unknown shop")
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        items = (db.version_items(conn, version_id)
                 if version_id is not None else [])
        item = next((it for it in items if it.id == item_id), None)
        if item is None:
            raise HTTPException(404, "no such item")
        clip = (db.media_path(data_dir, item.proof.audio_clip)
                if item.proof else None)
        if clip is None or not clip.is_file():
            raise HTTPException(404, "no voice clip")
        return FileResponse(clip, media_type="audio/mp4")

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
