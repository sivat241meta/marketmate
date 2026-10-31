"""Task 133: three small homepage hero fixes (design v13).

1. The voice card's text sits exactly where the anchor cards' text
   sits: the <button> must not use native button layout (which
   vertically centers content ~58px down), the title is the first
   child, and all art is absolutely positioned so it never pushes
   the text. The bubble sits above the mic, right-aligned, >= 8px
   clear of the pill.
2. On phones the round arrow sits below the pill with >= 8px gap on
   every card (taller Tamil cards, tightened text).
3. The phone headline keeps a real space where the wide-only break
   collapses: "...market prices. Order by voice. ...".

Vertical math assumes single-line English rows (Pango-measured text
widths: title 235px, sub 239px, pill 176px in 282px) and the
Pango-measured Tamil wrap counts pinned in test_phone_arrow_gap.
"""
from __future__ import annotations

import html as html_module
import re
from pathlib import Path

import pytest
from test_task84 import draft, make_client, seed_shop

from app.web.i18n import lookup

ROOT = Path(__file__).resolve().parent.parent
V13 = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
APP = (ROOT / "app" / "web" / "static" / "app.css").read_text()
HOME = (ROOT / "app" / "web" / "templates" / "home.html").read_text()


def _media(css: str, query: str) -> str:
    i = css.find(f"@media ({query})")
    i = css.find("{", i)
    depth, j = 0, i
    while True:
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1:j]
        j += 1


def _strip_media(css: str) -> str:
    out, i = [], 0
    while True:
        j = css.find("@media", i)
        if j == -1:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:j])
        k = css.find("{", j)
        depth, m = 0, k
        while True:
            if css[m] == "{":
                depth += 1
            elif css[m] == "}":
                depth -= 1
                if depth == 0:
                    break
            m += 1
        i = m + 1


DESK = _strip_media(V13)
PHONE = _media(V13, "max-width:700px")


def _block(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def _val(block: str, prop: str) -> str:
    m = re.search(r"(?<![\w-])" + re.escape(prop) + r":([^;}]+)", block)
    assert m, (prop, block)
    return m.group(1).strip()


def _px(block: str, prop: str) -> float:
    return float(_val(block, prop).removesuffix("px"))


def _margin_top(block: str) -> float:
    m = re.search(r"(?<![\w-])margin-top:([^;}]+)", block)
    if m:
        return float(m.group(1).strip().removesuffix("px"))
    return float(_val(block, "margin").split()[0].removesuffix("px"))


def _pad_top(block: str) -> float:
    return float(_val(block, "padding").split()[0].removesuffix("px"))


def _body_line_height() -> float:
    m = re.search(r"(?m)^body\s*\{([^}]*)\}", APP)
    assert m
    return float(_val(m.group(1), "line-height"))


def _seed(tmp_path):
    seed_shop(tmp_path, "T133 Veg", "Koyambedu",
              [draft("tomato", "தக்காளி", "30"),
               draft("onion", "வெங்காயம்", "40")])
    return make_client(tmp_path)


def test_voice_button_lays_out_like_anchor_cards():
    btn = _block(DESK, "body.v13 button.svc")
    assert "appearance:none" in btn.replace(" ", "")
    assert "-webkit-appearance:none" in btn.replace(" ", "")
    # No wrapper above the title: it is the button's first child.
    m = re.search(r'<button[^>]*class="svc"[^>]*>(.*?)</button>', HOME,
                  re.DOTALL)
    assert m
    assert m.group(1).lstrip().startswith('<span class="svc-t">')
    # The span title carries exactly the h2 title metrics.
    span = _block(DESK, "body.v13 .svc-t")
    h2 = _block(DESK, "body.v13 .svc h2")
    for prop in ("font-size", "font-weight", "letter-spacing",
                 "line-height"):
        assert _val(span, prop) == _val(h2, prop), prop
    assert _margin_top(span) == _margin_top(h2) == 0


def test_art_absolute_and_text_in_flow():
    for sel in (".svc-art", ".svc-art img", ".art-voice .bubble",
                ".art-voice .mic-big", ".wave", ".art-board .board",
                ".svc-go"):
        block = _block(DESK, "body.v13 " + sel)
        assert "position:absolute" in block.replace(" ", ""), sel
    for sel in (".svc-t", ".svc-sub", ".svc-pill"):
        assert "position" not in _block(DESK, "body.v13 " + sel), sel
    assert "position" not in _block(DESK, "body.v13 .svc h2")
    rel = _block(DESK, "body.v13 .svc h2,body.v13 .svc-t,"
                       "body.v13 .svc-sub,body.v13 .svc-pill")
    assert "position:relative" in rel.replace(" ", "")
    # Phones keep art absolute (bubble hides, so it clears trivially).
    assert "position" not in _block(PHONE, "body.v13 .svc-art")
    assert "position" not in _block(PHONE, "body.v13 .wave")
    assert "display:none" in _block(PHONE, "body.v13 .art-voice .bubble")
    mid = _media(V13, "max-width:1100px")
    assert "display:none" in _block(mid, "body.v13 .art-voice .bubble")
    # In every card the art container comes after the text in the DOM.
    row = HOME[HOME.index("svc-row"):HOME.index('id="fresh"')]
    cards = re.split(r'(?=<a class="svc"|<button[^>]*class="svc")', row)[1:]
    assert len(cards) == 3
    for card in cards:
        assert card.index("svc-pill") < card.index("svc-art")


def test_desktop_bubble_clearance():
    card = _block(DESK, "body.v13 .svc")
    card_h, pad = _px(card, "height"), _pad_top(card)
    title = _block(DESK, "body.v13 .svc h2")
    title_h = _px(title, "font-size") * float(_val(title, "line-height"))
    sub = _block(DESK, "body.v13 .svc-sub")
    assert "line-height" not in sub  # inherits body 1.5
    sub_h = _px(sub, "font-size") * _body_line_height()
    pill = _block(DESK, "body.v13 .svc-pill")
    pill_h = (_px(pill, "font-size") * float(_val(pill, "line-height"))
              + 2 * _pad_top(pill))
    pill_bottom = (pad + title_h + _margin_top(sub) + sub_h
                   + _px(pill, "margin-top") + pill_h)
    bub = _block(DESK, "body.v13 .art-voice .bubble")
    bub_h = (_px(bub, "font-size") * float(_val(bub, "line-height"))
             + 2 * _pad_top(bub))
    b1 = _block(DESK, "body.v13 .art-voice .b1")
    bub_top = card_h - _px(b1, "bottom") - bub_h
    assert bub_top - pill_bottom >= 8
    mic = _block(DESK, "body.v13 .art-voice .mic-big")
    assert _px(b1, "right") == _px(mic, "right")  # right-aligned
    assert card_h - _px(b1, "bottom") < card_h - _px(mic, "bottom")


def test_phone_arrow_below_pill():
    card = _block(PHONE, "body.v13 .svc")
    h_base, pad = _px(card, "height"), _pad_top(card)
    h_ta = _px(_block(PHONE, "body.v13 .svc:lang(ta)"), "height")
    title = _block(PHONE, "body.v13 .svc h2,body.v13 .svc-t")
    assert "line-height" not in title  # inherits desktop 1.05
    desk_title = _block(DESK, "body.v13 .svc h2")
    title_ln = _px(title, "font-size") * float(_val(desk_title,
                                                   "line-height"))
    sub = _block(PHONE, "body.v13 .svc-sub")
    sub_ln = _px(sub, "font-size") * float(_val(sub, "line-height"))
    pill = _block(PHONE, "body.v13 .svc-pill")
    assert "line-height" not in pill  # inherits desktop 1.3
    desk_pill = _block(DESK, "body.v13 .svc-pill")
    pill_ln = _px(pill, "font-size") * float(_val(desk_pill,
                                                 "line-height"))
    go = _block(PHONE, "body.v13 .svc-go")
    # (title, sub, pill) line counts are Pango-measured at 320/360/390;
    # (2,2,2) is the envelope covering every card and language.
    cases = [(1, 1, 1, h_base), (1, 1, 1, h_ta), (1, 1, 2, h_ta),
             (1, 2, 2, h_ta), (2, 1, 2, h_ta), (2, 2, 2, h_ta)]
    for tls, sls, pls, height in cases:
        bottom = (pad + tls * title_ln + _px(sub, "margin-top")
                  + sls * sub_ln + _px(pill, "margin-top")
                  + pls * pill_ln + 2 * _pad_top(pill))
        arrow_top = height - _px(go, "bottom") - _px(go, "height")
        assert arrow_top - bottom >= 8, (tls, sls, pls, height)


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_headline_space(tmp_path, lang):
    pat = ("{{ t('v13.hero_a') }} <span class=\"h1-br\"><br></span>"
           "{{ t('v13.hero_b') }}")
    assert pat in HOME
    flat = PHONE.replace(" ", "")
    assert ".h1-br{display:none}" in flat
    assert "h1br{display:none}" not in flat
    client = _seed(tmp_path)
    client.cookies.set("ui_lang", lang)
    m = re.search(r"<h1>(.*?)</h1>", client.get("/").text, re.DOTALL)
    assert m
    h1 = html_module.unescape(m.group(1))
    a, b, c = (lookup("v13.hero_a", lang), lookup("v13.hero_b", lang),
               lookup("v13.hero_c", lang))
    phone = re.sub(r'<span class="h1-br"><br></span>', "", h1)
    phone_text = re.sub(r"<[^>]+>", "", phone)
    assert phone_text == f"{a} {b} {c}"
    assert "  " not in phone_text
    wide = h1.replace('<span class="h1-br"><br></span>', "\n")
    assert wide.split("\n")[0] == a + " "  # trailing space collapses


def test_hooks_routes_i18n_kept(tmp_path):
    html = _seed(tmp_path).get("/").text
    m = re.search(r'<button[^>]*class="svc"[^>]*>', html)
    assert m
    for hook in ("data-search-open", "data-search-voice",
                 'aria-haspopup="dialog"', 'aria-controls="search-pop"'):
        assert hook in m.group(0), hook
    assert 'class="svc" href="/market' in html
    assert 'class="svc" href="/new"' in html
    keys = ["v13.hero_a", "v13.hero_b", "v13.hero_c", "v13.svc_find_t",
            "v13.svc_find_s", "v13.svc_voice_t", "v13.svc_voice_s",
            "v13.svc_voice_p", "v13.svc_sell_t", "v13.svc_sell_s",
            "v13.svc_sell_p"]
    for key in keys:
        for lang in ("en", "ta", "hi"):
            assert lookup(key, lang), (key, lang)


def test_overflow_guards_present():
    assert re.search(r"body\.v13\{[^}]*overflow-x:hidden", DESK)
    assert "overflow:hidden" in _block(DESK, "body.v13 .v13-hero")
    assert "overflow:hidden" in _block(DESK, "body.v13 .svc")
    assert "width:calc(100%-32px)" in PHONE.replace(" ", "")
