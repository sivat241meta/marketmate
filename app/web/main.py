import hashlib
import secrets
import sqlite3
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import db, storage
from app.config import Settings, load_settings
from app.costs import CostCapExceeded, CostLedger
from app.limits import RateLimiter
from app.market.basket import explain_basket, plan_basket
from app.market.search import find_listings, parse_query
from app.meta.spark import SparkError
from app.meta.transcribe import TranscribeError, transcribe_wav
from app.pipeline.checks import WEIGHT_ITEMS
from app.pipeline.media import extract_audio
from app.pipeline.names import PRODUCE_KEYWORDS
from app.web import photos as photo_routes
from app.web import seller as seller_routes


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


def _fmt_rate(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")).normalize(), "f")


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
    startup_conn = db.connect(data_dir)
    try:
        db.purge_expired(startup_conn, data_dir, datetime.now(UTC))
    finally:
        startup_conn.close()
    templates = Jinja2Templates(directory=str(here / "templates"))
    templates.env.globals["static_url"] = build_static_url(here / "static")
    app.mount("/static", StaticFiles(directory=str(here / "static")), name="static")
    seller_routes.register(app, settings, templates)
    photo_routes.register(app, settings, templates)

    def get_conn():
        conn = db.connect(data_dir)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def _rows_from_listings(listings, now):
        rows = []
        for found in listings:
            name = (f"{found.name_en} ({found.variety})"
                    if found.variety else found.name_en)
            rows.append({
                "shop_name": found.shop_name,
                "slug": found.slug,
                "is_demo": found.is_demo,
                "name": name,
                "price": str(found.line.price),
                "per": f"{found.line.per_amount} {found.line.unit}",
                "rate": _fmt_rate(found.rate) if found.rate is not None else "",
                "rate_unit": found.rate_unit or "",
                "rel": _relative_time(found.updated_at, now),
                "stale": found.stale,
                "lowest": False,
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
                label += f" under ₹{format(want.max_rate.normalize(), 'f')}"
            chips.append(label)
        if query.budget is not None:
            chips.append(f"Budget ₹{format(query.budget.normalize(), 'f')}")
        if query.area:
            chips.append(query.area)
        return chips

    def _basket_dict(plans, budget, explanation):
        plan_dicts = []
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
                })
            plan_dicts.append({
                "kind": plan.kind,
                "shop": plan.shop,
                "total": _fmt_rate(plan.total),
                "lines": lines,
                "missing": list(plan.missing),
            })
        return {
            "budget": _fmt_rate(budget) if budget is not None else "",
            "explanation": explanation,
            "plans": plan_dicts,
        }

    def _build_basket(query, listings, ledger):
        if query.budget is None or not query.wants:
            return None
        plans = plan_basket(query.wants, listings, query.budget)
        explanation = explain_basket(plans, query.budget, ledger=ledger,
                                     settings=app.state.settings)
        return _basket_dict(plans, query.budget, explanation)

    def _market_context(request, *, q="", heard=None, query=None, rows=None,
                        error=None, searched=False, basket=None):
        flat = rows or []
        return templates.TemplateResponse(request, "market.html", {
            "q": q, "heard": heard, "rows": flat, "groups": _group_rows(flat),
            "chips": _chips(query),
            "unknown": list(query.unknown) if query else [],
            "error": error, "searched": searched, "basket": basket})

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(request, "home.html", {})

    @app.post("/find")
    def find_prices(slug: str = Form(...)):
        return RedirectResponse(f"/p/{slug.strip()}", status_code=303)

    @app.get("/market")
    def market_page(request: Request, conn: Conn, q: str | None = None):
        if not q or not q.strip():
            return _market_context(request)
        ledger = CostLedger(data_dir / "costs.db",
                            app.state.settings.daily_budget_usd)
        try:
            query = parse_query(q.strip(), ledger=ledger,
                                settings=app.state.settings)
        except (SparkError, CostCapExceeded) as exc:
            return _market_context(request, q=q.strip(), error=str(exc),
                                   searched=True)
        now = datetime.now(UTC)
        listings = find_listings(conn, query, now)
        return _market_context(
            request, q=q.strip(), query=query,
            rows=_rows_from_listings(listings, now),
            basket=_build_basket(query, listings, ledger), searched=True)

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
        listings = find_listings(conn, query, now)
        return _market_context(
            request, q=transcript.text, heard=transcript.text, query=query,
            rows=_rows_from_listings(listings, now),
            basket=_build_basket(query, listings, ledger), searched=True)

    return app


app = create_app(load_settings())
