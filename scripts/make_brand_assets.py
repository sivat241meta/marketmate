"""Draw the MarketMate logo in code and emit the brand assets.

The logo is an original basket-"M" mark plus a "MarketMate" wordmark, drawn
entirely from code (no image input). The mark geometry is defined once below
in a 512x512 design space, as cubic-Bezier outline paths shared by the SVG
and PNG emitters, so the SVG and PNG versions match.

The mark: a tapered basket-"M" (wider at the top, soft rim band, diagonal
lime->green->blue gradient, subtle inner highlight), a thick semicircular
handle tucked behind the legs, and a produce cluster sitting in the basket
mouth (tomato, carrot, leafy greens). Favicons use a simplified small-size
variant (produce merged into two plain discs, thicker handle).

Outputs (all under app/web/static/brand/):
  logo.svg, mark.svg,
  mark-64.png, mark-256.png, favicon-16.png, favicon-32.png,
  apple-touch-icon.png (180), icon-192.png, icon-512.png,
  icon-maskable-512.png, logo-full.png (h160), logo-full@2x.png (h320),
  favicon.ico (16+32+48).

Usage: .venv/bin/python scripts/make_brand_assets.py
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "app" / "web" / "static" / "brand"
FONT_PATH = ROOT / "app" / "web" / "static" / "fonts" / "PlusJakartaSans-Variable.ttf"

DESIGN = 512  # design space is 512 x 512

# --- palette ---------------------------------------------------------------
LIME = (140, 208, 58)  # #8CD03A gradient start (top-left)
MID_GREEN = (34, 169, 85)  # #22A955 gradient middle
BLUE = (31, 111, 214)  # #1F6FD6 gradient end (bottom-right)
HANDLE_GREEN = (30, 158, 71)  # #1E9E47 basket handle (deep green)
RIM = (192, 229, 147)  # #C0E593 soft rim band (light lime tint)
NAVY = (27, 42, 92)  # #1B2A5C "Market"
WORD_GREEN = (45, 169, 79)  # #2DA94F "Mate"
TOMATO = (232, 65, 44)  # #E8412C
TOMATO_SHADOW = (192, 50, 32)  # #C03220 shadow crescent
CALYX = (46, 158, 62)  # #2E9E3E calyx + dark leaves
CARROT = (245, 154, 35)  # #F59A23
LEAF_LIGHT = (59, 181, 74)  # #3BB54A light leaves
MIDRIB_DARK = (30, 122, 50)  # #1E7A32 midrib on light leaves


def _css(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _num(v: float) -> str:
    if abs(v) < 0.005:
        return "0"
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


# --- cubic-Bezier path helpers ------------------------------------------------
# A path is a list of ops; every curve is a cubic Bezier, fills only.
Op = tuple  # ("M",x,y) | ("L",x,y) | ("C",x1,y1,x2,y2,x,y) | ("Z",)


def _norm_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _arc_cubics(cx: float, cy: float, r: float, a0: float,
                sweep: float) -> list[tuple[float, ...]]:
    """Cubic segments for the arc from angle a0 sweeping `sweep` radians."""
    n = max(1, math.ceil(abs(sweep) / (math.pi / 2)))
    out = []
    for i in range(n):
        b0 = a0 + sweep * i / n
        b1 = a0 + sweep * (i + 1) / n
        k = 4.0 / 3.0 * math.tan((b1 - b0) / 4.0)
        x0, y0 = cx + r * math.cos(b0), cy + r * math.sin(b0)
        x3, y3 = cx + r * math.cos(b1), cy + r * math.sin(b1)
        out.append((x0 - k * r * math.sin(b0), y0 + k * r * math.cos(b0),
                    x3 + k * r * math.sin(b1), y3 - k * r * math.cos(b1),
                    x3, y3))
    return out


def _arc_ops(cx: float, cy: float, r: float, a0: float,
             sweep: float) -> list[Op]:
    ops: list[Op] = [("L", cx + r * math.cos(a0), cy + r * math.sin(a0))]
    ops.extend(("C", *seg) for seg in _arc_cubics(cx, cy, r, a0, sweep))
    return ops


def _circle_ops(cx: float, cy: float, r: float) -> list[Op]:
    ops: list[Op] = [("M", cx + r, cy)]
    for k in range(4):
        ops.extend(("C", *seg)
                   for seg in _arc_cubics(cx, cy, r, k * math.pi / 2, math.pi / 2))
    ops.append(("Z",))
    return ops


def _rrect_ops(x0: float, y0: float, x1: float, y1: float, r: float) -> list[Op]:
    ops: list[Op] = [("M", x0 + r, y0), ("L", x1 - r, y0)]
    ops.extend(("C", *seg) for seg in _arc_cubics(x1 - r, y0 + r, r, -math.pi / 2, math.pi / 2))
    ops.append(("L", x1, y1 - r))
    ops.extend(("C", *seg) for seg in _arc_cubics(x1 - r, y1 - r, r, 0.0, math.pi / 2))
    ops.append(("L", x0 + r, y1))
    ops.extend(("C", *seg) for seg in _arc_cubics(x0 + r, y1 - r, r, math.pi / 2, math.pi / 2))
    ops.append(("L", x0, y0 + r))
    ops.extend(("C", *seg) for seg in _arc_cubics(x0 + r, y0 + r, r, math.pi, math.pi / 2))
    ops.append(("Z",))
    return ops


def _star_ops(cx: float, cy: float, r_out: float, r_in: float,
              n: int = 5, rot_deg: float = -90.0) -> list[Op]:
    ops: list[Op] = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot_deg + i * 180.0 / n)
        ops.append(("M" if i == 0 else "L", cx + r * math.cos(a), cy + r * math.sin(a)))
    ops.append(("Z",))
    return ops


def _stroke_outline(pts: list[tuple[float, float]],
                    halfs: list[float]) -> list[Op]:
    """Centreline + per-point half widths -> closed outline (round joins/caps)."""
    segs = len(pts) - 1
    norms = []
    for i in range(segs):
        dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        ln = math.hypot(dx, dy)
        norms.append((-dy / ln, dx / ln))
    la = [math.atan2(ny, nx) for nx, ny in norms]
    ops: list[Op] = [("M", pts[0][0] + norms[0][0] * halfs[0],
                      pts[0][1] + norms[0][1] * halfs[0])]
    for j in range(1, segs):  # left-side round joins
        ops.extend(_arc_ops(pts[j][0], pts[j][1], halfs[j],
                             la[j - 1], _norm_angle(la[j] - la[j - 1])))
    ops.append(("L", pts[-1][0] + norms[-1][0] * halfs[-1],
                pts[-1][1] + norms[-1][1] * halfs[-1]))
    fwd = math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0])
    cap = math.pi if _norm_angle(fwd - la[-1]) > 0 else -math.pi
    ops.extend(_arc_ops(pts[-1][0], pts[-1][1], halfs[-1], la[-1], cap))
    for j in range(segs - 1, 0, -1):  # right side, reversed
        ops.extend(_arc_ops(pts[j][0], pts[j][1], halfs[j], la[j] + math.pi,
                             _norm_angle(la[j - 1] - la[j])))
    ops.append(("L", pts[0][0] - norms[0][0] * halfs[0],
                pts[0][1] - norms[0][1] * halfs[0]))
    back = math.atan2(pts[0][1] - pts[1][1], pts[0][0] - pts[1][0])
    cap = math.pi if _norm_angle(back - la[0] - math.pi) > 0 else -math.pi
    ops.extend(_arc_ops(pts[0][0], pts[0][1], halfs[0], la[0] + math.pi, cap))
    ops.append(("Z",))
    return ops


def _leaf_ops(bx: float, by: float, tx: float, ty: float, w: float) -> list[Op]:
    """Pointed-oval leaf from base (bx,by) to tip (tx,ty), width w."""
    dx, dy = tx - bx, ty - by
    ln = math.hypot(dx, dy)
    ux, uy, nx, ny = dx / ln, dy / ln, -dy / ln, dx / ln
    h = w / 2
    return [
        ("M", bx, by),
        ("C", bx + ux * 0.25 * ln + nx * h, by + uy * 0.25 * ln + ny * h,
         bx + ux * 0.70 * ln + nx * h * 0.9, by + uy * 0.70 * ln + ny * h * 0.9,
         tx, ty),
        ("C", bx + ux * 0.70 * ln - nx * h * 0.9, by + uy * 0.70 * ln - ny * h * 0.9,
         bx + ux * 0.25 * ln - nx * h, by + uy * 0.25 * ln - ny * h, bx, by),
        ("Z",),
    ]


def _midrib_ops(bx: float, by: float, tx: float, ty: float) -> list[Op]:
    dx, dy = tx - bx, ty - by
    ln = math.hypot(dx, dy)
    ux, uy, nx, ny = dx / ln, dy / ln, -dy / ln, dx / ln
    sx, sy = bx + ux * 0.10 * ln, by + uy * 0.10 * ln
    ex, ey = bx + ux * 0.94 * ln, by + uy * 0.94 * ln
    hw = 2.4
    return [
        ("M", sx, sy),
        ("C", sx + ux * 0.3 * ln + nx * hw, sy + uy * 0.3 * ln + ny * hw,
         sx + ux * 0.6 * ln + nx * hw, sy + uy * 0.6 * ln + ny * hw, ex, ey),
        ("C", sx + ux * 0.6 * ln - nx * hw, sy + uy * 0.6 * ln - ny * hw,
         sx + ux * 0.3 * ln - nx * hw, sy + uy * 0.3 * ln - ny * hw, sx, sy),
        ("Z",),
    ]


def _path_d(ops: list[Op]) -> str:
    parts = []
    for op in ops:
        if op[0] == "Z":
            parts.append("Z")
        else:
            parts.append(op[0] + " ".join(_num(v) for v in op[1:]))
    return " ".join(parts)


def _flatten(ops: list[Op], subdiv: int = 32) -> list[list[tuple[float, float]]]:
    """Sample every cubic; returns one point list per subpath."""
    subs: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    x0 = y0 = 0.0
    for op in ops:
        if op[0] == "M":
            if cur:
                subs.append(cur)
            cur = [(op[1], op[2])]
        elif op[0] == "L":
            cur.append((op[1], op[2]))
        elif op[0] == "C":
            _, x1, y1, x2, y2, x3, y3 = op
            for k in range(1, subdiv + 1):
                t = k / subdiv
                mt = 1 - t
                cur.append((
                    mt**3 * x0 + 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t**3 * x3,
                    mt**3 * y0 + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t**3 * y3,
                ))
        elif op[0] == "Z":
            if cur:
                subs.append(cur)
                cur = []
            continue
        x0, y0 = cur[-1]
    if cur:
        subs.append(cur)
    return subs


# --- mark geometry (design space) ----------------------------------------------
# Basket-M centreline: two thick rounded legs, middle dipping into a V.
# Half widths taper 46 (top) -> 40 (bottom) so the basket is wider at the top.
M_LINE = [(122, 424), (112, 266), (256, 382), (400, 266), (390, 424)]
M_HALF = [40, 46, 44, 46, 40]
BODY_OPS = _stroke_outline(M_LINE, M_HALF)
BODY_POLY = _flatten(BODY_OPS)[0]
BODY_BBOX = (min(p[0] for p in BODY_POLY), min(p[1] for p in BODY_POLY),
             max(p[0] for p in BODY_POLY), max(p[1] for p in BODY_POLY))
# Diagonal gradient anchors: lime top-left -> green -> blue bottom-right.
GRAD_START = (66, 210)
GRAD_END = (446, 478)
# Semicircular handle tucked behind the legs; ~9% of the 380-unit mark width.
HANDLE_C = (256, 268)
HANDLE_R = 160
HANDLE_W = 34
SMALL_HANDLE_W = 40
# Soft rim band across the basket mouth; ends tuck behind the legs.
RIM_OPS = _rrect_ops(150, 272, 362, 300, 14)
# Subtle inner highlight stripe on the left leg (flat white, low opacity).
HIGHLIGHT_OPS = _rrect_ops(92, 300, 106, 392, 7)
HIGHLIGHT_ALPHA = 0.22

# Produce: (leaf base, tip, width, fill, rib fill).
LEAVES = [
    ((230, 252), (148, 206), 56, CALYX, LEAF_LIGHT),
    ((226, 254), (150, 232), 48, LEAF_LIGHT, MIDRIB_DARK),
    ((234, 250), (186, 158), 50, LEAF_LIGHT, MIDRIB_DARK),
]
# Carrot leaning out to the right: top centre, top half-width, tip, tip radius.
CARROT_TOP = (318, 200)
CARROT_HT = 23
CARROT_TIP = (268, 298)
CARROT_TR = 4
# Three fronds on the carrot top: (base, tip, width, fill).
FRONDS = [
    ((310, 195), (304, 156), 10, CALYX),
    ((320, 193), (320, 150), 12, LEAF_LIGHT),
    ((330, 196), (336, 158), 11, CALYX),
]
TOMATO_C = (243, 230)
TOMATO_R = 50
CALYX_C = (243, 184)
STEM_RECT = (239.5, 150, 246.5, 170, 3.5)
# Small-size produce: two plain discs (tomato + carrot merged).
SMALL_RED = (238, 236, 56)
SMALL_ORANGE = (318, 246, 44)


def _handle_ops(width: float) -> list[Op]:
    cx, cy = HANDLE_C
    r_out, r_in = HANDLE_R + width / 2, HANDLE_R - width / 2
    ops: list[Op] = [("M", cx - r_out, cy)]
    ops.extend(_arc_ops(cx, cy, r_out, math.pi, math.pi))  # outer, over the top
    ops.extend(_arc_ops(cx + HANDLE_R, cy, width / 2, 0.0, math.pi))  # right cap
    ops.extend(_arc_ops(cx, cy, r_in, 0.0, -math.pi))  # inner, back left
    ops.extend(_arc_ops(cx - HANDLE_R, cy, width / 2, 0.0, math.pi))  # left cap
    ops.append(("Z",))
    return ops


def _carrot_ops() -> list[Op]:
    (tcx, tcy), tip = CARROT_TOP, CARROT_TIP
    dx, dy = tip[0] - tcx, tip[1] - tcy
    ln = math.hypot(dx, dy)
    ux, uy, nx, ny = dx / ln, dy / ln, -dy / ln, dx / ln
    lx, ly = tcx + nx * CARROT_HT, tcy + ny * CARROT_HT
    rx, ry = tcx - nx * CARROT_HT, tcy - ny * CARROT_HT
    ops: list[Op] = [("M", lx, ly),
                     ("L", tip[0] + nx * CARROT_TR, tip[1] + ny * CARROT_TR)]
    a_from = math.atan2(ny, nx)
    fwd = math.atan2(uy, ux)
    delta = math.pi if _norm_angle(fwd - a_from) > 0 else -math.pi
    ops.extend(_arc_ops(tip[0], tip[1], CARROT_TR, a_from, delta))
    ops.append(("L", rx, ry))
    ops.append(("C", rx - 7, ry - 10, lx + 7, ly - 10, lx, ly))  # domed top
    ops.append(("Z",))
    return ops


def _crescent_ops() -> list[Op]:
    """Darker shadow crescent hugging the tomato's lower-right inside edge."""
    cx, cy = TOMATO_C
    a0, a1 = math.radians(-35), math.radians(55)
    ops: list[Op] = [("M", cx + 49 * math.cos(a0), cy + 49 * math.sin(a0))]
    ops.extend(("C", *seg) for seg in _arc_cubics(cx, cy, 49, a0, a1 - a0))
    ops.append(("C", 272, 255, 270, 217, cx + 49 * math.cos(a0), cy + 49 * math.sin(a0)))
    ops.append(("Z",))
    return ops


def _produce_shapes(variant: str) -> list[tuple[list[Op], tuple[int, int, int]]]:
    """Produce cluster in draw order: (path ops, fill)."""
    if variant == "small":
        return [(_circle_ops(*SMALL_ORANGE), CARROT),
                (_circle_ops(*SMALL_RED), TOMATO)]
    shapes: list[tuple[list[Op], tuple[int, int, int]]] = []
    for (bx, by), (tx, ty), w, fill, rib in LEAVES:
        shapes.append((_leaf_ops(bx, by, tx, ty, w), fill))
        shapes.append((_midrib_ops(bx, by, tx, ty), rib))
    shapes.append((_carrot_ops(), CARROT))
    for (bx, by), (tx, ty), w, fill in FRONDS:
        shapes.append((_leaf_ops(bx, by, tx, ty, w), fill))
    shapes.append((_circle_ops(*TOMATO_C, TOMATO_R), TOMATO))
    shapes.append((_crescent_ops(), TOMATO_SHADOW))
    shapes.append((_star_ops(*CALYX_C, 25, 10.5), CALYX))
    shapes.append((_rrect_ops(*STEM_RECT), CALYX))
    return shapes


def _content_bbox(variant: str = "full") -> tuple[int, int, int, int]:
    """Union of every mark path, plus a small margin (design units)."""
    xs: list[float] = []
    ys: list[float] = []
    paths = [_handle_ops(HANDLE_W if variant == "full" else SMALL_HANDLE_W),
             RIM_OPS, BODY_OPS]
    paths.extend(ops for ops, _ in _produce_shapes(variant))
    for ops in paths:
        for poly in _flatten(ops):
            xs.extend(p[0] for p in poly)
            ys.extend(p[1] for p in poly)
    m = 6
    return (math.floor(min(xs) - m), math.floor(min(ys) - m),
            math.ceil(max(xs) + m), math.ceil(max(ys) + m))


# --- wordmark ------------------------------------------------------------------
# Plus Jakarta Sans ExtraBold as paths. Lockup: gap 0.18 x mark height,
# cap height 0.42 x mark height, optically centred on the basket body,
# slight negative tracking.
TRACKING = 0.99
_MARK_CX0, _MARK_CY0, _MARK_CX1, _MARK_CY1 = _content_bbox("full")
_MARK_H = _MARK_CY1 - _MARK_CY0
WORD_CAP = round(0.42 * _MARK_H)
WORD_GAP = round(0.18 * _MARK_H)
WORD_X0 = _MARK_CX1 - 6 + WORD_GAP  # visual gap from the mark's right edge
WORD_A = ("Market", NAVY)
WORD_B = ("Mate", WORD_GREEN)
_BODY_CY = (BODY_BBOX[1] + BODY_BBOX[3]) / 2


def _extrabold_font() -> TTFont:
    font = TTFont(str(FONT_PATH))
    instantiateVariableFont(font, {"wght": 800}, inplace=True)
    return font


def _word_svg(font: TTFont, word: str, scale: float, x0: float,
              baseline: float) -> tuple[str, float]:
    """(SVG path data, advance width in design units) for one word."""
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    parts = []
    pen_x = 0.0
    for ch in word:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyph_set)
        tp = TransformPen(pen, (scale, 0, 0, -scale, x0 + pen_x, baseline))
        glyph_set[name].draw(tp)
        parts.append(pen.getCommands())
        pen_x += hmtx[name][0] * scale * TRACKING
    return " ".join(p for p in parts if p), pen_x


def _wordmark() -> tuple[str, float, float]:
    """(SVG group, total advance, baseline-y) for the two-tone wordmark."""
    font = _extrabold_font()
    cap_units = font["OS/2"].sCapHeight
    scale = WORD_CAP / cap_units
    baseline = _BODY_CY + WORD_CAP / 2
    out = []
    x = WORD_X0
    for word, colour in (WORD_A, WORD_B):
        d, adv = _word_svg(font, word, scale, x, baseline)
        out.append(f'<path d="{d}" fill="{_css(colour)}"/>')
        x += adv
    return "\n".join(out), x - WORD_X0, baseline


# --- SVG ----------------------------------------------------------------------


def _mark_inner(variant: str = "full") -> str:
    width = HANDLE_W if variant == "full" else SMALL_HANDLE_W
    lines = [
        "<defs>",
        (f'<linearGradient id="mmg" gradientUnits="userSpaceOnUse" '
         'color-interpolation="sRGB" '
         f'x1="{GRAD_START[0]}" y1="{GRAD_START[1]}" '
         f'x2="{GRAD_END[0]}" y2="{GRAD_END[1]}">'),
        f'<stop offset="0" stop-color="{_css(LIME)}"/>',
        f'<stop offset="0.5" stop-color="{_css(MID_GREEN)}"/>',
        f'<stop offset="1" stop-color="{_css(BLUE)}"/>',
        "</linearGradient>",
        "</defs>",
        f'<path d="{_path_d(_handle_ops(width))}" fill="{_css(HANDLE_GREEN)}"/>',
    ]
    for ops, colour in _produce_shapes(variant):
        lines.append(f'<path d="{_path_d(ops)}" fill="{_css(colour)}"/>')
    lines.append(f'<path d="{_path_d(RIM_OPS)}" fill="{_css(RIM)}"/>')
    lines.append(f'<path d="{_path_d(BODY_OPS)}" fill="url(#mmg)"/>')
    lines.append(f'<path d="{_path_d(HIGHLIGHT_OPS)}" fill="#FFFFFF" '
                 f'fill-opacity="{HIGHLIGHT_ALPHA}"/>')
    return "\n".join(lines)


def _svg_doc(width: float, height: float, vb: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_num(width)}" height="{_num(height)}" viewBox="{vb}">\n'
        "<title>MarketMate</title>\n" + body + "\n</svg>\n"
    )


def _lockup_box() -> tuple[int, int, int, int]:
    """viewBox (x, y, w, h) cropping the full lockup to its content."""
    _, word_adv, _ = _wordmark()
    cx0, cy0, _, cy1 = _content_bbox("full")
    x0, y0 = cx0 - 4, cy0 - 2
    x1, y1 = WORD_X0 + word_adv + 8, cy1 + 2
    return (x0, y0, math.ceil(x1 - x0), math.ceil(y1 - y0))


def write_svgs() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    (BRAND_DIR / "mark.svg").write_text(
        _svg_doc(DESIGN, DESIGN, f"0 0 {DESIGN} {DESIGN}", _mark_inner("full")))
    words, _, _ = _wordmark()
    x, y, w, h = _lockup_box()
    (BRAND_DIR / "logo.svg").write_text(
        _svg_doc(w, h, f"{x} {y} {w} {h}", _mark_inner("full") + "\n" + words))


# --- PNG ----------------------------------------------------------------------


def _lerp3(t: float) -> tuple[int, int, int]:
    """Three-stop diagonal gradient: lime -> green -> blue."""
    t = min(1.0, max(0.0, t))
    if t < 0.5:
        a, b, u = LIME, MID_GREEN, t * 2.0
    else:
        a, b, u = MID_GREEN, BLUE, (t - 0.5) * 2.0
    return tuple(round(x + (y - x) * u) for x, y in zip(a, b))


def _paint_mark(img: Image.Image, s: float, dx: float, dy: float,
                variant: str = "full") -> None:
    """Paint the mark on `img`; design (x, y) maps to (x*s+dx, y*s+dy)."""
    draw = ImageDraw.Draw(img)

    def polys(ops: list[Op]) -> list[list[tuple[float, float]]]:
        return [[(x * s + dx, y * s + dy) for x, y in poly]
                for poly in _flatten(ops)]

    width = HANDLE_W if variant == "full" else SMALL_HANDLE_W
    for poly in polys(_handle_ops(width)):
        draw.polygon(poly, fill=HANDLE_GREEN + (255,))
    for ops, colour in _produce_shapes(variant):
        for poly in polys(ops):
            draw.polygon(poly, fill=colour + (255,))
    for poly in polys(RIM_OPS):
        draw.polygon(poly, fill=RIM + (255,))
    # M body with the diagonal gradient, painted through a mask.
    pad = 2
    bx0, by0, bx1, by1 = BODY_BBOX
    rx0 = math.floor((bx0 - pad) * s + dx)
    ry0 = math.floor((by0 - pad) * s + dy)
    rx1 = math.ceil((bx1 + pad) * s + dx)
    ry1 = math.ceil((by1 + pad) * s + dy)
    rw, rh = rx1 - rx0, ry1 - ry0
    gx, gy = GRAD_END[0] - GRAD_START[0], GRAD_END[1] - GRAD_START[1]
    norm2 = gx * gx + gy * gy

    def proj(x: float, y: float) -> float:
        return ((x - GRAD_START[0]) * gx + (y - GRAD_START[1]) * gy) / norm2

    grad = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    ts = [proj(x, y) for x, y in
          ((bx0 - pad, by0 - pad), (bx1 + pad, by0 - pad),
           (bx0 - pad, by1 + pad), (bx1 + pad, by1 + pad))]
    t0, t1 = min(ts), max(ts)
    # Constant-colour bands ~0.75 raw px apart (overlapped for coverage).
    span = (t1 - t0) * math.sqrt(norm2) * s
    nbands = max(2, math.ceil(span / 0.75))
    llen = math.hypot(bx1 - bx0 + 2 * pad, by1 - by0 + 2 * pad) / 2 + pad
    dlx, dly = -gy / math.sqrt(norm2), gx / math.sqrt(norm2)
    mx, my = (bx0 + bx1) / 2, (by0 + by1) / 2
    cm = ((mx - GRAD_START[0]) * gx + (my - GRAD_START[1]) * gy) / norm2
    lw = max(2, round(s * 1.5))
    for k in range(nbands):
        t = t0 + (t1 - t0) * (k + 0.5) / nbands
        back = (t - cm) * norm2 / math.sqrt(norm2)
        qx = mx + back * gx / math.sqrt(norm2)
        qy = my + back * gy / math.sqrt(norm2)
        gd.line([qx * s + dx - rx0 - dlx * llen * s,
                 qy * s + dy - ry0 - dly * llen * s,
                 qx * s + dx - rx0 + dlx * llen * s,
                 qy * s + dy - ry0 + dly * llen * s],
                width=lw, fill=_lerp3(t) + (255,))
    mask = Image.new("L", (rw, rh), 0)
    md = ImageDraw.Draw(mask)
    for poly in polys(BODY_OPS):
        md.polygon([(x - rx0, y - ry0) for x, y in poly], fill=255)
    # Subtle inner highlight blended onto the body.
    hl_mask = Image.new("L", (rw, rh), 0)
    hd = ImageDraw.Draw(hl_mask)
    for poly in polys(HIGHLIGHT_OPS):
        hd.polygon([(x - rx0, y - ry0) for x, y in poly], fill=255)
    hl_mask = ImageChops.multiply(mask, hl_mask)
    hl_mask = hl_mask.point(lambda a: round(a * HIGHLIGHT_ALPHA))
    white = Image.new("RGBA", (rw, rh), (255, 255, 255, 0))
    white.putalpha(hl_mask)
    grad = Image.alpha_composite(grad, white)
    grad.putalpha(mask)
    img.paste(grad, (rx0, ry0), grad)


def _downscale(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    out = img.resize(size, Image.LANCZOS)
    if out.mode == "RGBA":
        # Snap resampling dust: visually identical, keeps solid areas solid.
        alpha = out.getchannel("A").point(lambda a: 255 if a >= 254 else a)
        out.putalpha(alpha)
    return out


def _render_mark_square(size: int, variant: str = "full",
                        ss: int = 4) -> Image.Image:
    raw = size * ss
    img = Image.new("RGBA", (raw, raw), (0, 0, 0, 0))
    _paint_mark(img, raw / DESIGN, 0, 0, variant)
    return _downscale(img, (size, size))


def _render_mark_fitted(size: int, box: int, ss: int = 4) -> Image.Image:
    """Mark on white: content fitted into a centred `box` px square."""
    cx0, cy0, cx1, cy1 = _content_bbox("full")
    cw, ch = cx1 - cx0, cy1 - cy0
    raw = size * ss
    img = Image.new("RGB", (raw, raw), (255, 255, 255))
    s = (box / max(cw, ch)) * ss
    dx = (raw - cw * s) / 2 - cx0 * s
    dy = (raw - ch * s) / 2 - cy0 * s
    _paint_mark(img, s, dx, dy, "full")
    return _downscale(img, (size, size))


def _static_800_path(tmp: Path) -> Path:
    font = _extrabold_font()
    out = tmp / "PlusJakartaSans-ExtraBold.ttf"
    font.save(str(out))
    return out


def _render_lockup(height: int, tmp: Path, ss: int = 4) -> Image.Image:
    """Full lockup on transparency, `height` px tall."""
    font = _extrabold_font()
    cap_units = font["OS/2"].sCapHeight
    upm = font["head"].unitsPerEm
    _, _, baseline = _wordmark()
    lx, ly, lw, lh = _lockup_box()
    width = round(height * lw / lh)
    raw_w, raw_h = width * ss, height * ss
    img = Image.new("RGBA", (raw_w, raw_h), (0, 0, 0, 0))
    s = raw_h / lh
    _paint_mark(img, s, -lx * s, -ly * s, "full")
    em_px = round(WORD_CAP * s / (cap_units / upm))
    pil_font = ImageFont.truetype(str(_static_800_path(tmp)), em_px)
    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    draw = ImageDraw.Draw(img)
    x = WORD_X0 * s - lx * s
    y = baseline * s - ly * s
    for word, colour in (WORD_A, WORD_B):
        # Glyph by glyph so the -1% tracking matches the SVG layout.
        for ch in word:
            # anchor="ls" puts the advance origin at x, matching SVG.
            draw.text((x, y), ch, font=pil_font,
                      anchor="ls", fill=colour + (255,))
            x += hmtx[cmap[ord(ch)]][0] / upm * em_px * TRACKING
    return _downscale(img, (width, height))


def write_pngs() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    with tempfile.TemporaryDirectory(prefix="mm_brand_") as tmpdir:
        tmp = Path(tmpdir)
        jobs.append(("mark-64.png", _render_mark_square(64, "full")))
        jobs.append(("mark-256.png", _render_mark_square(256, "full")))
        jobs.append(("favicon-16.png", _render_mark_square(16, "small")))
        jobs.append(("favicon-32.png", _render_mark_square(32, "small")))
        jobs.append(("apple-touch-icon.png",
                     _render_mark_fitted(180, round(180 * 0.76))))
        jobs.append(("icon-192.png", _render_mark_fitted(192, round(192 * 0.8))))
        jobs.append(("icon-512.png", _render_mark_fitted(512, round(512 * 0.8))))
        jobs.append(("icon-maskable-512.png", _render_mark_fitted(512, 400)))
        jobs.append(("logo-full.png", _render_lockup(160, tmp)))
        jobs.append(("logo-full@2x.png", _render_lockup(320, tmp)))
        for name, img in jobs:
            img.save(BRAND_DIR / name)
    ico_sizes = [(16, 16), (32, 32), (48, 48)]
    ico_imgs = [_render_mark_square(n, "small") for n, _ in ico_sizes]
    # Largest first: the ICO writer skips sizes bigger than the first image.
    ico_imgs[-1].save(BRAND_DIR / "favicon.ico", format="ICO",
                      sizes=ico_sizes, append_images=ico_imgs[:-1])


def main() -> None:
    write_svgs()
    write_pngs()
    for path in sorted(BRAND_DIR.iterdir()):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
