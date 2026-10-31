from __future__ import annotations

import json
import subprocess
from pathlib import Path
from time import perf_counter

from app import db
from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded, CostLedger
from app.languages import get_language, language_bias, shop_bias
from app.meta.spark import SparkError
from app.meta.transcribe import TranscribeError, transcribe_wav
from app.models import Flag, Frame, Transcript, Turn
from app.parallel import map_parallel_ordered, photo_workers
from app.pipeline.checks import check_item, flag_same_name_two_prices
from app.pipeline.extract import extract_items, merge_repeated_prices
from app.pipeline.frames import frames_for_window, item_window, pick_best_frame
from app.pipeline.media import (
    VideoTooLong,
    check_length,
    cut_audio_clip,
    extract_audio,
    extract_frames,
    extract_window_frames,
    has_video_stream,
)
from app.pipeline.names import correct_draft_from_variety, keywords_for
from app.pipeline.photos import (
    ensure_visual_nouns,
    make_candidates,
    make_photo,
    window_frames,
)
from app.pipeline.scripts import script_mismatch

#: At most this many guard re-transcriptions per session; then the last
#: transcript continues through the normal review flags.
MAX_LANG_RERUNS = 2


def friendly_error_message(exc: BaseException, media: str = "video") -> str:
    """Plain-English failure line for sellers; never includes stack traces."""
    if isinstance(exc, CostCapExceeded):
        return BUDGET_EXHAUSTED_MESSAGE
    if isinstance(exc, VideoTooLong):
        return "That video is longer than 3 minutes. Please send a shorter clip."
    if isinstance(exc, TranscribeError):
        return ("We could not hear any prices. "
                "Try again closer to the phone, in a quieter spot.")
    if isinstance(exc, SparkError):
        return "We had trouble understanding your prices. Please try again."
    if isinstance(exc, (subprocess.CalledProcessError, OSError)):
        return f"We could not open that {media}. Please try recording it again."
    return f"Something went wrong while processing your {media}. Please try again."


def _session_dir(settings, session_id: int) -> Path:
    path = Path(settings.data_dir) / "sessions" / str(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _progress(conn, session_id: int, message: str) -> None:
    db.set_session_status(conn, session_id, "processing", message)


def _shop_language(conn, session_id: int) -> str:
    row = conn.execute(
        "SELECT shops.language AS language FROM shops"
        " JOIN sessions ON sessions.shop_id = shops.id"
        " WHERE sessions.id = ?",
        (session_id,)).fetchone()
    return row["language"] if row and row["language"] else "ta"


def spoken_language(conn, session_id: int) -> str:
    """Language the seller speaks: the picked speak_lang, else the shop."""
    speak = db.session_speak_lang(conn, session_id)
    if speak:
        try:
            get_language(speak)
        except KeyError:
            pass
        else:
            return speak
    return _shop_language(conn, session_id)


def _speak_bias(conn, session_id: int) -> tuple[str, ...]:
    """Voice languageBias for a session: speak_lang, else the shop as today."""
    speak = db.session_speak_lang(conn, session_id)
    if speak:
        try:
            return tuple(language_bias(speak))
        except KeyError:
            pass
    return shop_bias(_shop_language(conn, session_id))


def _stop_for_language(conn, session_id: int, script: str,
                       language_code: str) -> None:
    """Park a session in language_check; no Spark call has been made."""
    try:
        lang_name = get_language(language_code).api_name
    except KeyError:
        lang_name = "English"
    heard = f"{script} letters" if script != "other" else "an unfamiliar script"
    db.set_stage(conn, session_id, "language_check", detail=script)
    db.set_session_status(
        conn, session_id, "processing",
        f"We heard {heard}, but this video was set to {lang_name}. "
        "Pick the language you spoke.")


def _transcript_to_json(transcript: Transcript) -> dict:
    return {
        "text": transcript.text,
        "duration_ms": transcript.duration_ms,
        "turns": [{"id": t.id, "start_ms": t.start_ms, "end_ms": t.end_ms,
                   "text": t.text} for t in transcript.turns],
    }


def _transcript_from_json(data: dict) -> Transcript:
    return Transcript(
        text=data.get("text", ""),
        duration_ms=int(data.get("duration_ms", 0)),
        turns=[Turn(id=t["id"], start_ms=t["start_ms"], end_ms=t["end_ms"],
                    text=t["text"]) for t in data.get("turns", [])],
    )


def _load_frames(frames_dir: Path) -> list[Frame]:
    frames: list[Frame] = []
    for path in sorted(frames_dir.glob("f_*.jpg")):
        try:
            moment = int(path.stem[2:])
        except ValueError:
            continue
        frames.append(Frame(path=path, t_ms=moment))
    return sorted(frames, key=lambda f: f.t_ms)


def live_frame_for_item(item, frames_by_turn, turns=None):
    """End frame else start frame of the turn holding the item's quote.

    ``frames_by_turn`` maps turn id -> {"start": Frame, "end": Frame} or a
    list of Frames (last wins as the end frame). Falls back to any frame
    when the quoted turn has none, else None.
    """
    if not frames_by_turn:
        return None

    def _pick(entry):
        if entry is None:
            return None
        if isinstance(entry, dict):
            return entry.get("end") or entry.get("start")
        if isinstance(entry, (list, tuple)) and entry:
            return entry[-1]
        return entry if isinstance(entry, Frame) else None

    candidates: list[int] = list(getattr(item.proof, "turn_ids", None) or [])
    quote = getattr(item.proof, "quote", "") or ""
    if not candidates and quote and turns:
        for turn in turns:
            if quote in (turn.text or ""):
                candidates.append(turn.id)
                break
    for turn_id in candidates:
        frame = _pick(frames_by_turn.get(turn_id))
        if frame is not None:
            return frame
    for entry in frames_by_turn.values():
        frame = _pick(entry)
        if frame is not None:
            return frame
    return None


def process_turns(conn, session_id: int, turns: list[Turn], frames_by_turn,
                  wav_path, *, settings, ledger, language: str = "ta",
                  all_frames: list[Frame] | None = None,
                  video: Path | None = None):
    """Shared final steps after transcription for the video and live paths.

    ``turns`` are the completed turns. ``frames_by_turn`` maps turn id to
    that turn's saved frames (live path) or None (video path, which uses
    ``all_frames`` with the windowed Spark picker). Cuts clips from
    ``wav_path``, saves drafts and moves the session to review.
    Returns the draft items.
    """
    wav_path = Path(wav_path)
    session_dir = _session_dir(settings, session_id)
    duration_ms = max((t.end_ms for t in turns), default=0)
    transcript = Transcript(text=" ".join(t.text for t in turns),
                            duration_ms=duration_ms, turns=list(turns))

    def _extract_progress(part: int, total: int) -> None:
        detail = f"part {part} of {total}" if total > 1 else None
        db.set_stage(conn, session_id, "items", detail=detail)

    db.set_stage(conn, session_id, "items")
    items = extract_items(transcript, ledger=ledger, settings=settings,
                          language=language, progress=_extract_progress)
    for item in items:
        merge_repeated_prices(item)
    shop_id = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()["shop_id"]
    for item in items:
        # A known variety decides the item (Task 97), before photo
        # selection so the photo search uses the right noun. Items
        # carrying a seller-chosen name are never touched.
        if db.chosen_name_for(conn, shop_id, db.match_key_of(item),
                              item.variety) is None:
            correct_draft_from_variety(item, language=language)
    previous = db.last_prices(conn, shop_id)
    photo_dir = Path(settings.data_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    clip_dir = session_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    matched: list[bool] = [True] * len(items)
    use_live_frames = frames_by_turn is not None
    row = conn.execute("SELECT kind FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    is_live = (row["kind"] == "live") if row else use_live_frames
    # Voice note (or any audio-only file): no frames, so no photo step and
    # no photo flags; transcription, extraction, clips and checks continue.
    audio_only = not is_live and not (all_frames or [])
    if not is_live and not audio_only:
        db.set_stage(conn, session_id, "photos")
    # Video path, first pass: pick each item's frame and pool up front, so
    # the photo step knows the other items' picked frames (cross-check).
    # Task 140: the per-item Spark frame picks run concurrently.
    video_prep: dict[int, tuple] = {}
    if not use_live_frames and not audio_only and items:
        def _prep(pos: int):
            entry = items[pos]
            start_ms, end_ms = item_window(entry, transcript.turns)
            picked, matches = pick_best_frame(
                entry, frames_for_window(all_frames or [], start_ms, end_ms),
                ledger=ledger, settings=settings)
            pool = list(all_frames or [])
            near = sum(1 for f in pool if abs(f.t_ms - picked.t_ms) <= 1000)
            if video is not None and near < 3:
                try:
                    dense = extract_window_frames(
                        Path(video), picked.t_ms,
                        session_dir / "frames" / f"dense_{pos}")
                except Exception:  # noqa: BLE001 - dense frames are optional
                    dense = []
                pool = pool + dense
            return (picked, matches, pool)

        for pos, result in enumerate(map_parallel_ordered(
                _prep, list(range(len(items))), workers=photo_workers())):
            video_prep[pos] = result
    # Task 67: the session's visual-noun cache survives reprocessing.
    # Task 72: the kitchen-category cache ("fruit"/"vegetable"/"produce")
    # from the same Spark call rides along for the generic fallback.
    noun_cache: dict[str, str] = {}
    category_cache: dict[str, str] = {}
    nouns_path = session_dir / "visual_nouns.json"
    categories_path = session_dir / "visual_categories.json"
    if not use_live_frames and not audio_only and nouns_path.is_file():
        try:
            loaded = json.loads(nouns_path.read_text())
        except (OSError, ValueError):
            # A bad cache is remade on the next run.
            loaded = {}
        if isinstance(loaded, dict):
            noun_cache = {str(k): str(v) for k, v in loaded.items()
                          if isinstance(v, str)}
    if not use_live_frames and not audio_only and categories_path.is_file():
        try:
            loaded_categories = json.loads(categories_path.read_text())
        except (OSError, ValueError):
            loaded_categories = {}
        if isinstance(loaded_categories, dict):
            category_cache = {str(k): str(v)
                              for k, v in loaded_categories.items()
                              if isinstance(v, str)}
    if not use_live_frames and not audio_only and items:
        # One Spark call for every item's visual noun up front (the call the
        # first item used to make), so the photo workers only read the
        # caches. A failure falls back to English names, as before; without
        # this the workers would hammer one failing call per item.
        try:
            ensure_visual_nouns(
                [entry.name_en for entry in items], noun_cache,
                ledger=ledger, settings=settings,
                category_cache=category_cache)
        except CostCapExceeded:
            raise
        except Exception:  # noqa: BLE001 - nouns fall back to English
            for entry in items:
                noun_cache.setdefault(entry.name_en, entry.name_en)
    # Task 140: the per-item photo work runs concurrently. Workers only do
    # API calls and file work on their own item; progress (and later the
    # drafts) is written on this thread, in completion order for progress
    # and in item order for results.
    if use_live_frames:
        def _live_one(index: int) -> bool:
            item = items[index]
            frame = live_frame_for_item(item, frames_by_turn, turns)
            if frame is None:
                clip = cut_audio_clip(wav_path, item.proof.start_ms,
                                      item.proof.end_ms,
                                      clip_dir / f"item_{index}.m4a")
                item.proof.audio_clip = str(clip)
                return False
            photo = make_photo(
                frame, item.name_en,
                photo_dir / f"s{session_id}_{index}.jpg",
                ledger=ledger, settings=settings)
            item.photo = str(photo) if photo is not None else None
            item.proof.frame = str(frame.path)
            clip = cut_audio_clip(wav_path, item.proof.start_ms,
                                  item.proof.end_ms,
                                  clip_dir / f"item_{index}.m4a")
            item.proof.audio_clip = str(clip)
            return True

        for index, result in enumerate(map_parallel_ordered(
                _live_one, list(range(len(items))),
                workers=photo_workers())):
            matched[index] = result
    elif audio_only:
        for index, item in enumerate(items):
            clip = cut_audio_clip(wav_path, item.proof.start_ms,
                                  item.proof.end_ms,
                                  clip_dir / f"item_{index}.m4a")
            item.proof.audio_clip = str(clip)
    else:
        session_names = [entry.name_en for entry in items]
        picked_list = [(entry.name_en, video_prep[pos][0])
                       for pos, entry in enumerate(items)]

        def _photo_one(index: int) -> bool:
            item = items[index]
            frame, matches, pool = video_prep[index]
            ranked = window_frames(pool, frame)
            saved = make_candidates(
                pool, frame, item.name_en,
                photo_dir / f"s{session_id}_{index}",
                ledger=ledger, settings=settings,
                session_items=session_names,
                picked_frames=picked_list,
                noun_cache=noun_cache, category_cache=category_cache)
            if saved:
                item.photo = saved[0]
                item.photo_candidates = list(saved)
            else:
                # No product in any tried frame, or every frame
                # face-blocked: the item gets no photo (letter tile).
                item.photo = None
                item.photo_candidates = []
            item.proof.frame = (str(ranked[0].path) if ranked
                                else str(frame.path))
            clip = cut_audio_clip(wav_path, item.proof.start_ms,
                                  item.proof.end_ms,
                                  clip_dir / f"item_{index}.m4a")
            item.proof.audio_clip = str(clip)
            return matches

        def _photo_done(done: int, total: int) -> None:
            db.set_stage(conn, session_id, "photos",
                         detail=f"item {done} of {total}")

        photo_workers_used = photo_workers()
        photo_started = perf_counter()
        for index, result in enumerate(map_parallel_ordered(
                _photo_one, list(range(len(items))),
                workers=photo_workers_used, on_done=_photo_done)):
            matched[index] = result
        if items:
            photo_s = perf_counter() - photo_started
            ledger.add("local", "timing", 0.0, step="photos", ok=1,
                       summary=(f"{len(items)} items in {photo_s:.1f} s"
                                f" with {photo_workers_used} workers"))
    if not use_live_frames and not audio_only and noun_cache:
        try:
            nouns_path.write_text(json.dumps(noun_cache, sort_keys=True))
        except OSError:
            pass  # The cache is a nice-to-have.
    if not use_live_frames and not audio_only and category_cache:
        try:
            categories_path.write_text(json.dumps(category_cache,
                                                 sort_keys=True))
        except OSError:
            pass  # The cache is a nice-to-have.
    db.set_stage(conn, session_id, "checking")
    # Task 140: the per-item checks (one cross-check Spark call each for
    # unparsed languages) run concurrently; flags land in item order.
    def _check_one(index: int):
        return check_item(items[index], previous, language=language,
                          ledger=ledger, settings=settings)

    for index, flags in enumerate(map_parallel_ordered(
            _check_one, list(range(len(items))), workers=photo_workers())):
        items[index].flags.extend(flags)
        if not matched[index]:
            items[index].flags.append(Flag(
                field="photo", code="PICTURE_MISMATCH",
                message=f"no frame clearly shows {items[index].name_en}"))
    flag_same_name_two_prices(items, language=language)
    db.save_drafts(conn, session_id, items)
    db.set_stage(conn, session_id, "ready")
    db.ensure_session_base(conn, session_id)
    db.set_session_status(conn, session_id, "review", f"{len(items)} items need review")
    return items


def _finish_session(conn, session_id: int, transcript: Transcript, frames: list[Frame],
                    wav: Path, session_dir: Path, *, settings, ledger,
                    language: str = "ta", video: Path | None = None) -> None:
    process_turns(conn, session_id, transcript.turns, None, wav,
                  settings=settings, ledger=ledger, language=language,
                  all_frames=frames, video=video)


def _bind_session(conn, session_id: int, ledger: CostLedger) -> None:
    """Stamp the ledger with this job's shop/session for the AI calls page."""
    try:
        row = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
    except Exception:  # noqa: BLE001 - a missing row leaves NULLs
        row = None
    ledger.bind(shop_id=row["shop_id"] if row else None,
                session_id=session_id)


def process_video_session(conn, session_id: int, video: Path, *,
                          settings, ledger: CostLedger) -> None:
    """Run the full pipeline for one uploaded video. Never raises."""
    video = Path(video)
    _bind_session(conn, session_id, ledger)
    try:
        db.set_stage(conn, session_id, "uploaded")
        check_length(video, settings.max_video_seconds)
        session_dir = _session_dir(settings, session_id)
        _progress(conn, session_id, "Extracting audio and frames...")
        db.set_stage(conn, session_id, "audio")
        wav = extract_audio(video, session_dir / "audio.wav")
        if has_video_stream(video):
            frames = extract_frames(video, session_dir / "frames")
        else:
            frames = []
        _progress(conn, session_id, "Transcribing...")
        db.set_stage(conn, session_id, "listening")
        language = spoken_language(conn, session_id)
        bias = _speak_bias(conn, session_id)
        transcript = transcribe_wav(wav, keywords=keywords_for(language),
                                    ledger=ledger, settings=settings,
                                    languages=bias)
        (session_dir / "transcript.json").write_text(
            json.dumps(_transcript_to_json(transcript)))
        if not transcript.turns:
            db.save_drafts(conn, session_id, [])
            db.set_stage(conn, session_id, "ready")
            db.ensure_session_base(conn, session_id)
            db.set_session_status(conn, session_id, "review", "No prices heard")
        else:
            bad_script = script_mismatch(transcript.text, bias)
            if bad_script is not None:
                _stop_for_language(conn, session_id, bad_script, language)
                video.unlink(missing_ok=True)
                return
            _progress(conn, session_id, "Extracting items...")
            _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                            settings=settings, ledger=ledger, language=language,
                            video=video)
        video.unlink(missing_ok=True)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc))


def apply_spoken_language(conn, session_id: int, new_lang: str, *,
                            settings, ledger: CostLedger) -> None:
    """Apply the seller's language choice from the language_check page.

    Re-runs transcription on the saved audio.wav with the new bias, unless
    the saved transcript already matches (the seller really spoke that
    language) or the session already used its re-runs: then it continues
    with the last transcript and the normal review flags handle the rest.
    Never raises.
    """
    try:
        get_language(new_lang)
    except KeyError:
        db.set_session_status(conn, session_id, "failed",
                              "Unknown language. Please try again.")
        return
    _bind_session(conn, session_id, ledger)
    try:
        row = conn.execute("SELECT stage FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        if row is None or row["stage"] != "language_check":
            # A second tap racing the first job: nothing left to do.
            return
        session_dir = _session_dir(settings, session_id)
        transcript_path = session_dir / "transcript.json"
        wav = session_dir / "audio.wav"
        transcript = _transcript_from_json(json.loads(transcript_path.read_text()))
        bias = tuple(language_bias(new_lang))
        retries = db.session_lang_retries(conn, session_id)
        if (script_mismatch(transcript.text, bias) is None
                or retries >= MAX_LANG_RERUNS):
            # Already the right script, or out of re-runs: continue as-is.
            db.set_session_speak_lang(conn, session_id, new_lang)
        else:
            _progress(conn, session_id, "Transcribing...")
            db.set_stage(conn, session_id, "listening")
            transcript = transcribe_wav(
                wav, keywords=keywords_for(new_lang), ledger=ledger,
                settings=settings, languages=bias)
            (session_dir / "transcript.json").write_text(
                json.dumps(_transcript_to_json(transcript)))
            db.set_session_speak_lang(conn, session_id, new_lang)
            db.bump_session_lang_retries(conn, session_id)
            bad_script = script_mismatch(transcript.text, bias)
            if transcript.turns and bad_script is not None:
                _stop_for_language(conn, session_id, bad_script, new_lang)
                return
        if not transcript.turns:
            db.save_drafts(conn, session_id, [])
            db.set_stage(conn, session_id, "ready")
            db.ensure_session_base(conn, session_id)
            db.set_session_status(conn, session_id, "review", "No prices heard")
        else:
            _progress(conn, session_id, "Extracting items...")
            frames = _load_frames(session_dir / "frames")
            _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                            settings=settings, ledger=ledger, language=new_lang)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc))


def _load_live_frames(frames_dir: Path) -> dict[int, dict[str, Frame]]:
    """Live frames turn<N>_<at>.jpg grouped by turn for process_turns."""
    grouped: dict[int, dict[str, Frame]] = {}
    for path in sorted(frames_dir.glob("turn*_*.jpg")):
        stem = path.stem
        try:
            turn_part, at = stem.split("_", 1)
            turn_id = int(turn_part[4:])
        except (ValueError, IndexError):
            continue
        if at not in ("start", "end"):
            continue
        grouped.setdefault(turn_id, {})[at] = Frame(path=path, t_ms=0)
    return grouped


def reprocess(conn, session_id: int, *, settings, ledger: CostLedger) -> None:
    """Retry a failed (or review) session from its cached transcript."""
    row = conn.execute("SELECT status, kind FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    # "processing" is allowed so the retry route can flip the session to the
    # stepper immediately and let the background job do the re-run.
    if row is None or row["status"] not in ("failed", "review", "processing"):
        raise ValueError("reprocess is only for failed or review sessions")
    _bind_session(conn, session_id, ledger)
    session_dir = _session_dir(settings, session_id)
    transcript_path = session_dir / "transcript.json"
    if not transcript_path.is_file():
        raise ValueError("this session has nothing to re-run yet; upload again")
    transcript = _transcript_from_json(json.loads(transcript_path.read_text()))
    db.set_session_status(conn, session_id, "processing", "Trying again...")
    try:
        wav = session_dir / "audio.wav"
        language = spoken_language(conn, session_id)
        if row["kind"] == "live":
            frames_by_turn = _load_live_frames(session_dir / "frames")
            process_turns(conn, session_id, transcript.turns, frames_by_turn, wav,
                          settings=settings, ledger=ledger, language=language)
            return
        frames = _load_frames(session_dir / "frames")
        _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                        settings=settings, ledger=ledger,
                        language=language)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc))
