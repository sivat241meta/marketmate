# Fonts (Task 76)

English (Latin) text uses Inter; Tamil, Hindi and the other Indian scripts
keep their Noto fonts. Plus Jakarta Sans is no longer used by the UI, but
its file stays in the repo because `scripts/make_brand_assets.py` (the logo
generator) uses it.

## Inter (Latin UI + PDFs)

- Source: official release only, https://github.com/rsms/inter/releases
- Release: v4.1 (`Inter-4.1.zip`, 15 Nov 2024)
- Files taken from the zip (nothing else):
  - `InterVariable.ttf` → `app/web/static/fonts/InterVariable.ttf`
    (web fallback + WeasyPrint PDFs)
  - `web/InterVariable.woff2` → `app/web/static/fonts/InterVariable.woff2`
    (first choice for the web UI)
  - `LICENSE.txt` → `app/web/static/fonts/Inter-LICENSE.txt`
    (SIL Open Font License 1.1)
- No italic file: the UI never renders italics (every `<em>`/`<i>` is
  `font-style: normal` or an icon), so `InterVariable-Italic.ttf` is skipped.
- CSS: `app/web/static/app.css` declares `@font-face "Inter"` first for
  Latin (`font-display: swap`, Latin `unicode-range`), then the Noto
  families for their scripts. Prices, totals and tables use Inter's
  tabular numbers (`font-feature-settings: "tnum" 1`).
- PDFs: `board.html`, `tags.html`, `bill_pdf.html`, `quote_pdf.html`,
  `close_pdf.html` and `link_card.html` load `InterVariable.ttf` via the
  local file path for Latin, Noto for Tamil/Hindi as before.

| File | SHA-256 |
| --- | --- |
| InterVariable.ttf | `4989b125924991b90d05b2d16e0e388c48f7d5bb8b30539bbf9c755278d0ccaf` |
| InterVariable.woff2 | `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3` |
| Inter-LICENSE.txt | `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a` |

## Noto (Tamil, Devanagari, Bengali, Telugu, Kannada + Latin fallback)

Unchanged — see `app/web/static/fonts/SOURCES.md`. The Tamil and
Devanagari `@font-face` rules keep their `unicode-range`s, so Tamil and
Hindi text renders exactly as before.
