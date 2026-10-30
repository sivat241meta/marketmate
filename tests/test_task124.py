"""Task 124: composer in the v12 design — merges tasks 122 + 123.

Pins: the Find-a-shop voice panel and the search pop-up mic both use
the voice+text composer posting to /market/voice (audio + q fields);
POST /market/voice accepts typed text as well as audio; the pop-up
mic toggles the composer; composer.css uses the v12 teal tokens.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

from test_task84 import _home, draft, make_client, seed_market, seed_shop

ROOT = Path(__file__).resolve().parent.parent
POPUPS_JS = ROOT / "app" / "web" / "static" / "popups.js"
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
COMPOSER_CSS = ROOT / "app" / "web" / "static" / "css" / "composer.css"


def _search_pop(html):
    return html.split('id="search-pop"')[1].split('id="filter-pop"')[0]


def _token(css, name):
    match = re.search(rf"{re.escape(name)}\s*:\s*(#[0-9A-Fa-f]{{6}})", css)
    assert match, name
    return match.group(1)


def _luminance(code):
    rgb = [int(code[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def channel(value):
        return (value / 12.92 if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4)

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(fore, back):
    lighter = max(_luminance(fore), _luminance(back))
    darker = min(_luminance(fore), _luminance(back))
    return (lighter + 0.05) / (darker + 0.05)


# --- 1. the Find-a-shop voice panel is the composer ---------------------------


def test_market_voice_panel_is_voice_text_composer(tmp_path):
    seed_market(tmp_path)
    html = make_client(tmp_path).get("/market").text
    panel = html.split('id="market-voice"')[1].split("</section>")[0]
    assert "data-voice-panel" in html
    assert "data-composer" in panel
    assert 'action="/market/voice"' in panel
    assert 'data-text-field="q"' in panel
    assert 'name="audio"' in panel
    assert 'name="q"' in panel
    assert "data-composer-text" in panel
    assert "composer.js" in html
    assert "composer.css" in html
    # Task 125: the old search card (with the voice tab and mic that
    # jumped to the panel) is gone; the query pill opens the search
    # pop-up, whose mic reveals the same composer.
    assert 'class="hp-search"' not in html
    assert "mkt-pill" in html
    # The old recorder markup is gone from the page.
    for hook in ("rec-start", "rec-stop", "rec-status", "market-audio",
                 "data-upload-url", "recorder.js", "Upload and search"):
        assert hook not in html, hook


# --- 2. the search pop-up mic reveals the same composer -----------------------


def test_search_popup_voice_posts_to_market_voice(tmp_path):
    seed_market(tmp_path)
    html = _home(make_client(tmp_path), "en")
    pop = _search_pop(html)
    assert "data-voice-toggle" in pop
    assert 'aria-controls="search-voice"' in pop
    assert 'aria-expanded="false"' in pop
    voice = pop.split('id="search-voice"')[1]
    assert "data-composer" in voice
    assert 'action="/market/voice"' in voice
    assert 'data-text-field="q"' in voice
    assert 'name="audio"' in voice
    # The composer form sits after the GET form, never nested in it.
    assert pop.index("</form>") < pop.index("data-composer-form")


def test_popup_voice_toggle_js():
    node = shutil.which("node")
    assert node, "node is required for --check"
    result = subprocess.run([node, "--check", str(POPUPS_JS)], check=False,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    src = POPUPS_JS.read_text()
    assert "data-voice-toggle" in src
    assert "aria-expanded" in src
    assert "initVoice" in src


# --- 3. /market/voice takes typed text as well as audio -----------------------


def _mock_text_search(monkeypatch):
    from app.market.search import Query, Want

    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")


def test_market_voice_typed_text_searches(tmp_path, monkeypatch):
    slug, _token = seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "40")])
    _mock_text_search(monkeypatch)
    client = make_client(tmp_path)
    resp = client.post("/market/voice", data={"q": "tomato"})
    assert resp.status_code == 200, resp.text
    assert f"/s/{slug}" in resp.text
    assert "₹40" in resp.text


def test_market_voice_empty_audio_falls_through_to_text(tmp_path,
                                                        monkeypatch):
    slug, _token = seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "40")])
    _mock_text_search(monkeypatch)
    client = make_client(tmp_path)
    resp = client.post(
        "/market/voice", data={"q": "tomato"},
        files={"audio": ("empty.webm", b"", "audio/webm")})
    assert resp.status_code == 200, resp.text
    assert f"/s/{slug}" in resp.text


def test_market_voice_audio_wins_over_text(tmp_path, monkeypatch):
    from app.market.search import Query, Want

    seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "40")])
    calls = {}

    class _Transcript:
        text = "tomato"

    def fake_transcribe(path, **_kw):
        calls["heard"] = True
        return _Transcript()

    monkeypatch.setattr("app.web.main.extract_audio",
                        lambda src, dst: dst)
    monkeypatch.setattr("app.web.main.transcribe_wav", fake_transcribe)
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")
    client = make_client(tmp_path)
    resp = client.post(
        "/market/voice", data={"q": "mango"},
        files={"audio": ("search.webm", b"fake-opus", "audio/webm")})
    assert resp.status_code == 200, resp.text
    assert calls.get("heard"), "audio must win when both are sent"
    assert "Heard: tomato" in resp.text


def test_market_voice_empty_post_is_422(tmp_path):
    seed_market(tmp_path)
    resp = make_client(tmp_path).post("/market/voice", data={})
    assert resp.status_code == 422


# --- 4. composer.css in the v12 teal theme ------------------------------------


def test_composer_css_uses_v12_tokens():
    css = COMPOSER_CSS.read_text()
    app = APP_CSS.read_text()
    for var in ("var(--accent)", "var(--accent-soft)", "var(--ink)",
                "var(--muted)", "var(--line)", "var(--card)",
                "var(--shadow-card)"):
        assert var in css, var
    assert "rgba(0, 0, 0" not in css
    assert ":focus-visible" in css
    # White on the teal accent (user bubbles, send button) and teal on
    # the mint wash (mic button) both pass 4.5:1.
    accent = _token(app, "--accent")
    soft = _token(app, "--accent-soft")
    assert _contrast("#FFFFFF", accent) >= 4.5, accent
    assert _contrast(accent, soft) >= 4.5, (accent, soft)


# --- 5. header + pop-ups + composer on every public page ----------------------


def test_public_pages_carry_header_popups_and_composer(tmp_path):
    slug, _token = seed_shop(tmp_path, "Kannan Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "40")])
    client = make_client(tmp_path)
    for url in ("/", "/market", f"/s/{slug}", "/sellers", "/how",
                f"/s/{slug}/quote"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert "data-public-header" in resp.text, url
        assert 'id="search-pop"' in resp.text, url
        assert "data-composer" in resp.text, url
        assert "composer.js" in resp.text, url
