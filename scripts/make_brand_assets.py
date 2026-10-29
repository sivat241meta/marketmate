"""Draw the MarketMate logo in code and emit the brand assets.

The logo is direction 3 ("Mm leaves") from the Task 88 explorations: a
lowercase "m" whose two humps peak in outward leaf tips, drawn here in TWO
different colours (the owner: green + lime read as one colour). The geometry
below is copied from our own Task 88 drawing (/tmp/mm_logo3/draw_logos.py,
build_g3) and parameterized by fill colour. Everything is drawn from code
(no image input); the SVG and PNG emitters share the same cubic-Bezier
paths, so the SVG and PNG versions match.

The mark: two abutting leaf-half paths (no gap between them, so small
sizes keep both colours). The wordmark is Inter ExtraBold as paths with
-1.5% tracking: "Market" in the pair's left colour, "Mate" in the right
(except pair E, where "Market" uses the deeper #0064E0).

Colour pairs (left, right):
  A  purple + green     #5F55EE + #1FA34A  (left = old app primary)
  B  green + orange     #1FA34A + #F28C28
  C  navy + green       #1B2A5C + #1FA34A
  D  purple + orange    #5F55EE + #F28C28
  E  meta blue + green  #0866FF + #1FA34A  (default; "Market" in #0064E0)

Outputs (all under app/web/static/brand/):
  logo.svg, mark.svg, mark-dark.svg (lighter left leaf for #1E1F21 chrome),
  mark-64.png, mark-256.png, favicon-16.png, favicon-32.png,
  apple-touch-icon.png (180, two-colour mark on a white rounded tile),
  icon-192.png, icon-512.png (same),
  icon-maskable-512.png (mark on white inside the safe zone),
  logo-full.png (h160), logo-full@2x.png (h320),
  favicon.ico (16+32+48).

Usage:
  .venv/bin/python scripts/make_brand_assets.py          # pair E (default)
  .venv/bin/python scripts/make_brand_assets.py --pair C # switch pair
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "app" / "web" / "static" / "brand"
FONT_PATH = ROOT / "app" / "web" / "static" / "fonts" / "InterVariable.ttf"

DESIGN = 512  # design space is 512 x 512
SS = 4  # PNG supersampling factor
TRACK = -0.015  # wordmark tracking as a fraction of cap height (-1.5%)
BORDER = (226, 229, 234)  # #E2E5EA subtle tile border

# --- colour pairs (left leaf, right leaf) ------------------------------------
PAIRS: dict[str, tuple[str, str]] = {
    "A": ("#5F55EE", "#1FA34A"),  # purple + green
    "B": ("#1FA34A", "#F28C28"),  # green + orange
    "C": ("#1B2A5C", "#1FA34A"),  # navy + green
    "D": ("#5F55EE", "#F28C28"),  # purple + orange
    "E": ("#0866FF", "#1FA34A"),  # meta blue + green (default)
}
# Wordmark "Market" colour: the pair's left colour, except pair E where the
# leaf stays Meta blue #0866FF but the wordmark uses the deeper #0064E0.
WORD_LEFT: dict[str, str] = {
    "E": "#0064E0",
}
# Left leaf on the dark seller chrome (#1E1F21): purple #5F55EE is only
# 3.3:1 there, so the dark variant uses lighter purple; navy would vanish
# (1.2:1) so pair C gets a lightened navy; green (5.1:1) stays as is.
# Meta blue #0866FF is 3.4:1 there, so pair E uses #4D9BFF (5.9:1).
DARK_LEFT: dict[str, str] = {
    "A": "#7B68EE",
    "B": "#1FA34A",
    "C": "#6C7FD8",
    "D": "#7B68EE",
    "E": "#4D9BFF",
}
INK = "#292D34"  # candidate "Market" colour (kept for reference)

# --- lockup metrics (from direction 3 as presented) ---------------------------
WORD_CAP = 150.0  # wordmark cap height in design units
WORD_GAP = 128.0  # mark-to-wordmark gap (0.25 x the 512 design box)


def _num(v: float) -> str:
    if abs(v) < 0.005:
        return "0"
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# --- mini vector lib (copied from our Task 88 drawing) ------------------------
# M/L/C/Z paths drive both the SVG output and the Pillow flattening.


class Path:
    def __init__(self, fill: str):
        self.fill = fill
        self.subs: list[list[tuple]] = []
        self._cur: list[tuple] | None = None

    def move(self, x: float, y: float) -> Path:
        self._cur = [("M", x, y)]
        self.subs.append(self._cur)
        return self

    def line(self, x: float, y: float) -> Path:
        assert self._cur is not None
        self._cur.append(("L", x, y))
        return self

    def cubic(self, x1: float, y1: float, x2: float, y2: float,
              x: float, y: float) -> Path:
        assert self._cur is not None
        self._cur.append(("C", x1, y1, x2, y2, x, y))
        return self

    def close(self) -> Path:
        assert self._cur is not None
        self._cur.append(("Z",))
        return self

    def svg_d(self) -> str:
        parts: list[str] = []
        for sub in self.subs:
            for op in sub:
                if op[0] == "M":
                    parts.append(f"M{_num(op[1])} {_num(op[2])}")
                elif op[0] == "L":
                    parts.append(f"L{_num(op[1])} {_num(op[2])}")
                elif op[0] == "C":
                    parts.append(f"C{_num(op[1])} {_num(op[2])} "
                                 f"{_num(op[3])} {_num(op[4])} "
                                 f"{_num(op[5])} {_num(op[6])}")
                else:
                    parts.append("Z")
        return "".join(parts)

    def flatten(self, steps: int = 28) -> list[list[tuple[float, float]]]:
        polys: list[list[tuple[float, float]]] = []
        for sub in self.subs:
            pts: list[tuple[float, float]] = []
            cx, cy = 0.0, 0.0
            for op in sub:
                if op[0] in ("M", "L"):
                    cx, cy = op[1], op[2]
                    pts.append((cx, cy))
                elif op[0] == "C":
                    x1, y1, x2, y2, x, y = op[1:]
                    for i in range(1, steps + 1):
                        t = i / steps
                        mt = 1 - t
                        px = (mt**3 * cx + 3 * mt**2 * t * x1
                              + 3 * mt * t**2 * x2 + t**3 * x)
                        py = (mt**3 * cy + 3 * mt**2 * t * y1
                              + 3 * mt * t**2 * y2 + t**3 * y)
                        pts.append((px, py))
                    cx, cy = x, y
            if pts:
                polys.append(pts)
        return polys


def build_mark(left: str, right: str) -> list[Path]:
    """Direction 3 geometry: lowercase m; two humps peak in outward leaf
    tips. The halves share their middle edge (no thin gap to close up)."""
    l = Path(left)
    l.move(60, 448).line(60, 200)
    l.cubic(60, 140, 105, 100, 168, 86)      # left edge to tip 1
    l.cubic(200, 110, 225, 145, 256, 180)    # tip 1 down to valley
    l.line(256, 448).line(212, 448).line(212, 336)
    l.cubic(212, 318, 196, 304, 180, 304)
    l.cubic(164, 304, 148, 318, 148, 336)
    l.line(148, 448).line(60, 448).close()
    r = Path(right)
    r.move(256, 180)
    r.cubic(287, 145, 312, 110, 344, 86)     # valley up to tip 2
    r.cubic(407, 100, 452, 140, 452, 200)
    r.line(452, 448).line(364, 448).line(364, 336)
    r.cubic(364, 318, 348, 304, 332, 304)
    r.cubic(316, 304, 300, 318, 300, 336)
    r.line(300, 448).line(256, 448).close()
    return [l, r]


def bbox_of(paths: list[Path]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for p in paths:
        for poly in p.flatten():
            for x, y in poly:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys))


MARK_BBOX = bbox_of(build_mark("#000000", "#000000"))


# --- Inter wordmark ------------------------------------------------------------

_font800: TTFont | None = None
_cap_ratio: float | None = None
_tmp800: str | None = None


def inter800() -> TTFont:
    global _font800
    if _font800 is None:
        font = TTFont(str(FONT_PATH))
        instantiateVariableFont(font, {"wght": 800}, inplace=True)
        _font800 = font
    return _font800


def cap_ratio() -> float:
    global _cap_ratio
    if _cap_ratio is None:
        f = inter800()
        _cap_ratio = f["OS/2"].sCapHeight / f["head"].unitsPerEm
    return _cap_ratio


def inter800_file() -> str:
    """Instanced wght-800 TTF on disk for Pillow."""
    global _tmp800
    if _tmp800 is None:
        fd, _tmp800 = tempfile.mkstemp(suffix="-inter800.ttf")
        import os
        os.close(fd)
        inter800().save(_tmp800)
    return _tmp800


def wordmark_svg(cap: float, x0: float, baseline: float,
                 market_fill: str, mate_fill: str,
                 ) -> tuple[str, float]:
    """'Market' + 'Mate' as path elements; returns (svg, width)."""
    font = inter800()
    sc = cap / font["OS/2"].sCapHeight
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    track = TRACK * cap
    els: list[str] = []
    x = x0
    for word, colour in (("Market", market_fill), ("Mate", mate_fill)):
        ds: list[str] = []
        pen_x = 0.0
        for ch in word:
            name = cmap[ord(ch)]
            pen = SVGPathPen(gs)
            tp = TransformPen(pen, (sc, 0, 0, -sc, x + pen_x, baseline))
            gs[name].draw(tp)
            d = pen.getCommands()
            if d:
                ds.append(d)
            pen_x += hmtx[name][0] * sc + track
        els.append(f'<path d="{" ".join(ds)}" fill="{colour}"/>')
        x += pen_x
    x -= track  # no trailing tracking after the last glyph
    return "".join(els), x - x0


def lockup_layout(left: str, right: str,
                  cap: float = WORD_CAP, gap: float = WORD_GAP,
                  ) -> dict[str, float]:
    """Shared SVG/PNG lockup geometry: mark box + wordmark to its right,
    cap-centre on the mark's visual centre."""
    x0, y0, _x1, y1 = MARK_BBOX
    cy = (y0 + y1) / 2
    baseline = cy + cap / 2
    wm_x = DESIGN + gap
    _, wm_w = wordmark_svg(cap, wm_x, baseline, left, right)
    pad = 8.0
    vx0, vy0 = min(x0, 0.0) - pad, min(y0, baseline - cap) - pad
    vx1, vy1 = wm_x + wm_w + pad, max(y1, baseline) + pad
    return {"baseline": baseline, "wm_x": wm_x, "wm_w": wm_w,
            "vx0": vx0, "vy0": vy0, "w": vx1 - vx0, "h": vy1 - vy0}


# --- SVG -----------------------------------------------------------------------


def _svg_doc(width: float, height: float, vb: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_num(width)}" height="{_num(height)}" viewBox="{vb}">\n'
        "<title>MarketMate</title>\n" + body + "\n</svg>\n"
    )


def mark_svg(left: str, right: str) -> str:
    body = "".join(f'<path d="{p.svg_d()}" fill="{p.fill}"/>'
                   for p in build_mark(left, right))
    return _svg_doc(DESIGN, DESIGN, f"0 0 {DESIGN} {DESIGN}", body)


def lockup_svg(left: str, right: str, word_left: str | None = None) -> str:
    lay = lockup_layout(left, right)
    grp = "".join(f'<path d="{p.svg_d()}" fill="{p.fill}"/>'
                  for p in build_mark(left, right))
    wm, _ = wordmark_svg(WORD_CAP, lay["wm_x"], lay["baseline"],
                         word_left or left, right)
    vb = (f"{_num(lay['vx0'])} {_num(lay['vy0'])} "
          f"{_num(lay['w'])} {_num(lay['h'])}")
    return _svg_doc(lay["w"], lay["h"], vb, grp + wm)


def write_svgs(pair: str = "E") -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    left, right = PAIRS[pair]
    word_left = WORD_LEFT.get(pair, left)
    (BRAND_DIR / "mark.svg").write_text(mark_svg(left, right))
    (BRAND_DIR / "mark-dark.svg").write_text(
        mark_svg(DARK_LEFT[pair], right))
    (BRAND_DIR / "logo.svg").write_text(lockup_svg(left, right, word_left))


# --- PNG -----------------------------------------------------------------------


def _draw_paths(dr: ImageDraw.ImageDraw, paths: list[Path], s: float,
                tx: float, ty: float, fill: tuple, steps: int = 28):
    for p in paths:
        for poly in p.flatten(steps):
            dr.polygon([(x * s + tx, y * s + ty) for x, y in poly], fill=fill)


def _downscale(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    out = img.resize(size, Image.LANCZOS)
    if out.mode == "RGBA":
        # Snap resampling dust: visually identical, keeps solid areas solid.
        alpha = out.getchannel("A").point(lambda a: 255 if a >= 254 else a)
        out.putalpha(alpha)
    return out


def render_mark(size: int, left: str, right: str) -> Image.Image:
    """The two-colour mark on transparency, `size` px square."""
    raw = size * SS
    img = Image.new("RGBA", (raw, raw), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    k = raw / DESIGN
    for p in build_mark(left, right):
        _draw_paths(dr, [p], k, 0.0, 0.0, _hex(p.fill))
    return _downscale(img, (size, size))


def render_icon(size: int, box: int, left: str, right: str,
                border: bool = True) -> Image.Image:
    """The two-colour mark on a white rounded tile (opaque)."""
    raw = size * SS
    img = Image.new("RGB", (raw, raw), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    x0, y0, x1, y1 = MARK_BBOX
    cw, ch = x1 - x0, y1 - y0
    s = (box / max(cw, ch)) * SS
    dx = (raw - cw * s) / 2 - x0 * s
    dy = (raw - ch * s) / 2 - y0 * s
    for p in build_mark(left, right):
        _draw_paths(dr, [p], s, dx, dy, _hex(p.fill))
    out = _downscale(img, (size, size))
    if border:
        # Hairline rounded tile edge, 1px inside so the corners stay white.
        d = ImageDraw.Draw(out)
        d.rounded_rectangle([1, 1, size - 1, size - 1],
                            radius=round(0.22 * size),
                            outline=BORDER, width=1)
    return out


def render_lockup(height: int, left: str, right: str,
                  word_left: str | None = None) -> Image.Image:
    """Full lockup on transparency, `height` px tall."""
    font = inter800()
    cap_units = font["OS/2"].sCapHeight
    upm = font["head"].unitsPerEm
    lay = lockup_layout(left, right)
    w, h = lay["w"], lay["h"]
    width = round(height * w / h)
    img = Image.new("RGBA", (width * SS, height * SS), (0, 0, 0, 0))
    s = height * SS / h
    dr = ImageDraw.Draw(img)
    for p in build_mark(left, right):
        _draw_paths(dr, [p], s, -lay["vx0"] * s, -lay["vy0"] * s,
                    _hex(p.fill))
    em_px = round(WORD_CAP * s / (cap_units / upm))
    pil_font = ImageFont.truetype(inter800_file(), em_px)
    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    track = TRACK * WORD_CAP * s
    x = lay["wm_x"] * s - lay["vx0"] * s
    y = lay["baseline"] * s - lay["vy0"] * s
    for word, colour in (("Market", word_left or left), ("Mate", right)):
        for ch in word:
            # anchor="ls" puts the advance origin at x, matching the SVG.
            dr.text((x, y), ch, font=pil_font,
                    anchor="ls", fill=_hex(colour) + (255,))
            x += hmtx[cmap[ord(ch)]][0] / upm * em_px + track
    return _downscale(img, (width, height))


def write_pngs(pair: str = "E") -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    left, right = PAIRS[pair]
    word_left = WORD_LEFT.get(pair, left)
    jobs = [
        ("mark-64.png", render_mark(64, left, right)),
        ("mark-256.png", render_mark(256, left, right)),
        ("favicon-16.png", render_mark(16, left, right)),
        ("favicon-32.png", render_mark(32, left, right)),
        ("apple-touch-icon.png",
         render_icon(180, round(180 * 0.76), left, right)),
        ("icon-192.png", render_icon(192, round(192 * 0.8), left, right)),
        ("icon-512.png", render_icon(512, round(512 * 0.8), left, right)),
        ("icon-maskable-512.png",
         render_icon(512, 400, left, right, border=False)),
        ("logo-full.png", render_lockup(160, left, right, word_left)),
        ("logo-full@2x.png", render_lockup(320, left, right, word_left)),
    ]
    for name, img in jobs:
        img.save(BRAND_DIR / name)
    ico_sizes = [(16, 16), (32, 32), (48, 48)]
    ico_imgs = [render_mark(n, left, right) for n, _ in ico_sizes]
    # Largest first: the ICO writer skips sizes bigger than the first image.
    ico_imgs[-1].save(BRAND_DIR / "favicon.ico", format="ICO",
                      sizes=ico_sizes, append_images=ico_imgs[:-1])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Regenerate MarketMate brand assets.")
    ap.add_argument("--pair", choices=sorted(PAIRS), default="E",
                    help="colour pair (default E: meta blue + green)")
    args = ap.parse_args(argv)
    write_svgs(args.pair)
    write_pngs(args.pair)
    for path in sorted(BRAND_DIR.iterdir()):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
