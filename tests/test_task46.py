"""Task 46: one price said several times is one price (failing first).

Real shop video (Tamil, 18 s): the seller repeats 60 three times for
emphasis and the item came out with three identical lines, three
UNIT_MISSING flags and a blocking TWO_PRICES flag. That is wrong.

No network: Meta is faked with canned extraction JSON fed to
parse_extract_json; checks run in Tamil (parsed locally, no ledger).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, PriceLine, Proof, Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.extract import merge_repeated_prices, parse_extract_json

QUOTE_60X3 = (
    "ujjala அறுபது அறுபது ரூபா vari Krishnagiri vari வந்து அறுபது ரூபா"
)


def _transcript(*texts: str) -> Transcript:
    turns = [
        Turn(id=i + 1, start_ms=i * 3000, end_ms=(i + 1) * 3000, text=text)
        for i, text in enumerate(texts)
    ]
    return Transcript(
        text=" ".join(texts), duration_ms=len(texts) * 3000, turns=turns)


def _item(canned: dict, transcript: Transcript) -> DraftItem:
    (item,) = parse_extract_json(canned, transcript, language="ta")
    merge_repeated_prices(item)
    return item


def test_three_identical_sixty_is_one_line():
    canned = {"items": [{
        "name_spoken": "ujjala",
        "name_en": "onion",
        "variety": "krishnagiri",
        "prices": [
            {"said": "அறுபது", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "அறுபது ரூபா", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "அறுபது ரூபா", "price": 60,
             "per_amount": None, "unit": None},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": QUOTE_60X3,
    }]}
    item = _item(canned, _transcript(QUOTE_60X3))
    assert len(item.price_lines) == 1
    (line,) = item.price_lines
    assert line.price == Decimal(60)
    assert line.per_amount is None
    assert line.unit is None
    assert line.said == "அறுபது"
    codes = [f.code for f in check_item(item, {}, language="ta")]
    assert codes.count("UNIT_MISSING") == 1
    assert "TWO_PRICES" not in codes


def test_sixty_and_eighty_still_two_prices():
    quote = "thakkali அறுபது எண்பது"
    canned = {"items": [{
        "name_spoken": "thakkali",
        "name_en": "tomato",
        "variety": None,
        "prices": [
            {"said": "அறுபது", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "எண்பது", "price": 80,
             "per_amount": None, "unit": None},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": quote,
    }]}
    item = _item(canned, _transcript(quote))
    assert len(item.price_lines) == 2
    codes = [f.code for f in check_item(item, {}, language="ta")]
    assert "TWO_PRICES" in codes


def test_sixty_and_eighty_with_unit_still_two_prices():
    quote = "tomato kilo அறுபது எண்பது"
    canned = {"items": [{
        "name_spoken": "thakkali",
        "name_en": "tomato",
        "variety": None,
        "prices": [
            {"said": "kilo அறுபது", "price": 60,
             "per_amount": 1, "unit": "kg"},
            {"said": "எண்பது", "price": 80,
             "per_amount": 1, "unit": "kg"},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": quote,
    }]}
    item = _item(canned, _transcript(quote))
    assert len(item.price_lines) == 2
    codes = [f.code for f in check_item(item, {}, language="ta")]
    assert "TWO_PRICES" in codes


def test_kilo_sixty_plus_bare_sixty_merges_to_known():
    quote = "ஒரு கிலோ அறுபது அறுபது ரூபா"
    canned = {"items": [{
        "name_spoken": "thakkali",
        "name_en": "tomato",
        "variety": None,
        "prices": [
            {"said": "ஒரு கிலோ அறுபது", "price": 60,
             "per_amount": 1, "unit": "kg"},
            {"said": "அறுபது ரூபா", "price": 60,
             "per_amount": None, "unit": None},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": quote,
    }]}
    item = _item(canned, _transcript(quote))
    assert len(item.price_lines) == 1
    (line,) = item.price_lines
    assert line.price == Decimal(60)
    assert line.per_amount == Decimal(1)
    assert line.unit == "kg"
    codes = [f.code for f in check_item(item, {}, language="ta")]
    assert "TWO_PRICES" not in codes
    assert "UNIT_MISSING" not in codes


def test_bare_sixty_before_kilo_sixty_merges_to_known():
    quote = "அறுபது ரூபா ஒரு கிலோ அறுபது"
    canned = {"items": [{
        "name_spoken": "thakkali",
        "name_en": "tomato",
        "variety": None,
        "prices": [
            {"said": "அறுபது ரூபா", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "ஒரு கிலோ அறுபது", "price": 60,
             "per_amount": 1, "unit": "kg"},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": quote,
    }]}
    item = _item(canned, _transcript(quote))
    assert len(item.price_lines) == 1
    (line,) = item.price_lines
    assert (line.price, line.per_amount, line.unit) == (
        Decimal(60), Decimal(1), "kg")
    assert "TWO_PRICES" not in [
        f.code for f in check_item(item, {}, language="ta")]


def test_missing_beside_two_known_units_stays_for_seller():
    quote = "அறுபது ஒரு கிலோ அறுபது ஐநூறு கிராம் அறுபது"
    canned = {"items": [{
        "name_spoken": "thakkali",
        "name_en": "tomato",
        "variety": None,
        "prices": [
            {"said": "அறுபது", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "ஒரு கிலோ அறுபது", "price": 60,
             "per_amount": 1, "unit": "kg"},
            {"said": "ஐநூறு கிராம் அறுபது", "price": 60,
             "per_amount": 500, "unit": "g"},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": quote,
    }]}
    item = _item(canned, _transcript(quote))
    assert len(item.price_lines) == 3


def test_merge_keeps_first_said_and_extends_quote():
    item = DraftItem(
        name_spoken="tomato", name_local="tomato", name_en="tomato",
        variety=None,
        price_lines=[
            PriceLine(Decimal(60), None, None, "sixty rupees"),
            PriceLine(Decimal(60), None, None, "sixty bucks"),
        ],
        qty=None, qty_unit=None,
        proof=Proof(quote="tomato sixty rupees", turn_ids=[],
                    start_ms=0, end_ms=0),
    )
    merge_repeated_prices(item)
    assert len(item.price_lines) == 1
    assert item.price_lines[0].said == "sixty rupees"
    assert "sixty bucks" in item.proof.quote


def test_answer_keys_score_offline():
    from scripts.benchmark import compare_clips

    for name in ("real1.json", "testreal2.json", "synth1.json"):
        key = json.loads(
            (Path("eval/answers") / name).read_text(encoding="utf-8"))
        out = {"clip": key["clip"], "items": [
            {"name_en": entry["name_en"], "variety": entry.get("variety"),
             "price_lines": [{"price": str(entry["price"]),
                              "per_amount": str(entry["per_amount"]),
                              "unit": entry["unit"]}],
             "flags": [{"code": code, "blocking": True}
                       for code in entry.get("expect_flags", [])]}
            for entry in key["items"]
        ]}
        row = compare_clips(key, out)
        assert row["found"] == row["in_key"] == len(key["items"]), name
        assert row["exact"] == len(key["items"]), name
        assert row["missed"] == {}, name
