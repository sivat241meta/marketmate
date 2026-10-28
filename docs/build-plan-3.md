# MarketMate build plan, phase 3 (Tasks 35–41)

For Muse Code workers. Read `docs/build-plan.md` Global Constraints and `docs/build-plan-2.md`
first; they still apply (models, honesty rules, Fresh Market look, commit trailer
`Built-with: Muse Code`, never push). Sockets and network are blocked in the worker sandbox:
fake every Meta call and every WebSocket in tests, and render pages in-process with TestClient.

**Goal:** a complete day for a small vegetable shop, from the morning market run to closing.
The owner described today's workflow:
1. The shopkeeper buys at Koyambedu market in the morning and arranges the stall.
2. They write prices on a board, or on small boards hung over each vegetable.
3. They type each bill into Excel, then type it again into a POS.

MarketMate should remove that double work and make billing at the counter as fast as speaking.

## Ground rules added in phase 3

- **Three allowed price sources** (owner approved on 28 Oct). Nothing else may set a price.
  1. The seller's voice. The price must be heard in the recording, as today.
  2. Numbers the seller typed and confirmed.
  3. **The seller's own price board, read from a photo.** Every price read from a board is
     stored with `proof.source = "board_photo"`. It carries a blocking `BOARD_CONFIRM` flag
     ("read from your board – tap to confirm") until the seller taps it. A board-read price is
     never published without that tap.

  A photo of the vegetables themselves never gives a price.
- **Bills and quotes use only the shop's published prices**, as in phase 2. An amount-based
  order ("₹20 worth of coriander") converts money to quantity using the published rate. It never
  invents a rate.
- **Live mode facts, measured on 28 Oct** (`wss://api.meta.ai/v1/asr/realtime`, owner's Tamil
  video streamed at real time):
  - The handshake ack arrives in about 1.3 s.
  - Each turn sends `speechStart` with `turnId` (starting at 0) and `audioProcessedMs`.
  - About one `transcript` partial arrives per second, as a cumulative string without a
    `turnId`.
  - `speechEnd` and `speechComplete` (with `turnId` and the final `transcript`) arrive together,
    within about 0–2 s of the seller stopping.
  - A seller who talks without pausing produces one long turn holding several items, for
    example "இது மாதுளை கிலோ எண்பத்தேழு ரூபா அது சாத்துக்குடி கிலோ முப்பத்தி ஆறு ரூபா …".
    Extraction must handle many items per turn and items split across turns ("இது வாழைத்தண்டு" /
    "கிலோ" / "… முப்பது ரூபா").
  - Audio is PCM 16-bit mono, 24 kHz (48,000 bytes/s), in roughly 80 ms frames sent at real-time
    pace. The server rejects audio more than 5 s ahead. Sessions last at most 60 min.
  - Authentication goes in the first JSON frame: `{"authorization":{"accessToken":"Bearer <key>"}, ...}`.
    **The key must never reach the browser**, so our server relays the audio.
  - Price: $0.18 per audio hour, the same as upload.
- **Exports:** Excel (.xlsx) and a **general POS CSV**. There is exactly one CSV per
  surface: the price-list CSV and the day-close sales CSV.

## Tasks

- **Task 35 – Live price capture.**
  - A WebSocket relay sits on our server: browser mic PCM → our server → Meta realtime, with
    events relayed back to the browser.
  - A "Live prices" screen shows the camera preview, live captions and item cards that appear
    as each turn completes.
  - The browser grabs a camera frame at each `speechStart` and `speechComplete`. No video upload
    is needed.
  - The finished session goes into the normal review / approve flow.
- **Task 36 – Live voice billing and faster counter.**
  - The seller speaks the order and bill lines appear live.
  - A fast local order parser (no AI) handles known item names and numbers; Spark is the
    fallback.
  - Amount-based orders ("₹20 worth").
  - Quick weight buttons and a keypad.
  - Live captions on the customer quote "Speak" tab.
- **Task 37 – Settings and payments.**
  - Settings page: edit shop profile, UPI ID, language, currency.
  - UPI QR for the exact bill amount.
  - Mark paid by cash or UPI.
  - Change calculator and round-off.
  - Public bill link with QR, for customers without a phone number.
- **Task 38 – Match their boards.**
  - Per-item price tags PDF.
  - Board photo → price list, with every price confirmed.
  - Purchase entry by voice or typing (Koyambedu buying cost), giving cost per unit, opening
    stock and margin.
- **Task 39 – Day close and exports.**
  - Day-close page: sales, cash vs UPI, items sold, stock left, wastage, spend and gross margin.
  - Sales export to .xlsx and general POS CSV.
  - WhatsApp summary.
- **Task 40 – Tamil and Hindi seller screens.** Every seller page and message is translated,
  with a language toggle.
- **Task 41 – App polish.**
  - Installable PWA.
  - Offline tap-billing with sync.
  - Order status (packing / ready / collected).
  - Staff billing-only link.
  - Link recovery: "send my link to my WhatsApp", plus a seller-link QR card.
