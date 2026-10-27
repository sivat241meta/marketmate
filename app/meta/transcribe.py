from __future__ import annotations

import json
from pathlib import Path

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
    raw_turns = data.get("turns", [])
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
) -> Transcript:
    """Transcribe a 16 kHz mono WAV via Voice Transcribe; log cost; parse."""
    ledger.check()
    request_payload = {
        "model": VOICE_MODEL,
        "audioEncoding": "WAV",
        "mode": "ENDPOINTING",
        "languageBias": list(languages),
        "keywords": list(keywords),
    }
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
        raise TranscribeError(f"transcribe request failed: {exc}") from exc
    data = response.json()
    duration_ms = int(data.get("audioDurationMs", 0))
    ledger.add("meta", VOICE_MODEL, duration_ms / 3_600_000 * TRANSCRIBE_USD_PER_HOUR,
               "transcribe_wav")
    return transcript_from_json(data)
