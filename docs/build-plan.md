# MarketMate Implementation Plan

> **For agentic workers (Muse Code):** implement **one task per run**, in order. Before starting,
> read `docs/design.md`, the *Global Constraints* and *Review Focus* below, and your task. Follow
> the steps in order (test first). Before committing, run the whole suite (`pytest -q`) and
> `ruff check .`. Commit with the message given. Then **stop and report**: files changed, test
> results, and anything you had to guess. Use only the names in each task's *Interfaces* block
> for code from other tasks. Never print, log or commit secrets.

**Goal:** A mobile-first web app where a produce seller films their stall and speaks prices.
It produces a proof-checked price list the seller approves, then a PDF price board, a public
shop page, CSV export and customer search/compare/budget.

**Architecture:**
- One Python FastAPI app with server-rendered pages and a little JS.
- A processing pipeline: ffmpeg → Voice Transcribe → Muse Spark → code checks → Muse Spark
  picture check → SAM 3.1 crop. It runs in a background thread and stores everything in SQLite
  plus files under `DATA_DIR`.
- Deployed as a single Modal container with a Volume.

**Tech Stack:**
- Python ≥ 3.12, FastAPI, Jinja2, python-multipart, httpx, openai (SDK), python-dotenv.
- Pillow, qrcode, WeasyPrint (+ pango).
- pytest, respx, pypdf, ruff, Modal.
- ffmpeg/ffprobe binaries.

**Spec:** `docs/design.md` (approved 27 Oct 2026). The flow picture is
`docs/marketmate-flow.html`.

**Day map (IST):**

| Day | Date | Tasks |
|---|---|---|
| Day 1 | Wed 28 Oct | 1–5 |
| Day 2 | Thu 29 | 6–8 |
| Day 3 | Fri 30 | 9–11 (gate numbers) |
| Day 4 | Sat 31 | 12–13 |
| Day 5 | Sun 1 Nov | 14–16 |
| Day 6 | Mon 2 | 17–19 |
| Day 7 | Tue 3 | 18 seeding with real stalls, 20 |
| Day 8 | Wed 4 | 20 finish, submit by 9 PM IST |

Task 21 is stretch.

## Global Constraints

**Models**
- Base URLs:
  - Meta: `https://api.meta.ai/v1`, key `MODEL_API_KEY`.
  - Baseten: `https://inference.baseten.co/v1`, key `BASETEN_API_KEY`.
- Model IDs:
  - `muse-spark-1.3` (text + images);
  - `muse-voice-transcribe-1.0`;
  - `sam-3.1`;
  - Baseten `meta-models/muse-spark-open-1026` (text-only steps).
- `TEXT_PROVIDER` = `meta` (default) or `baseten`. Any call that includes an image always uses
  Meta.
- Never use `-contributor` model variants. Never use Muse Image.
- Voice Transcribe call:
  - `POST /v1/asr/transcribe`, multipart parts `request` (JSON) + `audio` (WAV);
  - `request = {"model":"muse-voice-transcribe-1.0","audioEncoding":"WAV","mode":"ENDPOINTING","languageBias":["Tamil","English"],"keywords":[...]}`.
  - `mode` must not be `PUSH_TO_TALK`: its `turns` come back empty.
- Audio sent to Voice Transcribe: mono, 16-bit PCM, 16 kHz WAV, ≤ 10 min.
- Muse Spark spends hidden reasoning tokens. Always pass `max_tokens` ≥ 4000 for JSON tasks.

**Numbers and data rules**
- **Prices and quantities come only from the seller's speech.** Unknown means `None`, never a
  guess.
- **Nothing is visible to customers until the seller approves a version.**
- Each price is "price for `per_amount` `unit`". Units: `kg, g, piece, dozen, bunch, packet`.
- Fixed values:

  | Setting | Value |
  |---|---|
  | `DAILY_BUDGET_USD` default | 3.0 |
  | Max video | 180 s |
  | Stale after | 24 h |
  | Jump flag | ±50% |
  | Judge shops expire | 7 days |
  | Media kept | 30 days (demo shops: forever) |
  | Raw video | deleted after processing |
  | Frames | 2 per second |

- Costs:
  - Muse Spark: $1.25 per 1M input tokens, $4.25 per 1M output tokens;
  - Voice Transcribe: $0.18 per audio hour;
  - SAM: $0.0025 per image call;
  - Baseten tokens are logged with $0 against the Meta cap.

**Product copy**
- Upload page notice: **"Your voice recording is sent to Meta's AI service to be transcribed."**
- Demo shops show the label **"Demo data"**.
- Never claim "works with POS app" unless an import was tested. Only measured numbers appear
  in the README.

**Repo**
- Never commit `.env` (commit `.env.example` only).
- Git identity: `sivat241meta` / `348483894+sivat241meta@users.noreply.github.com`.
- Remote: `github.com/sivat241meta/marketmate`, **private until Task 20**, then public.
  Muse Code commits but does **not** push: git network access is blocked in its sandbox. The
  reviewer pushes after approving each task. Never force-push.
- Every commit message written by Muse Code ends with the trailer line
  `Built-with: Muse Code`, so the history shows the build tool.

**UI**
- Pages are mobile-first. Seller pages need the private edit token in the path; customer pages
  never show proof quotes or audio.

## Review Focus

1. **Seller corrects themselves** ("thakkali 18… illa illa, 20"): both prices are kept and a
   `TWO_PRICES` flag offers 18 / 20. The app never silently keeps one. *(Task 8 test)*
2. **Two items in one breath** (one turn, two items): each item gets its own best frame, chosen
   by its name. *(Task 10 test)*
3. **Numbers in any script:** digits, Tamil script (பதினெட்டு), romanised Tamil (pathinettu),
   English words (eighteen). All parse the same. *(Task 6 test)*
4. **Phone video formats:** portrait iPhone `.mov` with rotation metadata, and Android/Chrome
   `.webm`. Frames come out upright and audio extracts. *(Task 3 test)*
5. **API failure or cost cap mid-session:** the session ends `failed` with a readable message,
   nothing is published, and "Try again" reuses the saved transcript. *(Task 11 test)*

---

### Task 1: Project skeleton, settings, core types

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md` (one paragraph),
  `app/__init__.py`, `app/config.py`, `app/models.py`, `tests/test_config.py`

**Interfaces:**
- Produces in `app/config.py`:
  - `META_BASE_URL`, `BASETEN_BASE_URL`, `SPARK_MODEL="muse-spark-1.3"`,
    `SPARK_OPEN_MODEL="meta-models/muse-spark-open-1026"`,
    `VOICE_MODEL="muse-voice-transcribe-1.0"`, `SAM_MODEL="sam-3.1"`.
  - `@dataclass(frozen=True) Settings(model_api_key: str, baseten_api_key: str | None, text_provider: str, data_dir: Path, daily_budget_usd: float, max_video_seconds: int, public_base_url: str, uploads_per_ip_hour: int, uploads_per_hour: int)`
  - `load_settings(env: Mapping[str, str] | None = None) -> Settings`. Reads `.env` via
    python-dotenv when `env` is None.
  - Defaults:

    | Field | Default |
    |---|---|
    | `text_provider` | `"meta"` |
    | `data_dir` | `./data` |
    | `daily_budget_usd` | `3.0` |
    | `max_video_seconds` | `180` |
    | `public_base_url` | `http://127.0.0.1:8000` |
    | `uploads_per_ip_hour` | `5` |
    | `uploads_per_hour` | `30` |

- Produces in `app/models.py` (dataclasses; money and amounts as `Decimal`):
  - `Turn(id: int, start_ms: int, end_ms: int, text: str)`
  - `Transcript(text: str, duration_ms: int, turns: list[Turn])`
  - `Frame(path: Path, t_ms: int)`
  - `PriceLine(price: Decimal | None, per_amount: Decimal | None, unit: str | None, said: str = "")`
  - `Proof(quote: str, turn_ids: list[int], start_ms: int, end_ms: int, frame: str | None = None, audio_clip: str | None = None)`
  - `Flag(field: str, code: str, message: str, options: list[str] = [], blocking: bool = True)`
  - `DraftItem(name_spoken: str, name_ta: str, name_en: str, variety: str | None, price_lines: list[PriceLine], qty: Decimal | None, qty_unit: str | None, proof: Proof, range_said: bool = False, flags: list[Flag] = [], photo: str | None = None, condition_hint: str | None = None, confirmed: bool = False)`
  - `Item(id: int, version_id: int, name_ta: str, name_en: str, variety: str | None, qty: Decimal | None, qty_unit: str | None, photo: str | None, sold_out: bool, price_lines: list[PriceLine], proof: Proof)`
  - `Box(x1: int, y1: int, x2: int, y2: int, w: int, h: int, confidence: float | None)`
  - `UNITS = ("kg", "g", "piece", "dozen", "bunch", "packet")`
  - Use `field(default_factory=list)` for list defaults.

- [ ] **Step 1: Initialise the repo.**

  ```bash
  cd /Users/siva-6452/muse && git init
  git config user.name sivat241meta
  git config user.email 348483894+sivat241meta@users.noreply.github.com
  ```

  `.gitignore` must include `.env`, `data/`, `eval/clips/`, `eval/out/`, `.venv/` and
  `__pycache__/`. `.env.example` lists `MODEL_API_KEY=`, `BASETEN_API_KEY=`,
  `TEXT_PROVIDER=meta`, `DAILY_BUDGET_USD=3` and `PUBLIC_BASE_URL=`.

- [ ] **Step 2: Write the failing test** in `tests/test_config.py`:

  ```python
  def test_defaults():
      s = load_settings({"MODEL_API_KEY": "k"})
      assert s.text_provider == "meta" and s.daily_budget_usd == 3.0 and s.max_video_seconds == 180
  def test_baseten_switch():
      s = load_settings({"MODEL_API_KEY": "k", "BASETEN_API_KEY": "b", "TEXT_PROVIDER": "baseten"})
      assert s.text_provider == "baseten"
  def test_baseten_without_key_rejected():
      with pytest.raises(ValueError):
          load_settings({"MODEL_API_KEY": "k", "TEXT_PROVIDER": "baseten"})
  def test_missing_meta_key_rejected():
      with pytest.raises(ValueError):
          load_settings({})
  ```

- [ ] **Step 3:** Create a venv (`python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`),
  run `pytest tests/test_config.py -q` and expect FAIL. Then implement `config.py` and
  `models.py`.
- [ ] **Step 4:** `pytest -q && ruff check .` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 1: project skeleton, settings, core types"`

### Task 2: API probe and fixtures (Day-1 gate, part 1)

Needs the owner's test clips: `eval/clips/clip1.mp4` and `clip2.mp4` (not committed), plus
answer keys `eval/answers/clip1.json` and `clip2.json` (committed).

Answer key format:

```json
{"clip":"clip1.mp4","items":[{"name_en":"tomato","variety":"bengaluru","price":18,"per_amount":1,"unit":"kg","qty":40,"qty_unit":"kg"}]}
```

**Files:**
- Create: `scripts/probe_apis.py`, `tests/fixtures/` (saved raw responses)

**Interfaces:**
- Produces fixtures that Tasks 4–5 parse:
  - `tests/fixtures/transcribe_clip1.json`
  - `tests/fixtures/spark_text.json`
  - `tests/fixtures/spark_image.json`
  - `tests/fixtures/sam_frame.txt` (the concatenated `output_text`)
  - `tests/fixtures/baseten_text.json`

- [ ] **Step 1:** Write `scripts/probe_apis.py <clip>`. It uses plain httpx and openai calls,
  not app code. It:
  1. converts the clip to WAV with ffmpeg (`-ac 1 -ar 16000 -sample_fmt s16`);
  2. calls Voice Transcribe as in Global Constraints, with keywords `["thakkali","vengayam","tomato","onion"]`;
  3. calls Muse Spark with the transcript: "list items and prices as JSON";
  4. grabs one frame at 5 s, then calls Muse Spark with that frame as a `data:image/jpeg;base64`
     URL, and calls SAM 3.1 (Responses API, streaming, `input_text` = `"tomato"`,
     `input_image.image_url` = the same data URL);
  5. sends the same Muse Spark text prompt to Baseten.

  It saves each raw response to the fixture files and prints, per call: HTTP status, latency,
  token usage and estimated cost. Keys are never printed.
- [ ] **Step 2:** Run `.venv/bin/python scripts/probe_apis.py eval/clips/clip1.mp4`.

  Expected: all five calls succeed. **Write the findings into a new `docs/api-notes.md`:**
  - Are data URLs accepted by Muse Spark and by SAM?
  - Which script is the Tamil transcript in?
  - Does `turns` arrive in ENDPOINTING mode?
  - What do the SAM box tokens look like?
  - What did each call cost?

  If SAM rejects data URLs, note "SAM needs a public URL". Task 10 then serves frames from
  `PUBLIC_BASE_URL/m/tmp/<random>.jpg`.
- [ ] **Step 3:** `git add scripts tests/fixtures docs/api-notes.md eval/answers && git commit -m "task 2: API probe, fixtures, API notes"`

### Task 3: Media helpers (ffmpeg)

**Files:**
- Create: `app/pipeline/__init__.py`, `app/pipeline/media.py`, `tests/test_media.py`

**Interfaces:**
- Produces in `app/pipeline/media.py`:
  - `class VideoTooLong(Exception)`
  - `probe_duration_s(video: Path) -> float`
  - `extract_audio(video: Path, out_wav: Path) -> Path`: mono, 16 kHz, s16 WAV.
  - `extract_frames(video: Path, out_dir: Path, fps: float = 2.0) -> list[Frame]`: JPEGs named
    `f_<t_ms>.jpg`, sorted by `t_ms`.
  - `cut_audio_clip(wav: Path, start_ms: int, end_ms: int, out: Path, pad_ms: int = 300) -> Path`: AAC `.m4a`.
  - `check_length(video: Path, max_s: int) -> None`: raises `VideoTooLong`.

- [ ] **Step 1: Write failing tests.** Test videos are generated with ffmpeg in a pytest
  fixture (`testsrc` + `sine`); there are no binary files in the repo.

  ```python
  def test_audio_is_16k_mono(tmp_path, video_mp4):
      wav = extract_audio(video_mp4, tmp_path/"a.wav")
      assert wave.open(str(wav)).getframerate() == 16000 and wave.open(str(wav)).getnchannels() == 1
  def test_two_frames_per_second(tmp_path, video_mp4):  # 3 s video
      frames = extract_frames(video_mp4, tmp_path)
      assert len(frames) == 6 and frames[1].t_ms == 500
  def test_portrait_rotation_upright(tmp_path, rotated_mp4):  # 320x240 source, display rotation 90
      f = extract_frames(rotated_mp4, tmp_path)[0]
      assert Image.open(f.path).size == (240, 320)
  def test_webm_input(tmp_path, video_webm):
      assert extract_audio(video_webm, tmp_path/"a.wav").exists()
  def test_too_long(video_mp4):
      with pytest.raises(VideoTooLong):
          check_length(video_mp4, 2)
  ```

  Make the rotated fixture with
  `ffmpeg -display_rotation 90 -i plain.mp4 -c copy rotated.mp4`.
- [ ] **Step 2:** Run `pytest tests/test_media.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement with `subprocess.run([...], check=True)`. Keep ffmpeg's default
  autorotate, and use `-vf fps=2`.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 3: media helpers"`

### Task 4: Cost ledger and Muse Spark / Baseten JSON client

**Files:**
- Create: `app/costs.py`, `app/meta/__init__.py`, `app/meta/spark.py`, `tests/test_costs.py`,
  `tests/test_spark.py`

**Interfaces:**
- Produces in `app/costs.py`:
  - `class CostCapExceeded(Exception)`
  - `class CostLedger(db_path: Path, daily_cap_usd: float)`, with methods:
    - `.check() -> None`: raises when today's Meta total ≥ the cap;
    - `.add(provider: str, model: str, usd: float, detail: str = "") -> None`;
    - `.today_usd(provider: str = "meta") -> float`.
  - `spark_cost(usage: dict) -> float`, using the prices in Global Constraints.
    `completion_tokens` already includes reasoning tokens.
  - The ledger keeps its own SQLite file at `DATA_DIR/costs.db`. "Today" means the IST date.
- Produces in `app/meta/spark.py`:
  - `class SparkError(Exception)`
  - `image_part(path: Path) -> dict`: OpenAI `image_url` content part with a data URL.
  - `chat_json(messages: list[dict], *, ledger: CostLedger, settings: Settings, provider: str | None = None, max_tokens: int = 4000) -> dict`

- [ ] **Step 1: Write failing tests.**

  ```python
  def test_cap_blocks(tmp_path):
      l = CostLedger(tmp_path/"c.db", 0.01); l.add("meta","muse-spark-1.3",0.02); 
      with pytest.raises(CostCapExceeded): l.check()
  def test_spark_cost():
      assert spark_cost({"prompt_tokens":1_000_000,"completion_tokens":1_000_000}) == pytest.approx(5.50)
  def test_chat_json_parses_fenced_json(respx_mock, ledger, settings): ...  # content "```json\n{\"a\":1}\n```" -> {"a":1}; ledger.today_usd()>0
  def test_chat_json_retries_once_then_raises(respx_mock, ledger, settings): ...  # two non-JSON replies -> SparkError, exactly 2 calls
  def test_images_force_meta(respx_mock, ledger, settings_baseten): ...  # message with image_part -> request goes to api.meta.ai
  def test_baseten_text_logged_zero_usd(respx_mock, ledger, settings_baseten): ...  # baseten call -> ledger.today_usd("meta")==0
  def test_cap_checked_before_call(respx_mock, settings): ...  # exhausted ledger -> CostCapExceeded, 0 HTTP calls
  ```

  Use `tests/fixtures/spark_text.json` as the realistic response body.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement using the `openai` SDK with `base_url` and key chosen by provider.
  - The model is `SPARK_MODEL` or `SPARK_OPEN_MODEL`.
  - Strip code fences and parse the first JSON object.
  - On a parse failure, append the assistant reply plus "Return only valid JSON." and retry once.
  - Retry HTTP 429/5xx with backoff, 3 attempts.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 4: cost ledger and Spark/Baseten JSON client"`

### Task 5: Voice Transcribe and SAM 3.1 adapters

**Files:**
- Create: `app/meta/transcribe.py`, `app/meta/sam.py`, `tests/test_transcribe.py`,
  `tests/test_sam.py`

**Interfaces:**
- Consumes: `CostLedger`, `Settings`, `Transcript`, `Turn`, `Box`.
- Produces:
  - `transcript_from_json(data: dict) -> Transcript`: pure. If `turns` is empty but there is
    text, it returns one turn covering the whole audio.
  - `transcribe_wav(wav: Path, *, keywords: list[str], ledger: CostLedger, settings: Settings, languages: tuple[str, ...] = ("Tamil", "English")) -> Transcript`
  - `parse_sam_text(text: str) -> list[Box]`: pure parse of `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>`
    tokens, by key, ignoring mask tokens and frame markers.
  - `find_boxes(image: Path, noun: str, *, ledger: CostLedger, settings: Settings) -> list[Box]`

- [ ] **Step 1: Write failing tests.**

  ```python
  def test_parse_fixture_turns():   # tests/fixtures/transcribe_clip1.json
      t = transcript_from_json(json.load(...))
      assert t.turns and all(x.end_ms >= x.start_ms for x in t.turns)
  def test_empty_turns_become_one_turn():
      t = transcript_from_json({"transcript":"thakkali 18","audioDurationMs":4000,"turns":[]})
      assert t.turns == [Turn(1, 0, 4000, "thakkali 18")]
  def test_request_part_uses_endpointing(respx_mock, ...):  # inspect multipart: mode=ENDPOINTING, languageBias, keywords
  def test_voice_cost_logged(respx_mock, ...):  # audioDurationMs=3_600_000 -> ledger +0.18
  def test_parse_sam_boxes():
      s = "<0f>1,<|box;x1=10;y1=20;x2=110;y2=220;w=640;h=480|><|mask;x=0;y=0;data=2,2,~abc|>,2,<|box;x1=0;y1=0;x2=5;y2=5;w=640;h=480|><|mask;x=0;y=0;data=1,1,~a|>"
      assert parse_sam_text(s)[0] == Box(10,20,110,220,640,480,None) and len(parse_sam_text(s)) == 2
  def test_sam_zero_matches():
      assert parse_sam_text("") == []
  ```

  `transcript_from_json(data: dict) -> Transcript` is a pure helper in `transcribe.py`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - `transcribe_wav` uses httpx multipart; the `request` part has content type
    `application/json`.
  - `find_boxes` posts to `/v1/responses` with `stream: true`. It reads SSE lines, joins every
    `response.output_text.delta`'s `delta` until `response.completed`, then calls
    `parse_sam_text`.
  - Image input follows `docs/api-notes.md` (a data URL, or a temporary public URL from
    Task 10).
  - Cost is `SAM_USD_PER_IMAGE` per call.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 5: Voice Transcribe and SAM adapters"`

### Task 6: Numbers and units

**Files:**
- Create: `app/pipeline/numbers.py`, `app/pipeline/units.py`, `tests/test_numbers.py`,
  `tests/test_units.py`

**Interfaces:**
- Produces:
  - `parse_number(token: str) -> Decimal | None`
  - `find_numbers(text: str) -> list[tuple[Decimal, str]]`: each entry is `(value, kind)`, with
    `kind` in `{"digits","english","tamil"}`, in spoken order. Multi-word numbers count as one.
  - `normalise_unit(said: str) -> str | None`
  - `parse_amount(said: str) -> tuple[Decimal, str] | None`
  - `rate(line: PriceLine) -> tuple[Decimal, str] | None`: price per kg (weights) or per piece
    (piece/dozen). For bunch/packet it is per that unit. `None` if the price or amount is
    missing.
  - `convert(amount: Decimal, unit: str, to: str) -> Decimal | None`: kg↔g and piece↔dozen only.

- [ ] **Step 1: Write failing tests.** These are the coverage contract:

  ```python
  @pytest.mark.parametrize("said,val", [("18",18),("18.50",Decimal("18.50")),("eighteen",18),("eighty",80),
      ("twenty five",25),("one hundred twenty",120),("pathinettu",18),("padhinettu",18),("பதினெட்டு",18),
      ("enbathu",80),("எண்பது",80),("irupathu anju",25),("irupathanju",25),("nooru",100),("நூறு",100),("muppathu",30)])
  def test_parse_number(said, val): assert parse_number(said) == val
  def test_find_numbers_kinds():
      assert find_numbers("thakkali kilo pathinettu, vengayam 25") == [(18,"tamil"),(25,"digits")]
  def test_find_numbers_english_kind():
      assert find_numbers("small onion forty rupees")[0] == (40, "english")
  @pytest.mark.parametrize("said,amt", [("kaal kilo",(250,"g")),("arai kilo",(500,"g")),("1 kilo",(1,"kg")),
      ("கிலோ",(1,"kg")),("dozen",(1,"dozen")),("4 pieces",(4,"piece")),("oru kattu",(1,"bunch"))])
  def test_parse_amount(said, amt): assert parse_amount(said) == (Decimal(amt[0]), amt[1])
  def test_rate_quarter_kilo():
      assert rate(PriceLine(Decimal(15), Decimal(250), "g")) == (Decimal(60), "kg")
  def test_rate_dozen_per_piece():
      assert rate(PriceLine(Decimal(60), Decimal(1), "dozen")) == (Decimal(5), "piece")
  def test_rate_missing_price(): assert rate(PriceLine(None, Decimal(1), "kg")) is None
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement with lexicon tables:
  - Tamil 1–19, the tens (pathu … thonnooru), hundreds (nooru, irunooru …), in both Tamil
    script and common romanised spellings;
  - English 0–19, the tens and "hundred";
  - compounds of tens + units, written as separate words or joined (irupathanju).
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 6: number words and units"`

### Task 7: Extraction with Muse Spark

**Files:**
- Create: `app/pipeline/extract.py`, `app/pipeline/names.py`, `tests/test_extract.py`

**Interfaces:**
- Consumes: `chat_json`, `Transcript`, `DraftItem`, `PriceLine`, `Proof`.
- Produces:
  - `CANONICAL_NAMES: dict[str, str]` in `names.py`, mapping English canonical name → Tamil
    script. Around 60 common produce items, e.g. `"tomato":"தக்காளி"`, `"small onion":"சின்ன வெங்காயம்"`.
  - `PRODUCE_KEYWORDS: list[str]`: romanised + Tamil script + English names, used for
    Voice Transcribe keywords.
  - `build_extract_messages(transcript: Transcript) -> list[dict]`
  - `parse_extract_json(data: dict, transcript: Transcript) -> list[DraftItem]`
  - `extract_items(transcript: Transcript, *, ledger, settings) -> list[DraftItem]`

  The JSON contract the prompt demands:

  ```json
  {"items":[{"name_spoken":"bengaluru thakkali","name_en":"tomato","variety":"bengaluru",
    "prices":[{"said":"kilo pathinettu","price":18,"per_amount":1,"unit":"kg"}],
    "range_said":false,"qty_said":"40 kilo","qty":40,"qty_unit":"kg",
    "turn_ids":[3],"quote":"bengaluru thakkali kilo pathinettu"}]}
  ```

  The prompt rules, which are part of the spec:
  1. Use only what was said; null when it wasn't said.
  2. `quote` must be copied exactly from one or more turn texts.
  3. If the seller says several prices for one item (corrections or tiers), list all in
     spoken order.
  4. A spoken range sets `range_said: true` and price null.
  5. `name_en` must be a key of `CANONICAL_NAMES`, or `"other"`.
  6. Never estimate quantities.

- [ ] **Step 1: Write failing tests.** They use a fake `chat_json` (monkeypatch) returning
  canned JSON.

  ```python
  def test_parse_builds_proof_times(transcript_3_turns):
      items = parse_extract_json(CANNED, transcript_3_turns)
      assert items[0].proof.start_ms == transcript_3_turns.turns[2].start_ms
  def test_name_ta_from_canonical():
      assert parse_extract_json(CANNED, t)[0].name_ta == "தக்காளி"
  def test_null_price_stays_none():
      assert parse_extract_json(CANNED_NO_PRICE, t)[0].price_lines[0].price is None
  def test_turn_ids_must_exist():  # unknown turn id -> item kept, proof times from quote search, no crash
  def test_prompt_lists_turns_with_ids():
      assert "[3]" in build_extract_messages(t)[-1]["content"]
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Turns are shown to the model as `[id] text`. `name_ta` comes from
  `CANONICAL_NAMES`; for `"other"`, `name_ta = name_spoken`.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 7: Spark extraction with quotes"`

### Task 8: Honesty checks

**Files:**
- Create: `app/pipeline/checks.py`, `tests/test_checks.py`

**Interfaces:**
- Consumes: `find_numbers`, `rate`, `DraftItem`, `Flag`.
- Produces:
  - `SOUND_ALIKE_PAIRS = {13:30,14:40,15:50,16:60,17:70,18:80,19:90}`, applied in both
    directions.
  - `WEIGHT_ITEMS: set[str]`: canonical names normally sold by weight.
  - `check_item(item: DraftItem, previous: dict[str, PriceLine]) -> list[Flag]`

  | Flag code | When | Blocking |
  |---|---|---|
  | `NOT_HEARD` | A price/qty value is not among `find_numbers(quote)` | yes |
  | `SOUND_ALIKE` | The value was said in English (kind `"english"`) and is in the pairs; options `["18","80"]` | yes |
  | `UNIT_MISSING` | A price is present but its unit is None | yes |
  | `UNIT_ODD` | `name_en in WEIGHT_ITEMS` and the unit is `piece` | yes |
  | `JUMP` | `abs(rate-prev)/prev > 0.5`; message shows the previous price | yes |
  | `RANGE` | `range_said` | yes |
  | `TWO_PRICES` | ≥ 2 lines with the same amount+unit; options = the prices | yes |
  | `NO_PRICE` | No price at all | yes |
  | `QTY_MISSING` | No quantity | **no** |

- [ ] **Step 1: Write failing tests**, one per row, plus:

  ```python
  def test_self_correction_two_prices():   # Review Focus 1
      it = draft(quote="thakkali 18 illa illa 20", lines=[pl(18,1,"kg"), pl(20,1,"kg")])
      f = [x for x in check_item(it, {}) if x.code == "TWO_PRICES"][0]
      assert f.options == ["18", "20"]
  def test_digits_not_sound_alike():
      assert not [x for x in check_item(draft(quote="thakkali 18", lines=[pl(18,1,"kg")]), {}) if x.code=="SOUND_ALIKE"]
  def test_jump_uses_rate_not_raw_price():  # prev ₹40/kg: ₹16 per 250 g (=₹64/kg, +60%) -> JUMP; ₹15 per 250 g (=₹60/kg, exactly +50%) -> no JUMP
  def test_clean_item_only_qty_missing():
      assert [f.code for f in check_item(draft(quote="tomato kilo 18", lines=[pl(18,1,"kg")]), {})] == ["QTY_MISSING"]
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 8: honesty checks"`

### Task 9: Database

**Files:**
- Create: `app/db.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: the models.
- Produces:
  - `connect(data_dir: Path) -> sqlite3.Connection`: creates the schema; `Row` factory; foreign
    keys on.
  - `create_shop(conn, *, name: str, phone: str, area: str, language: str, currency: str, shop_type: str, is_demo: bool = False, is_judge: bool = False, listed: bool = False) -> tuple[int, str, str]`.
    Returns `(shop_id, slug, edit_token)`. The token is `secrets.token_urlsafe(24)`; only its
    sha256 is stored. Judge shops get `expires_at` = now + 7 days.
  - `shop_by_token(conn, token: str) -> sqlite3.Row | None`
  - `shop_by_slug(conn, slug: str) -> sqlite3.Row | None`
  - `create_session(conn, shop_id: int, kind: str) -> int`: kind is `video` or `voice_update`.
  - `set_session_status(conn, session_id: int, status: str, message: str = "") -> None`.
    Status is one of `uploaded|processing|review|approved|failed`.
  - `save_drafts(conn, session_id: int, items: list[DraftItem]) -> None`
  - `load_drafts(conn, session_id: int) -> list[DraftItem]`
  - `class ApprovalError(Exception)`
  - `approve(conn, session_id: int, items: list[DraftItem]) -> int`: creates the version, items
    and price_lines, and returns `version_id`. Raises `ApprovalError` if any item has a blocking
    flag and `confirmed` is False, or has no price line with a price.
  - `latest_version(conn, shop_id: int, published_only: bool = False) -> int | None`
  - `version_items(conn, version_id: int) -> list[Item]`
  - `set_published(conn, version_id: int, published: bool) -> None`. Publishing one version
    unpublishes the shop's others.
  - `set_sold_out(conn, item_id: int, sold_out: bool) -> None`
  - `last_prices(conn, shop_id: int) -> dict[str, PriceLine]`: `name_en` → first line of the
    latest approved version.
  - `version_time(conn, version_id: int) -> datetime`

- [ ] **Step 1: Write failing tests:**
  - create/lookup by token and slug (wrong token → None);
  - drafts round-trip with Decimals intact;
  - `approve` rejects an unconfirmed blocking flag;
  - `approve` accepts it once `confirmed=True`;
  - publish switches versions;
  - `last_prices` returns the latest approved version's lines.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Store `flags` and `proof` as JSON text and Decimals as strings.
  Tables follow design §4.4, plus shops `listed`, `is_judge`, `expires_at`, `created_at` and
  items `sold_out`.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 9: SQLite storage and approval rules"`

### Task 10: Best frame and real product photo

**Files:**
- Create: `app/pipeline/frames.py`, `app/pipeline/photos.py`, `tests/test_frames.py`,
  `tests/test_photos.py`

**Interfaces:**
- Consumes: `chat_json`, `image_part`, `find_boxes`, `Frame`, `DraftItem`, `Box`.
- Produces:
  - `frames_for_window(frames: list[Frame], start_ms: int, end_ms: int, k: int = 4) -> list[Frame]`.
    The window is `[start_ms-500, end_ms+1500]`; pick k evenly spaced frames.
  - `pick_best_frame(item: DraftItem, candidates: list[Frame], *, ledger, settings) -> tuple[Frame, bool]`.
    One Muse Spark call with all candidates. It asks: which image best shows `<name_en>`, and
    does it match? Reply `{"best_index": int, "matches": bool}`.
  - `crop_to_boxes(image: Path, boxes: list[Box], out: Path) -> Path`: pure Pillow. It takes
    the union of the 6 largest boxes, pads 8%, clamps to the image, and saves a JPEG with max
    side 800 px. With no boxes it centre-crops 80%.
  - `make_photo(frame: Frame, noun: str, out: Path, *, ledger, settings) -> Path`

- [ ] **Step 1: Write failing tests.**

  ```python
  def test_window_bounds(): ...  # frames every 500 ms 0..10s, turn 3000-4000 -> all chosen within 2500..5500
  def test_two_items_same_turn_get_own_frames(fake_spark):   # Review Focus 2
      # fake returns best_index by name: tomato->0, onion->2
      a = pick_best_frame(item("tomato"), cands, ...); b = pick_best_frame(item("onion"), cands, ...)
      assert a[0] != b[0]
  def test_mismatch_returns_false(fake_spark_no_match): assert pick_best_frame(...)[1] is False
  def test_crop_union_padded(tmp_path): ...  # boxes (100,100,200,200),(300,100,400,200) on 640x480 -> crop covers 92..408 x 92..208 (8% pad of union)
  def test_crop_no_boxes_centre(tmp_path): ...  # 640x480 -> 512x384
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. If `docs/api-notes.md` says SAM needs public URLs, `make_photo`
  copies the frame to `DATA_DIR/public_tmp/<token>.jpg`, passes
  `PUBLIC_BASE_URL/m/tmp/<token>.jpg`, and deletes the file afterwards.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 10: best frame and SAM product photo"`

### Task 11: Pipeline run, jobs, clip runner and benchmark (Day-3 gate)

**Files:**
- Create: `app/jobs.py`, `app/pipeline/run.py`, `scripts/run_clip.py`, `scripts/benchmark.py`,
  `tests/test_run.py`, `tests/test_benchmark.py`

**Interfaces:**
- Consumes: everything from Tasks 3–10.
- Produces:
  - `submit(fn: Callable, *args) -> None` in `jobs.py`: ThreadPoolExecutor with 2 workers.
  - `process_video_session(conn, session_id: int, video: Path, *, settings, ledger) -> None`.
    Steps:
    1. check length;
    2. extract audio and frames;
    3. transcribe, cached at `DATA_DIR/sessions/<id>/transcript.json`;
    4. extract items;
    5. checks (with `last_prices`);
    6. for each item: best frame, `PICTURE_MISMATCH` flag (blocking) if no match, photo, audio
       clip;
    7. save drafts;
    8. status `review`;
    9. delete the raw video.

    Progress messages go into the session status message. Any exception (including
    `CostCapExceeded` and `VideoTooLong`) sets status `failed`, with a human message and no
    drafts saved.
  - `reprocess(conn, session_id: int, *, settings, ledger) -> None`: reuses the cached
    transcript; only for failed sessions.
  - `scripts/run_clip.py <clip>` runs the same steps without the web app and writes
    `eval/out/<clip>.json`.
  - `scripts/benchmark.py` compares `eval/out/*.json` with `eval/answers/*.json` (match by
    `name_en` + variety) and prints a markdown table: items in key, found, price exactly right
    before review, wrong but flagged, wrong and not flagged. With `--provider baseten` it reruns
    extraction only.

- [ ] **Step 1: Write failing tests.** Fakes are used for all model calls; the video is
  generated.

  ```python
  def test_happy_path_reaches_review(db, fakes, video): process_video_session(...); assert status(db)=="review" and load_drafts(db, sid)
  def test_raw_video_deleted(...): assert not video.exists()
  def test_cap_mid_session_fails_cleanly(...):   # Review Focus 5: fake SAM raises CostCapExceeded
      assert status(db)=="failed" and "budget" in message(db) and load_drafts(db, sid)==[]
  def test_reprocess_uses_cached_transcript(...): # transcribe fake called once across fail+reprocess
  def test_no_speech_gives_empty_review(...): # transcript "" -> status review, 0 drafts, message "No prices heard"
  def test_benchmark_counts(tmp_path): ...  # tiny key/out pair -> exact counts row
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS. Then the **gate**: run
  `scripts/run_clip.py eval/clips/clip1.mp4`, then clip2, then `scripts/benchmark.py`. Paste
  the table into `docs/api-notes.md`. If items are found but prices land on the wrong item,
  add the rule "one item per sentence" to the recording tips.
- [ ] **Step 5:** `git add -A && git commit -m "task 11: pipeline runner, jobs, benchmark"`

### Task 12: Seller web flow (create, upload, progress, review, approve)

**Files:**
- Create: `app/web/__init__.py`, `app/web/main.py`, `app/web/templates/{base,home,new_shop,seller,session,review}.html`,
  `app/web/static/app.css`, `app/web/static/review.js`, `tests/test_web_seller.py`

**Interfaces:**
- Consumes: db functions, `submit`, `process_video_session`, `reprocess`, `load_settings`,
  `CostLedger`.
- Produces: `create_app(settings: Settings) -> FastAPI`, with routes:

  | Route | Purpose |
  |---|---|
  | `GET /` | Choice: start as seller · find prices (customer) · try it (judges) |
  | `GET/POST /new` | Create shop → redirect `/e/{token}` |
  | `GET /e/{token}` | Seller home: upload, sessions, current version, action buttons |
  | `POST /e/{token}/upload` | `<input type=file accept="video/*" capture="environment">` → session → `submit` → redirect |
  | `GET /e/{token}/s/{sid}` | Progress (auto-refresh every 3 s) or review cards |
  | `GET /e/{token}/s/{sid}/status` | JSON status |
  | `GET /e/{token}/s/{sid}/clip/{i}` | Audio clip (seller only) |
  | `POST /e/{token}/s/{sid}/approve` | Edited fields + per-item confirm → `approve` |
  | `POST /e/{token}/s/{sid}/retry` | `reprocess` |
  | `GET /m/{path}` | Public photos only (under `DATA_DIR/photos`, plus `public_tmp`) |

  - Unknown token → 404.
  - Review cards show: photo, name (ta/en), variety, price lines, quantity, quote, ▶ clip, and
    flags with option buttons.
  - Approve is disabled until every blocking flag is resolved or confirmed.
  - The upload page shows the Meta notice from Global Constraints.

- [ ] **Step 1: Write failing tests** with `TestClient` and `process_video_session`
  monkeypatched to write canned drafts:
  - create shop → redirect contains a token;
  - wrong token → 404;
  - upload → session page;
  - review HTML contains the quote and the flag options `18` and `80`;
  - approve with an unresolved blocking flag → 400;
  - resolved → redirect and a version exists;
  - upload page contains the Meta notice text.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Uvicorn entry: `uvicorn app.web.main:app` where
  `app = create_app(load_settings())`.
- [ ] **Step 4:** `pytest -q` should PASS. Then a manual check on a phone (same Wi-Fi,
  `--host 0.0.0.0`): upload clip1 and approve.
- [ ] **Step 5:** `git add -A && git commit -m "task 12: seller flow pages"`

### Task 13: Stock value, CSV, POS-app template, QR, PDF price board

**Files:**
- Create: `app/outputs/__init__.py`, `app/outputs/value.py`, `app/outputs/csv_export.py`,
  `app/outputs/qr.py`, `app/outputs/pdf.py`, `app/web/templates/board.html`,
  `app/web/static/fonts/` (Noto Sans Tamil Regular + Bold TTF and `OFL.txt`),
  `tests/test_outputs.py`
- Modify: `app/web/main.py` (routes)

**Interfaces:**
- Produces:
  - `stock_value(items: list[Item]) -> tuple[Decimal, list[str]]`: returns the total and the
    names left out (missing qty, or a qty unit not convertible to any price line's unit).
  - `generic_csv(items: list[Item], updated_at: datetime) -> str`. Columns:
    `name_en,name_ta,variety,price,per_amount,unit,qty,qty_unit,updated_at`, one row per price
    line.
  - `posapp_pos_csv(items: list[Item]) -> str`. Columns: `Item Name,Selling Price,Unit,Description`.
    Uses the first price line; Item Name = `"Tomato (Bengaluru)"`; Description = `name_ta`.
  - `qr_png(url: str) -> bytes`
  - `price_board_pdf(shop: sqlite3.Row, items: list[Item], at: datetime, shop_url: str) -> bytes`
- Routes:
  - `GET /e/{token}/v/{vid}/board.pdf`
  - `/e/{token}/v/{vid}/export.csv`
  - `/e/{token}/v/{vid}/posapp.csv`
  - The seller home shows the stock value and the "left out" list.

- [ ] **Step 1: Write failing tests:**

  ```python
  def test_value_example(): assert stock_value([item(qty=40, unit="kg", line=pl(18,1,"kg"))])[0] == 720
  def test_value_quarter_kilo_line(): assert stock_value([item(qty=2, unit="kg", line=pl(15,250,"g"))])[0] == 120
  def test_value_lists_missing(): assert stock_value([item(qty=None, ...)])[1] == ["tomato"]
  def test_generic_csv_rows_per_line(): ...  # 2 lines -> 2 data rows
  def test_pdf_has_prices_and_shop(): text = pypdf_text(price_board_pdf(...)); assert "₹18" in text and "Demo Stall" in text
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. WeasyPrint uses `@font-face` pointing at the bundled Noto Sans
  Tamil. Prices are in large type; there's a QR to `PUBLIC_BASE_URL/s/<slug>` and the
  date/time. On a Mac, `brew install pango` first.
- [ ] **Step 4:** `pytest -q` should PASS. Then a visual check: open the PDF and confirm the
  Tamil names render joined (not as broken letters). Save a screenshot to
  `docs/img/board.png`.
- [ ] **Step 5:** `git add -A && git commit -m "task 13: stock value, CSV, PDF board"`

### Task 14: Publish and public shop page

**Files:**
- Create: `app/web/templates/shop.html`, `tests/test_web_public.py`
- Modify: `app/web/main.py`

**Interfaces:**
- Routes:
  - `POST /e/{token}/v/{vid}/publish` and `/unpublish`
  - `POST /e/{token}/item/{id}/soldout` (toggle)
  - `GET /s/{slug}?lang=ta|en`: latest published version. It shows:
    - real photos;
    - names in the chosen language;
    - price lines;
    - sold-out greyed out;
    - "Set by seller · <relative time>";
    - a `Demo data` badge if `is_demo`;
    - `tel:` and `https://wa.me/<digits>` links.
  - The page **must not** include quotes, audio links or condition hints.

- [ ] **Step 1: Write failing tests:**
  - an unpublished shop → page says "No prices published yet";
  - publish → the price appears;
  - the page HTML contains neither the quote text nor `/clip/`;
  - sold out shows a "Sold out" label;
  - the demo shop shows "Demo data";
  - `lang=ta` shows `தக்காளி`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 14: publish and public shop page"`

### Task 15: Next-day voice price update

**Files:**
- Create: `app/pipeline/update.py`, `app/web/templates/update.html`,
  `app/web/static/recorder.js`, `tests/test_update.py`
- Modify: `app/web/main.py`

**Interfaces:**
- Produces:
  - `@dataclass Change(name_en: str, action: str, price_lines: list[PriceLine], qty: Decimal | None, qty_unit: str | None, proof: Proof, flags: list[Flag] = [])`.
    Action is one of `set_price|sold_out|in_stock|set_qty`.
  - `parse_update(transcript: Transcript, current: list[Item], *, ledger, settings) -> list[Change]`.
    It is a Muse Spark JSON call with the same "only what was said, exact quote" rules. Checks
    reuse `check_item`, converted to a `DraftItem`. An item not in the current list gets the
    blocking flag `NEW_ITEM`.
  - `apply_changes(conn, shop_id: int, base_version_id: int, changes: list[Change]) -> int`:
    copies the base version, applies the changes and returns the new version id (unpublished).
- Routes:
  - `GET /e/{token}/update`: record with `recorder.js`, which uses MediaRecorder and uploads the
    blob;
  - `POST /e/{token}/update` (audio file): ffmpeg → WAV → transcribe → `parse_update` → a
    confirm page listing the changes and flags;
  - `POST /e/{token}/update/{sid}/confirm`: `apply_changes`, then publish.

- [ ] **Step 1: Write failing tests:**
  - "thakkali 22 today, vengayam sold out" (fake Spark) → 2 changes;
  - `apply_changes` copies untouched items and the new price is 22;
  - onion is `sold_out`;
  - an unknown item gets `NEW_ITEM`;
  - a jump from 18 to 60 is flagged.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 15: voice price update"`

### Task 16: Customer search and compare (text and voice)

**Files:**
- Create: `app/market/__init__.py`, `app/market/search.py`, `app/web/templates/market.html`,
  `tests/test_search.py`
- Modify: `app/web/main.py`

**Interfaces:**
- Produces in `app/market/search.py`:
  - `@dataclass Want(name_en: str, amount: Decimal | None, unit: str | None, max_rate: Decimal | None)`
  - `@dataclass Query(wants: list[Want], budget: Decimal | None, area: str | None)`
  - `@dataclass Listing(shop_name: str, slug: str, area: str, is_demo: bool, name_en: str, variety: str | None, line: PriceLine, rate: Decimal | None, rate_unit: str | None, updated_at: datetime, stale: bool)`
  - `SYNONYMS: dict[str, str]`, e.g. `"shallot"→"small onion"`, `"eggplant"→"brinjal"`,
    `"bhindi"→"okra"`.
  - `parse_query(text: str, *, ledger, settings) -> Query`: Muse Spark JSON. Names go through
    `SYNONYMS` and must be `CANONICAL_NAMES` keys.
  - `find_listings(conn, query: Query, now: datetime) -> list[Listing]`:
    - only `listed` shops with a published version; sold-out items excluded;
    - `stale = now - updated_at > 24h`;
    - sorted fresh-first, then by rate ascending;
    - a `max_rate` filter on `rate`;
    - if `query.area` is set, only shops whose area contains it (case-insensitive). This is
      "near me" in this version: no GPS.
- Routes:
  - `GET /market?q=...`: results table with shop, price, last updated and a stale badge
    ("may be old"), plus `Demo data` badges;
  - `POST /market/voice` (audio): transcribe, then the same as `q`.

- [ ] **Step 1: Write failing tests:**
  - "tomato under 25" → only listings with rate ≤ 25/kg;
  - a 30-hour-old listing is marked stale and sorts after fresh ones;
  - an unlisted judge shop never appears;
  - "shallot" finds "small onion";
  - a sold-out item is excluded.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 16: customer search and compare"`

### Task 17: Budget basket

**Files:**
- Create: `app/market/basket.py`, `tests/test_basket.py`
- Modify: `app/web/templates/market.html`, `app/web/main.py`

**Interfaces:**
- Consumes: `Want`, `Listing`, `rate`, `convert`.
- Produces:
  - `@dataclass BasketLine(want: Want, listing: Listing, cost: Decimal, assumed: bool)`
  - `@dataclass BasketPlan(kind: str, shop: str | None, lines: list[BasketLine], total: Decimal, missing: list[str])`.
    Kind is `split` or `single_shop`.
  - `plan_basket(wants: list[Want], listings: list[Listing], budget: Decimal | None) -> list[BasketPlan]`:
    - only fresh listings are used;
    - an amount that wasn't given becomes 1 kg (`WEIGHT_ITEMS`) or 1 piece, with
      `assumed=True`;
    - "split" means the cheapest listing per want;
    - "single_shop" means the cheapest shop that has all wants (omitted if none);
    - costs are rounded to ₹0.5.
  - `explain_basket(plans: list[BasketPlan], budget: Decimal | None, *, ledger, settings) -> str`.
    Muse Spark writes 2–3 friendly sentences from the plans' JSON. **Every ₹ number in its text
    must exist in the plans** (totals, line costs, budget); otherwise return a template sentence
    built in code.
- `/market` handles queries with a budget by showing the plans, the assumptions and the
  explanation.

- [ ] **Step 1: Write failing tests:**

  ```python
  def test_split_cheapest_per_item(): ...  # tomato 18@A, 22@B; onion 30@B, 25@A -> split total = 18*1 + 25*1
  def test_single_shop_needs_all_items(): ...  # only B has potato -> single_shop shop == "B"
  def test_missing_amount_assumed(): assert plan_basket([Want("tomato",None,None,None)], L, None)[0].lines[0].assumed
  def test_stale_ignored(): ...
  def test_explanation_with_foreign_number_falls_back(fake_spark_says_999): assert "999" not in explain_basket(...)
  ```

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 17: budget basket with checked explanation"`

### Task 18: Judge "try it" mode, limits, expiry, demo seeding

**Files:**
- Create: `app/limits.py`, `scripts/seed_demo.py`, `tests/test_limits.py`
- Modify: `app/web/main.py`, `app/db.py` (add `purge_expired`)

**Interfaces:**
- Produces:
  - `class RateLimiter(per_ip_hour: int, global_hour: int)` with
    `.allow(ip: str, now: datetime) -> bool`. It's in-memory and resets per hour.
  - `purge_expired(conn, data_dir: Path, now: datetime) -> int`. It deletes expired judge shops
    with their files, and media older than 30 days for non-demo shops. Returns the number of
    shops removed. It is called at app startup and before each upload.
  - `GET /try`: creates a judge shop (`is_judge=True`, `listed=False`) → seller home with a
    banner: "Test shop — not listed in the market, deleted after 7 days".
  - `scripts/seed_demo.py eval/out/<clip>.json --name "..." --area "..."`: creates a listed demo
    shop (`is_demo=True`), approves and publishes.
  - Upload → 429 page when limited. `CostCapExceeded` → page: "Today's demo budget is used up —
    please try the sample shops."

- [ ] **Step 1: Write failing tests:**
  - the 6th upload in an hour from one IP → 429;
  - an expired judge shop is purged and its slug returns 404;
  - a demo shop seeded from canned JSON is listed and shows "Demo data";
  - the `/try` shop never appears in `find_listings`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 18: judge mode, limits, expiry, demo seeding"`

### Task 19: Deploy on Modal

**Files:**
- Create: `modal_app.py`, `app/storage.py`, `docs/deploy.md`
- Modify: `app/jobs.py`, `app/web/main.py` (call `storage.commit()` after writes)

**Interfaces:**
- Produces:
  - `storage.commit() -> None`: calls `volume.commit()` when running on Modal, no-op locally.
  - `modal_app.py` defines:
    - an image: Debian slim, Python 3.12, apt `ffmpeg libpango-1.0-0 libpangoft2-1.0-0`, pip
      install of the project;
    - Volume `marketmate-data` mounted at `/data`;
    - Secret `marketmate-secrets`;
    - env `DATA_DIR=/data`;
    - one `@modal.asgi_app()` function with `max_containers=1`, `scaledown_window=1200`,
      `timeout=900`. Processing threads run in this one container, so SQLite has a single
      writer.

- [ ] **Step 1:** Run
  `modal secret create marketmate-secrets --from-dotenv .env`, then `modal deploy modal_app.py`.
  Note the `*.modal.run` URL, set it as `PUBLIC_BASE_URL` in the secret, and redeploy.
- [ ] **Step 2:** Smoke test on a phone over mobile data:
  - create a shop;
  - upload clip1;
  - approve;
  - publish;
  - open `/s/<slug>` and the QR from the PDF;
  - search on `/market`.

  Record the run in `docs/deploy.md`.
- [ ] **Step 3:** Check the Modal usage page and the cost ledger (`today_usd`). Both should be
  within limits.
- [ ] **Step 4:** `git add -A && git commit -m "task 19: Modal deployment"`

### Task 20: Real stalls, benchmark, README, submission

**Files:**
- Create: `docs/architecture.md`, `docs/benchmark.md`, `docs/demo-script.md`
- Modify: `README.md`

- [ ] **Step 1:** Record 3 real stalls with the sellers' consent, plus answer keys in
  `eval/answers/`. Run `run_clip.py` and `benchmark.py`, once with `--provider meta` and once
  with `--provider baseten` (extraction step only). Write `docs/benchmark.md` with the measured
  tables only.
- [ ] **Step 2:** `seed_demo.py` for each stall (listed, labelled demo data). Deploy.
- [ ] **Step 3:** Write the README:
  - what it does;
  - the live link;
  - "try it" steps for judges;
  - the Meta models table (design §3);
  - the measured benchmark;
  - privacy notes;
  - a "built during the hackathon" statement;
  - "Built with Muse Code" if true.

  POS wording is "CSV for any POS" unless a POS app import was actually tested.

  `docs/architecture.md` is the flow from design §4; `docs/demo-script.md` is the 3-minute
  scene list from design §4.6.
- [ ] **Step 4:** Final checks:
  - `git ls-files` has no `.env`;
  - switch the repo to public with
    `gh repo edit sivat241meta/marketmate --visibility public --accept-visibility-change-consequences`.
- [ ] **Step 5:** `git add -A && git commit -m "task 20: benchmark, docs, submission"` and
  `git push`.

### Task 21 (stretch): Seller-only visible-condition hint

**Files:**
- Create: `app/pipeline/condition.py`, `tests/test_condition.py`
- Modify: `app/pipeline/run.py`, `app/web/templates/review.html`

**Interfaces:**
- Produces:
  - `condition_hint(photo: Path, name_en: str, *, ledger, settings) -> tuple[str, str]`:
    returns `(code, reason)`, with code in `looks_ok|some_marks|visible_damage|cannot_tell`.
    It's a Muse Spark image call whose prompt says to describe only visible surface marks and
    to say `cannot_tell` when unsure.
  - The review card shows: "Visible check (only what the camera sees): …".

- [ ] **Step 1: Write failing tests:**
  - the code is always one of the four values (bad model output → `cannot_tell`);
  - the public shop page HTML never contains the hint text.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` should PASS.
- [ ] **Step 5:** `git add -A && git commit -m "task 21: seller-only condition hint"`
