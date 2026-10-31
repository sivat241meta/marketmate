# MarketMate — design

Status: draft for approval (27 Oct 2026). Owner: Siva (solo, Indie track).
Source: the owner's "MarketMate AI — Complete Hackathon Project Blueprint" (27 Oct), narrowed
here to what is buildable and honest in 8 days. Section 7 lists where this differs from it.
Event: Meta Global AI Developer Hackathon. Building 27 Oct – 4 Nov 2026.
Submission deadline: Wed 4 Nov 9 PM ET = **Thu 5 Nov 07:30 IST**.

---

## 1. Intent

Small vegetable and fruit sellers change prices every day, keep them in their head or on a
chalkboard, and rarely type. MarketMate lets a seller **film their stall and say their prices
the way they already talk** (Tamil and English, mixed). It turns that into a **checked price
list**, a **printed price board**, a **public shop page** and a **POS file**. Customers then
use those same checked prices to find what they want, compare shops and plan a budget.

**Who it serves, in priority order:**
1. **Sellers (main user, ~80% of the effort).** It saves them typing, gives them a price board and
   a shop page for free, and shows their stock value.
2. **Customers (second user, ~20%).** They can see today's prices before walking to the market,
   compare stalls and fit a budget.

**What makes it different (the "why us"):**
- **Speech is the only source of prices and quantities.** The AI never invents or "suggests" a
  price. A rival in this hackathon (Souk Lens) has the AI suggest prices; we do the opposite.
- **Proof for every number.** Every price links to the seller's own words (quote and audio clip)
  and the video moment it came from. Anything uncertain is flagged for a one-tap check.
- **One recording, many uses.** The same verified data drives the PDF price board, the public
  page, the POS export and customer search, so nothing is entered twice.

**Headline message for the demo:** *"One recording. One checked price list. Every way to sell."*

We do not claim the concept is new. Voice inventory, photo-to-listing and shop-ledger apps
exist, including several in this hackathon. Our claim is the proof-first, speech-first
workflow for produce sellers, connected to customers.

---

## 2. Goals, non-goals, anti-goals

### Goals (must work end to end in the demo and for judges)
1. Seller records a stall video (≤ 3 min) while speaking items and prices in Tamil, English or
   a mix of both. The app produces a draft price list: item, variety, price, unit and, if
   spoken, quantity.
2. Every draft field carries proof: transcript quote, audio timestamp and a video frame. Fields
   without proof are left blank, not guessed.
3. Automatic checks flag risky values: sound-alike numbers (18/80 and similar), a price not
   found in the transcript, a big jump from yesterday's price, a missing unit, and a video
   frame that doesn't seem to show the spoken item.
4. A review screen where the seller confirms or fixes every flagged field and approves the list.
5. Real product photos: the item cut out of the seller's own video frame with SAM 3.1.
6. **Seller outputs:**
   - a printable PDF price board (Tamil + English, with a QR code to the shop page);
   - a public shop page;
   - a CSV export (one generic file).
7. **Next-day voice update:** the seller says "thakkali 22, vengayam sold out" with no video.
   The app shows the changes and the seller confirms them.
8. Stock value = sum of (confirmed quantity × confirmed price). It only counts items whose units
   match, and lists what's missing otherwise.
9. **Customer side:**
   - search across published shops by text or voice, e.g. "tomato under ₹25", "shop with
     tomato, onion and potato";
   - compare shops with "last updated" times, where stale listings are marked;
   - budget basket ("I have ₹300 for tomato, onion, potato, chilli");
   - call or chat link to the seller.
10. A measured benchmark from real recordings: item recall, exact-price accuracy before review,
    and the share of errors the checks caught. We report only numbers we measured.

### Non-goals (this hackathon)
- Payments, orders, delivery, reservations, stock sync with a POS, direct POS API integrations.
- Estimating weight or count from video. Quantity comes from the seller only.
- Demand forecasting, mandi-price comparison, price trends beyond "changed since last update".
- Native mobile apps. This is a mobile-first web app.
- Languages beyond Tamil + English in the demo. The speech model supports 25 languages (of
  which 6 are Indian), and those may work, but we only claim what we tested.
- Seller accounts with passwords.

### Anti-goals (would make this a failure even if it "works")
- **Any price, quantity or unit shown to customers that the seller didn't confirm.**
- AI-generated product images or AI-drawn prices. Image models garble numbers, and a fake
  "nice tomato" photo misleads customers.
- Quality verdicts presented as freshness or food-safety guarantees, or auto-published to
  customers.
- Inventing accuracy figures, user numbers or "market prices" in the demo or README. Demo shops
  must be labelled as demo data.
- Claiming support for languages or POS systems we didn't test.
- Spending more than the free credits. The owner's limit is ≤ $5 of their own money; the plan
  is $0.

---

## 3. Constraints

### Meta models

All facts below were checked against dev.meta.ai docs on 27 Oct 2026 unless marked otherwise.

| Model | ID | Use in MarketMate | Limits that matter |
|---|---|---|---|
| Voice Transcribe | `muse-voice-transcribe-1.0` | Seller speech (video audio, daily update); customer voice search | File endpoint `POST /v1/asr/transcribe`: WAV mono 16-bit PCM 16/24 kHz, ≤ 10 min, ≤ 32 MB. 25 languages incl. Tamil, code-switching. **Turn-level timestamps only, no word-level, no confidence scores.** Keyword biasing is supported. $0.18/hour |
| Muse Spark | `muse-spark-1.3` (text + image) | Extract items/prices as JSON with quotes; check that a frame shows the spoken item; visible-condition hints; parse customer queries; translate item names | Reasons before answering, so even "OK" used ~240 hidden reasoning tokens in our key check. **Use generous `max_tokens`.** Use 1.2 if audio input is ever sent directly (1.3 audio is degraded) |
| SAM 3.1 | `sam-3.1` | Cut out each product from its best frame for the photo | Masks and boxes only, cannot name or read text; one noun phrase per request; $2.50 per 1,000 images |
| Muse Spark Open | `meta-models/muse-spark-open-1026` via Baseten (`https://inference.baseten.co/v1`, key `BASETEN_API_KEY`) | Switchable provider (`TEXT_PROVIDER`) for text-only steps: extraction, voice-update parsing, customer query, basket wording. The benchmark compares it with Muse Spark 1.3 (open-weights bonus) | $100 Baseten credit, up to 2M tokens/min. Image steps always use Meta |

**Not used:** Muse Image (no AI product photos or prices). Muse Wonder (POS typing agent) is
postponed.

The API is OpenAI-SDK compatible. The base URL is `https://api.meta.ai/v1` and the key is
`MODEL_API_KEY` in `.env`. The key is verified working (27 Oct). Meta's spend limit only sends
a notification, so **the app must enforce its own daily cost cap.**

### Money and hosting
- **Hosting:** a Modal web app (free Starter credit; spend limit set to $0), served at a free
  `*.modal.run` URL with no custom domain. Modal Volumes for SQLite + media. Volume storage can
  bill, so keep media small.
- **Cost guards:** app-level daily budget (e.g. $3/day), max video 3 min, max uploads per hour
  for the public demo, and cached results so judges replaying samples cost nothing.

**Cost per recording.** This is an estimate, to be measured on Day 1 with real token counts.
Prices are from Meta's price list:
- Muse Spark costs $1.25 per 1M input tokens and $4.25 per 1M output tokens; hidden reasoning
  tokens count as output.
- Voice Transcribe costs $0.18/hour; SAM costs $2.50 per 1,000 images.

For a 2-minute, 10-item video:
- transcription ≈ $0.01;
- extraction ≈ $0.02;
- picture checks (≈3 frames × 10 items) ≈ $0.05–0.10;
- SAM ≈ $0.03.

**Total: roughly $0.10–0.20 per recording.** Use the batched picture check (all frames of one
item in one call) if the measured cost is at the high end.

Never use the `-contributor` model variants for seller data: they are cheaper, but Meta trains
on what's sent to them. The owner should confirm how much Meta credit is on the key from the
billing page; the daily cap is a config value.

### Judging rubric
Impact 30%, Meta AI tooling 25%, technical depth 20%, demo 25%. Required:
- a public repo, with only new work built during the hackathon;
- a 3-minute demo video;
- a live product judges can try.

Anti-project risk: "simple image analyzers", which is why quality is a minor, seller-only hint.

### Repo rules
- Never commit `.env`; keep secrets in a Modal Secret.

### Privacy
- Audio goes to Meta's cloud API, and the app must say so.
- Don't publish raw video. Keep only proof frames and cut-outs.
- Shop location is area-level text, entered by the seller. No GPS.
- Get sellers' consent before filming real stalls; avoid faces in published crops.

---

## 4. How it works (decided)

### 4.1 Seller flow
```
Create shop (name, phone, area, language, currency, type)
   └─► gets a private EDIT LINK (no password) + a public SHOP PAGE link
Record stall video and speak  ──►  processing (≈1–2 min, progress shown)
   1. ffmpeg: audio → WAV 16 kHz mono; frames → 2 per second (JPEG)
   2. Voice Transcribe (+ keyword list of produce names, Tamil + English) → turns with times
   3. Muse Spark → JSON items [{name, variety, price, unit, qty?, quote, turn}]
   4. Code checks → flags (see 4.3)
   5. For each item: frames inside its turn → Muse Spark picks the frame that shows it best
      and says if it matches → mismatch = flag
   6. SAM 3.1 on that frame with the item's English noun ("tomato") → cut-out photo
   7. (stretch) Muse Spark visible-condition hint on the cut-out → seller-only
Review screen: one card per item (photo, fields, quote, ▶ play audio clip, flags)
   seller taps to fix / confirm / delete / add missing item → APPROVE
Approved list = new dated version ──► three actions:
   [Print price board PDF]  [Publish today's prices]  [Export CSV]
Next day: "Update prices by voice" → transcribe → Muse Spark diff → seller confirms → new version
```

### 4.2 Customer flow
```
Scan QR on a price board or open the market page
   ├─ Shop page: today's prices, real photos (from today's video), "set by seller · 10 min ago"
   │             call / chat link (tel: and wa.me, no WhatsApp API)
   ├─ Search (type or speak): "tomato under 25", "shop with tomato, onion, potato"
   │      Muse Spark turns words into a structured query → plain database query (code)
   │      results table: shop · price · unit · last updated · stale marker (> 24 h)
   └─ Budget basket: "₹300: tomato 1 kg, onion 1 kg, potato 2 kg, chilli 100 g"
          code computes cheapest fresh options (one shop or split) → numbers from code;
          Muse Spark only writes the friendly explanation around them
```

### 4.3 Checks that keep numbers honest (core of the technical-depth story)
1. **Quote check:** every price/quantity must appear in its quote. It can be digits or number
   words; Tamil and English number words are parsed by our own code. Otherwise flag "not heard".
2. **Sound-alike check:** if the number was said in English and is one of 13–19 / 30–90, flag
   it for a one-tap choice ("18 or 80?").
3. **Unit check:** a missing unit, or one that doesn't fit the item (e.g. tomato "per piece"),
   gets flagged. Units are normalised: kg, g, piece, dozen, bunch, packet.
   - **Every price is "₹X for an amount":** ₹40 for 1 kg, ₹15 for 250 g ("kaal kilo 15"),
     ₹10 for 4 pieces.
   - An item may have **several price lines** ("kilo 40, 2 kilo 70").
   - **Ranges** ("30–35") are never stored. They are flagged, and the seller picks one number.
   - Search and the budget use a per-kg or per-piece rate computed from the lowest-amount line.
     Lines that can't be converted (e.g. bunch) are compared only with the same unit.
4. **Jump check:** a change of more than ±50% vs the seller's last confirmed price gets flagged.
5. **Picture check:** a frame that doesn't show the spoken item gets flagged. **The speech
   decides the name and variety; vision only confirms.**
6. **Nothing reaches customers without seller approval.** Stock value is computed only from
   confirmed fields with compatible units. Anything else is listed as "missing".

### 4.4 Data (SQLite)
- `shops`: id, slug, name, phone, area, language, currency, type, edit_token_hash, is_demo
- `sessions`: id, shop_id, kind (video | voice_update), status, cost, created_at
- `drafts`: id, session_id, fields + per-field proof (quote, t_start, t_end, frame), flags,
  photo, condition_hint
- `versions`: id, shop_id, created_at, published (bool). Approved lists are immutable versions.
- `items`: id, version_id, name_ta, name_en, variety, qty, qty_unit, photo, proof
- `price_lines`: id, item_id, price, per_amount, unit
  (e.g. 15, 250, g). One item has one or more lines.

**Proof and storage:**
- `proof` holds, per field, the quote text, `t_start`/`t_end`, the frame path and the audio clip
  path.
- **Proof is shown to the seller only** (review screen and history). Customers see the real
  photo and "set by seller · <time>", not the seller's voice or quotes.
- Raw video is deleted after processing.
- Frames, cut-outs and per-item audio clips (a few seconds, compressed) are kept 30 days.
  Demo shops keep theirs.

### 4.5 Outputs
- **PDF price board:** A4, Tamil + English names, real photos, prices in big type, date/time,
  shop name and phone, QR to the shop page. Tamil must render with correct shaping, so use an
  engine with HarfBuzz shaping (e.g. WeasyPrint or headless Chromium) and Noto Sans Tamil.
- **Public pages:** `/s/<slug>` (shop page) and `/market` (search, compare, budget).
  Mobile-first. Language toggle Tamil/English; item names are translated once at publish time
  and cached.
- **CSV:** a single generic file (name_en, name_ta, variety, price, unit, qty, updated_at)
  that any billing software can import.

### 4.6 Judges and demo
- **"Try it" mode:** judges film any fruit or vegetable at home for 30 seconds and say prices
  in English or Tamil. Their shop is marked as a judge test shop.
  - Its page works through its own link and QR.
  - It is **not listed in `/market`**; it expires after 7 days.
  - Uploads are rate-limited, so strangers can't fill the public market.
  - To try the customer side, a judge searches the demo market. Their own shop page shows how
    their prices look to customers.
- **`/market` lists only shops the owner marks as listed:** the demo shops (labelled demo data)
  and any real stalls filmed with consent.
- **Sample sessions:** three pre-processed demo shops from real recordings, labelled demo data,
  so the customer side has something to compare. They can be replayed at no cost.
- **3-minute demo:**
  - problem (15 s);
  - film and speak (25 s);
  - processing with proof and one flagged "18 or 80?" (35 s);
  - approve (15 s);
  - PDF board with QR (20 s);
  - publish (10 s);
  - customer scans QR, searches "tomato under 25", budget ₹300 (40 s);
  - next-morning voice update changes the page (10 s);
  - benchmark numbers and Meta models used (10 s).

---

## 5. Order of work and checkpoints (IST)

| Day | Date | Work | Checkpoint |
|---|---|---|---|
| 0 | Tue 27 Oct | Key verified ✓. Record 2 test clips (10 items, Tamil + English prices) | Clips + typed answer key exist |
| 1 | Wed 28 Oct | **Gate test:** transcribe → extract → checks on the clips; one SAM cut-out. Attend "Agents 102: verifiable agents" (9:30 PM IST) | Measured price accuracy and flag rate. If speech-to-item matching is weak, require "one item per sentence" |
| 2 | Thu 29 Oct | Pipeline service + checks + tests on recorded transcripts | Pipeline runs from video to draft JSON |
| 3 | Fri 30 Oct | Frame matching, SAM cut-outs, review screen | Seller can approve a list on phone |
| 4 | Sat 31 Oct | Versions, stock value, PDF (Tamil), CSV, shop page + QR | All three seller actions work |
| 5 | Sun 1 Nov | Voice price update; customer search (text + voice) and compare | Customer can find tomato across shops |
| 6 | Mon 2 Nov | Budget basket; deploy to Modal; cost caps. Stretch: condition hints, photo mode | Live URL works on a phone |
| 7 | Tue 3 Nov | Record at real stalls (with consent); seed demo shops; benchmark; bug fixes | Benchmark table with real numbers |
| 8 | Wed 4 Nov | Demo video, README, architecture notes; **submit by 9 PM IST** | Submitted ~10 h before deadline |

If behind schedule, cut in this order:
1. photo mode;
2. condition hints;
3. budget basket;
4. voice search (keep text);
5. Extra export formats (keep one generic CSV).

Never cut: the proof and checks, the review screen, the PDF, the shop page or the customer
search.

---

## 6. Left to the builder
- Web framework and front-end approach (keep it simple: server-rendered pages with light JS are
  fine), file layout, test framework.
- Exact prompts and JSON schemas for Muse Spark; frame-sampling rate; how many frames are sent
  per item.
- The SAM 3.1 request format (read the docs page): image vs video mode, mask → cut-out
  rendering.
- PDF engine, as long as Tamil shapes correctly.
- Budget-basket algorithm (simple greedy or exhaustive over ≤ 5 items × ≤ 10 shops is fine).
- Exact thresholds (jump %, stale hours, cost cap), within the spirit above.

## 7. Calls I made (owner to check)
1. Video first; photo mode is a stretch goal, not essential (the blueprint called photos
   essential).
2. Visible-quality hints are **seller-only** and never auto-published. Customers judge quality
   from today's real photo instead (the blueprint showed quality on the public page).
3. No passwords: each shop gets a private edit link.
4. Shop location is area text, not GPS distance ("near me" = same area).
5. Hosting on Modal with SQLite; no custom domain.
6. Muse Image and Muse Wonder are not used in the MVP.
7. POS: one generic CSV only. Billing software maps columns during
   import, so we export clean, named columns labelled "CSV (works with any billing software)".
8. Prices are stored as "₹X for an amount", with several lines allowed per item; ranges are
   flagged for the seller to pick one number.
9. Proof (quotes and audio) is shown to the seller only; customers see the real photo and the
   update time.
10. Judges' test shops are unlisted and expire after 7 days. `/market` shows only shops the
    owner marks as listed.
