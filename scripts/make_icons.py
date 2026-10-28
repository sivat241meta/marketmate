"""Generate PWA icons from the MarketMate leaf logo.

Draws the base.html brand mark (green leaf, saffron stem) on the cream
background with Pillow, at 192 and 512 px.

Usage: .venv/bin/python scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

GREEN = "#14532d"
SAFFRON = "#f59e0b"
CREAM = "#fbf7ef"

OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "icons"


def make_icon(size: int) -> Image.Image:
    """Cream square with the green leaf + saffron stem, `size` px."""
    img = Image.new("RGB", (size, size), CREAM)
    # Leaf on its own layer so it can be rotated 45 degrees.
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    margin = int(size * 0.20)
    draw.ellipse([margin, int(size * 0.10), size - margin,
                  int(size * 0.90)], fill=GREEN)
    layer = layer.rotate(45, resample=Image.BICUBIC, center=(size / 2, size / 2))
    img.paste(layer, (0, 0), layer)
    # Saffron stem from the bottom-left towards the centre.
    stem = ImageDraw.Draw(img)
    width = max(2, size // 16)
    stem.line([(size * 0.20, size * 0.80), (size * 0.52, size * 0.48)],
              fill=SAFFRON, width=width, joint="round")
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = OUT_DIR / f"icon-{size}.png"
        make_icon(size).save(path, format="PNG")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
