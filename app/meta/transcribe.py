from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

import httpx

from app.config import META_BASE_URL, VOICE_MODEL, Settings
from app.costs import CostLedger
from app.models import Transcript, Turn

TRANSCRIBE_USD_PER_HOUR = 0.18


class TranscribeError(Exception):
    pass


def transcript_from_json(data: dict) -> Transcript:
    """Build a Transcript from a Voice Transcribe response body."""
    text = data.get("transcript", "")
    duration_ms = int(data.get("audioDurationMs", 0))
    raw_turns = data.get("turns") or []
    turns = [
        Turn(id=int(turn.get("turnId", i)) + 1,
             start_ms=int(turn.get("startMs", 0)),
             end_ms=int(turn.get("endMs", 0)),
             text=turn.get("transcript", ""))
        for i, turn in enumerate(raw_turns)
    ]
    if not turns and text:
        turns = [Turn(id=1, start_ms=0, end_ms=duration_ms, text=text)]
    return Transcript(text=text, duration_ms=duration_ms, turns=turns)


def transcribe_wav(
    wav: Path,
    *,
    keywords: list[str],
    ledger: CostLedger,
    settings: Settings,
    languages: tuple[str, ...] = ("Tamil", "English"),
    step: str = "transcribe",
    shop_id: int | None = None,
    session_id: int | None = None,
) -> Transcript:
    """Transcribe a 24 kHz mono WAV via Voice Transcribe; log cost; parse.

    The logged summary names only the language and audio length, never the
    transcript.
    """
    ledger.check()
    request_payload = {
        "model": VOICE_MODEL,
        "audioEncoding": "WAV",
        "mode": "ENDPOINTING",
        "languageBias": list(languages),
        "keywords": list(keywords),
    }
    started = monotonic()
    try:
        response = httpx.post(
            f"{META_BASE_URL}/asr/transcribe",
            files={
                "request": ("request.json", json.dumps(request_payload), "application/json"),
                "audio": (Path(wav).name, Path(wav).read_bytes(), "audio/wav"),
            },
            headers={"Authorization": "Bearer " + settings.model_api_key},
            timeout=180.0,
        )
        response.raise_for_status()
    except Exception as exc:
        ledger.add("meta", VOICE_MODEL, 0.0, "transcribe_wav",
                   shop_id=shop_id, session_id=session_id, step=step,
                   latency_ms=int((monotonic() - started) * 1000), ok=0)
        raise TranscribeError(f"transcribe request failed: {exc}") from exc
    latency_ms = int((monotonic() - started) * 1000)
    data = response.json()
    duration_ms = int(data.get("audioDurationMs", 0))
    language = languages[0] if languages else "English"
    seconds = round(duration_ms / 1000)
    ledger.add("meta", VOICE_MODEL, duration_ms / 3_600_000 * TRANSCRIBE_USD_PER_HOUR,
               "transcribe_wav", shop_id=shop_id, session_id=session_id,
               step=step, latency_ms=latency_ms, ok=1,
               summary=f"{language} · {seconds} s audio")
    return transcript_from_json(data)
