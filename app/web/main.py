import hashlib
import secrets
import sqlite3
import subprocess
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import db, storage
from app.config import Settings, load_settings
from app.costs import CostCapExceeded, CostLedger
from app.limits import RateLimiter
from app.market.basket import best_partial_shop, explain_basket, plan_basket
from app.market.search import find_listings, parse_query
from app.meta.spark import SparkError
from app.meta.transcribe import TranscribeError, transcribe_wav
from app.outputs.money import format_money
from app.outputs.time import format_relative
from app.pipeline.checks import WEIGHT_ITEMS
from app.pipeline.media import extract_audio
from app.pipeline.names import PRODUCE_KEYWORDS
from app.web import bills as bills_routes
from app.web import close as close_routes
from app.web import credit as credit_routes
from app.web import home_data as home_data_mod
from app.web import live as live_routes
from app.web import photos as photo_routes
from app.web import purchases as purchases_routes
from app.web import quotes as quote_routes
from app.web import seller as seller_routes
from app.web import settings as settings_routes
from app.web import shell as shell_data


def _fmt_rate(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")).normalize(), "f")


def _closed_with_items(conn, query, listings, now, area, pincode,
                     settings=None) -> int:
    """Distinct closed shops with fresh listings the open filter hides.

    ``listings`` is the open-filtered result; wants it covers need no
    notice. Only wants missing there count, and only fresh listings
    from closed shops (unknown-hours shops are never filtered out).
    """
    covered = {row.name_en for row in listings if not row.stale}
    missing = {want.name_en for want in query.wants} - covered
    if not missing:
        return 0
    unfiltered = find_listings(conn, query, now, area=(area or None),
                               pincode=(pincode or None),
                               open_only=False, settings=settings)
    return len({row.slug for row in unfiltered
                if not row.stale and row.name_en in missing
                and row.open_state == "closed"})


def _open_all_url(*, q: str, area: str, pincode: str, sort: str,
                  budget: str) -> str:
    """Same market search with the Open-now filter unticked."""
    from urllib.parse import urlencode

    params = [("q", q)]
    if area:
        params.append(("area", area))
    if pincode:
        params.append(("pincode", pincode))
    params.append(("open_now", "0"))
    params.append(("sort", sort))
    if budget:
        params.append(("budget", budget))
    return "/market?" + urlencode(params)


def _parse_budget(value: str | None) -> Decimal | None:
    """Basket budget from a ``?budget=`` param; None when blank/invalid."""
    text = (value or "").strip().replace("₹", "").replace(",", "")
    text = text.replace(" ", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount.is_nan() or amount <= 0:
        return None
    return amount


def build_static_url(static_dir: Path):
    """Cache-busting helper: /static/<rel>?v=<first 10 sha1 hex chars>."""
    versions: dict[str, str] = {}
    for path in sorted(static_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(static_dir).as_posix()
            versions[rel] = hashlib.sha1(path.read_bytes()).hexdigest()[:10]

    def static_url(path: str) -> str:
        rel = path
        if rel.startswith("/static/"):
            rel = rel[len("/static/"):]
        elif rel.startswith("static/"):
            rel = rel[len("static/"):]
        else:
            rel = rel.lstrip("/")
        version = versions.get(rel)
        if version:
            return f"/static/{rel}?v={version}"
        return f"/static/{rel}"

    return static_url


def create_app(settings: Settings) -> FastAPI:
    """Build the MarketMate web app (seller flow plus the customer market)."""
    app = FastAPI()
    app.state.settings = settings
    app.state.limiter = RateLimiter(settings.uploads_per_ip_hour,
                                    settings.uploads_per_hour)

    @app.middleware("http")
    async def _commit_volume_after_writes(request: Request, call_next):
        response = await call_next(request)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            storage.commit()
        return response

    here = Path(__file__).parent
    data_dir = Path(settings.data_dir)

    @app.middleware("http")
    async def _shell_announcement(request: Request, call_next):
        request.state.shell_ann = None
        if request.method == "GET":
            request.state.shell_ann = shell_data.ann_for_path(
                data_dir, request.url.path)
        return await call_next(request)
    startup_conn = db.connect(data_dir)
    try:
        db.purge_expired(startup_conn, data_dir, datetime.now(UTC))
    finally:
        startup_conn.close()
    templates = Jinja2Templates(directory=str(here / "templates"))
    templates.env.globals["static_url"] = build_static_url(here / "static")
    templates.env.filters["money"] = format_money
    from app.web.i18n import jinja_flag, jinja_t

    templates.env.globals["t"] = jinja_t
    templates.env.globals["t_flag"] = jinja_flag
    app.mount("/static", StaticFiles(directory=str(here / "static")), name="static")
    seller_routes.register(app, settings, templates)
    photo_routes.register(app, settings, templates)
    quote_routes.register(app, settings, templates)
    bills_routes.register(app, settings, templates)
    credit_routes.register(app, settings, templates)
    live_routes.register(app, settings, templates)
    settings_routes.register(app, settings, templates)
    purchases_routes.register(app, settings, templates)
    close_routes.register(app, settings, templates)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _rows_from_listings(listings, now, lang="en", conn=None):
        from app.web.i18n import t_for

        sample_rel = t_for(lang)("hp.said_sample")
        covers = {}
        if conn is not None:
            for slug, cover in conn.execute(
                    "SELECT slug, cover_photo FROM shops"):
                if cover:
                    covers[slug] = "/m/" + Path(cover).name
        rows = []
        for found in listings:
            name = (f"{found.name_en} ({found.variety})"
                    if found.variety else found.name_en)
            per = (
                f"{found.line.per_amount} {found.line.unit}"
                if found.line.per_amount is not None and found.line.unit
                else (found.line.unit or "")
            )
            rows.append({
                "shop_name": found.shop_name,
                "slug": found.slug,
                "is_demo": found.is_demo,
                "name": name,
                "price": str(found.line.price),
                "per": per,
                "rate": _fmt_rate(found.rate) if found.rate is not None else "",
                "rate_unit": found.rate_unit or "",
                "currency": found.currency,
                "rel": (sample_rel if found.is_demo
                        else format_relative(found.updated_at, now)),
                "stale": found.stale,
                "lowest": False,
                "area": found.area,
                "lat": found.lat,
                "lng": found.lng,
                "open_state": found.open_state,
                "open_time": found.open_time,
                "cover_url": covers.get(found.slug),
            })
        return rows

    def _group_rows(rows):
        groups: list[dict] = []
        by_name: dict[str, dict] = {}
        for row in rows:
            key = row["name"]
            if key not in by_name:
                by_name[key] = {"name": key, "rows": []}
                groups.append(by_name[key])
            by_name[key]["rows"].append(row)
        for group in groups:
            first = group["rows"][0] if group["rows"] else None
            if first is not None and not first["stale"]:
                first["lowest"] = True
        return groups

    def _chips(query):
        chips = []
        if query is None:
            return chips
        for want in query.wants:
            label = want.name_en
            if want.amount is not None and want.unit:
                qty = format(want.amount.normalize(), "f")
                label += f" · {qty} {want.unit}"
            elif want.amount is not None:
                label += f" · {format(want.amount.normalize(), 'f')}"
            if want.max_rate is not None:
                label += f" under {format_money(want.max_rate, 'INR')}"
            chips.append(label)
        if query.budget is not None:
            chips.append(f"Budget {format_money(query.budget, 'INR')}")
        if query.area:
            chips.append(query.area)
        return chips

    def _basket_dict(plans, budget, explanation, conn):
        from app.market.hours import shop_open_status

        plan_dicts = []
        best_total = None
        for plan in plans:
            if (plan.kind in ("single_shop", "partial_shop")
                    and not plan.missing
                    and (best_total is None or plan.total < best_total)):
                best_total = plan.total
        for plan in plans:
            lines = []
            for line in plan.lines:
                if line.assumed:
                    amount = ("1 kg" if line.want.name_en in WEIGHT_ITEMS
                              else "1 piece")
                else:
                    qty = line.want.amount
                    qty_text = format(qty.normalize(), "f") if qty is not None else "1"
                    amount = f"{qty_text} {line.want.unit}"
                lines.append({
                    "want": line.want.name_en,
                    "amount": amount,
                    "assumed": line.assumed,
                    "shop": line.listing.shop_name,
                    "slug": line.listing.slug,
                    "cost": _fmt_rate(line.cost),
                    "currency": line.listing.currency,
                })
            plan_currency = (lines[0]["currency"] if lines else "INR")
            saved = ""
            if budget is not None and plan.total < budget:
                saved = _fmt_rate(budget - plan.total)
            lat = lng = None
            slug = None
            area = ""
            cover_url = None
            open_state, open_time = "unknown", ""
            if plan.kind in ("single_shop", "partial_shop") and lines:
                slug = lines[0]["slug"]
                shop = db.shop_by_slug(conn, slug)
                if shop is not None:
                    lat, lng = shop["lat"], shop["lng"]
                    area = shop["area"] or ""
                    status = shop_open_status(shop)
                    open_state, open_time = status["state"], status["time"]
                    cover = db.shop_cover(shop)
                    if cover:
                        cover_url = "/m/" + Path(cover).name
            plan_demo = False
            if plan.kind == "split":
                for line in lines:
                    other = db.shop_by_slug(conn, line["slug"])
                    if other is not None and other["is_demo"]:
                        plan_demo = True
                        break
            elif slug is not None:
                plan_shop = db.shop_by_slug(conn, slug)
                plan_demo = bool(plan_shop is not None
                                 and plan_shop["is_demo"])
            plan_dicts.append({
                "kind": plan.kind,
                "shop": plan.shop,
                "slug": slug,
                "area": area,
                "total": _fmt_rate(plan.total),
                "currency": plan_currency,
                "lines": lines,
                "missing": list(plan.missing),
                "saved": saved,
                "lat": lat,
                "lng": lng,
                "open_state": open_state,
                "open_time": open_time,
                "cover_url": cover_url,
                "is_demo": plan_demo,
                "best": bool(best_total is not None
                             and plan.total == best_total
                             and plan.kind in ("single_shop",
                                               "partial_shop")
                             and not plan.missing),
            })
        # Default sort: cheapest basket total first (stable), sample
        # shops after real shops.
        plan_dicts.sort(key=lambda entry: Decimal(entry["total"] or 0))
        plan_dicts.sort(key=lambda entry: entry["is_demo"])
        return {
            "budget": _fmt_rate(budget) if budget is not None else "",
            "explanation": explanation,
            "plans": plan_dicts,
        }

    def _build_basket(conn, query, listings, ledger, *, empty_text,
                      closed_text=""):
        if not query.wants:
            return None
        has_qty = any(want.amount is not None for want in query.wants)
        if query.budget is None and not has_qty:
            return None
        plans = plan_basket(query.wants, listings, query.budget)
        if not any(plan.kind == "single_shop" for plan in plans):
            partial = best_partial_shop(query.wants, listings)
            if partial is not None:
                plans = [*plans, partial]
        if closed_text:
            # Open-now hides matching closed shops: fixed sentence, no call.
            explanation = closed_text
        elif not any(plan.lines for plan in plans):
            # No plan covers any item: fixed sentence, never a Spark call.
            explanation = empty_text
        else:
            explanation = explain_basket(plans, query.budget, ledger=ledger,
                                         settings=app.state.settings)
        return _basket_dict(plans, query.budget, explanation, conn)

    def _market_context(request, *, q="", heard=None, query=None, rows=None,
                        error=None, searched=False, basket=None, areas=None,
                        area="", pincode="", open_now=False, sort="total",
                        market_empty=False, budget="", closed_notice=None):
        from app.web.i18n import get_strings, get_ui_lang

        flat = rows or []
        ui_lang = get_ui_lang(request)
        return templates.TemplateResponse(request, "market.html", {
            "q": q, "heard": heard, "rows": flat, "groups": _group_rows(flat),
            "chips": _chips(query),
            "unknown": list(query.unknown) if query else [],
            "error": error, "searched": searched, "basket": basket,
            "areas": areas or [], "area": area or "",
            "pincode": pincode or "", "open_now": open_now,
            "sort": sort or "total", "market_empty": market_empty,
            "budget": budget or "", "closed_notice": closed_notice,
            "t": get_strings(ui_lang),
            "ui_lang": ui_lang})

    @app.get("/manifest.webmanifest")
    def manifest():
        return JSONResponse(
            {
                "name": "MarketMate",
                "short_name": "MarketMate",
                "theme_color": "#1E1F21",
                "background_color": "#FAFBFC",
                "display": "standalone",
                "start_url": "/",
                "icons": [
                    {"src": "/static/brand/icon-192.png",
                     "sizes": "192x192", "type": "image/png"},
                    {"src": "/static/brand/icon-512.png",
                     "sizes": "512x512", "type": "image/png"},
                    {"src": "/static/brand/icon-maskable-512.png",
                     "sizes": "512x512", "type": "image/png",
                     "purpose": "maskable"},
                ],
                "share_target": {
                    "action": "/share",
                    "method": "POST",
                    "enctype": "multipart/form-data",
                    "files": [{
                        "name": "media",
                        "accept": ["audio/*", "video/*", ".opus", ".ogg",
                                   ".m4a", ".mp4"],
                    }],
                },
            },
            media_type="application/manifest+json",
        )

    @app.get("/sw.js")
    def service_worker():
        body = (here / "static" / "sw.js").read_bytes()
        return Response(
            body, media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/",
                     "Cache-Control": "no-cache"},
        )

    @app.get("/")
    def home(request: Request, conn: Conn, area: str | None = None):
        from app.web.i18n import get_ui_lang

        data = home_data_mod.home_data(conn, area=area,
                                       settings=app.state.settings)
        return templates.TemplateResponse(
            request, "home.html", {
                "ui_lang": get_ui_lang(request),
                "hp": data})

    @app.get("/my")
    def my_page(request: Request):
        from app.web.i18n import get_ui_lang

        return templates.TemplateResponse(
            request, "my.html", {"ui_lang": get_ui_lang(request)})

    @app.get("/share")
    def share_page(request: Request):
        from app.languages import LANGUAGES
        from app.web.i18n import get_ui_lang

        return templates.TemplateResponse(
            request, "share.html",
            {"languages": LANGUAGES, "ui_lang": get_ui_lang(request)})

    @app.post("/find")
    def find_prices(slug: str = Form(...)):
        return RedirectResponse(f"/p/{slug.strip()}", status_code=303)

    @app.get("/market")
    def market_page(request: Request, conn: Conn, q: str | None = None,
                    area: str | None = None, pincode: str | None = None,
                    sort: str | None = None, budget: str | None = None):
        from app.config import sample_shops_enabled

        areas = db.listed_areas(
            conn, include_samples=sample_shops_enabled(
                app.state.settings))
        # The open-now toggle is off by default; the form always sends
        # open_now=0 plus open_now=1 when ticked, so read every value.
        picked = request.query_params.getlist("open_now")
        open_flag = ("1" in picked) if picked else False
        sort_mode = sort if sort in ("total", "distance") else "total"
        budget_text = budget or ""
        if not q or not q.strip():
            return _market_context(request, areas=areas, area=area or "",
                                   pincode=pincode or "",
                                   open_now=open_flag, sort=sort_mode,
                                   budget=budget_text)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            query = parse_query(q.strip(), ledger=ledger,
                                settings=app.state.settings)
        except (SparkError, CostCapExceeded) as exc:
            return _market_context(request, q=q.strip(), error=str(exc),
                                   searched=True, areas=areas,
                                   area=area or "", pincode=pincode or "",
                                   open_now=open_flag, sort=sort_mode,
                                   budget=budget_text)
        explicit = _parse_budget(budget)
        if explicit is not None:
            query.budget = explicit
        now = datetime.now(UTC)
        listings = find_listings(conn, query, now, area=(area or None),
                                 pincode=(pincode or None),
                                 open_only=open_flag,
                                 settings=app.state.settings)
        # Honest empty state: no listed shop has shared prices at all, so
        # there is no basket to plan (never a "totals 0" card).
        market_empty = bool(query.wants) and not areas
        from app.web.i18n import get_strings, get_ui_lang

        ui_lang = get_ui_lang(request)
        strings = get_strings(ui_lang)
        closed_n = (0 if (market_empty or not open_flag)
                    else _closed_with_items(conn, query, listings, now,
                                            area, pincode,
                                            app.state.settings))
        closed_text = (strings("market.closed_have", n=closed_n,
                               count=closed_n) if closed_n else "")
        empty_text = closed_text or strings("market.none_today")
        basket = (None if market_empty
                  else _build_basket(conn, query, listings, ledger,
                                     empty_text=empty_text,
                                     closed_text=closed_text))
        rows = _rows_from_listings(listings, now, ui_lang, conn)
        closed_notice = None
        if open_flag and closed_n:
            if ((basket is None
                 or not any(plan["lines"] for plan in basket["plans"]))
                    and not rows):
                # Open-now hides everything matching: notice, not an
                # empty basket or a "No fresh prices" card.
                basket = None
            closed_notice = {
                "n": closed_n,
                "url": _open_all_url(q=q.strip(), area=area or "",
                                     pincode=pincode or "",
                                     sort=sort_mode, budget=budget_text),
            }
        return _market_context(
            request, q=q.strip(), query=query, rows=rows, basket=basket,
            searched=True, areas=areas, area=area or "",
            pincode=pincode or "", open_now=open_flag, sort=sort_mode,
            market_empty=market_empty, budget=budget_text,
            closed_notice=closed_notice)

    @app.post("/market/voice")
    async def market_voice(request: Request):
        # Own connection: the sync request dependency may live on another thread.
        conn = db.connect(data_dir)
        try:
            return await _market_voice_impl(request, conn)
        finally:
            conn.close()

    async def _market_voice_impl(request: Request, conn):
        form = await request.form()
        upload = form.get("audio")
        if upload is None or not hasattr(upload, "file"):
            raise HTTPException(422, "an audio recording is required")
        voice_dir = data_dir / "voice_search"
        voice_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(getattr(upload, "filename", "") or "search.webm").name
        saved = voice_dir / f"{secrets.token_hex(8)}_{safe_name}"
        saved.write_bytes(await upload.read())
        wav = saved.with_suffix(".wav")
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            extract_audio(saved, wav)
            transcript = transcribe_wav(
                wav, keywords=PRODUCE_KEYWORDS, ledger=ledger,
                settings=app.state.settings)
            query = parse_query(transcript.text, ledger=ledger,
                                settings=app.state.settings)
        except (TranscribeError, SparkError, CostCapExceeded,
                subprocess.CalledProcessError, OSError) as exc:
            return _market_context(request, error=str(exc) or "search failed",
                                   searched=True)
        finally:
            saved.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)
        now = datetime.now(UTC)
        listings = find_listings(conn, query, now,
                                 settings=app.state.settings)
        from app.config import sample_shops_enabled

        voice_areas = db.listed_areas(
            conn, include_samples=sample_shops_enabled(
                app.state.settings))
        market_empty = bool(query.wants) and not voice_areas
        from app.web.i18n import get_strings, get_ui_lang

        # Voice search never filters by open hours, so there is no
        # closed-shops sentence here; empty baskets get the fixed line.
        voice_lang = get_ui_lang(request)
        voice_empty = get_strings(voice_lang)("market.none_today")
        return _market_context(
            request, q=transcript.text, heard=transcript.text, query=query,
            rows=_rows_from_listings(listings, now, voice_lang, conn),
            basket=(None if market_empty
                    else _build_basket(conn, query, listings, ledger,
                                       empty_text=voice_empty)),
            searched=True, areas=voice_areas,
            market_empty=market_empty)

    return app


app = create_app(load_settings())
