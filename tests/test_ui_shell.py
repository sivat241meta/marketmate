"""Task 22: Fresh Market design system, app shell, home and seller dashboard."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.web.main import create_app

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
BASE = ROOT / "app" / "web" / "templates" / "base.html"

TOKENS = ["--forest", "--leaf", "--cta", "--gold", "--mint", "--bg", "--surface", "--ink", "--muted", "--line", "--danger"]


def make_client(tmp_path):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
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
    html = make_client(tmp_path).get("/").text
    assert_shell(html, "Say your prices. Get a price board, a shop page and a market listing.")
    assert "Start as seller" in html or "start your shop" in html.lower()
    assert "/try" in html
    assert 'action="/find"' in html and 'name="slug"' in html
    assert "Every price comes from the seller" in html


def test_new_shop_has_shell_and_form(tmp_path):
    response = make_client(tmp_path).get("/new")
    assert response.status_code == 200
    assert_shell(response.text, "Create shop")
    for field in ("name", "phone", "area", "language", "currency", "type"):
        assert f'name="{field}"' in response.text
    assert 'value="ta"' in response.text and 'value="en"' in response.text


def test_seller_dashboard_has_shell_and_actions(tmp_path):
    client = make_client(tmp_path)
    response = client.get(create_shop(client))
    assert response.status_code == 200
    assert_shell(response.text, "Record today")
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
