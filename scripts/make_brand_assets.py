"""Draw the MarketMate logo in code and emit the brand assets.

The logo is an original basket-"M" mark plus a "MarketMate" wordmark, drawn
entirely from code (no image input). The mark geometry is defined once below
in a 512x512 design space and shared by the SVG and PNG emitters.

Outputs (all under app/web/static/brand/):
  logo.svg, mark.svg,
  mark-64.png, mark-256.png, favicon-16.png, favicon-32.png,
  apple-touch-icon.png (180), icon-192.png, icon-512.png,
  icon-maskable-512.png, logo-full.png (h160), logo-full@2x.png (h320),
  favicon.ico (16+32+48).

Usage: .venv/bin/python scripts/make_brand_assets.py
"""

from __future__ import annotations

import itertools
import math
import tempfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "app" / "web" / "static" / "brand"
FONT_PATH = ROOT / "app" / "web" / "static" / "fonts" / "PlusJakartaSans-Variable.ttf"

DESIGN = 512  # design space is 512 x 512

# --- palette ---------------------------------------------------------------
LIME = (140, 208, 58)  # #8CD03A gradient start (top-left)
MID_GREEN = (34, 169, 85)  # #22A955 gradient middle
BLUE = (31, 111, 214)  # #1F6FD6 gradient end (bottom-right)
HANDLE_GREEN = (45, 179, 74)  # #2DB34A basket handle
NAVY = (27, 42, 92)  # #1B2A5C "Market"
WORD_GREEN = (45, 169, 79)  # #2DA94F "Mate"
TOMATO = (232, 68, 46)  # #E8442E
ORANGE = (245, 158, 11)  # #F59E0B
LEAF_DARK = (31, 157, 68)  # #1F9D44


def _css(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


# --- mark geometry (design space) --------------------------------------------
# Bold rounded M: two thick outer legs, middle dipping into a V.
M_POINTS = [(112, 428), (112, 272), (256, 386), (400, 272), (400, 428)]
M_WIDTH = 92
# Diagonal gradient anchors: lime top-left -> green -> blue bottom-right.
GRAD_START = (66, 226)
GRAD_END = (446, 474)
# Semicircular basket handle arcing above the M.
HANDLE_C = (256, 265)
HANDLE_R = 135
HANDLE_W = 30
# Produce peeking out between the legs (drawn before the M body).
ORANGE_VEG = (180, 252, 44)  # cx, cy, r
TOMATO_VEG = (272, 268, 54)
CALYX_C = (272, 218)  # star centre; outer r 22, inner r 9
STEM = ((272, 200), (272, 188), 9)  # x1, y1, x2, y2 packed below
LEAVES = [
    # cx, cy, length, width, angle_deg, colour
    (168, 198, 112, 48, -38, HANDLE_GREEN),
    (334, 194, 122, 52, 30, LEAF_DARK),
    (256, 180, 92, 42, -6, LIME),
]

# Wordmark: Plus Jakarta Sans ExtraBold, cap height in design units.
WORD_CAP = 160
WORD_GAP = 128  # 0.25 x mark height
WORD_X0 = DESIGN + WORD_GAP
WORD_A = ("Market", NAVY)
WORD_B = ("Mate", WORD_GREEN)


def _star_points(cx: float, cy: float, r_out: float, r_in: float,
                 n: int = 5, rot_deg: float = -90.0) -> list[tuple[float, float]]:
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot_deg + i * 180.0 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _leaf_points(cx: float, cy: float, length: float, width: float,
                 angle_deg: float, steps: int = 5) -> list[tuple[float, float]]:
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx
    pts: list[tuple[float, float]] = []
    for side in (1.0, -1.0):
        order = range(steps + 1) if side > 0 else range(steps, -1, -1)
        for i in order:
            t = i / steps
            px = cx + (t - 0.5) * length * dx
            py = cy + (t - 0.5) * length * dy
            w = (width / 2) * math.sin(math.pi * t) ** 0.8
            pts.append((px + side * nx * w, py + side * ny * w))
    return pts


def _body_shapes() -> list[str]:
    """The M body as filled shapes sharing one gradient.

    A round-cap/round-join stroke equals the union of its segment
    rectangles plus a disc at every vertex. Emitting that union (all
    filled with the same userSpaceOnUse gradient, so it stays seamless)
    keeps the exact stroke shape while using only gradient fills, which
    every SVG renderer (including WeasyPrint) supports.
    """
    r = M_WIDTH / 2
    shapes = []
    for (x0, y0), (x1, y1) in itertools.pairwise(M_POINTS):
        ln = math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / ln * r, (x1 - x0) / ln * r
        quad = [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
        shapes.append(
            f'<polygon points="{_pts_attr(quad)}" fill="url(#mmg)"/>')
    for x, y in M_POINTS:
        shapes.append(
            f'<circle cx="{x}" cy="{y}" r="{_num(r)}" fill="url(#mmg)"/>')
    return shapes


def _content_bbox() -> tuple[int, int, int, int]:
    """Union of every mark primitive, plus a small margin (design units)."""
    xs: list[float] = []
    ys: list[float] = []

    def box(x0: float, y0: float, x1: float, y1: float) -> None:
        xs.extend((x0, x1))
        ys.extend((y0, y1))

    hw = M_WIDTH / 2
    mxs = [p[0] for p in M_POINTS]
    mys = [p[1] for p in M_POINTS]
    box(min(mxs) - hw, min(mys) - hw, max(mxs) + hw, max(mys) + hw)
    hcx, hcy = HANDLE_C
    box(hcx - HANDLE_R - HANDLE_W / 2, hcy - HANDLE_R - HANDLE_W / 2,
        hcx + HANDLE_R + HANDLE_W / 2, hcy + HANDLE_W / 2)
    for cx, cy, r in (ORANGE_VEG, TOMATO_VEG):
        box(cx - r, cy - r, cx + r, cy + r)
    for x, y in _star_points(*CALYX_C, 22, 9):
        box(x, y, x, y)
    (sx1, sy1), (sx2, sy2), sw = STEM
    box(min(sx1, sx2) - sw / 2, min(sy1, sy2) - sw / 2,
        max(sx1, sx2) + sw / 2, max(sy1, sy2) + sw / 2)
    for cx, cy, ln, wd, ang, _ in LEAVES:
        for x, y in _leaf_points(cx, cy, ln, wd, ang):
            box(x, y, x, y)
    m = 6
    return (math.floor(min(xs) - m), math.floor(min(ys) - m),
            math.ceil(max(xs) + m), math.ceil(max(ys) + m))


def _num(v: float) -> str:
    if abs(v) < 0.005:
        return "0"
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def _pts_attr(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{_num(x)},{_num(y)}" for x, y in pts)


# --- wordmark from the variable font ------------------------------------------

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
        pen_x += hmtx[name][0] * scale
    return " ".join(p for p in parts if p), pen_x


def _wordmark() -> tuple[str, float, float]:
    """(SVG group, total advance, baseline-y) for the two-tone wordmark."""
    font = _extrabold_font()
    cap_units = font["OS/2"].sCapHeight
    scale = WORD_CAP / cap_units
    _, cy0, _, cy1 = _content_bbox()
    baseline = (cy0 + cy1) / 2 + WORD_CAP / 2
    out = []
    x = WORD_X0
    for word, colour in (WORD_A, WORD_B):
        d, adv = _word_svg(font, word, scale, x, baseline)
        out.append(f'<path d="{d}" fill="{_css(colour)}"/>')
        x += adv
    return "\n".join(out), x - WORD_X0, baseline


# --- SVG ----------------------------------------------------------------------

def _mark_inner() -> str:
    hcx, hcy = HANDLE_C
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
        (f'<path d="M{_num(hcx - HANDLE_R)} {_num(hcy)}A{HANDLE_R} '
         f'{HANDLE_R} 0 0 1 {_num(hcx + HANDLE_R)} {_num(hcy)}" fill="none" '
         f'stroke="{_css(HANDLE_GREEN)}" stroke-width="{HANDLE_W}" '
         'stroke-linecap="round"/>'),
    ]
    for cx, cy, ln, wd, ang, colour in LEAVES:
        pts = _leaf_points(cx, cy, ln, wd, ang)
        lines.append(
            f'<polygon points="{_pts_attr(pts)}" fill="{_css(colour)}"/>')
    for cx, cy, r in (ORANGE_VEG, TOMATO_VEG):
        colour = ORANGE if r == ORANGE_VEG[2] else TOMATO
        lines.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{_css(colour)}"/>')
    star = _star_points(*CALYX_C, 22, 9)
    lines.append(
        f'<polygon points="{_pts_attr(star)}" fill="{_css(HANDLE_GREEN)}"/>')
    (sx1, sy1), (sx2, sy2), sw = STEM
    lines.append(
        f'<line x1="{sx1}" y1="{sy1}" x2="{sx2}" y2="{sy2}" '
        f'stroke="{_css(HANDLE_GREEN)}" stroke-width="{sw}" '
        'stroke-linecap="round"/>')
    lines.extend(_body_shapes())
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
    right = WORD_X0 + word_adv + 8
    return (56, 100, math.ceil(right - 56), 392)


def write_svgs() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    (BRAND_DIR / "mark.svg").write_text(
        _svg_doc(DESIGN, DESIGN, f"0 0 {DESIGN} {DESIGN}", _mark_inner()))
    words, _, _ = _wordmark()
    x, y, w, h = _lockup_box()
    (BRAND_DIR / "logo.svg").write_text(
        _svg_doc(w, h, f"{x} {y} {w} {h}", _mark_inner() + "\n" + words))


# --- PNG ----------------------------------------------------------------------

def _lerp3(t: float) -> tuple[int, int, int]:
    """Three-stop diagonal gradient: lime -> green -> blue."""
    t = min(1.0, max(0.0, t))
    if t < 0.5:
        a, b, u = LIME, MID_GREEN, t * 2.0
    else:
        a, b, u = MID_GREEN, BLUE, (t - 0.5) * 2.0
    return tuple(round(x + (y - x) * u) for x, y in zip(a, b))


def _paint_mark(img: Image.Image, s: float, dx: float, dy: float) -> None:
    """Paint the mark on `img`; design (x, y) maps to (x*s+dx, y*s+dy)."""
    draw = ImageDraw.Draw(img)

    def disc(cx: float, cy: float, r: float, fill: tuple[int, ...]) -> None:
        draw.ellipse([cx * s + dx - r * s, cy * s + dy - r * s,
                      cx * s + dx + r * s, cy * s + dy + r * s], fill=fill)

    # Handle (behind everything).
    hcx, hcy = HANDLE_C
    draw.arc([hcx * s + dx - HANDLE_R * s, hcy * s + dy - HANDLE_R * s,
              hcx * s + dx + HANDLE_R * s, hcy * s + dy + HANDLE_R * s],
             start=180, end=360, width=max(1, round(HANDLE_W * s)),
             fill=HANDLE_GREEN + (255,))
    disc(hcx - HANDLE_R, hcy, HANDLE_W / 2, HANDLE_GREEN + (255,))
    disc(hcx + HANDLE_R, hcy, HANDLE_W / 2, HANDLE_GREEN + (255,))
    # Produce.
    for cx, cy, ln, wd, ang, colour in LEAVES:
        pts = [(x * s + dx, y * s + dy)
               for x, y in _leaf_points(cx, cy, ln, wd, ang)]
        draw.polygon(pts, fill=colour + (255,))
    for cx, cy, r in (ORANGE_VEG, TOMATO_VEG):
        colour = ORANGE if r == ORANGE_VEG[2] else TOMATO
        draw.ellipse([cx * s + dx - r * s, cy * s + dy - r * s,
                      cx * s + dx + r * s, cy * s + dy + r * s],
                     fill=colour + (255,))
    star = [(x * s + dx, y * s + dy)
            for x, y in _star_points(*CALYX_C, 22, 9)]
    draw.polygon(star, fill=HANDLE_GREEN + (255,))
    (sx1, sy1), (sx2, sy2), sw = STEM
    draw.line([sx1 * s + dx, sy1 * s + dy, sx2 * s + dx, sy2 * s + dy],
              width=max(1, round(sw * s)), fill=HANDLE_GREEN + (255,))
    disc(sx1, sy1, sw / 2, HANDLE_GREEN + (255,))
    disc(sx2, sy2, sw / 2, HANDLE_GREEN + (255,))
    # M body with the diagonal gradient, painted through a mask.
    pad = M_WIDTH / 2 + 2
    mxs = [p[0] for p in M_POINTS]
    mys = [p[1] for p in M_POINTS]
    rx0 = math.floor((min(mxs) - pad) * s + dx)
    ry0 = math.floor((min(mys) - pad) * s + dy)
    rx1 = math.ceil((max(mxs) + pad) * s + dx)
    ry1 = math.ceil((max(mys) + pad) * s + dy)
    rw, rh = rx1 - rx0, ry1 - ry0
    gx, gy = GRAD_END[0] - GRAD_START[0], GRAD_END[1] - GRAD_START[1]
    norm2 = gx * gx + gy * gy

    def proj(x: float, y: float) -> float:
        return ((x - GRAD_START[0]) * gx + (y - GRAD_START[1]) * gy) / norm2

    grad = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    corners = [(min(mxs) - pad, min(mys) - pad),
               (max(mxs) + pad, min(mys) - pad),
               (min(mxs) - pad, max(mys) + pad),
               (max(mxs) + pad, max(mys) + pad)]
    ts = [proj(x, y) for x, y in corners]
    t0, t1 = min(ts), max(ts)
    # Constant-colour bands ~0.75 raw px apart (overlapped for coverage).
    span = (t1 - t0) * math.sqrt(norm2) * s
    nbands = max(2, math.ceil(span / 0.75))
    llen = math.hypot(max(mxs) - min(mxs) + 2 * pad,
                      max(mys) - min(mys) + 2 * pad) / 2 + pad
    dlx, dly = -gy / math.sqrt(norm2), gx / math.sqrt(norm2)
    mx = (min(mxs) + max(mxs)) / 2
    my = (min(mys) + max(mys)) / 2
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
    md.line([(x * s + dx - rx0, y * s + dy - ry0) for x, y in M_POINTS],
            width=round(M_WIDTH * s), fill=255, joint="curve")
    for x, y in (M_POINTS[0], M_POINTS[-1]):
        md.ellipse([x * s + dx - rx0 - M_WIDTH * s / 2,
                    y * s + dy - ry0 - M_WIDTH * s / 2,
                    x * s + dx - rx0 + M_WIDTH * s / 2,
                    y * s + dy - ry0 + M_WIDTH * s / 2], fill=255)
    grad.putalpha(mask)
    img.paste(grad, (rx0, ry0), grad)


def _downscale(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    out = img.resize(size, Image.LANCZOS)
    if out.mode == "RGBA":
        # Snap resampling dust: visually identical, keeps solid areas solid.
        alpha = out.getchannel("A").point(lambda a: 255 if a >= 254 else a)
        out.putalpha(alpha)
    return out


def _render_mark_square(size: int, ss: int = 4) -> Image.Image:
    raw = size * ss
    img = Image.new("RGBA", (raw, raw), (0, 0, 0, 0))
    _paint_mark(img, raw / DESIGN, 0, 0)
    return _downscale(img, (size, size))


def _render_mark_fitted(size: int, box: int, ss: int = 4) -> Image.Image:
    """Mark on white: content fitted into a centred `box` px square."""
    cx0, cy0, cx1, cy1 = _content_bbox()
    cw, ch = cx1 - cx0, cy1 - cy0
    raw = size * ss
    img = Image.new("RGB", (raw, raw), (255, 255, 255))
    s = (box / max(cw, ch)) * ss
    dx = (raw - cw * s) / 2 - cx0 * s
    dy = (raw - ch * s) / 2 - cy0 * s
    _paint_mark(img, s, dx, dy)
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
    _paint_mark(img, s, -lx * s, -ly * s)
    em_px = round(WORD_CAP * s / (cap_units / upm))
    pil_font = ImageFont.truetype(str(_static_800_path(tmp)), em_px)
    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    draw = ImageDraw.Draw(img)
    x = WORD_X0 * s - lx * s
    y = baseline * s - ly * s
    for word, colour in (WORD_A, WORD_B):
        # anchor="ls" puts the advance origin at x, matching the SVG layout.
        draw.text((x, y), word, font=pil_font,
                  anchor="ls", fill=colour + (255,))
        x += sum(hmtx[cmap[ord(c)]][0] for c in word) / upm * em_px
    return _downscale(img, (width, height))


def write_pngs() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    with tempfile.TemporaryDirectory(prefix="mm_brand_") as tmpdir:
        tmp = Path(tmpdir)
        jobs.append(("mark-64.png", _render_mark_square(64)))
        jobs.append(("mark-256.png", _render_mark_square(256)))
        jobs.append(("favicon-16.png", _render_mark_square(16)))
        jobs.append(("favicon-32.png", _render_mark_square(32)))
        jobs.append(("apple-touch-icon.png",
                     _render_mark_fitted(180, round(180 * 0.76))))
        jobs.append(("icon-192.png", _render_mark_fitted(192, round(192 * 0.8))))
        jobs.append(("icon-512.png", _render_mark_fitted(512, round(512 * 0.8))))
        jobs.append(("icon-maskable-512.png", _render_mark_fitted(512, 400)))
        jobs.append(("logo-full.png", _render_lockup(160, tmp)))
        jobs.append(("logo-full@2x.png", _render_lockup(320, tmp)))
        for name, img in jobs:
            img.save(BRAND_DIR / name)
    ico_src = Image.open(BRAND_DIR / "mark-256.png")
    ico_src.save(BRAND_DIR / "favicon.ico", format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48)])


def main() -> None:
    write_svgs()
    write_pngs()
    for path in sorted(BRAND_DIR.iterdir()):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
