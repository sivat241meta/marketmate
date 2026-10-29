"""Task 95: "Mm leaves" logo in two colours (purple + green).

Pair A (purple #5F55EE + green #1FA34A) is the committed default; the
script's --pair option regenerates every asset in pairs B/C/D. The dark
seller chrome uses mark-dark.svg with a lighter left leaf.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "app" / "web" / "static" / "brand"

PAIRS = {
    "A": ("#5F55EE", "#1FA34A"),
    "B": ("#1FA34A", "#F28C28"),
    "C": ("#1B2A5C", "#1FA34A"),
    "D": ("#5F55EE", "#F28C28"),
}
DARK_LEFT = {"A": "#7B68EE", "B": "#1FA34A", "C": "#6C7FD8", "D": "#7B68EE"}


def _load_gen():
    spec = importlib.util.spec_from_file_location(
        "mm_brand_gen95", ROOT / "scripts" / "make_brand_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_assets_are_pair_A():
    for name in ("mark.svg", "logo.svg"):
        text = (BRAND / name).read_text()
        assert PAIRS["A"][0] in text and PAIRS["A"][1] in text, name


def test_pair_option_regenerates_every_pair(tmp_path):
    gen = _load_gen()
    gen.BRAND_DIR = tmp_path
    try:
        for pair, (left, right) in PAIRS.items():
            gen.write_svgs(pair)
            gen.write_pngs(pair)
            mark = (tmp_path / "mark.svg").read_text()
            assert left in mark and right in mark, pair
            logo = (tmp_path / "logo.svg").read_text()
            assert left in logo and right in logo, pair
            dark = (tmp_path / "mark-dark.svg").read_text()
            assert DARK_LEFT[pair] in dark and right in dark, pair
            assert Image.open(tmp_path / "favicon-16.png").size == (16, 16)
            assert Image.open(tmp_path / "icon-512.png").size == (512, 512)
    finally:
        gen.BRAND_DIR = BRAND


def _luminance(rgb: tuple[int, int, int]) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_dark_variant_lightens_weak_left_leaf():
    dark = (BRAND / "mark-dark.svg").read_text()
    assert DARK_LEFT["A"] in dark and PAIRS["A"][1] in dark
    chrome = (30, 31, 33)  # #1E1F21 seller top bar / rail
    assert _contrast((123, 104, 238), chrome) >= 3.5  # #7B68EE readable
    assert _contrast((123, 104, 238), chrome) > _contrast(
        (95, 85, 238), chrome)  # lighter than #5F55EE


def test_dark_bar_spots_use_mark_dark():
    base = (ROOT / "app" / "web" / "templates" / "base.html").read_text()
    assert "_brand_mark_dark(26)" in base  # seller top bar
    assert "_brand_mark_dark(30)" in base  # seller rail
    assert "/static/brand/mark-dark.svg" in base


def test_app_icons_white_corners_tile_border_and_both_colours():
    for name in ("apple-touch-icon.png", "icon-192.png", "icon-512.png"):
        img = Image.open(BRAND / name).convert("RGB")
        w, h = img.size
        for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            assert img.getpixel(p) == (255, 255, 255), (name, p)
        # Subtle 1px tile border on the middle of each edge.
        assert img.getpixel((1, h // 2)) == (226, 229, 234), name
        assert img.getpixel((w // 2, 1)) == (226, 229, 234), name
    # Maskable: white, no border (it would be clipped by the mask).
    maskable = Image.open(BRAND / "icon-maskable-512.png").convert("RGB")
    assert maskable.getpixel((0, 0)) == (255, 255, 255)
    assert maskable.getpixel((1, 256)) == (255, 255, 255)
    # Both leaf colours show on the white tile.
    img = Image.open(BRAND / "icon-512.png").convert("RGB")
    purple = green = 0
    for x in range(0, 512, 4):
        for y in range(0, 512, 4):
            px = img.getpixel((x, y))
            if math.dist(px, (95, 85, 238)) < 60:
                purple += 1
            if math.dist(px, (31, 163, 74)) < 60:
                green += 1
    assert purple > 500 and green > 500, (purple, green)


def test_readme_logo_line_updated():
    readme = (ROOT / "README.md").read_text()
    assert "Mm leaves" in readme
    assert "docs/brand.md" in readme
    assert "basket-M" not in readme


def test_brand_doc_covers_pairs_and_regeneration():
    doc = (ROOT / "docs" / "brand.md").read_text()
    assert "Mm leaves" in doc
    assert "--pair" in doc
    for pair, (left, right) in PAIRS.items():
        assert left in doc and right in doc, pair
    assert "mark-dark.svg" in doc
    assert "scripts/make_brand_assets.py" in doc
