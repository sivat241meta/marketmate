"""Task 172: a permanent "Judge demo" button on the real website.

1. The public header (_public_header.html) and the home hero header
   (home.html) carry a "Judge demo" pill linking to /try, next to the
   sell actions, with title/aria-label for hackathon judges.
2. The home page shows one slim judges strip directly under the hero
   search block (badge + text + "Start the judge demo" -> /try).
3. Seller pages, the judge page, bills and the entry page show
   neither the pill nor the strip.
4. New strings go through t() in en/ta/hi.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_task84 import draft, make_client, seed_shop

from app.web.i18n import missing_keys, t_for

ROOT = Path(__file__).resolve().parent.parent
V13_CSS = ROOT / "app" / "web" / "static" / "css" / "v13.css"
FONT = ROOT / "app" / "web" / "static" / "fonts" / "PlusJakartaSans-Variable.ttf"

NEW_KEYS = (
    "judge.hdr_btn",
    "judge.hdr_tip",
    "judge.strip_btn",
    "judge.strip_txt",
)


def _seed(tmp_path):
    slug, token = seed_shop(tmp_path, "T172 Veg", "Koyambedu",
                            [draft("tomato", "thakkali", "30")])
    return make_client(tmp_path), slug, token


def _hero(html: str) -> str:
    return re.search(r'<header class="topbar">.*?</header>', html,
                     re.DOTALL).group(0)


def _sticky(html: str) -> str:
    return re.search(r'<header id="site-header".*?</header>', html,
                     re.DOTALL).group(0)


def _pill(head: str) -> str:
    pills = re.findall(r'<a class="judge-pill".*?</a>', head, re.DOTALL)
    assert len(pills) == 1, head[:400]
    return pills[0]


def _media(css: str, query: str) -> str:
    i = css.index(f"@media ({query})")
    i = css.index("{", i)
    depth, j = 0, i
    while True:
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1:j]
        j += 1


# --- 1. home page: pill in both headers + the strip ---------------------------


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_home_headers_carry_judge_pill(tmp_path, lang):
    client, _slug, _token = _seed(tmp_path)
    client.cookies.set("ui_lang", lang)
    html = client.get("/home").text
    t = t_for(lang)
    tip = t("judge.hdr_tip")
    for head in (_hero(html), _sticky(html)):
        pill = _pill(head)
        assert 'href="/try"' in pill, lang
        assert f'title="{tip}"' in pill, lang
        assert f'aria-label="{tip}"' in pill, lang
        assert pill.endswith(f">{t('judge.hdr_btn')}</a>"), lang
    # With the other header actions: after Start selling, before menu.
    hero, sticky = _hero(html), _sticky(html)
    assert hero.index("btn-dark") < hero.index("judge-pill"), lang
    assert sticky.index("btn-teal") < sticky.index("judge-pill"), lang
    for head in (hero, sticky):
        assert head.index("judge-pill") < head.index("hp-menu-btn"), lang


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_home_strip_under_search_block(tmp_path, lang):
    client, _slug, _token = _seed(tmp_path)
    client.cookies.set("ui_lang", lang)
    html = client.get("/home").text
    t = t_for(lang)
    assert html.index('class="search-row"') < html.index(
        'class="judge-strip"') < html.index('class="svc-row"'), lang
    strip = re.search(r'<div class="judge-strip".*?</div>', html,
                      re.DOTALL).group(0)
    assert t("entry.judge_badge") in strip, lang
    assert t("judge.strip_txt") in strip, lang
    assert 'href="/try"' in strip, lang
    assert t("judge.strip_btn") in strip, lang


# --- 2. other public-header pages show the pill -------------------------------


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_public_pages_show_header_pill(tmp_path, lang):
    client, slug, _token = _seed(tmp_path)
    client.cookies.set("ui_lang", lang)
    for url in ("/market", "/how", f"/s/{slug}"):
        head = _sticky(client.get(url).text)
        pill = _pill(head)
        assert 'href="/try"' in pill, (lang, url)
        assert t_for(lang)("judge.hdr_btn") in pill, (lang, url)


# --- 3. seller / judge / bills / entry pages show neither ---------------------


def _bill_token(tmp_path, token: str) -> str:
    from datetime import UTC, datetime
    from decimal import Decimal

    from app import db
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(
            lines=[QuoteLine(name_en="tomato", name_local="",
                             qty=Decimal(1), unit="kg",
                             unit_price=Decimal(30), per_amount=Decimal(1),
                             line_total=Decimal("30.00"), status="priced")],
            total=Decimal("30.00"), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        saved = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                source="seller", kind="bill", status="billed")
        row = db.get_quote_by_token(conn, saved)
        bill_token = db.ensure_bill_token(conn, row["id"])
        conn.commit()
        return bill_token
    finally:
        conn.close()


def test_hidden_pages_show_no_pill_or_strip(tmp_path):
    client, _slug, token = _seed(tmp_path)
    resp = client.get("/try")
    assert resp.status_code in (302, 303)
    judge_url = resp.headers["location"]
    assert judge_url.endswith("/judge")
    assert client.get(judge_url).status_code == 200
    bill_url = f"/b/{_bill_token(tmp_path, token)}"
    assert client.get(bill_url).status_code == 200
    for url in (f"/e/{token}", f"/e/{token}/bills", judge_url, bill_url):
        html = client.get(url).text
        assert "judge-pill" not in html, url
        assert "judge-strip" not in html, url


def test_entry_page_still_renders_without_pill(tmp_path):
    from test_task167 import make_client as fresh_client

    html = fresh_client(tmp_path).get("/").text
    assert 'class="entry-cards"' in html
    assert 'href="/home?enter=1"' in html
    assert 'href="/try"' in html
    assert "judge-pill" not in html
    assert "judge-strip" not in html


# --- 4. translations -----------------------------------------------------------


def test_new_keys_exist_in_en_ta_hi():
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        for key in NEW_KEYS:
            assert t(key) and t(key) != key, (lang, key)
    assert missing_keys() == {"ta": [], "hi": []}
    for lang in ("en", "ta", "hi"):
        t = t_for(lang)
        assert "Judge demo" in t("judge.hdr_btn"), lang
        assert "Judge demo" in t("judge.hdr_tip"), lang
        assert "judge demo" in t("judge.strip_btn").lower(), lang


# --- 5. CSS: a distinct pill, a slim strip, no 320px overflow ------------------


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1).replace(" ", "").lower()


def test_pill_and_strip_styles():
    css = V13_CSS.read_text()
    pill = _rule(css, "body.v13 .judge-pill")
    # A compact pill, visibly different from plain nav links.
    assert "white-space:nowrap" in pill
    assert "flex:none" in pill
    assert "min-height:44px" in pill
    assert "border-radius:999px" in pill
    assert "font-weight:800" in pill
    assert "var(--teal-soft)" in pill
    assert "var(--teal" in pill
    assert "width:" not in pill and "min-width:" not in pill
    strip = _rule(css, "body.v13 .judge-strip")
    assert "background:var(--teal-soft)" in strip
    assert "border-radius:18px" in strip
    assert "min-width:0" in strip
    assert "max-width:700px" in strip
    text = _rule(css, "body.v13 .judge-strip p")
    assert "min-width:0" in text
    cta = _rule(css, "body.v13 .judge-cta")
    assert "background:var(--teal)" in cta
    assert "min-height:44px" in cta
    assert "white-space:nowrap" in cta


def test_phone_rules_keep_pill_in_bar():
    css = V13_CSS.read_text()
    phone = _media(css, "max-width:700px")
    flat = phone.replace(" ", "")
    # Compact pill text; the bar keeps one row.
    assert "body.v13.judge-pill{font-size:12px" in flat
    assert "body.v13.topbar.top-actions.lang{display:none}" in flat
    assert "body.v13.stickybar.loc-mini.chev{display:none}" in flat
    assert "body.v13.loc-mini" in flat and "overflow:hidden" in flat
    assert ".topbar-in.brand" in flat and "flex:none" in flat
    # The strip stacks.
    assert "body.v13.judge-strip{flex-direction:column" in flat
    narrow = _media(css, "max-width:359.98px")
    assert "body.v13 .stickybar .hp-bag" in narrow
    assert "body.v13 .topbar .brand-word" in narrow
    assert "display:none" in narrow.replace(" ", "")
    mid = _media(css, "max-width:900px")
    assert "body.v13 .stickybar .brand-word" in mid


def _text_width_px(text: str, size: int) -> float:
    from PIL import ImageFont

    font = ImageFont.truetype(str(FONT), size)
    font.set_variation_by_axes([700])
    box = font.getbbox(text)
    return box[2] - box[0]


def test_header_row_fits_320_360_390():
    if not FONT.exists():
        pytest.skip("bundled font missing")
    try:
        from PIL import ImageFont  # noqa: F401
    except ImportError:
        pytest.skip("PIL missing")
    css = V13_CSS.read_text()
    phone = _media(css, "max-width:700px")
    compact = _rule(phone, "body.v13 .judge-pill")
    assert "font-size:12px" in compact
    assert "padding:8px10px" in compact
    # Pinned facts the budget below builds on: 44px icons/menu, the
    # 34px sticky mark, the 38px phone hero tile, row gaps.
    flat = css.replace(" ", "")
    assert "body.v13.icon-btn{position:relative;width:44px;height:44px" in flat
    assert "body.v13.menu-btn{display:none;color:#fff;width:44px;height:44px" in flat
    assert "body.v13.brand.mk{width:34px" in flat
    assert "body.v13.brand-tile{width:38px;height:38px" in phone.replace(" ", "")
    pill = _text_width_px("Judge demo", 12) + 2 * 10 + 2 * 1.5
    assert pill <= 100, pill
    loc_min = 20 + 6  # pin icon + gap; text ellipsizes, chevron hidden

    def sticky_row(viewport: int, bag: bool, word: bool) -> float:
        wrap = viewport - 32
        gap = 6 if viewport <= 380 else 8
        items = 34 + (118 if word else 0)  # mark (+ wordmark)
        actions = 44 + 44 + pill + 44 if bag else 44 + pill + 44
        gaps = 2 * gap + (3 if bag else 2) * 4
        return wrap - (items + actions + gaps + loc_min)

    def hero_row(viewport: int, word_px: float) -> float:
        wrap = viewport - 32
        gap = 6 if viewport <= 380 else 8
        brand = 38 if word_px == 0 else 38 + 10 + word_px
        return wrap - (brand + 44 + pill + 2 * gap)  # menu + pill

    word18 = _text_width_px("MarketMate", 18)
    word20 = _text_width_px("MarketMate", 20)
    # 320: bag hidden, hero wordmark hidden; 360/390: everything shows.
    assert sticky_row(320, bag=False, word=False) >= 8
    assert hero_row(320, 0) >= 8
    assert sticky_row(360, bag=True, word=False) >= 8
    assert hero_row(360, word18) >= 8
    assert sticky_row(390, bag=True, word=False) >= 8
    assert hero_row(390, word20) >= 8
