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
    "--accent": "#0866FF",
    "--accent-ink": "#0064E0",
    "--accent-soft": "#E7F0FF",
    "--ink": "#1C2B33",
    "--muted": "#65676B",
    "--line": "#E4E6EB",
    "--soft": "#F0F2F5",
    "--bg": "#F7F8FA",
    "--chrome-on": "#1B2B44",
    "--chrome-accent": "#4D9BFF",
}


def test_v11_tokens_exist_with_new_values():
    css = CSS.read_text()
    for token, value in V11_TOKENS.items():
        assert re.search(rf"{re.escape(token)}\s*:\s*{re.escape(value)}",
                         css, re.IGNORECASE), token


def test_gradient_is_blue_and_only_on_the_mic_button():
    css = CSS.read_text()
    assert "--grad: linear-gradient(135deg,#0064E0,#0081FB 55%,#00B2FF)" \
        in css.replace("  ", " ")
    uses = [line for line in css.splitlines()
            if "var(--grad)" in line]
    assert len(uses) == 1, uses
    assert ".bnav .mic span" in css.split("var(--grad)")[0][-200:]


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
    home = (TEMPLATES / "home.html").read_text()
    assert "#A9C7FF" in home  # hero curve, was light purple
    assert "#C4B5FD" not in home
    link_card = (TEMPLATES / "link_card.html").read_text()
    assert "#0866FF" in link_card
    tags = (TEMPLATES / "tags.html").read_text()
    assert "#0064E0" in tags


def test_logo_default_is_pair_e():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mm_brand_gen105", ROOT / "scripts" / "make_brand_assets.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.PAIRS["E"] == ("#0866FF", "#1FA34A")
    assert gen.DARK_LEFT["E"] == "#4D9BFF"
    assert gen.WORD_LEFT["E"] == "#0064E0"
    import inspect

    assert inspect.signature(gen.write_svgs).parameters["pair"].default == "E"
    assert inspect.signature(gen.write_pngs).parameters["pair"].default == "E"
    mark = (BRAND / "mark.svg").read_text()
    assert "#0866FF" in mark and "#1FA34A" in mark
    dark = (BRAND / "mark-dark.svg").read_text()
    assert "#4D9BFF" in dark and "#1FA34A" in dark
    logo = (BRAND / "logo.svg").read_text()
    assert "#0064E0" in logo and "#1FA34A" in logo


def test_brand_doc_and_readme_note_pair_e():
    doc = (ROOT / "docs" / "brand.md").read_text()
    assert "E (default)" in doc
    assert "#0866FF" in doc and "#4D9BFF" in doc
    readme = (ROOT / "README.md").read_text()
    assert "Meta blue" in readme
