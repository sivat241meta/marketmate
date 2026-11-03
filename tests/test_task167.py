"""Task 167: a simple entry page before the existing website.

GET / shows the entry page only to browsers without the mm_entered
cookie; everyone else gets today's home page at / exactly as now.
"Visit MarketMate" goes to /home?enter=1 (stamps the cookie, lands on
today's home page); "Judge demo" links to /try. Any GET of an existing
page other than / stamps the cookie too. No existing page changes.
"""

from __future__ import annotations

import html as htmlmod
import re
from pathlib import Path

from fastapi.testclient import TestClient
from test_task84 import draft, seed_shop
from test_task84 import make_client as entered_client

from app.config import load_settings
from app.web.i18n import missing_keys, t_for
from app.web.main import create_app

ROOT = Path(__file__).resolve().parent.parent
ENTRY_CSS = ROOT / "app" / "web" / "static" / "css" / "entry.css"

ENTRY_KEYS = (
    "entry.title",
    "entry.visit_t",
    "entry.visit_d",
    "entry.visit_btn",
    "entry.judge_t",
    "entry.judge_badge",
    "entry.judge_d",
    "entry.judge_btn",
    "entry.footer",
)


def make_client(tmp_path):
    """Fresh browser: no mm_entered cookie, nothing entered yet."""
    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)),
                      follow_redirects=False)


def _assert_entered_cookie(resp):
    raw = resp.headers.get("set-cookie", "")
    assert "mm_entered=1" in raw, raw
    low = raw.lower()
    assert "max-age=31536000" in low, raw
    assert "path=/" in low, raw
    assert "samesite=lax" in low, raw


def _assert_home(html: str) -> None:
    assert 'id="hero"' in html
    assert "entry-cards" not in html


def _assert_entry(html: str) -> None:
    assert 'class="entry-cards"' in html
    assert 'href="/home?enter=1"' in html
    assert 'href="/try"' in html
    assert 'id="hero"' not in html


# --- 1. / without the cookie shows the entry page -----------------------------


def test_root_without_cookie_shows_entry_with_both_links(tmp_path):
    html = htmlmod.unescape(make_client(tmp_path).get("/").text)
    _assert_entry(html)
    text = t_for("en")
    assert text("entry.visit_t") in html
    assert text("entry.visit_d") in html
    assert text("entry.visit_btn") in html
    assert text("entry.judge_t") in html
    assert text("entry.judge_badge") in html
    assert text("entry.judge_d") in html
    assert text("entry.judge_btn") in html
    assert text("entry.footer") in html
    assert "muse-voice-transcribe-1.0" in html
    assert "muse-spark-1.3" in html
    assert "sam-3.1" in html
    # Language switch like the rest of the site.
    assert "data-ui-toggle" in html
    assert "MarketMate" in html


def test_root_without_cookie_sets_no_cookie(tmp_path):
    resp = make_client(tmp_path).get("/")
    assert resp.status_code == 200
    assert "mm_entered" not in resp.headers.get("set-cookie", "")


# --- 2. entered browsers get today's home page ---------------------------------


def test_root_with_cookie_matches_home(tmp_path):
    seed_shop(tmp_path, "T167 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30")])
    client = entered_client(tmp_path)
    home = client.get("/home").text
    _assert_home(home)
    # Task 171: the cookie alone is not enough; in-site navigation
    # (a same-host Referer) reads today's home page at /.
    root = client.get("/",
                      headers={"referer": "http://testserver/market"}).text
    _assert_home(root)
    assert root == home


def test_home_always_serves_home_without_cookie(tmp_path):
    seed_shop(tmp_path, "T167 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30")])
    html = make_client(tmp_path).get("/home").text
    _assert_home(html)


# --- 3. the cookie --------------------------------------------------------------


def test_home_enter_sets_cookie(tmp_path):
    resp = make_client(tmp_path).get("/home?enter=1")
    assert resp.status_code == 200
    _assert_entered_cookie(resp)
    _assert_home(resp.text)


def test_shop_page_sets_cookie(tmp_path):
    slug, _token = seed_shop(tmp_path, "T167 Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "30")])
    resp = make_client(tmp_path).get(f"/s/{slug}")
    assert resp.status_code == 200
    _assert_entered_cookie(resp)


def test_pages_mark_entered(tmp_path):
    slug, _token = seed_shop(tmp_path, "T167 Veg", "Koyambedu",
                             [draft("tomato", "தக்காளி", "30")])
    for url in ("/market", "/sellers", "/how", f"/s/{slug}",
                "/market?q=tomato"):
        resp = make_client(tmp_path).get(url)
        assert resp.status_code == 200, url
        _assert_entered_cookie(resp)


def test_try_marks_entered(tmp_path):
    resp = make_client(tmp_path).get("/try")
    assert resp.status_code in (302, 303)
    _assert_entered_cookie(resp)


def test_json_static_and_media_set_no_cookie(tmp_path):
    client = make_client(tmp_path)
    for url in ("/market/suggest.json?q=tomato",
                "/static/app.css",
                "/static/css/entry.css",
                "/sw.js",
                "/app-qr.png"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert "mm_entered" not in resp.headers.get("set-cookie", ""), url


# --- 4. languages ---------------------------------------------------------------


def test_entry_keys_exist_in_en_ta_hi():
    for lang in ("en", "ta", "hi"):
        text = t_for(lang)
        for key in ENTRY_KEYS:
            assert text(key) and text(key) != key, (lang, key)
    assert missing_keys() == {"ta": [], "hi": []}


def test_entry_renders_ta_and_hi(tmp_path):
    for lang in ("ta", "hi"):
        client = make_client(tmp_path)
        client.cookies.set("ui_lang", lang)
        html = htmlmod.unescape(client.get("/").text)
        _assert_entry(html)
        text = t_for(lang)
        assert text("entry.visit_t") in html
        assert text("entry.judge_t") in html
        assert text("entry.judge_badge") in html
        assert text("entry.judge_btn") in html
        assert text("entry.footer") in html


# --- 5. narrow widths: no horizontal overflow ------------------------------------


def _bodies_for(css: str, selector: str) -> str:
    found = []
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        if selector in match.group(1):
            found.append(match.group(2))
    assert found, selector
    return "".join(found).replace(" ", "").lower()


def _first_rule(css: str, selector: str) -> str:
    """Normalised body of the first rule for *selector* (outside @media)."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1).replace(" ", "").lower()


def test_entry_cards_stack_on_phones_side_by_side_on_laptop():
    css = ENTRY_CSS.read_text()
    base = _first_rule(css, ".entry-cards")
    assert "grid-template-columns:minmax(0,1fr)" in base
    assert "minmax(0,1fr)minmax(0,1fr)" not in base
    flat = css.replace(" ", "").lower()
    assert "@media(min-width:720px)" in flat
    assert "grid-template-columns:minmax(0,1fr)minmax(0,1fr)" in flat


def test_entry_blocks_shrink_and_wrap():
    css = ENTRY_CSS.read_text()
    for selector in (".entry-wrap", ".entry-cards", ".entry-card",
                     ".entry-foot"):
        body = _bodies_for(css, selector)
        assert "min-width:0" in body, selector
        assert "max-width:100%" in body, selector
    assert "overflow-wrap:anywhere" in _bodies_for(css, ".entry-card p")
    assert "overflow-wrap:anywhere" in _bodies_for(css, ".entry-foot")


def test_entry_css_has_no_wide_fixed_widths():
    css = "\n".join(line for line in ENTRY_CSS.read_text().splitlines()
                    if "@media" not in line)
    for match in re.finditer(r"(?<![a-z-])(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(match.group(1)) <= 320, match.group(0)


_WIDE_STYLE = re.compile(
    r'style="[^\"]*(?:^|[;\s])(?:width|min-width)\s*:\s*(\d+)px')
_WIDTH_ATTR = re.compile(r"<(?!img\b)[a-z][^>]*?\swidth=\"(\d+)\"")


def test_entry_html_has_no_wide_fixed_widths(tmp_path):
    for lang in ("en", "ta", "hi"):
        client = make_client(tmp_path)
        client.cookies.set("ui_lang", lang)
        html = client.get("/").text
        assert ('name="viewport"' in html
                and "width=device-width" in html), lang
        for match in _WIDE_STYLE.finditer(html):
            assert int(match.group(1)) <= 390, (lang, match.group(0)[:80])
        for match in _WIDTH_ATTR.finditer(html):
            assert int(match.group(1)) <= 390, (lang, match.group(0)[:80])
