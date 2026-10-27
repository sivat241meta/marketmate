import json
from pathlib import Path

import pytest
from httpx import Response

from app.config import load_settings
from app.costs import CostLedger
from app.meta.transcribe import transcribe_wav, transcript_from_json
from app.models import Turn

_TRANSCRIBE_URL = "https://api.meta.ai/v1/asr/transcribe"
_FIXTURE = json.loads(Path("tests/fixtures/transcribe_clip1.json").read_text())


@pytest.fixture
def ledger(tmp_path):
    return CostLedger(tmp_path / "c.db", 100.0)


@pytest.fixture
def settings():
    return load_settings({"MODEL_API_KEY": "k"})


def test_parse_fixture_turns():
    t = transcript_from_json(_FIXTURE)
    assert t.turns and all(x.end_ms >= x.start_ms for x in t.turns)


def test_empty_turns_become_one_turn():
    t = transcript_from_json({"transcript": "thakkali 18", "audioDurationMs": 4000, "turns": []})
    assert t.turns == [Turn(1, 0, 4000, "thakkali 18")]


def test_null_turns_become_one_turn():
    t = transcript_from_json(
        {"transcript": "thakkali 18", "audioDurationMs": 4000, "turns": None})
    assert t.turns == [Turn(1, 0, 4000, "thakkali 18")]


def test_request_part_uses_endpointing(respx_mock, ledger, settings, tmp_path):
    respx_mock.post(_TRANSCRIBE_URL).mock(return_value=Response(200, json=_FIXTURE))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"fakewav")
    transcribe_wav(wav, keywords=["thakkali", "tomato"], ledger=ledger, settings=settings)
    body = respx_mock.calls[0].request.content
    assert b'"mode": "ENDPOINTING"' in body
    assert b'"languageBias": ["Tamil", "English"]' in body
    assert b"thakkali" in body and b"tomato" in body
    assert b"application/json" in body


def test_voice_cost_logged(respx_mock, ledger, settings, tmp_path):
    body = {"transcript": "thakkali 18", "audioDurationMs": 3_600_000, "turns": []}
    respx_mock.post(_TRANSCRIBE_URL).mock(return_value=Response(200, json=body))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"fakewav")
    t = transcribe_wav(wav, keywords=["thakkali"], ledger=ledger, settings=settings)
    assert ledger.today_usd("meta") == pytest.approx(0.18)
    assert t.turns == [Turn(1, 0, 3_600_000, "thakkali 18")]
