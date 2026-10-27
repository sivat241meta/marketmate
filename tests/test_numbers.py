from decimal import Decimal

import pytest

from app.pipeline.numbers import find_numbers, parse_number


@pytest.mark.parametrize("said,val", [
    ("18", 18),
    ("18.50", Decimal("18.50")),
    ("eighteen", 18),
    ("eighty", 80),
    ("twenty five", 25),
    ("one hundred twenty", 120),
    ("pathinettu", 18),
    ("padhinettu", 18),
    ("பதினெட்டு", 18),
    ("enbathu", 80),
    ("எண்பது", 80),
    ("irupathu anju", 25),
    ("irupathanju", 25),
    ("nooru", 100),
    ("நூறு", 100),
    ("muppathu", 30),
])
def test_parse_number(said, val):
    assert parse_number(said) == val


def test_find_numbers_kinds():
    assert find_numbers("thakkali kilo pathinettu, vengayam 25") == [
        (18, "tamil"), (25, "digits")]


def test_find_numbers_english_kind():
    assert find_numbers("small onion forty rupees")[0] == (40, "english")


def test_live_transcript_spellings():
    assert parse_number("padinettu") == 18
    assert parse_number("pathinaindu") == 15


def test_no_unit_tens_compound():
    assert find_numbers("தேங்காய்ஒன்னுமுப்பதரூபாய்") == [(1, "tamil"), (30, "tamil")]


def test_english_no_unit_tens_compound():
    assert find_numbers("one thirty") == [(1, "english"), (30, "english")]


def test_tens_unit_compound_still_combines():
    assert find_numbers("muppathu onnu") == [(31, "tamil")]
    assert find_numbers("one hundred twenty") == [(120, "english")]


@pytest.mark.parametrize("said,val", [
    ("முப்பத்தைந்து", 35),
    ("இருபத்தைந்து", 25),
    ("நாற்பத்தைந்து", 45),
    ("எழுபத்தைந்து", 75),
    ("embadhu", 80),
    ("enpathu", 80),
    ("pathinanju", 15),
    ("pathinaindhu", 15),
    ("nalupathu", 40),
    ("naarpathu", 40),
    ("aimbathu", 50),
    ("ambathu", 50),
    ("அம்பது", 50),
])
def test_parse_number_reviewer_spellings(said, val):
    assert parse_number(said) == val


def test_potato_correction_sentence():
    text = "உருளைக்கிழங்கு கிலோ முப்பது ரூபாய். இல்ல இல்ல, முப்பத்தைந்து ரூபாய்."
    assert find_numbers(text) == [(30, "tamil"), (35, "tamil")]


@pytest.mark.parametrize("said,val", [
    ("பதினைஞ்சு", 15),
    ("இருவது", 20),
    ("இருவத்தஞ்சு", 25),
    ("நாப்பது", 40),
    ("அறுவது", 60),
    ("எழுவது", 70),
    ("எம்பது", 80),
    ("iruvathu", 20),
    ("naappathu", 40),
    ("aruvathu", 60),
    ("ezhuvathu", 70),
    ("embathu", 80),
    ("நூற்றி அம்பது", 150),
    ("நூத்தி அம்பது", 150),
    ("நூற்று அம்பது", 150),
    ("noothi ambathu", 150),
    ("nootri ambathu", 150),
])
def test_parse_number_spoken_tamil(said, val):
    assert parse_number(said) == val
    assert find_numbers(said) == [(val, "tamil")]


def test_english_hundreds_before_currency():
    assert find_numbers("one fifty rupees") == [(150, "english")]
    assert find_numbers("two twenty rupees") == [(220, "english")]
    assert find_numbers("one thirty") == [(1, "english"), (30, "english")]


def test_digits_stuck_to_text():
    assert find_numbers("Rs.40/kg, ₹25 per kilo, 2.5kg, 1,200 rupees") == [
        (40, "digits"), (25, "digits"), (Decimal("2.5"), "digits"), (1200, "digits")]
