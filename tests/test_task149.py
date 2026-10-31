"""Task 149: the shop page header must fit every screen in every language.

1. One shared header: /s/<slug> uses _public_header.html exactly like
   /market — no lang-btn in the header row; the language switch lives
   inside the More menu (desktop) and the phone sheet (mobile).
2. Priority+ nav: links never wrap; a small JS measure moves the
   rightmost links into a "More" dropdown one at a time until the
   header row fits (ResizeObserver + resize/load/fonts hooks), with a
   no-JS CSS fallback hiding For sellers / How it works below 1280px.
   The Start selling button shortens to icon + Sell/விற்க/बेचें.
3. Every scroller row and its parents carry min-width:0 +
   max-width:100% so rows scroll inside the page at every width.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from test_task84 import draft, make_client, seed_shop

from app.web.i18n import t_for

ROOT = Path(__file__).resolve().parent.parent
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
PUBLIC_CSS = ROOT / "app" / "web" / "static" / "css" / "public.css"
PNAV_JS = ROOT / "app" / "web" / "static" / "pnav.js"
POPUPS_JS = ROOT / "app" / "web" / "static" / "popups.js"
HEADER_HTML = ROOT / "app" / "web" / "templates" / "_public_header.html"

SHORT = {"en": "Sell", "ta": "விற்க", "hi": "बेचें"}


def _seed(tmp_path):
    seed_shop(tmp_path, "T149 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30"),
               draft("onion", "வெங்காயம்", "40")])
    # Shop pages render English + the shop's native language, so
    # Hindi needs its own Hindi-native shop.
    from app import db

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _slug, _token = db.create_shop(
            conn, name="T149 Hindi Veg", phone="+914400001499",
            area="Koyambedu", language="hi", currency="INR",
            shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            draft("tomato", "टमाटर", "30"),
            draft("onion", "प्याज़", "40")])
        db.set_published(conn, version_id, True)
    finally:
        conn.close()
    return make_client(tmp_path)


def _shop_html(client, lang: str) -> str:
    slug = "t149-hindi-veg" if lang == "hi" else "t149-veg"
    html = client.get(f"/s/{slug}?lang={lang}").text
    assert 'id="site-header"' in html, lang
    return html


def _header(html: str) -> str:
    return re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)


def _more_menu(head: str) -> str:
    return re.search(r'<span class="nav-more".*?</span>\s*</span>',
                     head, re.DOTALL).group(0)


# --- 1. one shared header, no lang-btn outside a menu --------------------------


def test_shop_header_matches_market_header(tmp_path):
    client = _seed(tmp_path)
    shop = _header(client.get("/s/t149-veg?lang=en").text)
    market = _header(client.get("/market").text)
    assert "data-public-header" in shop

    def norm(head: str) -> str:
        head = re.sub(r'<button type="button" class="loc-mini".*?</button>',
                      "<LOC>", head, flags=re.DOTALL)
        head = re.sub(r' class="is-active" aria-current="page"', "", head)
        head = re.sub(r' class=""', "", head)
        # Market uses cookie buttons, shop pages ?lang= links — the
        # switch kind is data, the component is shared.
        head = re.sub(r'<span class="lang".*?</span>\s*</span>',
                      "<LANG>", head, flags=re.DOTALL)
        return head

    assert norm(shop) == norm(market)


def test_no_lang_btn_outside_menus(tmp_path):
    client = _seed(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _shop_html(client, lang)
        head = _header(html)
        # The header row itself (brand / location / nav links /
        # actions) carries no language button at all.
        row = re.sub(r'<span class="nav-more".*?</span>\s*</span>', "",
                     head, flags=re.DOTALL)
        assert "lang-btn" not in row, lang
        assert "data-lang-btn" not in row, lang
        # The switch lives inside the More menu (desktop) and the
        # phone sheet (mobile) instead.
        menu = _more_menu(head)
        assert "data-ui-toggle" in menu, lang
        assert "?lang=en" in menu, lang
        sheet = html.split('id="mobile-nav"')[1].split("</nav>")[0]
        assert "lang-btn" in sheet, lang


def test_header_lang_links_cover_shop_language(tmp_path):
    client = _seed(tmp_path)
    menu = _more_menu(_header(client.get("/s/t149-veg").text))
    assert "?lang=en" in menu
    assert "?lang=ta" in menu


# --- 2. priority+ nav ----------------------------------------------------------


def test_more_dropdown_markup_and_priority_js(tmp_path):
    client = _seed(tmp_path)
    for lang in ("en", "ta", "hi"):
        head = _header(_shop_html(client, lang))
        nav = re.search(r'<nav class="nav dark".*?</nav>', head,
                        re.DOTALL).group(0)
        assert 'data-pnav' in nav, lang
        links = re.findall(r"<a [^>]*data-nav[\s>]", nav)
        assert len(links) == 5, lang
        assert 'data-nav-more' in nav, lang
        assert 'data-nav-more-btn' in nav, lang
        assert 'data-nav-more-list' in nav, lang
        assert t_for(lang)("nav.more") in nav, lang
        assert "pnav.js" in _shop_html(client, lang), lang
    src = PNAV_JS.read_text()
    assert "ResizeObserver" in src
    assert "scrollWidth" in src and "clientWidth" in src
    assert "fonts" in src


def test_nav_links_never_wrap_and_fallback_hides_two_below_1280():
    css = V13_CSS.read_text()
    nav = css.split("body.v13 .nav a{")[1].split("}")[0]
    assert "white-space:nowrap" in nav.replace(" ", "")
    menu_link = re.search(
        r"body\.v13 \.nav \.nav-more-menu a\{([^}]*)\}", css).group(1)
    assert "white-space:nowrap" in menu_link.replace(" ", "")
    narrow = css.split("@media (max-width:1280px)", 1)[1]
    narrow = narrow.split("@media", 1)[0]
    assert "html:not(.js)" in narrow
    assert "nth-of-type(4)" in narrow and "nth-of-type(5)" in narrow
    assert "display:none" in narrow.replace(" ", "")


def test_more_menu_and_indicator_styles():
    css = V13_CSS.read_text()
    flat = css.replace(" ", "")
    for selector in (".nav-more[hidden]{display:none}",
                     ".nav-more-menu", ".nav-more-btn",
                     ".nav-more-btn::after",
                     ".nav-more.open.nav-more-menu",
                     ".nav-more-btn.is-active"):
        assert selector.replace(" ", "") in flat, selector
    # The grow-from-left underline still works on plain links.
    assert ".nav a::after" in css


def test_start_selling_shortens_on_narrow_widths(tmp_path):
    client = _seed(tmp_path)
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        assert t("hp.sell_short") == SHORT[lang]
        head = _header(_shop_html(client, lang))
        sell = re.search(
            r'<a class="btn-teal".*?</a>', head, re.DOTALL).group(0)
        assert f'aria-label="{t("hp.start_selling")}"' in sell, lang
        assert t("hp.start_selling") in sell, lang
        assert SHORT[lang] in sell, lang
        assert "sell-short" in sell, lang
    css = V13_CSS.read_text()
    assert ".sell-short" in css and ".sell-full" in css
    assert "@media (max-width:1440px)" in css


def test_pnav_node_algorithm():
    node = shutil.which("node")
    assert node, "node is required for the pnav test"
    result = subprocess.run([node, "tests/js/pnav.test.mjs"],
                            cwd=ROOT, check=False, capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stderr


def test_touched_js_syntax():
    node = shutil.which("node")
    assert node, "node is required for --check"
    for path in (PNAV_JS, POPUPS_JS):
        result = subprocess.run([node, "--check", str(path)],
                                check=False, capture_output=True,
                                text=True)
        assert result.returncode == 0, (path.name, result.stderr)


# --- 3. scrollers shrink inside the page ---------------------------------------


def _bodies_for(css: str, selector: str) -> str:
    found = []
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        if selector in match.group(1):
            found.append(match.group(2))
    assert found, selector
    return "".join(found).replace(" ", "").lower()


def test_scroller_rows_and_parents_shrink():
    # The shop best-prices row + parents are pinned by Task 146; the
    # rows below had no shrink rule yet.
    v13 = V13_CSS.read_text()
    for selector in ("body.v13 .results-grid",
                     "body.v13 .mkt-shop-grid"):
        body = _bodies_for(v13, selector)
        assert "min-width:0" in body, selector
        assert "max-width:100%" in body, selector
    pub = PUBLIC_CSS.read_text()
    chips = _bodies_for(pub, "body.pub .chip-row")
    assert "min-width:0" in chips
    assert "max-width:100%" in chips
