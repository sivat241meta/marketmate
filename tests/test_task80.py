"""Task 80: refined MarketMate logo (basket taper, rim, handle, produce, small variant).

The generator script emits SVGs + PNGs/ICO from one Bezier geometry; these
tests pin the outputs (names, sizes, transparency, no font-dependent SVG)
and check the 16px favicon keeps distinct basket/produce/handle colours.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "app" / "web" / "static" / "brand"

PNG_SIZES = {
    "mark-64.png": (64, 64),
    "mark-256.png": (256, 256),
    "favicon-16.png": (16, 16),
    "favicon-32.png": (32, 32),
    "apple-touch-icon.png": (180, 180),
    "icon-192.png": (192, 192),
    "icon-512.png": (512, 512),
    "icon-maskable-512.png": (512, 512),
}
LOGO_HEIGHTS = {"logo-full.png": 160, "logo-full@2x.png": 320}


def _load_gen():
    spec = importlib.util.spec_from_file_location(
        "mm_brand_gen", ROOT / "scripts" / "make_brand_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_brand_files_and_sizes():
    for name, size in PNG_SIZES.items():
        img = Image.open(BRAND / name)
        assert img.size == size, (name, img.size)
    for name, height in LOGO_HEIGHTS.items():
        img = Image.open(BRAND / name)
        assert img.size[1] == height, (name, img.size)
        assert img.size[0] > img.size[1], name  # lockup is wider than tall
    ico = Image.open(BRAND / "favicon.ico")
    assert ico.info["sizes"] == {(16, 16), (32, 32), (48, 48)}
    for name in ("mark.svg", "logo.svg"):
        ET.parse(str(BRAND / name))  # well-formed XML


def test_brand_svgs_have_no_text_or_image():
    for name in ("mark.svg", "logo.svg"):
        text = (BRAND / name).read_text()
        assert "<text" not in text and "<image" not in text, name
        assert "<path" in text, name
    logo = (BRAND / "logo.svg").read_text()
    assert "#1B2A5C" in logo and "#2DA94F" in logo  # two-tone wordmark


def _corners_transparent(img: Image.Image) -> bool:
    img = img.convert("RGBA")
    w, h = img.size
    return all(img.getpixel(p)[3] < 16
               for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)))


def test_brand_transparency():
    for name in ("mark-64.png", "mark-256.png", "favicon-16.png",
                 "favicon-32.png", "logo-full.png", "logo-full@2x.png"):
        assert _corners_transparent(Image.open(BRAND / name)), name
    # The mark itself is substantially opaque (not a faint smudge).
    px = Image.open(BRAND / "mark-64.png").convert("RGBA").load()
    opaque = sum(1 for x in range(64) for y in range(64) if px[x, y][3] > 128)
    assert opaque / (64 * 64) > 0.20


def test_brand_outputs_deterministic():
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(BRAND.iterdir())}
    gen = _load_gen()
    gen.write_svgs()
    gen.write_pngs()
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(BRAND.iterdir())}
    assert before == after


def test_favicon_16keeps_three_colour_groups():
    """The 16px favicon must not collapse into one blob: basket, produce
    and handle colours must each own a solid set of pixels."""
    img = Image.open(BRAND / "favicon-16.png").convert("RGBA")
    groups = {
        "basket": [(140, 208, 58), (34, 169, 85), (31, 111, 214)],
        "produce": [(232, 65, 44), (245, 154, 35)],
        "handle": [(30, 158, 71)],
    }
    counts = dict.fromkeys(groups, 0)
    for x in range(16):
        for y in range(16):
            r, g, b, a = img.getpixel((x, y))
            if a < 128:
                continue
            best, dist = None, 1e9
            for name, anchors in groups.items():
                for c in anchors:
                    d = math.dist((r, g, b), c)
                    if d < dist:
                        best, dist = name, d
            if dist < 60:
                counts[best] += 1
    assert counts["basket"] >= 30, counts
    assert counts["produce"] >= 6, counts
    assert counts["handle"] >= 5, counts


def test_small_size_variant_is_simplified():
    """favicon-32 is rendered from the simplified variant, not a plain
    downscale of the full-detail mark."""
    full_down = Image.open(BRAND / "mark-256.png").convert("RGBA").resize(
        (32, 32), Image.LANCZOS).load()
    small = Image.open(BRAND / "favicon-32.png").convert("RGBA").load()
    diff = sum(1 for x in range(32) for y in range(32)
               if math.dist(full_down[x, y][:3], small[x, y][:3]) > 20)
    assert diff / (32 * 32) > 0.05, diff


def _path_points(d: str) -> tuple[list[float], list[float]]:
    """All ink x/y coordinates of an absolute-command path (control points
    included, so the bbox is a safe outer bound)."""
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "S": 4,
             "T": 2, "A": 7, "Z": 0}
    toks = re.findall(r"[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)", d)
    xs, ys, cx, cy, sx, sy, cmd = [], [], 0.0, 0.0, 0.0, 0.0, None
    i = 0
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i].upper()
            i += 1
            if cmd == "Z":
                cx, cy = sx, sy
            continue
        n = arity[cmd]
        vals = [float(toks[i + k]) for k in range(n)]
        i += n
        if cmd == "H":
            cx = vals[0]
        elif cmd == "V":
            cy = vals[0]
        elif cmd == "A":
            cx, cy = vals[-2], vals[-1]
        else:
            for k in range(0, n, 2):
                xs.append(vals[k])
                ys.append(vals[k + 1])
            cx, cy = vals[-2], vals[-1]
        xs.append(cx)
        ys.append(cy)
        if cmd == "M":
            sx, sy = cx, cy
            cmd = "L"  # further pairs are implicit linetos
    return xs, ys


def _path_bboxes(svg_text: str) -> list[tuple[str, tuple[float, float, float, float]]]:
    out = []
    for d, fill in re.findall(r'<path d="([^"]+)" fill="([^"]+)"', svg_text):
        xs, ys = _path_points(d)
        out.append((fill, (min(xs), min(ys), max(xs), max(ys))))
    return out


def test_tighter_lockup_metrics():
    """Gap ~0.18 x mark height, wordmark cap height ~0.42 x mark height."""
    boxes = _path_bboxes((BRAND / "logo.svg").read_text())
    word = [b for f, b in boxes if f in ("#1B2A5C", "#2DA94F")]
    mark = [b for f, b in boxes if f not in ("#1B2A5C", "#2DA94F", "#FFFFFF")]
    assert word and mark
    mark_x0 = min(b[0] for b in mark)
    mark_x1 = max(b[2] for b in mark)
    mark_y0 = min(b[1] for b in mark)
    mark_y1 = max(b[3] for b in mark)
    mark_h = mark_y1 - mark_y0
    word_x0 = min(b[0] for b in word)
    word_h = max(b[3] for b in word) - min(b[1] for b in word)
    assert mark_x0 > 0  # mark sits left of the wordmark
    assert abs((word_x0 - mark_x1) / mark_h - 0.18) < 0.04, (word_x0, mark_x1, mark_h)
    assert abs(word_h / mark_h - 0.42) < 0.06, (word_h, mark_h)
