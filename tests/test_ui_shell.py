"""Task 22: Fresh Market design system, app shell, home and seller dashboard."""

import html as htmlmod
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.web.main import create_app

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
BASE = ROOT / "app" / "web" / "templates" / "base.html"

# Task 105: v11 Meta blue tokens (was the v9 purple set).
TOKENS = ["--accent", "--accent-ink", "--accent-soft", "--chrome", "--chrome-2",
          "--chrome-txt", "--green", "--green-soft", "--amber", "--amber-soft",
          "--red", "--red-soft", "--blue", "--blue-soft", "--bg", "--surface",
          "--ink", "--muted", "--line"]


def make_client(tmp_path):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def create_shop(client):
    response = client.post(
        "/new",
        data={
            "name": "Kannan Store",
            "phone": "+914400000000",
            "area": "Koyambedu",
            "language": "ta",
            "currency": "INR",
            "type": "vegetable",
        },
    )
    assert response.status_code in (302, 303)
    return response.headers["location"]


def assert_shell(html, action):
    assert "MarketMate" in html
    assert 'class="hdr"' in html
    assert action in html
    assert "style=" not in html


def test_home_has_shell_and_hero(tmp_path):
    # Task 122: the hero + sellers content moved to /sellers and /how;
    # the homepage keeps the shell, CTAs and the honesty line.
    # Task 127: v13 hero headline on the teal band.
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    html = htmlmod.unescape(client.get("/").text)
    assert_shell(html, t_for("en")("v13.hero_a"))
    assert "Start selling" in html
    assert "/try" in html
    assert "Every price comes from the seller" in html
    sellers = client.get("/sellers").text
    assert_shell(sellers, "Sell more.")
    how = client.get("/how").text
    assert 'action="/find"' in how and 'name="slug"' in how


def test_new_shop_has_shell_and_form(tmp_path):
    response = make_client(tmp_path).get("/new")
    assert response.status_code == 200
    assert_shell(response.text, "Create my shop")
    for field in ("name", "phone", "area", "language", "currency", "type"):
        assert f'name="{field}"' in response.text
    assert 'value="ta"' in response.text and 'value="en"' in response.text


def test_seller_dashboard_has_shell_and_actions(tmp_path):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from app import db
    from app.models import DraftItem, PriceLine, Proof

    client = make_client(tmp_path)
    location = create_shop(client)
    # Say-prices step: yesterday's list is live, nothing said today (Task 61).
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, location.split("/e/")[1])
        draft = DraftItem(
            name_spoken="tomato", name_local="தக்காளி", name_en="tomato",
            variety=None, price_lines=[PriceLine(Decimal(40), Decimal(1),
                                                "kg")],
            qty=None, qty_unit=None,
            proof=Proof(quote="tomato 40", turn_ids=[], start_ms=0,
                        end_ms=0),
            confirmed=True)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, [draft])
        db.set_published(conn, version_id, True)
        noon = datetime.now(ZoneInfo("Asia/Kolkata")).replace(
            hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        conn.execute("UPDATE versions SET created_at = ? WHERE id = ?",
                     (noon.astimezone(UTC).isoformat(), version_id))
        conn.commit()
    finally:
        conn.close()
    response = client.get(location)
    assert response.status_code == 200
    assert_shell(response.text, "Upload video or voice note")
    assert 'action="/e/' in response.text and 'name="video"' in response.text
    assert "/update" in response.text
    assert "Your voice recording is sent to Meta's AI service to be transcribed." in response.text


def test_error_page_has_shell(tmp_path):
    from fastapi.templating import Jinja2Templates

    from app.web.i18n import jinja_flag, jinja_t

    templates = Jinja2Templates(directory=str(ROOT / "app" / "web" / "templates"))
    templates.env.globals["t"] = jinja_t
    templates.env.globals["t_flag"] = jinja_flag
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
    }
    from starlette.requests import Request

    response = templates.TemplateResponse(
        Request(scope), "error.html", {"title": "Oops", "message": "Something broke"}
    )
    assert response.status_code == 200
    body = response.body.decode()
    assert_shell(body, "/market")
    assert "empty-state" in body


def test_css_defines_tokens():
    css = CSS.read_text()
    for token in TOKENS:
        assert token in css
    assert "@font-face" in css and "NotoSansTamil" in css.replace(" ", "")
    assert "http" not in css.split("@font-face")[0]


def test_base_has_viewport_meta():
    assert 'name="viewport"' in BASE.read_text()
