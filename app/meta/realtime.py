"""Async client for Meta realtime Voice Transcribe (Task 35).

Audio is PCM 16-bit mono at 24 kHz. The server rejects audio more than
5 s ahead, so callers relay at real-time pace.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from app.config import VOICE_MODEL
from app.languages import shop_bias
from app.pipeline.names import keywords_for

REALTIME_URL = "wss://api.meta.ai/v1/asr/realtime"
REALTIME_USD_PER_HOUR = 0.18
BYTES_PER_SECOND = 48000  # 24000 samples/s * 2 bytes

_log = logging.getLogger(__name__)


class RealtimeError(Exception):
    pass


async def _default_connect(url: str):
    import websockets

    return await websockets.connect(url)


def build_handshake(api_key: str, language: str) -> dict[str, Any]:
    """Handshake JSON for the first frame. Caller must never log it."""
    return {
        "authorization": {"accessToken": f"Bearer {api_key}"},
        "audioEncoding": "PCM_24KHZ",
        "model": VOICE_MODEL,
        "mode": "ENDPOINTING",
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
        "languageBias": list(shop_bias(language)),
        "keywords": list(keywords_for(language)),
    }


def _error_text(data: dict) -> str | None:
    kind = str(data.get("type") or data.get("event") or "").lower()
    if kind == "error":
        return str(data.get("message") or data.get("error") or "realtime error")
    if isinstance(data.get("error"), str) and data["error"]:
        return data["error"]
    if isinstance(data.get("error"), dict):
        inner = data["error"]
        return str(inner.get("message") or inner.get("code") or "realtime error")
    return None


class RealtimeASR:
    """Minimal async client. Inject ``connect`` in tests with a fake server."""

    def __init__(self, *, settings, ledger, language: str = "ta",
                 connect=None, url: str = REALTIME_URL) -> None:
        self._settings = settings
        self._ledger = ledger
        self._language = language or "ta"
        self._connect = connect or _default_connect
        self._url = url
        self._ws = None
        self._session_id: str | None = None
        self._audio_bytes = 0
        self._cost_logged = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def audio_bytes(self) -> int:
        return self._audio_bytes

    async def start(self) -> str:
        self._ledger.check()
        self._ws = await self._connect(self._url)
        handshake = build_handshake(self._settings.model_api_key, self._language)
        payload = json.dumps(handshake)
        # Never log the payload: it carries the key.
        await self._ws.send(payload)
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise RealtimeError("realtime handshake got a bad reply") from exc
        err = _error_text(data) if isinstance(data, dict) else None
        if err is not None:
            raise RealtimeError(f"realtime handshake failed: {err}")
        session = data.get("sessionId") if isinstance(data, dict) else None
        if not session:
            raise RealtimeError("realtime handshake got no session id")
        self._session_id = str(session)
        _log.info("realtime session started")
        return self._session_id

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise RealtimeError("realtime session is not started")
        data = bytes(chunk)
        if not data:
            return
        await self._ws.send(data)
        self._audio_bytes += len(data)

    async def end(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "endStream"}))
        finally:
            self._log_cost()

    async def events(self):
        """Yield parsed JSON events until the server closes the stream."""
        if self._ws is None:
            raise RealtimeError("realtime session is not started")
        while True:
            try:
                raw = await self._ws.recv()
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code in (None, 1000, 1001):
                    # Normal close, or a fake signalling the end.
                    name = type(exc).__name__.lower()
                    if code is None and "closed" not in name and "close" not in name:
                        raise RealtimeError(
                            "live transcription stopped") from exc
                    return
                raise RealtimeError(
                    f"live transcription stopped (code {code})") from exc
            if raw is None:
                return
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            err = _error_text(data)
            if err is not None:
                raise RealtimeError(f"live transcription failed: {err}")
            yield data

    def _log_cost(self) -> None:
        if self._cost_logged:
            return
        self._cost_logged = True
        seconds = self._audio_bytes // BYTES_PER_SECOND
        if seconds <= 0:
            return
        usd = seconds / 3600 * REALTIME_USD_PER_HOUR
        self._ledger.add("meta", VOICE_MODEL, usd, "realtime_asr")

    async def close(self) -> None:
        self._log_cost()
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc_info):
        await self.close()
        return False
