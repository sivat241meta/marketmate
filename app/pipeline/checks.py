from __future__ import annotations

from decimal import Decimal

from app.models import DraftItem, Flag, PriceLine
from app.pipeline.numbers import find_numbers, parse_number
from app.pipeline.units import normalise_unit, rate

SOUND_ALIKE_PAIRS = {13: 30, 14: 40, 15: 50, 16: 60, 17: 70, 18: 80, 19: 90}

_PAIR_OF: dict[int, int] = {}
for _teen, _tens in SOUND_ALIKE_PAIRS.items():
    _PAIR_OF[_teen] = _tens
    _PAIR_OF[_tens] = _teen

WEIGHT_ITEMS: set[str] = {
    "tomato", "onion", "small onion", "potato", "carrot", "beans", "cabbage",
    "cauliflower", "brinjal", "okra", "drumstick", "pumpkin", "bottle gourd",
    "bitter gourd", "snake gourd", "ridge gourd", "cucumber", "mango", "papaya",
    "guava", "grapes", "apple", "lemon", "green chilli", "ginger", "garlic",
    "coriander", "radish", "beetroot", "peas", "capsicum", "spinach",
}

CORRECTION_MARKERS = (
    "illa illa", "illai", "sorry", "no no", "wait", "correction", "இல்ல", "இல்லை",
)

CURRENCY_WORDS = frozenset(
    {"rupai", "rupees", "rupee", "rs", "₹", "ரூபாய்", "ரூபா"}
)


def _raw_tokens(quote: str) -> list[str]:
    return [t.strip(".,;:!?\"'()[]{}").lower() for t in quote.split()]


def _within(rate: tuple[Decimal, str], ref: tuple[Decimal, str],
            tolerance: Decimal) -> bool:
    """True when rate is within tolerance of ref on the same per-unit base."""
    if rate[1] != ref[1] or ref[0] == 0:
        return False
    return abs(rate[0] - ref[0]) / abs(ref[0]) <= tolerance


def _sound_alike_rates(item: DraftItem, line: PriceLine, pair: list[int],
                       previous: dict[str, PriceLine]):
    """(heard rate, alternative rate, previous rate); None when incomparable."""
    prev_line = (previous or {}).get(item.name_en)
    if prev_line is None:
        return (None, None, None)
    heard = rate(line)
    alt_value = pair[1] if pair[0] == int(line.price) else pair[0]
    alt = rate(PriceLine(Decimal(alt_value), line.per_amount, line.unit))
    old = rate(prev_line)
    if heard is None or alt is None or old is None:
        return (None, None, None)
    return (heard, alt, old)


def check_item(item: DraftItem, previous: dict[str, PriceLine]) -> list[Flag]:
    """Flag risky values on a draft item. Proof decides; nothing is guessed."""
    flags: list[Flag] = []
    quote = item.proof.quote or ""
    heard = find_numbers(quote)
    heard_values = {value for value, _ in heard}

    for line in item.price_lines:
        if line.price is not None and line.price not in heard_values:
            flags.append(Flag(field="price", code="NOT_HEARD",
                              message=f"price {line.price} not heard in quote"))
        if line.price is not None and line.price == int(line.price):
            for value, kind in heard:
                if (kind == "english" and value == line.price
                        and int(value) in _PAIR_OF):
                    pair = sorted([int(value), _PAIR_OF[int(value)]])
                    message = f"did you say {pair[0]} or {pair[1]}?"
                    blocking = True
                    heard_rate, alt_rate, prev_rate = _sound_alike_rates(
                        item, line, pair, previous)
                    if (heard_rate is not None and alt_rate is not None
                            and prev_rate is not None
                            and _within(heard_rate, prev_rate, Decimal("0.3"))
                            and not _within(alt_rate, prev_rate, Decimal("0.3"))):
                        blocking = False
                        message += (f" {int(value)} matches the previous price"
                                    f" ({prev_rate[0]} per {prev_rate[1]})")
                    flags.append(Flag(
                        field="price", code="SOUND_ALIKE", message=message,
                        options=[str(pair[0]), str(pair[1])], blocking=blocking))
                    break

    if item.qty is not None and item.qty not in heard_values:
        flags.append(Flag(field="qty", code="NOT_HEARD",
                          message=f"quantity {item.qty} not heard in quote"))

    lowered = quote.lower()
    marker = next((m for m in CORRECTION_MARKERS if m in lowered), None)
    if marker is not None:
        flags.append(Flag(field="quote", code="CORRECTION_SAID",
                          message=f'seller corrected themselves ("{marker}")'))

    tokens = [t for t in _raw_tokens(quote) if t]
    for idx, token in enumerate(tokens):
        if token in CURRENCY_WORDS and idx > 0:
            before = tokens[idx - 1]
            if (before not in CURRENCY_WORDS
                    and parse_number(before) is None
                    and normalise_unit(before) is None):
                flags.append(Flag(field="price", code="UNCLEAR_NUMBER",
                                  message=f'unclear number "{before}" before currency'))

    for line in item.price_lines:
        if line.price is not None and line.unit is None:
            options: list[str] = []
            for other in item.price_lines:
                if other is line or other.unit is None:
                    continue
                if other.per_amount is not None:
                    label = f"per {other.per_amount} {other.unit}"
                else:
                    label = f"per {other.unit}"
                if label not in options:
                    options.append(label)
            flags.append(Flag(field="unit", code="UNIT_MISSING",
                              message="price is missing its unit", options=options))
        if line.unit == "piece" and item.name_en in WEIGHT_ITEMS:
            flags.append(Flag(
                field="unit", code="UNIT_ODD",
                message=f"{item.name_en} is usually sold by weight, not per piece"))

    prev_line = (previous or {}).get(item.name_en)
    if prev_line is not None:
        current = next((r for line in item.price_lines if (r := rate(line)) is not None),
                       None)
        old = rate(prev_line)
        if (current is not None and old is not None and old[0] != 0
                and current[1] == old[1]
                and abs(current[0] - old[0]) / abs(old[0]) > Decimal("0.5")):
            flags.append(Flag(
                field="price", code="JUMP",
                message=f"price jumped from {old[0]} to {current[0]} per {old[1]}"
                        " (last confirmed)"))

    if item.range_said:
        flags.append(Flag(field="price", code="RANGE",
                          message="seller said a range, pick one number"))

    groups: dict[tuple, list] = {}
    for line in item.price_lines:
        if line.price is None:
            continue
        groups.setdefault((line.per_amount, line.unit), []).append(line.price)
    for prices in groups.values():
        if len(prices) >= 2:
            flags.append(Flag(field="price", code="TWO_PRICES",
                              message="two prices for the same amount",
                              options=[str(p) for p in prices]))

    if not any(line.price is not None for line in item.price_lines):
        flags.append(Flag(field="price", code="NO_PRICE", message="no price at all"))

    if item.qty is None:
        flags.append(Flag(field="qty", code="QTY_MISSING",
                          message="no quantity", blocking=False))
    return flags
