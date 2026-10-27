import json
from pathlib import Path

import pytest

from app.config import load_settings
from app.costs import CostLedger
from app.models import Transcript, Turn
from app.pipeline.extract import (
    build_extract_messages,
    extract_items,
    parse_extract_json,
)
from app.pipeline.names import CANONICAL_NAMES

CANNED = {"items": [{
    "name_spoken": "bengaluru thakkali",
    "name_en": "tomato",
    "variety": "bengaluru",
    "prices": [{"said": "kilo pathinettu", "price": 18, "per_amount": 1, "unit": "kg"}],
    "range_said": False,
    "qty_said": "40 kilo",
    "qty": 40,
    "qty_unit": "kg",
    "turn_ids": [3],
    "quote": "bengaluru thakkali kilo pathinettu",
}]}

CANNED_NO_PRICE = {"items": [{
    "name_spoken": "thakkali",
    "name_en": "tomato",
    "variety": None,
    "prices": [{"said": "kilo", "price": None, "per_amount": 1, "unit": "kg"}],
    "range_said": False,
    "qty_said": None,
    "qty": None,
    "qty_unit": None,
    "turn_ids": [1],
    "quote": "thakkali kilo",
}]}

CANNED_BAD_TURN = {"items": [{
    "name_spoken": "thakkali",
    "name_en": "tomato",
    "variety": None,
    "prices": [{"said": "kilo pathinettu", "price": 18, "per_amount": 1, "unit": "kg"}],
    "range_said": False,
    "qty_said": None,
    "qty": None,
    "qty_unit": None,
    "turn_ids": [99],
    "quote": "bengaluru thakkali kilo pathinettu",
}]}

CANNED_LIVE = {"items": [
    {"name_spoken": "thakkali", "name_en": "tomato", "variety": "bengaluru",
     "prices": [{"said": "kilo eighteen", "price": 18, "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": "forty kilo", "qty": 40, "qty_unit": "kg",
     "turn_ids": [1], "quote": "Bangalore thakkali kilo eighteen rupees"},
    {"name_spoken": "big onion", "name_en": "onion", "variety": None,
     "prices": [{"said": "twenty five rupees per kilo", "price": 25,
                 "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [1], "quote": "big onion twenty five rupees per kilo"},
    {"name_spoken": "chinna vengayam", "name_en": "small onion", "variety": None,
     "prices": [{"said": "kilo forty", "price": 40, "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [1], "quote": "chinna vengayam kilo forty rupees"},
    {"name_spoken": "urulaikizhangu", "name_en": "potato", "variety": None,
     "prices": [{"said": "kilo thirty", "price": 30, "per_amount": 1, "unit": "kg"},
                {"said": "thirty five", "price": 35, "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [1],
     "quote": "urulaikizhangu kilo thirty rupees இல்ல இல்ல thirty five rupees"},
]}


@pytest.fixture
def transcript_3_turns():
    return Transcript(
        text="three turns",
        duration_ms=9000,
        turns=[
            Turn(id=1, start_ms=0, end_ms=3000, text="thakkali kilo pathinettu"),
            Turn(id=2, start_ms=3000, end_ms=6000, text="vengayam kilo twenty five"),
            Turn(id=3, start_ms=6000, end_ms=9000,
                 text="bengaluru thakkali kilo pathinettu"),
        ],
    )


@pytest.fixture
def live_transcript():
    from app.meta.transcribe import transcript_from_json

    data = json.loads(Path("tests/fixtures/transcribe_live_mixed.json").read_text())
    return transcript_from_json(data)


def test_parse_builds_proof_times(transcript_3_turns):
    items = parse_extract_json(CANNED, transcript_3_turns)
    assert items[0].proof.start_ms == transcript_3_turns.turns[2].start_ms
    assert items[0].proof.end_ms == transcript_3_turns.turns[2].end_ms


def test_name_ta_from_canonical(transcript_3_turns):
    assert parse_extract_json(CANNED, transcript_3_turns)[0].name_ta == "தக்காளி"
    assert CANONICAL_NAMES["tomato"] == "தக்காளி"


def test_null_price_stays_none(transcript_3_turns):
    assert parse_extract_json(CANNED_NO_PRICE, transcript_3_turns)[0].price_lines[0].price is None


def test_turn_ids_must_exist(transcript_3_turns):
    items = parse_extract_json(CANNED_BAD_TURN, transcript_3_turns)
    assert len(items) == 1
    assert items[0].proof.start_ms == transcript_3_turns.turns[2].start_ms
    assert items[0].proof.end_ms == transcript_3_turns.turns[2].end_ms


def test_prompt_lists_turns_with_ids(transcript_3_turns):
    assert "[3]" in build_extract_messages(transcript_3_turns)[-1]["content"]


def test_live_mixed_turn_shared_quotes(live_transcript):
    items = parse_extract_json(CANNED_LIVE, live_transcript)
    assert [item.name_en for item in items] == ["tomato", "onion", "small onion", "potato"]
    turn_text = live_transcript.turns[0].text
    for item in items:
        assert item.proof.turn_ids == [1]
        assert item.proof.quote and item.proof.quote in turn_text
        assert item.proof.start_ms == live_transcript.turns[0].start_ms
    assert "இல்ல" in items[3].proof.quote
    assert items[0].name_ta == "தக்காளி"
    assert items[2].name_ta == "சின்ன வெங்காயம்"


def test_extract_items_wires_chat_json(monkeypatch, transcript_3_turns, tmp_path):
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["messages"] = messages
        return CANNED

    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat_json)
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    items = extract_items(transcript_3_turns, ledger=ledger, settings=settings)
    assert [item.name_en for item in items] == ["tomato"]
    assert "[3]" in seen["messages"][-1]["content"]
