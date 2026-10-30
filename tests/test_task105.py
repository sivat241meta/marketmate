"""Task 105: Meta blue theme (v11).

The v9 purple accent becomes Meta blue: --accent #0866FF, --accent-ink
#0064E0, --accent-soft #E7F0FF, Meta neutrals, a blue-only mic gradient,
and the "Mm leaves" logo in pair E (Meta blue + green). Layout,
components and JS hooks are unchanged; only colours move.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "web" / "static" / "app.css"
TEMPLATES = ROOT / "app" / "web" / "templates"
BRAND = ROOT / "app" / "web" / "static" / "brand"

V11_TOKENS = {
    "--accent": "#0F766E",
    "--accent-ink": "#115E59",
    "--accent-soft": "#E6FAF6",
    "--accent-bright": "#14B8A6",
    "--ink": "#102A33",
    "--muted": "#56707A",
    "--line": "#E2EAEE",
    "--soft": "#F0F2F5",
    "--bg": "#F3F8FA",
    "--blue": "#0369A1",
    "--blue-soft": "#E8F4FD",
    "--sky": "#38BDF8",
    "--chrome-on": "#134E4A",
    "--chrome-accent": "#5EEAD4",
}


def test_v11_tokens_exist_with_new_values():
    css = CSS.read_text()
    for token, value in V11_TOKENS.items():
        assert re.search(rf"{re.escape(token)}\s*:\s*{re.escape(value)}",
                         css, re.IGNORECASE), token


def test_gradient_is_blue_and_only_on_the_mic_button():
    # Task 122: the one teal-to-sky gradient, on the mic buttons only.
    css = CSS.read_text()
    assert "--grad: linear-gradient(135deg,#0F766E,#0EA5A4 50%,#38BDF8)" \
        in css.replace("  ", " ")
    uses = [line for line in css.splitlines()
            if "var(--grad)" in line]
    assert len(uses) == 2, uses
    before_first, before_second = (css.split("var(--grad)")[0][-200:],
                                   css.split("var(--grad)")[1][-200:])
    assert ".bnav .mic span" in before_first
    assert ".mm-mic" in before_second


def test_new_badge_and_new_chip_use_accent_soft_and_ink():
    css = CSS.read_text()
    badge = re.search(r"\.new-badge\s*\{[^}]*\}", css).group(0)
    assert "var(--accent-soft)" in badge
    assert "var(--accent-ink)" in badge
    chip = re.search(r"\.chip\.c-new, \.pill\.pill-quote \{[^}]*\}",
                     css).group(0)
    assert "var(--accent-soft)" in chip
    assert "var(--accent-ink)" in chip


def test_accent_ink_class_renamed():
    css = CSS.read_text()
    assert ".accent-ink" in css
    assert ".purple-ink" not in css
    for name in ("home.html", "market.html"):
        text = (TEMPLATES / name).read_text()
        assert "purple-ink" not in text, name
        assert "accent-ink" in text, name


def test_inline_template_colours_are_blue():
    # Task 122: the v12 teal accent in the print templates; the hero
    # curve moved to the sellers page with the landing photos.
    sellers = (TEMPLATES / "sellers.html").read_text()
    assert "#A9C7FF" not in sellers and "#C4B5FD" not in sellers
    link_card = (TEMPLATES / "link_card.html").read_text()
    assert "#0F766E" in link_card
    tags = (TEMPLATES / "tags.html").read_text()
    assert "#0F766E" in tags


def test_logo_default_is_pair_e():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mm_brand_gen105", ROOT / "scripts" / "make_brand_assets.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.PAIRS["E"] == ("#0866FF", "#1FA34A")
    assert gen.DARK_LEFT["E"] == "#4D9BFF"
    assert gen.WORD_LEFT["E"] == "#0064E0"
    assert gen.PAIRS["F"] == ("#0F766E", "#38BDF8")
    assert gen.DARK_LEFT["F"] == "#5EEAD4"
    assert gen.WORD_LEFT["F"] == "#0F766E"
    import inspect

    assert inspect.signature(gen.write_svgs).parameters["pair"].default == "F"
    assert inspect.signature(gen.write_pngs).parameters["pair"].default == "F"
    mark = (BRAND / "mark.svg").read_text()
    assert "#0F766E" in mark and "#38BDF8" in mark
    dark = (BRAND / "mark-dark.svg").read_text()
    assert "#5EEAD4" in dark and "#38BDF8" in dark
    logo = (BRAND / "logo.svg").read_text()
    assert "#0F766E" in logo and "#38BDF8" in logo


def test_brand_doc_and_readme_note_pair_e():
    # Task 122: pair F (teal + soft blue) is the default now.
    doc = (ROOT / "docs" / "brand.md").read_text()
    assert "F (default)" in doc
    assert "#0F766E" in doc and "#5EEAD4" in doc
    readme = (ROOT / "README.md").read_text()
    assert "teal" in readme.lower()
