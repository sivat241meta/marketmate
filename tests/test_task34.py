"""Task 34: Tamil spaced compounds, more produce names, softer unit check.

From the owner's second real Tamil video (kitchen/fridge walk-through).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import DraftItem, PriceLine, Proof, Transcript, Turn
from app.pipeline.checks import WEIGHT_ITEMS, check_item
from app.pipeline.names import CANONICAL_NAMES, keywords_for
from app.pipeline.numbers import find_numbers, parse_number


def _draft(quote, price, per_amount=1, unit="kg", name_en="tomato"):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit, "")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0),
    )


# --- 1a. Tamil-script tens combining forms + ones ---

TAMIL_COMBINING = [
    ("இருபத்தி", 20), ("இருவத்தி", 20),
    ("முப்பத்தி", 30), ("முப்பத்து", 30),
    ("நாப்பத்தி", 40), ("நாற்பத்தி", 40), ("நாப்பத்து", 40),
    ("ஐம்பத்தி", 50), ("அம்பத்தி", 50), ("ஐம்பத்து", 50),
    ("அறுபத்தி", 60), ("அறுவத்தி", 60),
    ("எழுபத்தி", 70), ("எழுவத்தி", 70),
    ("எண்பத்தி", 80), ("எம்பத்தி", 80),
    ("தொண்ணூத்தி", 90), ("தொண்ணூற்றி", 90),
]

ROMAN_COMBINING = [
    ("irubathi", 20), ("muppathi", 30), ("naapathi", 40),
    ("aimbathi", 50), ("ambathi", 50),
    ("arubathi", 60), ("ezhubathi", 70),
    ("enbathi", 80), ("embathi", 80), ("thonnoothi", 90),
]

TAMIL_ONES = [
    ("ஒன்னு", 1), ("ரெண்டு", 2), ("மூணு", 3), ("நாலு", 4),
    ("அஞ்சு", 5), ("ஆறு", 6), ("ஏழு", 7), ("எட்டு", 8),
    ("ஒன்பது", 9),
]

ROMAN_ONES = [
    ("onnu", 1), ("rendu", 2), ("moonu", 3), ("naalu", 4),
    ("anju", 5), ("aaru", 6), ("ezhu", 7), ("ettu", 8),
    ("onbathu", 9),
]


@pytest.mark.parametrize("combining,tens", TAMIL_COMBINING)
def test_tamil_combining_form_with_ezhu(combining, tens):
    assert parse_number(f"{combining} ஏழு") == tens + 7
    assert find_numbers(f"kilo {combining} ஏழு ரூபா") == [(tens + 7, "tamil")]


@pytest.mark.parametrize("combining,tens", ROMAN_COMBINING)
def test_roman_combining_form_with_ezhu(combining, tens):
    assert parse_number(f"{combining} ezhu") == tens + 7
    assert find_numbers(f"kilo {combining} ezhu rupa") == [(tens + 7, "tamil")]


@pytest.mark.parametrize("one_word,one", TAMIL_ONES)
def test_tamil_every_ones_with_muppathi(one_word, one):
    assert parse_number(f"முப்பத்தி {one_word}") == 30 + one
    assert find_numbers(f"முப்பத்தி {one_word}") == [(30 + one, "tamil")]


@pytest.mark.parametrize("one_word,one", ROMAN_ONES)
def test_roman_every_ones_with_muppathi(one_word, one):
    assert parse_number(f"muppathi {one_word}") == 30 + one
    assert find_numbers(f"muppathi {one_word}") == [(30 + one, "tamil")]


@pytest.mark.parametrize("tens_word,tens", [
    ("இருபத்தி", 20), ("முப்பத்தி", 30), ("நாப்பத்தி", 40),
    ("ஐம்பத்தி", 50), ("அறுபத்தி", 60), ("எழுபத்தி", 70),
    ("எண்பத்தி", 80), ("தொண்ணூத்தி", 90),
])
@pytest.mark.parametrize("one_word,one", TAMIL_ONES)
def test_tamil_every_tens_every_ones(tens_word, tens, one_word, one):
    assert parse_number(f"{tens_word} {one_word}") == tens + one


@pytest.mark.parametrize("tens_word,tens", [
    ("irubathi", 20), ("muppathi", 30), ("naapathi", 40),
    ("aimbathi", 50), ("arubathi", 60), ("ezhubathi", 70),
    ("enbathi", 80), ("thonnoothi", 90),
])
@pytest.mark.parametrize("one_word,one", ROMAN_ONES)
def test_roman_every_tens_every_ones(tens_word, tens, one_word, one):
    assert parse_number(f"{tens_word} {one_word}") == tens + one


# --- 1b. hundreds compounds with a space ---

@pytest.mark.parametrize("said,val", [
    ("நூற்றி இருபது", 120),
    ("நூத்தி இருபது", 120),
    ("நூற்றி முப்பத்தி ஏழு", 137),
    ("இருநூறு", 200),
    ("இருநூத்தி ஐம்பது", 250),
])
def test_hundreds_compounds(said, val):
    assert parse_number(said) == val
    assert find_numbers(said) == [(val, "tamil")]


def test_hundred_compound_keeps_fifty_eighty_sound_alike():
    item = _draft("நூற்றி எம்பது ரூபாய்", 180, name_en="ginger")
    flag = next(f for f in check_item(item, {}) if f.code == "SOUND_ALIKE")
    assert flag.options == ["150", "180"]


# --- 1c. transcript from the second real video ---

TURN1 = ("அச்சா, இது beetroot, kilo முப்பத்தி ஏழு ரூபா, இது தக்காளி "
         "அரை கிலோ பதினெட்டு பதினெட்டு ரூபா உங்களுக்கு")
TURN2 = "இது வாழைத்தண்டு கிலோ வந்து இதுல ஒரு பீஸ் வந்து முப்பது ரூபா"
TURN3 = ("இது மாதுளை கிலோ எண்பத்தேழு ரூபா, அது சாத்துக்குடி கிலோ "
         "முப்பத்தி ஆறு ரூபா, கீழ இருக்கு பாரு apple அது வந்து "
         "அஞ்சு பீஸ் நூறு ரூபா")


def test_transcript_beetroot_37_no_not_heard():
    item = _draft(TURN1, 37, name_en="beetroot")
    assert "NOT_HEARD" not in [f.code for f in check_item(item, {})]


def test_transcript_sweet_lime_36_no_not_heard():
    item = _draft(TURN3, 36, name_en="sweet lime")
    assert "NOT_HEARD" not in [f.code for f in check_item(item, {})]


def test_transcript_all_prices_heard():
    assert find_numbers(TURN1) == [
        (37, "tamil"), (18, "tamil"), (18, "tamil")]
    assert find_numbers(TURN2) == [(1, "tamil"), (30, "tamil")]
    assert find_numbers(TURN3) == [
        (87, "tamil"), (36, "tamil"), (5, "tamil"), (100, "tamil")]
    cases = [
        (_draft(TURN1, 37, name_en="beetroot"), "beetroot 37"),
        (_draft(TURN1, 18, Decimal("0.5"), "kg", "tomato"), "tomato 18"),
        (_draft(TURN2, 30, 1, "piece", "banana stem"), "banana stem 30"),
        (_draft(TURN3, 87, name_en="pomegranate"), "pomegranate 87"),
        (_draft(TURN3, 36, name_en="sweet lime"), "sweet lime 36"),
        (_draft(TURN3, 100, 5, "piece", "apple"), "apple 100"),
    ]
    for item, label in cases:
        assert "NOT_HEARD" not in [f.code for f in check_item(item, {})], label


# --- 2a. canonical produce list ---

def test_canonical_names_has_video_items():
    assert CANONICAL_NAMES["banana stem"] == "வாழைத்தண்டு"
    assert CANONICAL_NAMES["banana flower"] == "வாழைப்பூ"
    assert CANONICAL_NAMES["sweet lime"] == "சாத்துக்குடி"
    assert CANONICAL_NAMES["beetroot"] == "பீட்ரூட்"
    assert CANONICAL_NAMES["pomegranate"] == "மாதுளை"
    assert CANONICAL_NAMES["raw banana"] == "வாழைக்காய்"
    assert CANONICAL_NAMES["guava"] == "கொய்யா"
    assert CANONICAL_NAMES["papaya"] == "பப்பாளி"
    assert CANONICAL_NAMES["lemon"] == "எலுமிச்சை"
    assert CANONICAL_NAMES["orange"] == "ஆரஞ்சு"
    assert CANONICAL_NAMES["grapes"] == "திராட்சை"
    assert CANONICAL_NAMES["mango"] == "மாம்பழம்"
    assert CANONICAL_NAMES["sapota"] == "சப்போட்டா"
    assert CANONICAL_NAMES["watermelon"] == "தர்பூசணி"
    assert CANONICAL_NAMES["jackfruit"] == "பலாப்பழம்"
    assert CANONICAL_NAMES["pineapple"] == "அன்னாசி"
    assert CANONICAL_NAMES["radish"] == "முள்ளங்கி"
    assert CANONICAL_NAMES["carrot"] == "கேரட்"
    assert CANONICAL_NAMES["cabbage"] == "முட்டைகோஸ்"
    assert CANONICAL_NAMES["cauliflower"] == "காலிஃபிளவர்"
    assert CANONICAL_NAMES["sweet potato"] == "சர்க்கரைவள்ளிக்கிழங்கு"
    assert CANONICAL_NAMES["green chilli"] == "பச்சை மிளகாய்"
    assert CANONICAL_NAMES["apple"] == "ஆப்பிள்"


def test_new_tamil_names_only_in_tamil_keywords():
    assert "வாழைத்தண்டு" in keywords_for("ta")
    assert "சாத்துக்குடி" in keywords_for("ta")
    assert "வாழைப்பூ" in keywords_for("ta")
    for code in ("en", "hi", "vi", "fr"):
        words = keywords_for(code)
        assert "banana stem" in words
        assert "sweet lime" in words
        for word in words:
            assert not any("\u0b80" <= ch <= "\u0bff" for ch in word), (code, word)


# --- 2b. extraction keeps real names ---

def _transcript(text):
    return Transcript(text=text, duration_ms=1000, turns=[
        Turn(id=1, start_ms=0, end_ms=1000, text=text)])


def test_extract_keeps_banana_stem_and_sweet_lime():
    from app.pipeline.extract import parse_extract_json

    data = {"items": [
        {"name_spoken": "vazhaithandu", "name_en": "banana stem",
         "variety": None,
         "prices": [{"said": "muppathu", "price": 30, "per_amount": 1,
                    "unit": "piece"}],
         "range_said": False, "qty": None, "qty_unit": None,
         "turn_ids": [1], "quote": TURN2},
        {"name_spoken": "saathukudi", "name_en": "sweet lime",
         "variety": None,
         "prices": [{"said": "muppathi aaru", "price": 36, "per_amount": 1,
                    "unit": "kg"}],
         "range_said": False, "qty": None, "qty_unit": None,
         "turn_ids": [1], "quote": TURN3},
    ]}
    items = parse_extract_json(data, _transcript(TURN2 + " " + TURN3))
    assert [item.name_en for item in items] == ["banana stem", "sweet lime"]
    assert items[0].name_local == "வாழைத்தண்டு"
    assert items[1].name_local == "சாத்துக்குடி"


def test_extract_plain_english_name_when_not_canonical():
    from app.pipeline.extract import parse_extract_json

    data = {"items": [{
        "name_spoken": "dragon fruit", "name_en": "dragon fruit",
        "variety": None,
        "prices": [{"said": "fifty", "price": 50, "per_amount": 1,
                    "unit": "piece"}],
        "range_said": False, "qty": None, "qty_unit": None,
        "turn_ids": [1], "quote": "dragon fruit fifty"}]}
    (item,) = parse_extract_json(data, _transcript("dragon fruit fifty"))
    assert item.name_en == "dragon fruit"
    assert item.name_en != "other"


def test_extract_other_only_when_unnamed():
    from app.pipeline.extract import parse_extract_json

    data = {"items": [{
        "name_spoken": "", "name_en": "other", "variety": None,
        "prices": [{"said": "fifty", "price": 50, "per_amount": 1,
                    "unit": "kg"}],
        "range_said": False, "qty": None, "qty_unit": None,
        "turn_ids": [1], "quote": "fifty"}]}
    (item,) = parse_extract_json(data, _transcript("fifty"))
    assert item.name_en == "other"


def test_extract_prompt_allows_plain_english_names():
    from app.pipeline.extract import build_extract_messages

    content = build_extract_messages(_transcript("t"))[-1]["content"]
    assert "banana stem" in content
    assert "sweet lime" in content
    assert "plain English name" in content
    assert "other" in content


# --- 3. softer unit check ---

PIECE_OK = ["apple", "orange", "sweet lime", "pomegranate", "mango",
            "coconut", "banana stem", "papaya", "pineapple", "watermelon",
            "jackfruit", "guava", "lemon"]


def test_piece_common_items_not_weight_items():
    for name in PIECE_OK:
        assert name not in WEIGHT_ITEMS, name


@pytest.mark.parametrize("name", PIECE_OK)
def test_piece_common_items_have_no_unit_odd(name):
    item = _draft(f"{name} ten per piece", 10, 1, "piece", name)
    assert "UNIT_ODD" not in [f.code for f in check_item(item, {})]


def test_unit_odd_is_gentle_and_non_blocking():
    item = _draft("tomato ten per piece", 10, 1, "piece", "tomato")
    flag = next(f for f in check_item(item, {}) if f.code == "UNIT_ODD")
    assert flag.blocking is False
    assert flag.message == "usually sold by weight - is per piece right?"
