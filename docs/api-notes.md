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

## Day-4 eval (synthetic + real video, Meta vs Baseten)

- `eval/clips/real1.answers.json` (owner's key for a real 32 s portrait
  phone video, Tamil speech, 5 items) copied to `eval/answers/real1.json`.
- Benchmark change: a key item with variety null now matches any variety
  (preferring a variety-less hit) — "big onion" vs key variety None counts
  as found again.
- `run_clip.py` now prints the run's own Meta spend (ledger delta), not the
  day total.
- Meta table (`benchmark.py` on the two `run_clip` outputs):

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| real1.mp4 | 5 | 5 | 5 | 0 | 0 |
| synth1.mp4 | 7 | 7 | 6 | 1 | 0 |
| TOTAL | 12 | 12 | 11 | 1 | 0 |

expect_flags raised: QTY_MISSING×11, SOUND_ALIKE×2, TWO_PRICES×1
expect_flags missed: (none)

- Run spend: synth1 **$0.0920**, real1 **$0.0581**.
- real1 per-item detail (all exact by rate): small onion 15 per 0.5 kg
  (key 15 per 500 g); onion 20 per 1 kg; potato 5 per 1 kg; ginger 150 per
  1 kg; garlic 90 per 1 kg. Every card carries non-blocking QTY_MISSING.
  Real-speech wins: `அரை கிலோ` → 0.5 kg and colloquial `அஞ்சு` → 5 both
  parse. One gap: ginger's `நூற்று அம்பது` (150) extracts correctly but
  `find_numbers` cannot parse `நூற்று` (hundred-compounds unsupported), so
  ginger also carries blocking NOT_HEARD ("price 150 not heard in quote")
  and needs a seller tick. Its transcript turn holds two items
  (turn 2: small onion + onion), handled fine.
- Baseten table (`benchmark.py --provider baseten`, extraction re-run
  through `meta-models/muse-spark-open-1026` with `reasoning_effort: low`,
  which the endpoint accepts):

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| real1.mp4 | 5 | 5 | 4 | 0 | 1 |
| synth1.mp4 | 7 | 7 | 6 | 0 | 1 |
| TOTAL | 12 | 12 | 10 | 0 | 2 |

expect_flags raised: (none)
expect_flags missed: QTY_MISSING×11, SOUND_ALIKE×2, TWO_PRICES×1

- Baseten misses: real1 small onion (price 15 with no amount/unit; 0.5
  landed in qty instead) and synth1 potato (first line 30 vs key 35).
  Caveat: the `--provider baseten` path re-runs extraction only, without
  the honesty checks, so no flags are raised and both misses count
  unflagged — a harness artifact, not a model verdict. Otherwise Baseten
  extraction matches Meta item for item (even coconut's `piece` unit).

## Day-5 fixes (spoken numbers, approved status, fair Baseten rerun)

- Numbers: Tamil-script பதினைஞ்சு/இருவது/இருவத்தஞ்சு/நாப்பது/அறுவது/
  எழுவது/எம்பது, romanised iruvathu/naappathu/aruvathu/ezhuvathu/
  embathu, hundreds prefixes நூற்றி/நூத்தி/நூற்று and noothi/nootri
  combining with a following tens word (நூற்று அம்பது = 150), and English
  "one fifty"/"two twenty" directly before a currency word = 150/220
  (bare "one thirty" still parses as 1 and 30). Ginger's real quote now
  yields 150, so NOT_HEARD is gone; small onion's quote stays clean.
- `db.approve` sets the session status to `approved`; the session page
  shows "Approved ✓" with a back-to-shop link instead of the working
  spinner.
- `benchmark.py --provider baseten` now runs the same `check_item`
  honesty checks (against the shop's previous prices) as the Meta run.
  Re-ran both on the current outputs — the tables are identical:

| clip | in key | found | exact | wrong+flagged | wrong+unflagged |
|---|---|---|---|---|---|
| real1.mp4 | 5 | 5 | 5 | 0 | 0 |
| synth1.mp4 | 7 | 7 | 6 | 1 | 0 |
| TOTAL | 12 | 12 | 11 | 1 | 0 |

expect_flags raised: QTY_MISSING×11, SOUND_ALIKE×2, TWO_PRICES×1
expect_flags missed: (none)

- No new Meta spend (benchmark scoring only); the Baseten rerun is 3
  extraction chunks on the saved transcripts, Baseten-side billing.
  Baseten even fixed its own earlier misses this round (small onion
  15 per 0.5 kg); the remaining flagged item on both providers is
  synth1 potato (first line 30 vs key 35, TWO_PRICES + CORRECTION_SAID).
