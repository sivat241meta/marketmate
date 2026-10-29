# MarketMate brand

The MarketMate logo was drawn in code by Muse Code — there is no image
source file. The generator script `scripts/make_brand_assets.py` defines the
mark geometry once (in a 512×512 design space) and emits the SVGs plus every
PNG/ICO from that same geometry, so the SVG and PNG versions match.

## The logo

- **The mark**: a bold, rounded letter "M" that is also a shopping basket —
  two thick rounded legs with the middle dipping into a V (the basket front),
  a semicircular handle arcing above, and fresh produce peeking out between
  the legs (red tomato with a green star calyx, a round orange vegetable,
  three green leaves). Flat style, no outlines.
- **The wordmark**: "Market" in navy + "Mate" in green, set in Plus Jakarta
  Sans ExtraBold. The glyphs are converted to SVG paths at build time, so
  `logo.svg` needs no font.
- **The lockup**: mark on the left, wordmark to the right, vertically
  centred, with a gap of 0.25× the mark height.

## Colours

| Use | Colour |
| --- | --- |
| Mark gradient, top-left | Lime `#8CD03A` |
| Mark gradient, middle | Green `#22A955` |
| Mark gradient, bottom-right | Blue `#1F6FD6` |
| Basket handle | Green `#2DB34A` |
| Wordmark "Market" | Navy `#1B2A5C` |
| Wordmark "Mate" | Green `#2DA94F` |
| Tomato / orange / dark leaf | `#E8442E` / `#F59E0B` / `#1F9D44` |

The v9 UI tokens (purple etc.) are unchanged — the brand colours above are
only used for the logo itself.

## Font

Plus Jakarta Sans, already in the repo at
`app/web/static/fonts/PlusJakartaSans-Variable.ttf` under the SIL Open Font
License (see `app/web/static/fonts/OFL.txt`). The script instantiates the
variable font at `wght=800` with `fontTools.varLib.instancer` and converts
the glyphs to paths with a fontTools pen.

## Files (all under `app/web/static/brand/`)

`logo.svg` (full lockup), `mark.svg` (mark only), `mark-64.png`,
`mark-256.png`, `favicon-16.png`, `favicon-32.png`, `favicon.ico`
(16+32+48), `apple-touch-icon.png` (180, mark on white), `icon-192.png`,
`icon-512.png` (mark on white), `icon-maskable-512.png` (mark inside the 80%
safe zone), `logo-full.png` / `logo-full@2x.png` (full lockup, transparent).

## Usage

- Dark chrome (seller top bar, rail): the **mark** only — navy wordmark text
  would vanish on dark backgrounds.
- White headers (seller phone top bar, customer header, landing header):
  the **full logo** at 26–28px tall; the landing hero shows it at ~56px.
- PDFs/print: full logo on white headers (bill, day close), the mark on dark
  or coloured headers (price board, quote, shelf tags).

## Regenerating

```sh
.venv/bin/python scripts/make_brand_assets.py
```

The script needs only Pillow and fontTools, is deterministic (re-running it
produces byte-identical PNGs), and needs no network. Commit the script and
its outputs together.
