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

First run: status `review`, 7 draft items, Meta spend **$0.1253** (inside the
$0.10–0.20 estimate).

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| synth1.mp4 | 7 | 6 | 5 | 1 | 0 |
| TOTAL | 7 | 6 | 5 | 1 | 0 |

expect_flags raised: QTY_MISSING×6, SOUND_ALIKE×2
expect_flags missed: TWO_PRICES×1

That run's misses: tomato's variety came back in Tamil script (`பெங்களூர்`
vs key `bengaluru`), and potato's unit-less `35` line could not group with
`30 per 1 kg`, so TWO_PRICES missed (blocking CORRECTION_SAID still caught
it). Both led to Task 7 fixes.

## Day-3 re-gate (Task 7 fix, 28 Oct)

Two process lessons first. The Task 11 gate run deleted the source clip
(`process_video_session` unlinks the video it processes), so `run_clip.py`
now works on a temp copy and never destroys the owner's clip
(regression-tested). The clip was rebuilt from its own session assets —
exact original audio plus original frames as a 2 fps slideshow at 1280x720
— after which one gate attempt died on a transient double length-cutoff
with empty content and the retry went clean.

Re-run: status `review`, 7 draft items, run spend **$0.1411**.

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| synth1.mp4 | 7 | 7 | 5 | 2 | 0 |
| TOTAL | 7 | 7 | 5 | 2 | 0 |

expect_flags raised: QTY_MISSING×6, SOUND_ALIKE×2, TWO_PRICES×1
expect_flags missed: (none)

- Variety fix works: tomato comes back `bangalore` and matches.
- Potato's `35` inherits `1 kg` via UNIT_FROM_EARLIER, so TWO_PRICES fires
  `[30, 35]` alongside blocking CORRECTION_SAID; first line `30` still
  scores wrong-but-flagged, which is correct (the seller corrected it).
- Coconut `(30, no unit)` scores wrong-but-flagged via blocking
  UNIT_MISSING — also correct, the unit is genuinely unknown.
- Carrot `15 per 0.25 kg` scores exact against key `15 per 250 g` by rate.
- This run's transcript came back in Tamil script (same audio as the
  Latin-script runs) — script choice varies run to run, like turn splits.
- No price landed on the wrong item, so no "one item per sentence" recording
  tip was added.

## Day-3 re-gate 2 (reasoning/cutoff fix)

Live failure: a mostly-Tamil-script web upload died in extraction with
"cut off by max_tokens twice" — Spark spent ~4000-7900 reasoning tokens
before hitting the 4000 budget. Fixes: `chat_json` takes
`reasoning_effort` (passed to Meta and Baseten — a live probe showed
Baseten's OpenAI-compatible endpoint accepts `reasoning_effort: low`
with HTTP 200) and every JSON task (extraction, best-frame check) uses
`"low"`; default `max_tokens` is 8000 with one escalation to 16000;
extraction splits transcripts into ≤6-turn groups (one Spark call each);
ledger detail now records budget and finish reason
(`chat_json max=8000 finish=stop`).

Re-run (`run_clip.py` + `benchmark.py`): status `review`, 7 draft items.
This run's transcript came back Tamil-script again (7 turns → 2 chunks).

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| synth1.mp4 | 7 | 6 | 4 | 2 | 0 |
| TOTAL | 7 | 6 | 4 | 2 | 0 |

expect_flags raised: QTY_MISSING×5, SOUND_ALIKE×2, TWO_PRICES×1
expect_flags missed: QTY_MISSING×1

- Run spend **$0.0896**: transcribe $0.0017, extraction 2× $0.0200,
  best-frame 7× $0.0504, SAM 7× $0.0175. (`run_clip` prints the whole
  day's ledger total, $0.4105, not the run delta.)
- Reasoning with `"low"`, re-measured per chunk: 1650 + 1990 = 3640
  tokens total, both calls `finish=stop` at max=8000 — no cutoffs.
- The 1 miss is run-to-run model variation, not the fix: onion came back
  with variety `big` ("big onion") while the key says variety None, so it
  no longer matches and its expected QTY_MISSING counts as missed.
  Everything else scores exactly as the previous re-gate.
