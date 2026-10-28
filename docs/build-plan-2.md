# MarketMate build plan, phase 2 (Tasks 22–30)

For Muse Code workers. Read `docs/build-plan.md` Global Constraints first; they still apply
(models, honesty rules, copy rules, commit trailer `Built-with: Muse Code`, never push).

**Goal:** turn the working pipeline into a polished product. The work covers:
- a Fresh Market look on mobile and web;
- clear upload progress;
- photo counting with suggestions;
- customer quotations;
- a seller bills dashboard;
- all 25 Muse Voice languages, with measured results.

## Ground rules added in phase 2

- **Prices come only from the seller.** That means spoken prices, or numbers the seller typed and confirmed.
  - Photos never produce a price.
  - Quotes and bills only use the shop's published price lines.
  - An item that isn't on the shop's list is shown as "not on this shop's list", never priced.
- **Photo counts are estimates and are labelled that way.**
  - Wording: "about N visible", or "between A and B, please check" when the two counters disagree.
  - The seller or customer can always edit a count.
- **Condition notes are for the seller only.** Example: "looks fresh". They never appear on public pages.
- **Measured facts on 28 Oct** (photos from eval/clips/src_wikimedia and the owner's video):
  - SAM 3.1 returns one box per visible item and over-counts on tight heaps:
    - coconut crate: 40 raw boxes for about 20–24 visible coconuts;
    - shallot tray: 36;
    - tomato heap: 84 raw, 74 after de-duplication.
  - Muse Spark (vision, `reasoning_effort="low"`) names products well and gives a count:
    - shallot vs. onion: 27 shallots + 1 onion;
    - coconut 24, plus 13 potatoes it spotted in a net;
    - tomato 75; banana 18.
  - Cost: about $0.01 per photo for Spark, plus $0.0025 per SAM call.
- **Muse Voice supports exactly these 25 languages.** Pass the names, as written, in `languageBias`:
  Arabic, Bengali, Dutch, English, French, German, Hebrew, Hindi, Indonesian, Italian,
  Japanese, Kannada, Korean, Malay, Mandarin Chinese, Marathi, Polish, Portuguese, Spanish,
  Tagalog, Tamil, Telugu, Thai, Turkish, Vietnamese.

## Look: "Fresh Market" (owner picked this on 28 Oct)

Reference mockup: `docs/ui/fresh-market.html`. Open it in a browser; it shows four phone screens.

Design tokens:

| Token | Value |
|---|---|
| Green (primary) | `#14532d` |
| Saffron (action) | `#f59e0b`, pressed shadow `#c77c06` |
| Cream background | `#fbf7ef` |
| Ink | `#1c1917` |
| Muted text | `#78716c` |
| Card border | `#efe8d8` |
| Success | `#15803d` |
| Font | system UI stack (`-apple-system, "Segoe UI", Roboto, "Noto Sans", system-ui, sans-serif`) plus the bundled Noto Sans Tamil; no font downloads |
| Radius | cards 18–22px, buttons 14–16px |

No external CDN at runtime.

Layout and behaviour:
- **Phone first** (360–430px): one column, sticky bottom action bar where a page has one main action.
- **Web (≥ 900px):**
  - seller pages use a left sidebar (Dashboard, Prices, Photos, Bills, Shop page, Settings) and a content column of at most 1100px;
  - customer pages use a 3–4 column product grid.
- **Accessibility:**
  - minimum 44px tap targets;
  - colour contrast AA;
  - every icon button has a text label;
  - `prefers-reduced-motion` respected.

## Tasks

| # | Task | Main files |
|---|---|---|
| 22 | Design system and app shell; restyle home, new shop, seller dashboard, error | `app/web/static/app.css`, `templates/base.html`, `templates/_ui.html` (Jinja macros), home, new_shop, seller, error |
| 23 | Restyle review, shop page, market, update, try, board PDF | review, shop, market, update, board templates; review.js keeps all `data-*` hooks |
| 24 | Upload and processing progress | `app/jobs.py`, `app/pipeline/run.py`, `app/db.py` (session stage), session template, `static/upload.js` |
| 25 | Photo analysis engine | `app/pipeline/vision.py`, `app/db.py` (photo_checks, stock fields) |
| 26 | Seller photo screens: scan stock, boxes overlay, counts, suggestions | `app/web/photos.py`, `templates/photo.html`, `static/photo.js` |
| 27 | Customer quotation: voice, text or photo to quote, WhatsApp or PDF | `app/market/quote.py`, `app/web/quotes.py`, templates quote*.html |
| 28 | Seller bills dashboard | `app/web/bills.py`, `templates/bills*.html`, `app/outputs/bill_pdf.py` |
| 29 | 25 languages | `app/languages.py`, numbers verification, extraction prompt, shop form, UI strings |
| 30 | Language test clips and benchmark | `scripts/make_lang_clips.py`, `scripts/lang_benchmark.py`, `docs/languages.md` |

Detailed requirements for each task are given in that task's prompt. They're summarised here so
the whole phase is reviewable in one place.

**Task 24: progress.**
- Upload uses XHR with a percentage bar and a cancel button.
- Processing stages, saved on the session:
  - uploaded;
  - getting the sound out;
  - listening to the prices (speech to text);
  - finding the items;
  - picking photos;
  - checking every price;
  - ready.
- Each stage has a start time. A detail line such as "item 3 of 5" is shown where it's known.
- `/status` returns `{status, stage, step, steps, detail, elapsed_s}`.
- The page polls every 1.5 s and shows a stepper. A failure shows a plain reason and a Retry button.

**Task 25: photo engine.**
- `analyse_photo(path, *, shop_items, ledger, settings) -> PhotoReport`:
  1. Spark vision lists the products: name_en, local name, countable, visible_count, condition, photo_quality.
  2. For each countable product, SAM counts with the product name as the prompt.
  3. `dedupe_boxes` drops boxes under 30% of the median area, then drops boxes that are at least 60% inside a larger kept box.
  4. Reconcile the counts: if the two are within 20% of each other, show `count = round(mean)`; otherwise show a range `[min, max]` with `needs_check=True`.
- Suggestions are deterministic rules, never prices:
  - **retake:** the photo is dark, blurry or too far;
  - **add_price:** the product isn't on the shop's list; action: say its price;
  - **back_on_sale:** the product is visible but marked sold out;
  - **set_stock:** the product is countable and has a count.
- Saved in a `photo_checks` table. Items get `stock_qty`, `stock_unit` and `stock_source`.

**Task 27: quotation.**
- Input is a spoken list, a typed list, or a photo of items or of a handwritten list.
- The engine:
  - parses the input into wanted lines;
  - matches them against the shop's latest published price lines (using SYNONYMS);
  - computes Decimal totals.
- Unknown items are listed without a price.
- Weight items need a quantity, defaulting to 1 of the shop's unit and editable.
- Countable items take their quantity from the photo count.
- The quote gets an unguessable link `/q/{token}`. From there the customer can share it on WhatsApp to the seller, or download a PDF.

**Task 28: bills.**
- `/e/{token}/bills` shows:
  - today's tiles: bills, sales in ₹, quotes waiting;
  - a list of quotes and bills with status (quote / billed / paid);
  - a "New bill" button: by voice, typing, photo, or tapping items;
  - a bill page with editable quantities, Mark paid, and Share or Print PDF;
  - top items today.

**Task 29: languages.**
- A registry of the 25 languages: API name, code, native name, script, default currency, currency words.
- The shop form lists all 25 by native name. `languageBias` is [shop language, English].
- Item names are stored as `name_local` (rename `name_ta` with a migration).
- Numbers count as heard when the digits appear in the transcript, or when they're parsed from number words:
  - English and Tamil: existing parsers;
  - Hindi: new parser, plus Devanagari and other Indic digits.
- Other languages are cross-checked: a second, independent model call turns only the quoted number phrase into digits.
  - If the two agree, the number counts as heard.
  - If they disagree, a blocking NUMBER_CHECK flag offers both values.
- UI labels: English everywhere. Tamil and Hindi strings for the customer shop page.

**Task 30: language benchmark.**
- One synthetic clip per language that has a macOS `say` voice, made from the Wikimedia photos.
- Each clip uses the same 4 items with known answers, using the scripts in `eval/lang/scripts.json`.
- Results are written to `docs/languages.md`, one row per language: voice, found, exact, flagged, wrong-unflagged, cost.
- Languages with no test voice are listed as "not tested". They are never claimed as working.
