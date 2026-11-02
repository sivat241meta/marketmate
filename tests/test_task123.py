"""Task 123: chat-style voice/text composer instead of "upload".

Pins the shared composer macro (voice and voice+text modes), its use on the
five speak/type pages with unchanged form actions and field names, the
composer JS/CSS assets, and the en/ta/hi strings.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof


@pytest.fixture(autouse=True)
def _show_extras(monkeypatch):
    """Task 154: these pages predate SHOW_EXTRAS; keep extras visible."""
    monkeypatch.setenv("SHOW_EXTRAS", "1")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "web" / "templates"
COMPOSER_JS = ROOT / "app" / "web" / "static" / "composer.js"
COMPOSER_CSS = ROOT / "app" / "web" / "static" / "css" / "composer.css"


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, language="ta"):
    resp = client.post("/new", data={
        "name": "T123 Store", "phone": "+914400000123", "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _slug(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def _publish(tmp_path, token):
    from app.pipeline.names import CANONICAL_NAMES

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        draft = DraftItem(
            name_spoken="tomato", name_local=CANONICAL_NAMES["tomato"],
            name_en="tomato", variety=None,
            price_lines=[PriceLine(Decimal(40), Decimal(1), "kg")],
            qty=None, qty_unit=None,
            proof=Proof(quote="tomato 40", turn_ids=[], start_ms=0, end_ms=0),
            confirmed=True)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, [draft])
        db.set_published(conn, version_id, True)
    finally:
        conn.close()


def _render_macro(lang="en", **kwargs):
    from app.web.i18n import t_for

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.globals["t"] = t_for(lang)
    env.globals["static_url"] = lambda p: f"/static/{p}"
    args = ", ".join([f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                      for k, v in kwargs.items()])
    template = env.from_string(
        '{% from "_composer.html" import composer with context %}'
        f"{{{{ composer({args}) }}}}")
    return template.render()


def _composer_form(html, action):
    # Task 124: public pages carry the search pop-up composer too, so
    # pick the composer form posting to the page's own action.
    matches = re.findall(
        r'<form[^>]*data-composer-form[^>]*>.*?</form>', html, re.DOTALL)
    assert matches, "composer form missing"
    forms = [form for form in matches if f'action="{action}"' in form]
    assert forms, f"composer posts to {action}"
    return forms[0]


# --- 1. macro renders in both modes -------------------------------------------


def test_macro_voice_mode_has_mic_send_cancel_plus_with_labels():
    html = _render_macro(action="/e/tok/update")
    for hook in ("data-composer", "data-composer-form", "data-composer-mic",
                 "data-composer-send", "data-composer-cancel",
                 "data-composer-plus", "data-composer-menu",
                 "data-composer-thread"):
        assert hook in html, hook
    assert "data-composer-text" not in html
    assert "<textarea" not in html
    for hook in ("data-composer-mic", "data-composer-send",
                 "data-composer-cancel", "data-composer-plus"):
        tag = re.search(rf"<button[^>]*{hook}[^>]*>", html)
        assert tag, hook
        assert 'aria-label="' in tag.group(0), hook
    assert "composer.js" in html
    assert "composer.css" in html


def test_macro_voice_text_mode_has_growing_textarea():
    html = _render_macro(action="/x", text_field="items", placeholder="Say it",
                         mode="voice+text")
    assert "data-composer-text" in html
    assert 'name="items"' in html
    assert 'placeholder="Say it"' in html
    assert 'rows="1"' in html


def test_macro_video_menu_and_extra_fields():
    html = _render_macro(action="/x", field="video", accept_upload="video",
                         extra_fields={"speak_lang": "ta"})
    assert "Upload a video" in html
    assert "Take a video" in html
    assert "Upload a recording" in html
    assert 'name="speak_lang"' in html
    assert 'capture="environment"' in html


# --- 2. the five pages --------------------------------------------------------


def _pages(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    return client, [(f"/s/{slug}/quote", f"/s/{slug}/quote", "audio", "items"),
                    (f"/e/{token}/live", f"/e/{token}/upload", "video", None),
                    (f"/e/{token}/update", f"/e/{token}/update", "audio", None),
                    (f"/e/{token}/bills/new", f"/e/{token}/bills/new",
                     "audio", "items"),
                    (f"/e/{token}/purchases", f"/e/{token}/purchases/voice",
                     "audio", None)]


def test_each_page_includes_composer_with_same_action_and_field(tmp_path):
    client, pages = _pages(tmp_path)
    for url, action, field, text_field in pages:
        html = client.get(url).text
        assert "data-composer" in html, url
        assert "composer.js" in html, url
        assert "composer.css" in html, url
        form = _composer_form(html, action)
        assert f'name="{field}"' in form, (url, field)
        assert 'method="post"' in form, url
        if text_field:
            assert f'name="{text_field}"' in form, (url, text_field)
        else:
            assert "data-composer-text" not in html, url


def test_upload_recording_only_inside_plus_menu(tmp_path):
    client, pages = _pages(tmp_path)
    for url, _action, _field, _text in pages:
        html = client.get(url).text
        stripped = re.sub(r'<div class="composer-menu".*?</div>', "", html,
                          flags=re.DOTALL)
        assert "Upload a recording" not in stripped, url
        for tag in re.findall(r"<button[^>]*>.*?</button>", html, re.DOTALL):
            assert "Upload a recording" not in tag, url


def test_old_upload_buttons_are_gone(tmp_path):
    client, pages = _pages(tmp_path)
    html_by_url = {url: client.get(url).text for url, *_ in pages}
    for needle in ("Upload and quote", "Upload and check", "Upload and bill",
                   "Upload a video instead", "Or upload a recording",
                   "Choose recording", "rec-start", "rec-stop", "rec-status"):
        for url, html in html_by_url.items():
            assert needle not in html, (needle, url)


def test_empty_recording_falls_through_to_typed_list(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token)
    resp = client.post(
        f"/s/{slug}/quote",
        data={"items": "2 kg tomato", "customer_name": "Kannan"},
        files={"audio": ("empty.webm", b"", "audio/webm")})
    assert resp.status_code in (302, 303), resp.text
    assert resp.headers["location"].startswith("/q/"), \
        resp.headers["location"]


# --- 3. assets -----------------------------------------------------------------


def test_composer_js_check_and_single_global():
    node = shutil.which("node")
    assert node, "node is required for --check"
    result = subprocess.run([node, "--check", str(COMPOSER_JS)], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    source = COMPOSER_JS.read_text()
    assigned = re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=(?![=>])", source)
    assert assigned == ["initComposer"], assigned


def test_composer_js_init_harness():
    node = shutil.which("node")
    assert node, "node is required"
    result = subprocess.run([node, "tests/js/composer_init.test.mjs"],
                            cwd=ROOT, check=False, capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_composer_js_uses_analyser_waveform_and_status_poll():
    source = COMPOSER_JS.read_text()
    for needle in ("createAnalyser", "getByteFrequencyData", "MediaRecorder",
                   "getUserMedia", "FormData", "/status", "fetch(",
                   "initComposer"):
        assert needle in source, needle


def test_composer_css_theme_vars_and_reduced_motion():
    css = COMPOSER_CSS.read_text()
    for var in ("var(--accent)", "var(--accent-soft)", "var(--ink)",
                "var(--muted)", "var(--line)", "var(--card)"):
        assert var in css, var
    assert "@media (prefers-reduced-motion" in css
    assert "min-height: 44px" in css or "min-width: 44px" in css


# --- 4. strings ------------------------------------------------------------------


def test_composer_strings_exist_in_en_ta_hi():
    from app.web.i18n import STRINGS, t_for

    keys = ("composer.send", "composer.cancel", "composer.recording",
            "composer.sending", "composer.listening", "composer.understanding",
            "composer.done", "composer.try_again", "composer.record_again",
            "composer.https_hint", "composer.upload_recording",
            "composer.upload_video", "composer.take_video")
    for lang in ("en", "ta", "hi"):
        for key in keys:
            assert key in STRINGS[lang], (lang, key)
            assert t_for(lang)(key) != key, (lang, key)
    assert "Muse Voice" in t_for("en")("composer.listening")
    assert "Muse Spark" in t_for("en")("composer.understanding")


def test_pages_render_in_ta_and_hi(tmp_path):
    client, pages = _pages(tmp_path)
    for lang in ("ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url, _action, _field, _text in pages:
            resp = client.get(url)
            assert resp.status_code == 200, (lang, url)
            assert "data-composer" in resp.text, (lang, url)
