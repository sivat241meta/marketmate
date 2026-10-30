"""Task 75: finish merging Task 73 (MarketMate logo drawn in code) into main.

The pages merged after Task 73 branched (market, settings, new shop) inherit
the brand logo from base.html; the print link card carries the mark like the
other PDFs; no old gradient logo square remains (the mic button keeps its
gradient).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "web" / "templates"
CSS = ROOT / "app" / "web" / "static" / "app.css"


def test_merged_pages_inherit_logo_from_base():
    base = (TEMPLATES / "base.html").read_text()
    assert "/static/brand/logo.svg" in base  # full logo on white headers
    assert "/static/brand/mark.svg" in base  # mark on dark seller chrome
    for page in ("market.html", "settings.html", "new_shop.html"):
        text = (TEMPLATES / page).read_text()
        assert '{% extends "base.html" %}' in text


def test_link_card_carries_brand_mark():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
    env.globals["t"] = lambda key, **kw: key
    html = env.get_template("link_card.html").render(
        shop={"name": "S"}, seller_url="http://x/e/tok",
        qr_data_uri="data:image/png;base64,AA",
        fonts_uri="FONTS", brand_uri="BRAND")
    assert 'src="BRAND/mark.svg"' in html


def test_no_old_gradient_logo_square():
    haystacks = [CSS.read_text()]
    haystacks += [p.read_text() for p in sorted(TEMPLATES.glob("*.html"))]
    for hay in haystacks:
        assert "logo-sq" not in hay
        assert "_mark()" not in hay
        assert 'class="mk"' not in hay
    css = CSS.read_text()
    assert ".bnav .mic span" in css
    # Task 122: the gradient lives on the voice mic and the search
    # pop-up mic only.
    assert css.count("var(--grad)") == 2  # mic buttons only
