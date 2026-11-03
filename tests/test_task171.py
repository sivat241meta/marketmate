"""Task 171: / shows the entry page to anyone arriving from outside.

GET / shows today's home page only for in-site navigation: the
browser has mm_entered=1 AND the Referer is a page on the same host.
A missing, malformed, or other-site Referer gets the entry page
(Visit MarketMate / Judge demo), cookie or not. /home is unchanged.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_task84 import draft, seed_shop
from test_task84 import make_client as entered_client

from app.config import load_settings
from app.web.main import create_app


def make_client(tmp_path):
    """Fresh browser: no mm_entered cookie, nothing entered yet."""
    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)),
                      follow_redirects=False)


def _assert_entry(html: str) -> None:
    assert 'class="entry-cards"' in html
    assert 'href="/home?enter=1"' in html
    assert 'href="/try"' in html
    assert 'id="hero"' not in html


def _assert_home(html: str) -> None:
    assert 'id="hero"' in html
    assert "entry-cards" not in html


def test_no_cookie_no_referer_shows_entry(tmp_path):
    _assert_entry(make_client(tmp_path).get("/").text)


def test_cookie_without_referer_shows_entry(tmp_path):
    client = entered_client(tmp_path)
    assert client.cookies.get("mm_entered") == "1"
    _assert_entry(client.get("/").text)


def test_cookie_with_other_site_referer_shows_entry(tmp_path):
    client = entered_client(tmp_path)
    html = client.get("/",
                      headers={"referer": "https://github.com/x"}).text
    _assert_entry(html)


def test_cookie_with_same_host_referer_shows_home(tmp_path):
    seed_shop(tmp_path, "T171 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30")])
    client = entered_client(tmp_path)
    home = client.get("/home").text
    _assert_home(home)
    root = client.get("/",
                      headers={"referer": "http://testserver/market"}).text
    _assert_home(root)
    assert root == home


def test_same_host_referer_without_cookie_shows_entry(tmp_path):
    html = make_client(tmp_path).get(
        "/", headers={"referer": "http://testserver/market"}).text
    _assert_entry(html)


def test_malformed_referer_shows_entry(tmp_path):
    client = entered_client(tmp_path)
    for referer in ("not a url", "http://", "://no-scheme",
                    "http:///no-host", "http://[::1"):
        html = client.get("/", headers={"referer": referer}).text
        _assert_entry(html)


def test_home_route_unchanged(tmp_path):
    seed_shop(tmp_path, "T171 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30")])
    fresh = make_client(tmp_path)
    _assert_home(fresh.get("/home").text)
    resp = fresh.get("/home?enter=1")
    assert resp.status_code == 200
    assert "mm_entered=1" in resp.headers.get("set-cookie", "")
    _assert_home(resp.text)
