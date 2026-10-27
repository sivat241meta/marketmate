from __future__ import annotations

from decimal import Decimal

from app.models import PriceLine
from app.pipeline.numbers import _words, parse_number

_UNIT_WORDS: dict[str, str] = {
    "kg": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg",
    "kilograms": "kg", "கிலோ": "kg",
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "கிராம்": "g",
    "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
    "dozen": "dozen", "dozens": "dozen", "டஜன்": "dozen",
    "bunch": "bunch", "bunches": "bunch", "kattu": "bunch",
    "kathu": "bunch", "கட்டு": "bunch",
    "packet": "packet", "packets": "packet", "pack": "packet",
    "பாக்கெட்": "packet", "பொட்டலம்": "packet",
}

_G_PER_KG = Decimal(1000)
_PIECES_PER_DOZEN = Decimal(12)


def normalise_unit(said: str) -> str | None:
    """Map a spoken unit word to kg, g, piece, dozen, bunch or packet."""
    return _UNIT_WORDS.get(said.strip().lower())


_KILO_WORDS = {"kilo", "kilos", "kilogram", "kilograms", "kg", "கிலோ"}


def parse_amount(said: str) -> tuple[Decimal, str] | None:
    """Parse e.g. "kaal kilo", "1 kilo", "oru kattu" into (amount, unit)."""
    words = [w for w in _words(said) if w]
    kilo_said = any(w in _KILO_WORDS for w in words)
    if "kaal" in words or "கால்" in words or ("quarter" in words and kilo_said):
        return (Decimal(250), "g")
    if "arai" in words or "அரை" in words or ("half" in words and kilo_said):
        return (Decimal(500), "g")
    unit: str | None = None
    number_words: list[str] = []
    for w in words:
        found = normalise_unit(w)
        if found is not None and unit is None:
            unit = found
        else:
            number_words.append(w)
    if unit is None:
        return None
    if not number_words:
        return (Decimal(1), unit)
    value = parse_number(" ".join(number_words))
    if value is None:
        return None
    return (value, unit)


def convert(amount: Decimal, unit: str, to: str) -> Decimal | None:
    """Convert kg<->g and piece<->dozen. Same unit returns the amount."""
    if unit == to:
        return amount
    if unit == "kg" and to == "g":
        return amount * _G_PER_KG
    if unit == "g" and to == "kg":
        return amount / _G_PER_KG
    if unit == "dozen" and to == "piece":
        return amount * _PIECES_PER_DOZEN
    if unit == "piece" and to == "dozen":
        return amount / _PIECES_PER_DOZEN
    return None


def rate(line: PriceLine) -> tuple[Decimal, str] | None:
    """Price per kg (weights) or per piece (piece/dozen); per unit otherwise."""
    if line.price is None or line.per_amount is None or line.unit is None:
        return None
    if line.per_amount == 0:
        return None
    if line.unit in ("kg", "g"):
        amount_kg = convert(line.per_amount, line.unit, "kg")
        if amount_kg is None or amount_kg == 0:
            return None
        return (line.price / amount_kg, "kg")
    if line.unit in ("piece", "dozen"):
        amount_piece = convert(line.per_amount, line.unit, "piece")
        if amount_piece is None or amount_piece == 0:
            return None
        return (line.price / amount_piece, "piece")
    if line.unit in ("bunch", "packet"):
        return (line.price / line.per_amount, line.unit)
    return None
