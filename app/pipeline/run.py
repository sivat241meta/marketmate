from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app import db
from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded, CostLedger
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
from app.pipeline.names import PRODUCE_KEYWORDS
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


def _finish_session(conn, session_id: int, transcript: Transcript, frames: list[Frame],
                    wav: Path, session_dir: Path, *, settings, ledger) -> None:
    def _extract_progress(part: int, total: int) -> None:
        detail = f"part {part} of {total}" if total > 1 else None
        db.set_stage(conn, session_id, "items", detail=detail)

    db.set_stage(conn, session_id, "items")
    items = extract_items(transcript, ledger=ledger, settings=settings,
                          progress=_extract_progress)
    shop_id = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()["shop_id"]
    previous = db.last_prices(conn, shop_id)
    photo_dir = Path(settings.data_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    clip_dir = session_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    matched: list[bool] = []
    db.set_stage(conn, session_id, "photos")
    for index, item in enumerate(items):
        db.set_stage(conn, session_id, "photos",
                     detail=f"item {index + 1} of {len(items)}")
        start_ms, end_ms = item_window(item, transcript.turns)
        frame, matches = pick_best_frame(
            item, frames_for_window(frames, start_ms, end_ms),
            ledger=ledger, settings=settings)
        matched.append(matches)
        item.photo = str(make_photo(
            frame, item.name_en, photo_dir / f"s{session_id}_{index}.jpg",
            ledger=ledger, settings=settings))
        item.proof.frame = str(frame.path)
        clip = cut_audio_clip(wav, item.proof.start_ms, item.proof.end_ms,
                              clip_dir / f"item_{index}.m4a")
        item.proof.audio_clip = str(clip)
    db.set_stage(conn, session_id, "checking")
    for item, matches in zip(items, matched):
        item.flags.extend(check_item(item, previous))
        if not matches:
            item.flags.append(Flag(
                field="photo", code="PICTURE_MISMATCH",
                message=f"no frame clearly shows {item.name_en}"))
    db.save_drafts(conn, session_id, items)
    db.set_stage(conn, session_id, "ready")
    db.set_session_status(conn, session_id, "review", f"{len(items)} items need review")


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
        transcript = transcribe_wav(wav, keywords=PRODUCE_KEYWORDS,
                                    ledger=ledger, settings=settings)
        (session_dir / "transcript.json").write_text(
            json.dumps(_transcript_to_json(transcript)))
        if not transcript.turns:
            db.save_drafts(conn, session_id, [])
            db.set_stage(conn, session_id, "ready")
            db.set_session_status(conn, session_id, "review", "No prices heard")
        else:
            _progress(conn, session_id, "Extracting items...")
            _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                            settings=settings, ledger=ledger)
        video.unlink(missing_ok=True)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc))


def reprocess(conn, session_id: int, *, settings, ledger: CostLedger) -> None:
    """Retry a failed (or review) session from its cached transcript."""
    row = conn.execute("SELECT status FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    if row is None or row["status"] not in ("failed", "review"):
        raise ValueError("reprocess is only for failed or review sessions")
    session_dir = _session_dir(settings, session_id)
    transcript_path = session_dir / "transcript.json"
    if not transcript_path.is_file():
        raise ValueError("this session has nothing to re-run yet; upload again")
    transcript = _transcript_from_json(json.loads(transcript_path.read_text()))
    db.set_session_status(conn, session_id, "processing", "Trying again...")
    try:
        frames = _load_frames(session_dir / "frames")
        wav = session_dir / "audio.wav"
        _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                        settings=settings, ledger=ledger)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc))
