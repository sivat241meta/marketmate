from decimal import Decimal

import pytest

from app.models import PriceLine
from app.pipeline.units import convert, normalise_unit, parse_amount, rate


@pytest.mark.parametrize("said,amt", [
    ("kaal kilo", (250, "g")),
    ("arai kilo", (500, "g")),
    ("1 kilo", (1, "kg")),
    ("கிலோ", (1, "kg")),
    ("dozen", (1, "dozen")),
    ("4 pieces", (4, "piece")),
    ("oru kattu", (1, "bunch")),
])
def test_parse_amount(said, amt):
    assert parse_amount(said) == (Decimal(amt[0]), amt[1])


def test_rate_quarter_kilo():
    assert rate(PriceLine(Decimal(15), Decimal(250), "g")) == (Decimal(60), "kg")


def test_rate_dozen_per_piece():
    assert rate(PriceLine(Decimal(60), Decimal(1), "dozen")) == (Decimal(5), "piece")


def test_rate_missing_price():
    assert rate(PriceLine(None, Decimal(1), "kg")) is None


@pytest.mark.parametrize("said,unit", [
    ("kilo", "kg"),
    ("KILOS", "kg"),
    ("grams", "g"),
    ("pieces", "piece"),
    ("dozens", "dozen"),
    ("kattu", "bunch"),
    ("packets", "packet"),
    ("litre", None),
])
def test_normalise_unit(said, unit):
    assert normalise_unit(said) == unit


def test_convert_weights():
    assert convert(Decimal(2), "kg", "g") == Decimal(2000)
    assert convert(Decimal(500), "g", "kg") == Decimal("0.5")


def test_convert_piece_dozen():
    assert convert(Decimal(2), "dozen", "piece") == Decimal(24)
    assert convert(Decimal(24), "piece", "dozen") == Decimal(2)


def test_convert_unknown():
    assert convert(Decimal(1), "kg", "piece") is None
