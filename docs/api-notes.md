# API notes (probe of 27 Oct 2026, clip `eval/clips/synth1.mp4`)

Probe: `scripts/probe_apis.py`. 33.6 s synth clip (Wikimedia photos, macOS
Tamil + Indian-English voices; answer key `eval/answers/synth1.json`).
Fixtures in `tests/fixtures/` come from the successful run below. Photo
credits for the clip sources: `eval/clips/src_wikimedia/ATTRIBUTION.txt`
(fixtures hold no images, only model text).

## Findings

- **Data URLs accepted by both Muse Spark and SAM 3.1.** Image steps sent the
  frame as a `data:image/jpeg;base64` URL; Spark image call and SAM both
  returned 200. "SAM needs a public URL" does NOT apply; Task 10 needs no
  `/m/tmp` serving for this.
- **Tamil transcript is in Latin script.** Transcribe returns romanised Tamil
  (`thakkali`, `padinettu`, `urulaikizhangu`) with English words inline
  (`twenty five rupees per kilo`). No Tamil-script output on this clip.
- **`turns` arrive in ENDPOINTING mode.** Each turn has `turnId`, `startMs`,
  `endMs` plus its own transcript. Timestamps line up with the answer key's
  `speech_ms` windows.
- **Turn segmentation varies run to run.** The same WAV gave 3 turns once and
  6 turns on the rerun, with slightly different wording
  (`muppathaindu` vs `muppathurupai`). Downstream code must not assume a fixed
  turn count; proof search should fall back to quote text (Task 7 already does).
- **SAM box tokens** look like
  `<0f>0<|box;x1=420;y1=636;x2=503;y2=688;w=1280;h=720|><|mask;x=0;y=0;data=...|>`.
  Boxes parse by key; mask payloads are ~100 KB per image, so fixtures keep
  the concatenated text only. SAM usage reports 0 tokens; cost is flat.
- **SAM endpoint is `POST {META}/responses`** (no extra `/v1`). A doubled
  `/v1/v1/responses` path 404s. Streaming SSE carries
  `response.output_text.delta` events until `response.completed`.
- **Spark JSON is fenced and free-form** (```json fence, its own key names).
  Task 7 must demand strict schema and strip fences (Task 4 already does).
- **Spelling variants to feed Task 6 later** (not implemented here):
  `pathinaindu` (no h), `rupai` (rupees), `muppathaindu`. Also genuine
  mishearings the checks must survive: potato `thirupathu` for 30, coconut
  `mukpathu` for `muppathu`.
- **SDK calls need explicit timeouts.** One run hung 20 min on the Spark text
  call with SDK defaults; the probe now passes `timeout=180, max_retries=2`
  (Task 4 should do the same).
- **Transcripts mix three writing styles** (live run
  `tests/fixtures/transcribe_live_mixed.json`): Latin-script Tamil
  (`thakkali`), Tamil script (`இருக்கு`, `ஒரு`, `ஒன்னு`, `முப்பது`), and
  English, including **Tamil numbers as English words** (`eighteen`,
  `twenty five`, `forty`, `thirty five`, `fifteen`, `sixty`). Number parsing
  must accept all three. **One turn can hold several items**: turn 0 of the
  live run packs tomato, onion, small onion and potato, so extraction quotes
  must be per-item slices of shared turn text, each copied exactly.

## Costs (successful run, 27 Oct)

| Call | Status | Latency | Usage | Cost USD |
|---|---|---|---|---|
| transcribe (33.6 s audio) | 200 | 9.9 s | 33.6 s audio | 0.0017 |
| spark-text (extraction) | ok | 19.5 s | 126 in / 2988 out (reasoning-heavy) | 0.0129 |
| spark-image (frame check) | ok | 3.0 s | 1226 in (image) / 336 out | 0.0030 |
| sam-3.1 (1 frame) | 200 | 4.3 s | 0 tokens, flat rate | 0.0025 |
| baseten open-weights (same prompt) | ok | 19.4 s | 263 in / 3098 out | 0.0000 |

Meta total ≈ **$0.0200** per probe run. Baseten is logged at $0 against the
Meta cap. A full recording with ~30 picture checks will cost more; the Day-1
gate (Task 11) must measure with real token counts before fixing batch sizes.

## Day-3 gate (Task 11, 27 Oct): `run_clip.py` on synth1.mp4 + benchmark

Run: status `review`, 7 draft items, Meta spend **$0.1253** (inside the
$0.10–0.20 estimate).

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| synth1.mp4 | 7 | 6 | 5 | 1 | 0 |
| TOTAL | 7 | 6 | 5 | 1 | 0 |

expect_flags raised: QTY_MISSING×6, SOUND_ALIKE×2
expect_flags missed: TWO_PRICES×1

Reading the misses honestly:

- Tomato counts as missed: the extractor returned variety in Tamil script
  (`பெங்களூர்`) while the key says `bengaluru`. Same variety, different
  script — matching stays script-sensitive; no new rule added.
- Potato's correction (`30` then `35`) carries blocking CORRECTION_SAID plus
  UNIT_MISSING on the unit-less `35` line, but not TWO_PRICES (the two lines
  have different amounts). The wrong value is still caught before review, so
  it scores wrong-but-flagged.
- Carrot `15 per 0.25 kg` scores exact against key `15 per 250 g` by rate.
- No price landed on the wrong item, so no "one item per sentence" recording
  tip was added.
