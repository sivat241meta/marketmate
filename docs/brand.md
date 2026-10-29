# MarketMate brand

The MarketMate logo was drawn in code by Muse Code — there is no image
source file. The generator script `scripts/make_brand_assets.py` defines the
mark geometry once (in a 512×512 design space) and emits the SVGs plus every
PNG/ICO from that same geometry, so the SVG and PNG versions match.

## The logo

- **The mark**: "Mm leaves" — a lowercase "m" whose two humps peak in
  outward leaf tips, in two different colours: LEFT leaf purple `#5F55EE`
  (the app's primary), RIGHT leaf fresh green `#1FA34A`. The two halves
  share their middle edge (no thin gap), so small sizes keep both colours.
  Flat style, cubic-Bezier paths, no outlines, no gradients.
- **The wordmark**: "Market" in purple + "Mate" in green, echoing the
  mark's left-to-right pairing, set in Inter ExtraBold. The glyphs are
  converted to SVG paths at build time, so `logo.svg` needs no font.
  (Purple on white is 5.0:1, so the wordmark still passes AA.)
- **The lockup**: mark on the left, wordmark to the right, cap-centre on
  the mark's visual centre, gap 0.25× the design box, −1.5% tracking.
- **Dark-background variant**: `mark-dark.svg` lightens the left leaf to
  `#7B68EE` (4.0:1 on `#1E1F21`, vs 3.3:1 for `#5F55EE`); the right leaf
  stays green. Used on the dark seller top bar and rail.

## Colours (pair A, the default)

| Use | Colour |
| --- | --- |
| Left leaf / "Market" | Purple `#5F55EE` (app primary) |
| Right leaf / "Mate" | Fresh green `#1FA34A` |
| Left leaf on dark chrome | Lighter purple `#7B68EE` (`mark-dark.svg` only) |
| App-icon tile | White with a 1px `#E2E5EA` border |
| Dark chrome (top bar, rail) | `#1E1F21` |

## Colour pairs

The script can emit the logo in four pairings (mark + wordmark follow the
pair; the dark variant lightens the left colour when it is weak on dark):

| Pair | Left | Right | Dark-variant left |
| --- | --- | --- | --- |
| A (default) | Purple `#5F55EE` | Green `#1FA34A` | `#7B68EE` |
| B | Green `#1FA34A` | Orange `#F28C28` | unchanged (5.1:1) |
| C | Navy `#1B2A5C` | Green `#1FA34A` | `#6C7FD8` (navy would vanish) |
| D | Purple `#5F55EE` | Orange `#F28C28` | `#7B68EE` |

To switch pairs (regenerates + overwrites every asset):

```sh
.venv/bin/python scripts/make_brand_assets.py --pair B
```

Commit the script and its outputs together.

## Font

Inter, already in the repo at `app/web/static/fonts/InterVariable.ttf`
under the SIL Open Font License (see `app/web/static/fonts/OFL.txt`). The
script instantiates the variable font at `wght=800` with
`fontTools.varLib.instancer` and converts the glyphs to paths with a
fontTools pen.

## Files (all under `app/web/static/brand/`)

`logo.svg` (full lockup), `mark.svg` (mark only), `mark-dark.svg` (mark
for dark backgrounds), `mark-64.png`, `mark-256.png`, `favicon-16.png`,
`favicon-32.png`, `favicon.ico` (16+32+48), `apple-touch-icon.png` (180,
two-colour mark on a white rounded tile), `icon-192.png`, `icon-512.png`
(same), `icon-maskable-512.png` (mark on white inside the safe zone),
`logo-full.png` / `logo-full@2x.png` (full lockup, transparent).

## Usage

- Dark chrome (seller top bar, rail): the **`mark-dark.svg`** mark only.
- White headers (seller phone top bar, customer header, landing header):
  the **full logo** at 26–28px tall; the landing hero shows it at ~56px.
- PDFs/print: full logo on white headers (bill, day close), the mark on dark
  or coloured headers (price board, quote, shelf tags).

## Regenerating

```sh
.venv/bin/python scripts/make_brand_assets.py
```

The script needs only Pillow and fontTools, is deterministic (re-running it
produces byte-identical outputs), and needs no network. Commit the script
and its outputs together.
