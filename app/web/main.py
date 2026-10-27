from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.config import Settings, load_settings
from app.web import seller as seller_routes


def create_app(settings: Settings) -> FastAPI:
    """Build the MarketMate web app (seller flow; customer pages land in Task 13)."""
    app = FastAPI()
    app.state.settings = settings
    here = Path(__file__).parent
    templates = Jinja2Templates(directory=str(here / "templates"))
    app.mount("/static", StaticFiles(directory=str(here / "static")), name="static")
    seller_routes.register(app, settings, templates)

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(request, "home.html", {})

    @app.post("/find")
    def find_prices(slug: str = Form(...)):
        return RedirectResponse(f"/p/{slug.strip()}", status_code=303)

    return app


app = create_app(load_settings())
