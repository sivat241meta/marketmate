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
