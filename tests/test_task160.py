"""Task 160: two fixes from the second live run of the VPS video.

The same 64 s Tamil stall video ran again with Task 157's code and Muse
Voice transcribed it differently. Broad beans "அவரக்கா கால் கிலோ கிலோ
முப்பத்தஞ்சு" (a quarter kilo for Rs.35) came out as Rs.35 / 1 kg and
passed with a green tick: the repeated "கிலோ கிலோ" lost the quarter.
And plain பூசணி came back as "பூசணி · pumpkin" when Tamil Nadu markets
call it ash gourd (yellow pumpkin is பரங்கிக்காய் / parangi /
மஞ்சள் பூசணி).

Fix 1a: a repeated unit word counts once in the unit/amount parsers.
Fix 1b: a blocking QTY_WORD_MISMATCH flag when the span says a fraction
of a unit but the line says another amount; the seller picks, the price
is never changed silently. Fix 2: plain பூசணி called "pumpkin" becomes
"ash gourd", a naming fix only. No model calls.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, PriceLine, Proof, Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.coverage import find_price_phrases
from app.pipeline.units import convert, parse_amount

QUOTE = "அவரக்கா கால் கிலோ கிலோ முப்பத்தஞ்சு"


def _draft(quote: str, price, per, unit,
           name_en: str = "broad beans",
           local: str = "அவரைக்காய்") -> DraftItem:
    return DraftItem(
        name_spoken=name_en, name_local=local, name_en=name_en, variety=None,
        price_lines=[PriceLine(
            Decimal(price), Decimal(per) if per is not None else None,
            unit, "")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0))


def _codes(item: DraftItem) -> list[str]:
    return [flag.code for flag in check_item(item, {}, language="ta")]


# --- 1a. a repeated unit word counts once -------------------------------------

def test_coverage_keeps_the_quarter_through_repeated_kilo():
    (phrase,) = find_price_phrases(QUOTE)
    assert (phrase.price, phrase.per_amount, phrase.unit) == (
        Decimal(35), Decimal("0.25"), "kg")


def test_coverage_keeps_the_half_through_repeated_kilo():
    (phrase,) = find_price_phrases("கத்தரிக்கா அரை கிலோ கிலோ இருபது ரூபா")
    assert (phrase.price, phrase.per_amount, phrase.unit) == (
        Decimal(20), Decimal("0.5"), "kg")


def test_parse_amount_repeated_unit_is_one():
    assert parse_amount("கால் கிலோ கிலோ") == (Decimal(250), "g")
    assert parse_amount("அரை கிலோ கிலோ") == (Decimal(500), "g")
    amount, unit = parse_amount("கால் கிலோ கிலோ")
    assert convert(amount, unit, "kg") == Decimal("0.25")
    amount, unit = parse_amount("அரை கிலோ கிலோ")
    assert convert(amount, unit, "kg") == Decimal("0.5")
    assert parse_amount("kilo kilo") == (Decimal(1), "kg")
    assert parse_amount("kg kg") == (Decimal(1), "kg")
    assert parse_amount("கிலோ கிலோ") == (Decimal(1), "kg")


def test_order_parse_repeated_kilo_keeps_the_fraction():
    from app.market.order_parse import parse_order
    from app.models import Item

    items = [Item(
        id=0, version_id=0, name_local="தக்காளி", name_en="tomato",
        variety=None, qty=None, qty_unit=None, photo=None, sold_out=False,
        price_lines=[PriceLine(Decimal(40), Decimal(1), "kg")],
        proof=Proof(quote="q", turn_ids=[1], start_ms=0, end_ms=1000))]
    lines, leftover = parse_order("கால் கிலோ கிலோ தக்காளி", items, "ta")
    assert leftover == []
    assert [(w.qty, w.unit) for w in lines] == [(Decimal("0.25"), "kg")]
    lines, leftover = parse_order("அரை கிலோ கிலோ தக்காளி", items, "ta")
    assert leftover == []
    assert [(w.qty, w.unit) for w in lines] == [(Decimal("0.5"), "kg")]


# --- 1b. QTY_WORD_MISMATCH ----------------------------------------------------

def test_qty_word_mismatch_blocks_and_names_both_amounts():
    item = _draft(QUOTE, 35, "1", "kg")
    flag = next(f for f in check_item(item, {}, language="ta")
                if f.code == "QTY_WORD_MISMATCH")
    assert flag.field == "per_amount"
    assert flag.blocking is True
    assert flag.message == (
        "We heard 'கால் கிலோ' (¼ kg) but the line says per 1 kg."
        " Which is right?")
    assert flag.options == ["¼ kg", "1 kg"]
    assert item.price_lines[0].price == Decimal(35)


def test_qty_word_mismatch_half_and_three_quarters():
    half = _draft("கத்தரிக்கா அரை கிலோ கிலோ இருபது ரூபா", 20, "1", "kg",
                  name_en="brinjal", local="கத்தரிக்காய்")
    flag = next(f for f in check_item(half, {}, language="ta")
                if f.code == "QTY_WORD_MISMATCH")
    assert flag.message == (
        "We heard 'அரை கிலோ' (½ kg) but the line says per 1 kg."
        " Which is right?")
    assert flag.options == ["½ kg", "1 kg"]
    three = _draft("வெண்டைக்கா முக்கால் கிலோ நாப்பது ரூபா", 40, "1", "kg",
                   name_en="okra", local="வெண்டைக்காய்")
    flag = next(f for f in check_item(three, {}, language="ta")
                if f.code == "QTY_WORD_MISMATCH")
    assert flag.message == (
        "We heard 'முக்கால் கிலோ' (¾ kg) but the line says per 1 kg."
        " Which is right?")
    assert flag.options == ["¾ kg", "1 kg"]
    assert three.price_lines[0].price == Decimal(40)


def test_qty_word_mismatch_silent_when_amounts_agree():
    assert "QTY_WORD_MISMATCH" not in _codes(_draft(QUOTE, 35, "0.25", "kg"))
    as_grams = _draft(QUOTE, 35, "250", "g")
    assert "QTY_WORD_MISMATCH" not in _codes(as_grams)
    bare = _draft("அவரக்கா கிலோ முப்பத்தஞ்சு", 35, "1", "kg")
    assert "QTY_WORD_MISMATCH" not in _codes(bare)


def test_qty_word_mismatch_skips_multi_line_items():
    item = DraftItem(
        name_spoken="beans", name_local="பீன்ஸ்", name_en="beans",
        variety="mannur",
        price_lines=[PriceLine(Decimal(35), Decimal("0.25"), "kg", ""),
                     PriceLine(Decimal(70), Decimal(1), "kg", "")],
        qty=None, qty_unit=None,
        proof=Proof(quote="beans கால் கிலோ முப்பத்தஞ்சு மன்னூர்ல "
                          "இன்னைக்கு ரேட்டு எழுபது ஒரு கிலோ",
                    turn_ids=[], start_ms=0, end_ms=0))
    assert "QTY_WORD_MISMATCH" not in _codes(item)


def test_no_qty_word_mismatch_on_existing_fixtures():
    import test_task156
    import test_task157
    from test_task136 import stall_transcript

    from app.pipeline.extract import parse_extract_json

    seen: list[DraftItem] = []
    seen.extend(test_task157.items_a())
    seen.extend(test_task157.items_b())
    seen.extend(test_task156.parsed_items())
    model_1 = json.loads((Path(test_task157.__file__).resolve().parent
                          / "fixtures" / "real_tamil_stall_1_model.json"
                          ).read_text())
    seen.extend(parse_extract_json(model_1, stall_transcript(), language="ta"))
    assert len(seen) > 40
    for item in seen:
        assert "QTY_WORD_MISMATCH" not in _codes(item), (
            item.name_en, item.proof.quote)


# --- 2. plain பூசணி is ash gourd ----------------------------------------------

def _pumpkin_item(local: str, quote: str) -> DraftItem:
    return DraftItem(
        name_spoken=local or "poosani", name_local=local, name_en="pumpkin",
        variety=None,
        price_lines=[PriceLine(Decimal(30), Decimal(1), "kg", "")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0))


def test_plain_poosani_pumpkin_becomes_ash_gourd():
    from app.pipeline.spoken import apply_spoken_name

    item = _pumpkin_item("பூசணி", "பூசணி ஒரு கிலோ முப்பது ரூபா")
    assert apply_spoken_name(item) is True
    assert item.name_en == "ash gourd"
    assert item.name_local == "பூசணி"
    assert [(line.price, line.per_amount, line.unit)
            for line in item.price_lines] == [
        (Decimal(30), Decimal(1), "kg")]


def test_poosani_word_variants_become_ash_gourd():
    from app.pipeline.spoken import apply_spoken_name

    long = _pumpkin_item("பூசணிக்காய்", "பூசணிக்காய் கிலோ நூறு ரூபா")
    assert apply_spoken_name(long) is True
    assert long.name_en == "ash gourd"
    span_only = _pumpkin_item("", "poosani ஒரு kilo 30 ரூபாய்")
    assert apply_spoken_name(span_only) is True
    assert span_only.name_en == "ash gourd"
    for item in (long, span_only):
        assert [(line.price, line.per_amount, line.unit)
                for line in item.price_lines] == [
            (Decimal(30), Decimal(1), "kg")]


def test_yellow_poosani_keeps_pumpkin():
    from app.pipeline.spoken import apply_spoken_name

    yellow = _pumpkin_item("மஞ்சள் பூசணி",
                           "மஞ்சள் பூசணி ஒரு கிலோ முப்பது ரூபா")
    assert apply_spoken_name(yellow) is False
    assert yellow.name_en == "pumpkin"
    canonical = _pumpkin_item("பரங்கிக்காய்", "பரங்கிக்காய் கிலோ நாப்பது")
    assert apply_spoken_name(canonical) is False
    assert canonical.name_en == "pumpkin"


def test_poosani_fix_end_to_end_through_extract():
    from app.pipeline.extract import parse_extract_json

    text = "பூசணி ஒரு கிலோ முப்பது ரூபா"
    transcript = Transcript(
        text=text, duration_ms=3000,
        turns=[Turn(id=1, start_ms=0, end_ms=3000, text=text)])
    model = {"items": [{
        "name_spoken": "பூசணி", "name_en": "pumpkin",
        "name_local": "பூசணி", "variety": None,
        "prices": [{"said": "ஒரு கிலோ முப்பது ரூபா", "price": 30,
                    "per_amount": 1, "unit": "kg"}],
        "range_said": False, "qty_said": None, "qty": None,
        "qty_unit": None, "turn_ids": [1], "quote": text}]}
    (item,) = parse_extract_json(model, transcript, language="ta")
    assert (item.name_local, item.name_en) == ("பூசணி", "ash gourd")
    assert [(line.price, line.per_amount, line.unit)
            for line in item.price_lines] == [
        (Decimal(30), Decimal(1), "kg")]
    assert "NAME_NOT_NEAR_PRICE" not in _codes(item)


def test_amount_option_parsing_in_the_browser():
    node = shutil.which("node")
    assert node, "node is required"
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run([node, "tests/js/review_amount_option.test.mjs"],
                          cwd=root, check=False, capture_output=True,
                          text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
