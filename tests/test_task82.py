"""Task 82: after merging tasks 76/79/81 and 80 into main.

Covers: the Meta AI calls page uses the Fluent object icons (robot for
the page, stat icons with labels) and the shared shell stylesheet; the
landing page's Built-with-Meta block links to the Meta AI calls note;
the README credits photos, icons, font and logo and mentions the AI
calls page.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.web.main import create_app

ROOT = Path(__file__).resolve().parent.parent
AI_URL = ("https://github.com/sivat241meta/marketmate"
          "/blob/main/README.md#meta-ai-calls")


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings(
        {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _create_shop(client: TestClient) -> str:
    response = client.post("/new", data={
        "name": "T82 Store", "phone": "+914400000082", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"].rsplit("/e/", 1)[1]


def test_ai_page_uses_object_icons_with_labels(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/ai").text
    for name, sizes in (("robot", ("28", "56")),
                          ("call", ("28",)),
                          ("cash", ("28",)),
                          ("clock", ("28",))):
        imgs = re.findall(
            rf'<img class="obj"[^>]*icons/fluent/{name}\.svg[^>]*>', html)
        assert imgs, f"ai page missing {name} object icon"
        for img in imgs:
            size = re.search(r'width="(\d+)"', img).group(1)
            assert size in sizes, img
            assert f'height="{size}"' in img, img
            assert 'alt=""' in img, img
    for label in ("Calls today", "Cost today", "Average time"):
        assert label in html, label


def test_ai_page_uses_shared_shell_stylesheet(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}/ai").text
    assert "/static/app.css" in html


def test_landing_meta_block_links_to_ai_calls_note(tmp_path):
    # Task 127: the v13 "How the prices get here" cards name the Meta
    # models and link to /how for the full story.
    client = _client(tmp_path)
    html = client.get("/").text
    meta = html.split('id="how"')[1].split('id="app"')[0]
    for known in ("muse-voice-transcribe-1.0", "muse-spark-1.3",
                  "sam-3.1"):
        assert known in meta, known
    assert 'href="/how"' in meta


def test_readme_credits_and_ai_calls_line():
    readme = (ROOT / "README.md").read_text()
    for name in ("Frédéric Barriol", "Ashwini Chaudhary", "Aditya Sethia",
                 "Abdullah Azeez", "Emil Widlund", "Unsplash"):
        assert name in readme, name
    assert "Icons: Fluent Emoji (Flat) by Microsoft, MIT licence." in readme
    assert "Inter" in readme and "OFL" in readme
    assert "drawn in code by Muse Code" in readme
    assert "## Meta AI calls" in readme
    assert '"Meta AI calls" page' in readme
