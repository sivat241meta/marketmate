from __future__ import annotations

import json
from pathlib import Path

from app import db
from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded, CostLedger
from app.meta.transcribe import transcribe_wav
from app.models import Flag, Frame, Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.extract import extract_items
from app.pipeline.frames import frames_for_window, item_window, pick_best_frame
from app.pipeline.media import (
    check_length,
    cut_audio_clip,
    extract_audio,
    extract_frames,
)
from app.pipeline.names import PRODUCE_KEYWORDS
from app.pipeline.photos import make_photo


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
    items = extract_items(transcript, ledger=ledger, settings=settings)
    shop_id = conn.execute("SELECT shop_id FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()["shop_id"]
    previous = db.last_prices(conn, shop_id)
    photo_dir = Path(settings.data_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    clip_dir = session_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(items):
        _progress(conn, session_id, f"Checking item {index + 1}/{len(items)}...")
        item.flags.extend(check_item(item, previous))
        start_ms, end_ms = item_window(item, transcript.turns)
        frame, matches = pick_best_frame(
            item, frames_for_window(frames, start_ms, end_ms),
            ledger=ledger, settings=settings)
        if not matches:
            item.flags.append(Flag(
                field="photo", code="PICTURE_MISMATCH",
                message=f"no frame clearly shows {item.name_en}"))
        item.photo = str(make_photo(
            frame, item.name_en, photo_dir / f"s{session_id}_{index}.jpg",
            ledger=ledger, settings=settings))
        item.proof.frame = str(frame.path)
        clip = cut_audio_clip(wav, item.proof.start_ms, item.proof.end_ms,
                              clip_dir / f"item_{index}.m4a")
        item.proof.audio_clip = str(clip)
    db.save_drafts(conn, session_id, items)
    db.set_session_status(conn, session_id, "review", f"{len(items)} items need review")


def process_video_session(conn, session_id: int, video: Path, *,
                          settings, ledger: CostLedger) -> None:
    """Run the full pipeline for one uploaded video. Never raises."""
    video = Path(video)
    try:
        check_length(video, settings.max_video_seconds)
        session_dir = _session_dir(settings, session_id)
        _progress(conn, session_id, "Extracting audio and frames...")
        wav = extract_audio(video, session_dir / "audio.wav")
        frames = extract_frames(video, session_dir / "frames")
        _progress(conn, session_id, "Transcribing...")
        transcript = transcribe_wav(wav, keywords=PRODUCE_KEYWORDS,
                                    ledger=ledger, settings=settings)
        (session_dir / "transcript.json").write_text(
            json.dumps(_transcript_to_json(transcript)))
        if not transcript.turns:
            db.save_drafts(conn, session_id, [])
            db.set_session_status(conn, session_id, "review", "No prices heard")
        else:
            _progress(conn, session_id, "Extracting items...")
            _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                            settings=settings, ledger=ledger)
        video.unlink(missing_ok=True)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed", f"Processing failed: {exc}")


def reprocess(conn, session_id: int, *, settings, ledger: CostLedger) -> None:
    """Retry a failed session from its cached transcript. Never raises."""
    row = conn.execute("SELECT status FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    if row is None or row["status"] != "failed":
        raise ValueError("reprocess is only for failed sessions")
    session_dir = _session_dir(settings, session_id)
    transcript = _transcript_from_json(
        json.loads((session_dir / "transcript.json").read_text()))
    try:
        frames = _load_frames(session_dir / "frames")
        wav = session_dir / "audio.wav"
        _finish_session(conn, session_id, transcript, frames, wav, session_dir,
                        settings=settings, ledger=ledger)
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed", BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed", f"Processing failed: {exc}")
