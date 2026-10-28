from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app import db
from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded, CostLedger
from app.languages import shop_bias
from app.meta.spark import SparkError
from app.meta.transcribe import TranscribeError, transcribe_wav
from app.models import Flag, Frame, Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.extract import extract_items
from app.pipeline.frames import frames_for_window, item_window, pick_best_frame
from app.pipeline.media import (
    VideoTooLong,
    check_length,
    cut_audio_clip,
    extract_audio,
    extract_frames,
)
from app.pipeline.names import keywords_for
from app.pipeline.photos import make_photo


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
                  all_frames: list[Frame] | None = None):
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
    shop_id = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()["shop_id"]
    previous = db.last_prices(conn, shop_id)
    photo_dir = Path(settings.data_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    clip_dir = session_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    matched: list[bool] = []
    use_live_frames = frames_by_turn is not None
    row = conn.execute("SELECT kind FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    is_live = (row["kind"] == "live") if row else use_live_frames
    if not is_live:
        db.set_stage(conn, session_id, "photos")
    for index, item in enumerate(items):
        if not is_live:
            db.set_stage(conn, session_id, "photos",
                         detail=f"item {index + 1} of {len(items)}")
        if use_live_frames:
            frame = live_frame_for_item(item, frames_by_turn, turns)
            if frame is None:
                matched.append(False)
                clip = cut_audio_clip(wav_path, item.proof.start_ms,
                                      item.proof.end_ms,
                                      clip_dir / f"item_{index}.m4a")
                item.proof.audio_clip = str(clip)
                continue
            matched.append(True)
        else:
            start_ms, end_ms = item_window(item, transcript.turns)
            frame, matches = pick_best_frame(
                item, frames_for_window(all_frames or [], start_ms, end_ms),
                ledger=ledger, settings=settings)
            matched.append(matches)
        item.photo = str(make_photo(
            frame, item.name_en, photo_dir / f"s{session_id}_{index}.jpg",
            ledger=ledger, settings=settings))
        item.proof.frame = str(frame.path)
        clip = cut_audio_clip(wav_path, item.proof.start_ms, item.proof.end_ms,
                              clip_dir / f"item_{index}.m4a")
        item.proof.audio_clip = str(clip)
    db.set_stage(conn, session_id, "checking")
    for item, matches in zip(items, matched):
        item.flags.extend(check_item(item, previous, language=language,
                                    ledger=ledger, settings=settings))
        if not matches:
            item.flags.append(Flag(
                field="photo", code="PICTURE_MISMATCH",
                message=f"no frame clearly shows {item.name_en}"))
    db.save_drafts(conn, session_id, items)
    db.set_stage(conn, session_id, "ready")
    db.set_session_status(conn, session_id, "review", f"{len(items)} items need review")
    return items


def _finish_session(conn, session_id: int, transcript: Transcript, frames: list[Frame],
                    wav: Path, session_dir: Path, *, settings, ledger,
                    language: str = "ta") -> None:
    process_turns(conn, session_id, transcript.turns, None, wav,
                  settings=settings, ledger=ledger, language=language,
                  all_frames=frames)


def process_video_session(conn, session_id: int, video: Path, *,
                          settings, ledger: CostLedger) -> None:
    """Run the full pipeline for one uploaded video. Never raises."""
    video = Path(video)
    try:
        db.set_stage(conn, session_id, "uploaded")
        check_length(video, settings.max_video_seconds)
        session_dir = _session_dir(settings, session_id)
        _progress(conn, session_id, "Extracting audio and frames...")
        db.set_stage(conn, session_id, "audio")
        wav = extract_audio(video, session_dir / "audio.wav")
        frames = extract_frames(video, session_dir / "frames")
        _progress(conn, session_id, "Transcribing...")
        db.set_stage(conn, session_id, "listening")
        language = _shop_language(conn, session_id)
        transcript = transcribe_wav(wav, keywords=keywords_for(language),
                                    ledger=ledger, settings=settings,
                                    languages=shop_bias(language))
        (session_dir / "transcript.json").write_text(
            json.dumps(_transcript_to_json(transcript)))
        if not transcript.turns:
            db.save_drafts(conn, session_id, [])
            db.set_stage(conn, session_id, "ready")
            db.set_session_status(conn, session_id, "review", "No prices heard")
        else:
            _progress(conn, session_id, "Extracting items...")
            _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                            settings=settings, ledger=ledger, language=language)
        video.unlink(missing_ok=True)
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
    session_dir = _session_dir(settings, session_id)
    transcript_path = session_dir / "transcript.json"
    if not transcript_path.is_file():
        raise ValueError("this session has nothing to re-run yet; upload again")
    transcript = _transcript_from_json(json.loads(transcript_path.read_text()))
    db.set_session_status(conn, session_id, "processing", "Trying again...")
    try:
        wav = session_dir / "audio.wav"
        language = _shop_language(conn, session_id)
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
