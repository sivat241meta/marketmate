"""Task 150: MarketMate feels like a phone app (mobile polish).

1. First visit: no drawer auto-open at any width, default All areas,
   one-time location-chip pulse + dismissible "all markets" hint.
2. Seller phones (<=700px): one 56px header row (mark, one status pill
   with ellipsis, sound, profile); strip text in the pill; language in
   the profile menu + Settings; action bar docked above the bottom nav.
3. Tap targets >= 44px on phones, laptop look unchanged.
4. No text below 12px on phones.
5. Phone forms: >= 16px inputs, right keyboards, normal-case labels
   with a small "Required" hint.
6. Installable app: manifest fields, real install prompt on Android,
   iPhone instructions on iOS, static-only service worker + offline.
7. Speed: lazy below-fold images, -800 cover srcset on phones, font
   preload, small hero WebPs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from test_task84 import draft, make_client, seed_shop

from app.web.i18n import missing_keys, t_for

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "app" / "web" / "static" / "app.css"
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
SHOP13_CSS = ROOT / "app" / "web" / "static" / "css" / "shop13.css"
FORMS_CSS = ROOT / "app" / "web" / "static" / "css" / "forms.css"
PUBLIC_CSS = ROOT / "app" / "web" / "static" / "css" / "public.css"
SELLER_CSS = ROOT / "app" / "web" / "static" / "css" / "seller.css"
POPUPS_JS = ROOT / "app" / "web" / "static" / "popups.js"
HOME_JS = ROOT / "app" / "web" / "static" / "home.js"
PUBLIC_JS = ROOT / "app" / "web" / "static" / "public.js"
SW_JS = ROOT / "app" / "web" / "static" / "sw.js"


def _phone_block(css: str) -> str:
    starts = [match.start() for match in
              re.finditer(r"@media\s*\(max-width:\s*700px\)", css)]
    assert starts, "no 700px block"
    tail = css[starts[-1]:]
    end = tail.find("@media", 1)
    return tail if end == -1 else tail[:end]


def _seed_seller(tmp_path):
    _slug, token = seed_shop(
        tmp_path, "T150 Veg", "Koyambedu",
        [draft("tomato", "தக்காளி", "30"),
         draft("onion", "வெங்காயம்", "40")])
    client = make_client(tmp_path)
    client.cookies.set("ui_lang", "en")
    return client, token


# --- 1. first visit: no drawer, All areas, pulse + hint -----------------------


def test_no_drawer_auto_open_and_all_areas_default(tmp_path):
    src = POPUPS_JS.read_text()
    assert "openPop2(pop, null)" not in src
    client = make_client(tmp_path)
    html = client.get("/").text
    assert 'id="loc-drawer"' in html
    assert '<div class="mm-pop" id="loc-drawer" hidden>' in html
    assert t_for("en")("hp.all_areas") in html


def test_first_visit_hint_and_pulse_hooks(tmp_path):
    for lang in ("en", "ta", "hi"):
        assert t_for(lang)("hp.all_hint"), lang
    assert missing_keys() == {"ta": [], "hi": []}
    client = make_client(tmp_path)
    html = client.get("/").text
    assert "data-loc-hint" in html
    assert t_for("en")("hp.all_hint") in html
    assert '<p class="loc-hint" data-loc-hint hidden>' in html
    assert "data-loc-hint-x" in html
    js = HOME_JS.read_text()
    assert "data-loc-hint" in js
    assert "loc-pulse" in js
    assert "mm_area_hint_seen" in js
    css = V13_CSS.read_text()
    assert ".loc-hint" in css
    assert ".loc-pulse" in css
    assert "locpulse13" in css
    # The hint never widens the page: it shrinks inside 320px.
    hint = re.search(r"body\.v13 \.loc-hint\{([^}]*)\}", css).group(1)
    assert "min-width:0" in hint.replace(" ", "")
    assert "max-width:" in hint


# --- 2. compact seller header on phones ---------------------------------------


def test_seller_header_one_pill_profile_menu_and_settings_switch(tmp_path):
    client, token = _seed_seller(tmp_path)
    html = client.get(f"/e/{token}").text
    # One status pill with the waiting count, full text kept.
    assert html.count("seller-status") == 1
    assert "ss-t" in html
    # Profile menu carries Settings + the language switch.
    assert "data-prof" in html
    assert "prof-menu" in html
    assert "prof-lang" in html
    assert f'href="/e/{token}/settings"' in html
    assert 'class="circ"' in html
    assert "data-sound-toggle" in html
    # The strip stays in the DOM (laptop + honesty strings).
    assert 'class="ann"' in html
    assert "data-ui-toggle" in html
    # Settings hosts the switch too, with its own help line.
    settings = client.get(f"/e/{token}/settings").text
    assert "set-lang" in settings
    assert t_for("en")("set.ui_lang_help") in settings
    assert settings.count('data-ui-lang="en"') >= 1


def test_seller_phone_chrome_css_budgets_and_docking():
    phone = _phone_block(APP_CSS.read_text())
    flat = phone.replace(" ", "")
    # No separate strip/language row on phones.
    assert "body.is-seller.ann{display:none;}" in flat
    # One 56px header row with the tile mark.
    assert "body.is-seller.hdr{" in flat
    assert "height:56px" in flat
    assert ".brand-mark{display:block;}" in flat
    # Sticky bars dock directly above the bottom nav.
    assert "bottom:var(--bnav-h);}" in flat
    # Compact bottom nav keeps word-boundary wrap (Tasks 109-113).
    assert ".bnava{min-height:44px;" in flat
    seller_phone = _phone_block(SELLER_CSS.read_text()).replace(" ", "")
    assert "bottom:var(--bnav-h);}" in seller_phone
    assert "min-height:44px;" in seller_phone
    # Nothing hides behind the bars: body + content padding kept.
    full = APP_CSS.read_text()
    assert "padding-bottom: var(--bnav-h);" in full
    seller = SELLER_CSS.read_text()
    assert "padding-bottom: 230px;" in seller
    assert "padding-bottom: 140px;" in seller


# --- 3. tap targets >= 44px on phones -----------------------------------------


def test_phone_tap_area_css_and_back_link_classes(tmp_path):
    phone = _phone_block(APP_CSS.read_text())
    flat = phone.replace(" ", "")
    assert ".langa,.langbutton,.langb{" in flat
    assert "min-height:44px" in flat
    assert "min-width:44px" in flat
    assert ".back-linka{" in flat
    assert ".ai-group-heada{" in flat
    shop_phone = _phone_block(SHOP13_CSS.read_text()).replace(" ", "")
    assert ".crumbsa::after" in shop_phone
    assert "height:44px" in shop_phone
    # The small links render inside 44px rows.
    client, token = _seed_seller(tmp_path)
    live = client.get(f"/e/{token}/live").text
    assert 'class="back-link"' in live
    assert t_for("en")("live.back") in live
    bills_new = client.get(f"/e/{token}/bills/new").text
    assert 'class="back-link"' in bills_new
    # The #id session chips render only with AI calls; the template
    # carries them and the CSS gives them 44px targets.
    ai_src = (ROOT / "app" / "web" / "templates" / "ai.html").read_text()
    assert "ai-group-head" in ai_src
    assert client.get(f"/e/{token}/ai").status_code == 200


# --- 4. no text below 12px on phones ------------------------------------------


def test_phone_min_font_size_css():
    phone = _phone_block(V13_CSS.read_text()).replace(" ", "")
    for selector in (".tag-sample{font-size:12px}",
                     ".board.ok{font-size:12px}",
                     ".store-btnsmall{font-size:12px}",
                     ".deal.rel{font-size:12px}",
                     ".pill-live.best{font-size:12px}"):
        assert selector in phone, selector
    assert ".veg-tag{font-size:12px}" in _phone_block(
        SHOP13_CSS.read_text()).replace(" ", "")
    app_phone = _phone_block(APP_CSS.read_text())
    assert "font-size: 12px;" in app_phone
    assert ".land-photo figcaption { font-size: 12px; }" in app_phone


# --- 5. phone forms: keyboards + labels ---------------------------------------


def test_phone_keyboard_input_types(tmp_path):
    client, token = _seed_seller(tmp_path)
    new = client.get("/new").text
    assert 'type="tel"' in new
    assert 'inputmode="tel"' in new
    assert 'autocomplete="tel"' in new
    assert 'autocomplete="organization"' in new
    settings = client.get(f"/e/{token}/settings").text
    assert 'type="tel"' in settings
    assert 'inputmode="tel"' in settings
    bills_new = client.get(f"/e/{token}/bills/new").text
    assert 'inputmode="decimal"' in bills_new
    # The close/review/update/bill quantity rows render only with day
    # data; their templates carry the same decimal keyboards. (Task 159:
    # the review rows live in the cards partial shared with the judge page.)
    for name in ("close.html", "_review_cards.html", "update.html",
                 "bill.html"):
        text = (ROOT / "app" / "web" / "templates" / name).read_text()
        assert 'inputmode="decimal"' in text, name
        assert 'type="number"' in text, name


def test_phone_labels_normal_case_with_required_hint(tmp_path):
    client = make_client(tmp_path)
    assert 'class="req-hint"' in client.get("/new").text
    assert "required" in client.get("/new").text
    forms_phone = _phone_block(FORMS_CSS.read_text())
    assert "text-transform: none;" in forms_phone
    assert ".req-hint" in forms_phone
    assert ".field > .field-label .req { display: none; }" in forms_phone
    pub_phone = _phone_block(PUBLIC_CSS.read_text())
    assert "text-transform: none;" in pub_phone
    assert ".req-hint" in pub_phone
    app_phone = _phone_block(APP_CSS.read_text())
    assert "font-size: max(16px, 1em);" in app_phone


# --- 6. installable app -------------------------------------------------------


def test_manifest_fields_and_install_hooks(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/manifest.webmanifest").json()
    assert body["name"] == "MarketMate"
    assert body["short_name"] == "MarketMate"
    assert body["display"] == "standalone"
    assert body["theme_color"] == "#0F766E"
    assert body["background_color"]
    assert body["start_url"] == "/"
    purposes = [icon.get("purpose", "") for icon in body["icons"]]
    assert any("maskable" in purpose for purpose in purposes)
    sizes = {icon["sizes"] for icon in body["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    html = client.get("/").text
    assert "data-install" in html
    assert "data-ios-hint" in html
    assert t_for("en")("dash.install_ios") in html
    js = PUBLIC_JS.read_text()
    assert "beforeinstallprompt" in js
    assert "data-ios-hint" in js
    assert "iphone|ipad|ipod" in js


def test_sw_caches_static_only_with_offline_page(tmp_path):
    client = make_client(tmp_path)
    text = client.get("/sw.js").text
    assert "/e/" not in text
    assert "prices.json" not in text
    assert "mm-shell-v" in text
    assert "offline" in text.lower()
    assert 'request.mode === "navigate"' in text
    assert "/share" in text and "mm-share" in text
    # Every cached URL is a static file that exists on disk.
    urls = re.findall(r'"/static/[^"]+"', text)
    assert len(urls) > 40, "shell must cover css/js/fonts/icons"
    static = ROOT / "app" / "web" / "static"
    kinds = set()
    for quoted in urls:
        rel = quoted.strip('"').split("?", 1)[0]
        assert (static / rel.replace("/static/", "")).is_file(), rel
        kinds.add(rel.rsplit(".", 1)[1])
    assert {"css", "js", "ttf", "svg", "png"} <= kinds


# --- 7. speed on phones -------------------------------------------------------


def test_homepage_speed_hooks_and_small_floats(tmp_path):
    client = make_client(tmp_path)
    html = client.get("/").text
    assert 'rel="preload"' in html
    assert "PlusJakartaSans-Variable.ttf" in html
    assert 'as="font"' in html
    floats = re.findall(r"<img\b[^>]*hero-float[^>]*>", html)
    assert len(floats) == 9
    assert sum('loading="lazy"' in tag for tag in floats) == 7
    assert sum('loading="eager"' in tag for tag in floats) == 2
    assert all(".webp" in tag for tag in floats)
    for path in (ROOT / "app" / "web" / "static" / "img" / "v13").glob(
            "*.webp"):
        assert path.stat().st_size <= 32768, f"{path.name} too big"


def test_cover_srcset_uses_800_on_phones(tmp_path):
    from PIL import Image

    from app import db

    client, token = _seed_seller(tmp_path)
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        shop = db.shop_by_token(conn, token)
        from app.web.settings import save_cover

        img = Image.new("RGB", (1600, 1000), (90, 140, 60))
        import io

        buf = io.BytesIO()
        img.save(buf, "JPEG")
        name = save_cover(buf.getvalue(), data_dir / "photos" / "t150cover")
        db.set_shop_cover(conn, shop["id"], name)
    finally:
        conn.close()
    assert client.get("/m/t150cover-800.jpg").status_code == 200
    html = client.get("/").text
    assert "/m/t150cover-800.jpg 800w" in html
    assert "/m/t150cover.jpg 1600w" in html
    shop_html = client.get("/s/t150-veg").text
    assert "/m/t150cover-800.jpg 800w" in shop_html


def test_touched_js_syntax():
    node = shutil.which("node")
    assert node, "node is required for --check"
    for path in (POPUPS_JS, HOME_JS, PUBLIC_JS, SW_JS):
        result = subprocess.run([node, "--check", str(path)],
                                check=False, capture_output=True,
                                text=True)
        assert result.returncode == 0, (path.name, result.stderr)
