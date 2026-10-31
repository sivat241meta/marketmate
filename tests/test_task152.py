"""Task 152: /find + /p redirects, POST /share, safer /try, no stray names."""

import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings

ROOT = Path(__file__).resolve().parent.parent


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _make_shop(client, tmp_path, name="T152 Store"):
    response = client.post("/new", data={
        "name": name, "phone": "+914400000152", "area": "Koyambedu",
        "language": "en", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    token = response.headers["location"].rsplit("/e/", 1)[1]
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        return token, shop["slug"]
    finally:
        conn.close()


def _shop_count(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        return conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
    finally:
        conn.close()


# --- 1. /find goes to the shop page or a market search ---


def test_find_known_slug_redirects_to_shop(tmp_path):
    client = _client(tmp_path)
    _token, slug = _make_shop(client, tmp_path)
    response = client.post("/find", data={"slug": slug})
    assert response.status_code == 303
    assert response.headers["location"] == f"/s/{slug}"
    assert client.get(response.headers["location"]).status_code == 200


def test_find_unknown_text_redirects_to_market_search(tmp_path):
    client = _client(tmp_path)
    response = client.post("/find", data={"slug": "tomato rates"})
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/market?")
    assert parse_qs(urlparse(location).query)["q"] == ["tomato rates"]


def test_old_p_link_redirects_to_shop(tmp_path):
    client = _client(tmp_path)
    _token, slug = _make_shop(client, tmp_path)
    response = client.get(f"/p/{slug}")
    assert response.status_code == 301
    assert response.headers["location"] == f"/s/{slug}"
    assert client.get(response.headers["location"]).status_code == 200


# --- 2. POST /share ---


def test_manifest_share_target_declares_text_params(tmp_path):
    payload = _client(tmp_path).get("/manifest.webmanifest").json()
    target = payload["share_target"]
    assert target["action"] == "/share"
    assert target["method"] == "POST"
    assert target["params"] == {"title": "title", "text": "text",
                                "url": "url"}
    assert target["files"][0]["name"] == "media"


def test_share_post_with_text_opens_market_search(tmp_path):
    client = _client(tmp_path)
    for field in ("text", "url", "title"):
        response = client.post("/share", data={field: "tomato 40"})
        assert response.status_code == 303, field
        location = response.headers["location"]
        assert parse_qs(urlparse(location).query)["q"] == ["tomato 40"]


def test_share_post_with_file_renders_share_page(tmp_path):
    client = _client(tmp_path)
    response = client.post("/share", files={
        "media": ("note.ogg", b"fake-audio", "audio/ogg")})
    assert response.status_code == 200
    assert "data-share-ready" in response.text


def test_share_post_empty_renders_share_page(tmp_path):
    response = _client(tmp_path).post("/share")
    assert response.status_code == 200
    assert "data-share-ready" in response.text


def test_sw_routes_text_shares_to_market():
    text = (ROOT / "app" / "web" / "static" / "sw.js").read_text()
    assert "/market?q=" in text


# --- 3. /try reuses one demo shop per browser and is rate-limited ---


def test_try_reuses_same_shop_per_browser(tmp_path):
    client = _client(tmp_path)
    first = client.get("/try")
    assert first.status_code in (302, 303)
    assert first.headers["location"].startswith("/e/")
    assert "mm_try" in first.headers.get("set-cookie", "")
    second = client.get("/try")
    assert second.headers["location"] == first.headers["location"]
    assert _shop_count(tmp_path) == 1


def test_try_ignores_bogus_or_non_judge_cookie(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("mm_try", "bogus-token")
    first = client.get("/try")
    assert first.status_code in (302, 303)
    token, _slug = _make_shop(client, tmp_path)
    client.cookies.set("mm_try", token)
    second = client.get("/try")
    assert second.status_code in (302, 303)
    assert second.headers["location"] != f"/e/{token}"


def test_try_is_capped_per_ip(tmp_path):
    client = _client(tmp_path)
    for _ in range(10):
        client.cookies.clear()
        response = client.get("/try")
        assert response.status_code in (302, 303)
    client.cookies.clear()
    limited = client.get("/try")
    assert limited.status_code == 429
    assert _shop_count(tmp_path) == 10


# --- 4. no stray internal names in tracked text ---


def test_tracked_text_has_no_stray_names():
    # Character classes so this test itself holds no banned literal.
    pattern = "c[l]aude|a[n]thropic|c[h]atgpt"
    result = subprocess.run(
        ["git", "grep", "-i", "-E", pattern],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode in (0, 1), result.stderr
    assert result.stdout.strip() == "", result.stdout
