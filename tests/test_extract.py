import json
from pathlib import Path

import pytest

from app.config import load_settings
from app.costs import CostLedger
from app.models import Transcript, Turn
from app.pipeline.checks import check_item
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


def test_name_local_from_canonical(transcript_3_turns):
    assert parse_extract_json(CANNED, transcript_3_turns)[0].name_local == "தக்காளி"
    assert CANONICAL_NAMES["tomato"] == "தக்காளி"


def test_null_items_means_no_items(transcript_3_turns):
    assert parse_extract_json({"items": None}, transcript_3_turns) == []


def test_null_prices_means_no_price_lines(transcript_3_turns):
    data = {"items": [dict(CANNED["items"][0], prices=None)]}
    (item,) = parse_extract_json(data, transcript_3_turns)
    assert item.name_en == "tomato"
    assert item.price_lines == []


def test_null_turn_ids_falls_back_to_quote(transcript_3_turns):
    data = {"items": [dict(CANNED["items"][0], turn_ids=None)]}
    (item,) = parse_extract_json(data, transcript_3_turns)
    assert item.proof.turn_ids == []
    assert item.proof.start_ms == transcript_3_turns.turns[2].start_ms
    assert item.proof.end_ms == transcript_3_turns.turns[2].end_ms


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
    turn = live_transcript.turns[0]
    turn_text = turn.text
    # Task 156: one turn with many items is split, so each item keeps
    # only its own words, with clip times by character proportion.
    for item in items:
        assert item.proof.turn_ids == [1]
        assert item.proof.quote and item.proof.quote in turn_text
        assert turn.start_ms <= item.proof.start_ms <= item.proof.end_ms <= turn.end_ms
    starts = [item.proof.start_ms for item in items]
    assert starts == sorted(starts)
    assert "இல்ல" in items[3].proof.quote
    assert items[0].name_local == "தக்காளி"
    assert items[2].name_local == "சின்ன வெங்காயம்"


def test_variety_lowercased_english(transcript_3_turns):
    data = {"items": [dict(CANNED["items"][0], variety="Bengaluru")]}
    assert parse_extract_json(data, transcript_3_turns)[0].variety == "bengaluru"


def test_prompt_says_variety_english_letters(transcript_3_turns):
    content = build_extract_messages(transcript_3_turns)[-1]["content"]
    assert "English letters" in content
    assert "bengaluru" in content


def test_unit_from_earlier_price_backfills(transcript_3_turns):
    data = {"items": [{
        "name_spoken": "urulaikizhangu",
        "name_en": "potato",
        "variety": None,
        "prices": [{"said": "kilo thirty", "price": 30, "per_amount": 1, "unit": "kg"},
                   {"said": "thirty five", "price": 35,
                    "per_amount": None, "unit": None}],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [3],
        "quote": "urulaikizhangu kilo thirty rupees thirty five rupees",
    }]}
    items = parse_extract_json(data, transcript_3_turns)
    second = items[0].price_lines[1]
    assert (second.price, second.per_amount, second.unit) == (35, 1, "kg")
    backfill = next(f for f in items[0].flags if f.code == "UNIT_FROM_EARLIER")
    assert backfill.blocking is False
    two = next(f for f in check_item(items[0], {}) if f.code == "TWO_PRICES")
    assert two.options == ["30", "35"]


def test_extract_items_wires_chat_json(monkeypatch, transcript_3_turns, tmp_path):
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return CANNED

    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat_json)
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    items = extract_items(transcript_3_turns, ledger=ledger, settings=settings)
    assert [item.name_en for item in items] == ["tomato"]
    assert "[3]" in seen["messages"][-1]["content"]
    assert seen["kwargs"]["reasoning_effort"] == "low"


def transcript_14_turns():
    return Transcript(
        text="fourteen turns",
        duration_ms=42000,
        turns=[
            Turn(id=i, start_ms=(i - 1) * 3000, end_ms=i * 3000,
                 text=f"item{i} kilo eighteen")
            for i in range(1, 15)
        ],
    )


def test_extract_items_chunks_long_transcripts(monkeypatch, tmp_path):
    calls = []

    def fake_chat_json(messages, **kwargs):
        calls.append(messages[-1]["content"])
        group = len(calls)
        return {"items": [{
            "name_spoken": f"item{group}",
            "name_en": "other",
            "variety": None,
            "prices": [{"said": "kilo eighteen", "price": 18,
                        "per_amount": 1, "unit": "kg"}],
            "range_said": False,
            "qty_said": None,
            "qty": None,
            "qty_unit": None,
            "turn_ids": [(group - 1) * 6 + 1],
            "quote": f"item{(group - 1) * 6 + 1} kilo eighteen",
        }]}

    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat_json)
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    items = extract_items(transcript_14_turns(), ledger=ledger, settings=settings)
    assert len(calls) == 3
    assert "[1]" in calls[0] and "[6]" in calls[0] and "[7]" not in calls[0]
    assert "[7]" in calls[1] and "[12]" in calls[1] and "[13]" not in calls[1]
    assert "[13]" in calls[2] and "[14]" in calls[2]
    assert [item.name_spoken for item in items] == ["item1", "item2", "item3"]
