from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from app.languages import by_api_name, currency_words_for, get_language
from app.meta.spark import chat_json
from app.models import DraftItem, Flag, PriceLine
from app.pipeline.extract import merge_repeated_prices
from app.pipeline.names import (
    CANONICAL_NAMES,
    display_name_en,
    find_items_in_text,
    item_name_in_text,
)
from app.pipeline.numbers import find_numbers, fold_tamil, parse_number
from app.pipeline.units import (
    CANONICAL_UNITS,
    convert,
    normalise_unit,
    normalize_unit,
    rate,
)

SOUND_ALIKE_PAIRS = {13: 30, 14: 40, 15: 50, 16: 60, 17: 70, 18: 80, 19: 90}

_PAIR_OF: dict[int, int] = {}
for _teen, _tens in SOUND_ALIKE_PAIRS.items():
    _PAIR_OF[_teen] = _tens
    _PAIR_OF[_tens] = _teen

WEIGHT_ITEMS: set[str] = {
    "tomato", "onion", "small onion", "potato", "carrot", "beans", "cabbage",
    "cauliflower", "brinjal", "okra", "drumstick", "pumpkin", "bottle gourd",
    "bitter gourd", "snake gourd", "ridge gourd", "cucumber", "grapes",
    "green chilli", "ginger", "garlic", "coriander", "radish", "beetroot",
    "peas", "capsicum", "spinach", "ivy gourd",
}

TAMIL_FIFTY_WORDS = frozenset({
    "ஐம்பது", "அம்பது",
    "aimbadhu", "aimbathu", "ambadhu", "ambathu",
})

TAMIL_EIGHTY_WORDS = frozenset({
    "எண்பது", "எம்பது",
    "enbadhu", "enbathu", "embadhu", "embathu", "yenbadhu",
})

TAMIL_HALF_WORDS = frozenset({
    "அரை",
    "arai", "ara",
})

TAMIL_SIX_WORDS = frozenset({
    "ஆறு",
    "aaru", "aru",
})

HINDI_SIXTY_WORDS = frozenset({
    "साठ",
    "saath", "sath",
})

HINDI_SEVEN_WORDS = frozenset({
    "सात",
    "saat", "sat",
})

# Marathi uses the same Devanagari words as Hindi (साठ/सात); the pair
# below is shared, with a Marathi label for Marathi shops.
BENGALI_SIXTY_WORDS = frozenset({
    "ষাট",
    "shaat", "shat",
})

BENGALI_SEVEN_WORDS = frozenset({
    "সাত",
    "saat", "sat",
})

# Confusable unit words: Mandarin 一打 (dozen) heard as 一扎, Thai โหล
# (dozen) heard as โล (also short for kilo). Fires a unit SOUND_ALIKE.
_ZH_DOZEN_WORD = "一打"
_ZH_BUNCH_HEARD = "一扎"
_TH_DOZEN_WORD = "โหล"
_TH_KILO_SHORT_RE = re.compile(r"(?<!กิ)โล")

CORRECTION_MARKERS = (
    "illa illa", "illai", "sorry", "no no", "wait", "correction", "இல்ல", "இல்லை",
)

_PARSED_LANGUAGES = frozenset({"en", "ta", "hi"})

# Currency words for the parsed languages only: "real" (Portuguese) or "en"
# (Japanese) are ordinary words in English quotes, so the full registry
# union must not drive UNCLEAR_NUMBER here.
_PARSED_CURRENCY_WORDS = frozenset(
    {"rupai", "rupees", "rupee", "rs", "₹", "ரூபாய்", "ரூபா"}
    | {word.lower() for code in ("en", "ta", "hi")
       for word in currency_words_for(code)}
)

_CROSS_CHECK_SYSTEM = (
    "You read one spoken price phrase and return only the money amount. "
    'Return only JSON shaped like {"price": 25}.'
)


def _cross_check_currency_hint(language_name: str) -> str:
    try:
        words = by_api_name(language_name).currency_words
    except KeyError:
        return ""
    if not words:
        return ""
    return f" Currency words in {language_name}: {', '.join(words)}."


def cross_check_number(phrase: str, language_name: str, *,
                       ledger, settings) -> Decimal | None:
    """Independently turn a quoted price phrase into digits.

    The model sees only the phrase, the language name and its currency
    words, never the price the first pass extracted. It must return the
    money amount only: the phrase may also hold a quantity or unit word
    (dozen, kilo, piece, bunch, packet, ...) that is NOT the price.
    Baseten's open-weights Spark answers when a key is set, else Meta.
    Returns None when the model fails; the cost is logged via the ledger.
    """
    provider = "baseten" if settings.baseten_api_key else "meta"
    messages = [
        {"role": "system", "content": _CROSS_CHECK_SYSTEM},
        {"role": "user", "content": (
            f"Language: {language_name}\nPhrase: \"{phrase}\"\n"
            "The phrase may also contain a quantity or unit word (such as "
            "dozen, kilo, piece, bunch or packet) that is NOT the price."
            f"{_cross_check_currency_hint(language_name)}\n"
            'Return only the money amount as JSON shaped like {"price": 25}.'
        )},
    ]
    try:
        data = chat_json(messages, ledger=ledger, settings=settings,
                         provider=provider, reasoning_effort="low",
                         step="check prices")
    except Exception:  # noqa: BLE001 - any failure means "not sure"
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("price", data.get("value", data.get("number",
                                                       data.get("digits"))))
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _raw_tokens(quote: str) -> list[str]:
    return [t.strip(".,;:!?\"'()[]{}।॥").lower() for t in quote.split()]


def _within(rate: tuple[Decimal, str], ref: tuple[Decimal, str],
            tolerance: Decimal) -> bool:
    """True when rate is within tolerance of ref on the same per-unit base."""
    if rate[1] != ref[1] or ref[0] == 0:
        return False
    return abs(rate[0] - ref[0]) / abs(ref[0]) <= tolerance


def _sound_alike_rates(item: DraftItem, line: PriceLine,
                       alt_value: int | Decimal,
                       previous: dict[str, PriceLine]):
    """(heard rate, alternative rate, previous rate); None when incomparable."""
    prev_line = (previous or {}).get(item.name_en)
    if prev_line is None:
        prev_line = (previous or {}).get(
            getattr(item, "match_key", None) or item.name_en)
    if prev_line is None:
        return (None, None, None)
    heard = rate(line)
    alt = rate(PriceLine(Decimal(alt_value), line.per_amount, line.unit))
    old = rate(prev_line)
    if heard is None or alt is None or old is None:
        return (None, None, None)
    return (heard, alt, old)


def _per_amount_sound_alike_rates(item: DraftItem, line: PriceLine,
                                  alt_per_amount: Decimal,
                                  previous: dict[str, PriceLine]):
    """(heard rate, alternative rate, previous rate) varying per_amount."""
    prev_line = (previous or {}).get(item.name_en)
    if prev_line is None:
        prev_line = (previous or {}).get(
            getattr(item, "match_key", None) or item.name_en)
    if prev_line is None:
        return (None, None, None)
    heard = rate(line)
    alt = rate(PriceLine(line.price, alt_per_amount, line.unit))
    old = rate(prev_line)
    if heard is None or alt is None or old is None:
        return (None, None, None)
    return (heard, alt, old)


def _closer_than(heard: tuple[Decimal, str], alt: tuple[Decimal, str],
                 ref: tuple[Decimal, str]) -> bool:
    """True when heard is strictly closer to ref than alt on the same base."""
    if heard[1] != ref[1] or alt[1] != ref[1]:
        return False
    return abs(heard[0] - ref[0]) < abs(alt[0] - ref[0])


def _has_word(tokens: list[str], words: frozenset[str]) -> bool:
    return any(token.startswith(word) for token in tokens for word in words)


def _has_exact_word(tokens: list[str], words: frozenset[str]) -> bool:
    return any(token in words for token in tokens)


def _sound_alike_alternatives(heard: list[tuple[Decimal, str]],
                              has_fifty: bool,
                              has_eighty: bool,
                              has_sixty: bool = False,
                              has_seven: bool = False) -> set[Decimal]:
    """Alternatives of heard numbers via English, Tamil 50/80, Hindi 60/7."""
    alts: set[Decimal] = set()
    for value, kind in heard:
        if value != int(value):
            continue
        ivalue = int(value)
        if kind == "english" and ivalue in _PAIR_OF:
            alts.add(Decimal(_PAIR_OF[ivalue]))
        if has_fifty and ivalue % 100 == 50:
            alts.add(Decimal(ivalue + 30))
        if has_eighty and ivalue % 100 == 80:
            alts.add(Decimal(ivalue - 30))
        if has_sixty and ivalue % 100 == 60:
            alts.add(Decimal(ivalue - 53))
        if has_seven and ivalue % 100 == 7:
            alts.add(Decimal(ivalue + 53))
    return alts


def _non_blocking(heard_rate, alt_rate, prev_rate) -> bool:
    if heard_rate is None or alt_rate is None or prev_rate is None:
        return False
    if not _within(heard_rate, prev_rate, Decimal("0.3")):
        return False
    if not _within(alt_rate, prev_rate, Decimal("0.3")):
        return True
    return _closer_than(heard_rate, alt_rate, prev_rate)


def _decimal_comma_for(language: str) -> bool:
    try:
        return get_language(language).decimal_comma
    except KeyError:
        return False


def _api_name_for(language: str) -> str | None:
    try:
        return get_language(language).api_name
    except KeyError:
        return None


# Task 143: a spoken quantity must never be accepted as a price. A real
# Tamil stall said "5 pieces for Rs.20" (அஞ்சு ... five piece இருபது)
# and one run invented a "Rs.5 / 1 kg" line from the quantity 5.
_COUNT_UNIT_WORDS = frozenset({
    "piece", "pieces", "pc", "pcs", "பீஸ்",
    "dozen", "dozens", "டஜன்",
    "bunch", "bunches", "கட்டு", "kattu", "kathu",
    "kg", "kilo", "kilos", "கிலோ",
})

_UNIT_PLURAL = {
    "piece": "pieces", "dozen": "dozen", "bunch": "bunches",
    "packet": "packets", "kg": "kg", "g": "g", "l": "l", "ml": "ml",
}


def _fmt_amount(value: Decimal) -> str:
    """Compact digits for flag text: Decimal(20) -> "20", not "20.00"."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _unit_plural(unit: str, per_amount: Decimal) -> str:
    if per_amount == 1:
        return unit
    return _UNIT_PLURAL.get(unit, unit)


def _describe_line(line: PriceLine) -> str:
    """One-line offer text, e.g. "Rs.20 for 5 pieces" / "Rs.5 per kg"."""
    price = _fmt_amount(line.price) if line.price is not None else "?"
    unit = line.unit
    per = line.per_amount
    if per is not None and unit:
        if per == 1:
            return f"₹{price} per {unit}"
        return f"₹{price} for {_fmt_amount(per)} {_unit_plural(unit, per)}"
    if unit:
        return f"₹{price} per {unit}"
    if per is not None:
        return f"₹{price} for {_fmt_amount(per)}"
    return f"₹{price}"


def _qty_as_price_pair(lines: list[PriceLine]
                       ) -> tuple[PriceLine, PriceLine] | None:
    """(suspect, other) when suspect.price equals another line's per_amount."""
    for index, suspect in enumerate(lines):
        if suspect.price is None:
            continue
        for other_index, other in enumerate(lines):
            if (other_index == index or other.per_amount is None
                    or other.price is None):
                continue
            if suspect.price == other.per_amount:
                return (suspect, other)
    return None


def _number_before_count_unit(tokens: list[str], value: Decimal) -> bool:
    """True when the number stands right before a count unit in the quote."""
    for index, token in enumerate(tokens):
        if token not in _COUNT_UNIT_WORDS:
            continue
        if index >= 1 and parse_number(tokens[index - 1]) == value:
            return True
        if (index >= 2
                and parse_number(tokens[index - 2] + " "
                                 + tokens[index - 1]) == value):
            return True
    return False


def _tier_base(unit: str) -> str | None:
    """Shared base for convertible units: g counts as kg, dozen as piece."""
    if unit in ("kg", "g"):
        return "kg"
    if unit in ("l", "ml"):
        return "l"
    if unit in ("piece", "dozen"):
        return "piece"
    if unit in ("bunch", "packet"):
        return unit
    return None


def _is_clear_tier_list(priced: list[PriceLine]) -> bool:
    """True for "1 kg 40, 2 kg 75": same unit, growing amounts in order."""
    if len(priced) < 2:
        return False
    if any(line.unit is None or line.per_amount is None for line in priced):
        return False
    base = _tier_base(priced[0].unit or "")
    if base is None:
        return False
    amounts: list[Decimal] = []
    for line in priced:
        if _tier_base(line.unit or "") != base:
            return False
        converted = convert(line.per_amount, line.unit or "", base)
        if converted is None:
            return False
        amounts.append(converted)
    return all(nxt > cur for cur, nxt in pairwise(amounts))


# Task 160: a fraction word right before a unit word ("கால் கிலோ")
# is the per amount the seller said. When the line says anything else,
# the seller picks; the price is never changed silently.
_QTY_FRACTIONS: dict[str, Decimal] = {
    "கால்": Decimal("0.25"), "kaal": Decimal("0.25"),
    "quarter": Decimal("0.25"),
    "அரை": Decimal("0.5"), "arai": Decimal("0.5"),
    "half": Decimal("0.5"),
    "முக்கால்": Decimal("0.75"), "mukkal": Decimal("0.75"),
    "mukkaal": Decimal("0.75"),
}

_VULGAR_FRACTIONS: dict[Decimal, str] = {
    Decimal("0.25"): "¼", Decimal("0.5"): "½", Decimal("0.75"): "¾",
}


def _qty_word_pairs(tokens: list[str]) -> list[tuple[Decimal, str, str]]:
    """(value, unit, heard words) for each fraction word before a unit."""
    pairs: list[tuple[Decimal, str, str]] = []
    for first, second in pairwise(tokens):
        value = _QTY_FRACTIONS.get(first)
        if value is None:
            continue
        unit, _ = normalize_unit(second)
        if unit is None:
            continue
        pairs.append((value, unit, f"{first} {second}"))
    return pairs


def _qty_word_mismatch_flag(pairs: list[tuple[Decimal, str, str]],
                            line: PriceLine) -> Flag | None:
    """Blocking flag when the said fraction differs from the line amount.

    Only for one heard pair on a single-line item: with several lines
    or several said fractions the words cannot be attributed to one
    line. A line that agrees (¼ kg heard, 250 g lined) or is
    incomparable (¼ kg heard, per piece lined) stays silent; the
    options only ever set the per amount.
    """
    if len(pairs) != 1:
        return None
    if line.per_amount is None or line.unit is None:
        return None
    heard_value, heard_unit, heard_words = pairs[0]
    if line.unit == heard_unit:
        if line.per_amount == heard_value:
            return None
        heard_opt = f"{_VULGAR_FRACTIONS[heard_value]} {heard_unit}"
    else:
        heard_in_line = convert(heard_value, heard_unit, line.unit)
        if heard_in_line is None or heard_in_line == line.per_amount:
            return None
        heard_opt = f"{_fmt_amount(heard_in_line)} {line.unit}"
    line_opt = f"{_fmt_amount(line.per_amount)} {line.unit}"
    return Flag(
        field="per_amount", code="QTY_WORD_MISMATCH",
        message=(f"We heard '{heard_words}' ({heard_opt})"
                 f" but the line says per {line_opt}. Which is right?"),
        options=[heard_opt, line_opt])


def _name_not_near_price_flag(item: DraftItem, quote: str) -> Flag | None:
    """Blocking flag when the span names a different item (Task 156).

    The claimed name is verified against the item's own per-item
    span: when none of its forms (local, English, transliteration,
    glossary aliases) occurs there but the span does name another
    known item, the name is wrong and must never pass silently.
    Bare spans naming nothing stay silent, as do unknown and
    seller-named items and items without a price.
    """
    base = (item.name_en or "").strip().lower()
    if not base or base not in CANONICAL_NAMES:
        return None
    span = quote or ""
    if not span.strip():
        return None
    if item_name_in_text(base, span, name_local=item.name_local):
        return None
    found = [(word, name) for word, name in find_items_in_text(span)
             if name != base]
    if not found:
        return None
    price = next((line.price for line in item.price_lines
                  if line.price is not None), None)
    if price is None:
        return None
    word, heard = found[0]
    options: list[str] = []
    for _, name in found:
        if name not in options:
            options.append(name)
    options.append(base)
    return Flag(
        field="name", code="NAME_NOT_NEAR_PRICE",
        message=(f"Is this {display_name_en(item.name_en, item.variety)}?"
                 f" Just before ₹{_fmt_amount(price)} we heard"
                 f" '{word}' ({heard})."),
        options=options)


def check_item(item: DraftItem, previous: dict[str, PriceLine], *,
               language: str = "ta", ledger=None, settings=None
               ) -> list[Flag]:
    """Flag risky values on a draft item. Proof decides; nothing is guessed.

    English, Tamil and Hindi prices verify against digits and the local
    number-word parsers. Every other shop language cross-checks an
    otherwise unheard price with one independent model call over only the
    quoted number phrase; agreement counts as heard, anything else is a
    blocking NUMBER_CHECK flag.
    """
    merge_repeated_prices(item)
    flags: list[Flag] = []
    quote = item.proof.quote or ""
    name_flag = _name_not_near_price_flag(item, quote)
    if name_flag is not None:
        flags.append(name_flag)
    heard = find_numbers(quote,
                         decimal_comma=_decimal_comma_for(language))
    heard_values = {value for value, _ in heard}
    quote_tokens = [t for t in _raw_tokens(quote) if t]
    folded_tokens = [fold_tamil(t) for t in quote_tokens]
    has_fifty = _has_word(folded_tokens,
                          frozenset(fold_tamil(w) for w in TAMIL_FIFTY_WORDS))
    has_eighty = _has_word(folded_tokens,
                           frozenset(fold_tamil(w) for w in TAMIL_EIGHTY_WORDS))
    has_half = _has_word(folded_tokens,
                         frozenset(fold_tamil(w) for w in TAMIL_HALF_WORDS))
    has_six = _has_word(folded_tokens,
                        frozenset(fold_tamil(w) for w in TAMIL_SIX_WORDS))
    has_sixty = _has_exact_word(quote_tokens, HINDI_SIXTY_WORDS.union(
        BENGALI_SIXTY_WORDS))
    has_seven = _has_exact_word(quote_tokens, HINDI_SEVEN_WORDS.union(
        BENGALI_SEVEN_WORDS))
    has_bengali_script = any(token in ("ষাট", "সাত")
                             for token in quote_tokens)
    alternatives = _sound_alike_alternatives(heard, has_fifty, has_eighty,
                                             has_sixty, has_seven)
    api_name = _api_name_for(language)
    cross_checkable = (language not in _PARSED_LANGUAGES
                       and api_name is not None
                       and ledger is not None and settings is not None)
    offers_half_six = any(
        line.per_amount is not None
        and (
            (line.per_amount == Decimal(6) and has_six)
            or (line.per_amount == Decimal("0.5") and has_half and has_six)
        )
        for line in item.price_lines
    )
    if offers_half_six:
        heard_values.add(Decimal("0.5"))
        alternatives.add(Decimal("0.5"))
        alternatives.add(Decimal(6))

    for line in item.price_lines:
        if (line.price is not None and line.price not in heard_values
                and line.price not in alternatives):
            if cross_checkable:
                phrase = line.said.strip() or quote
                checked = cross_check_number(phrase, api_name,
                                             ledger=ledger, settings=settings)
                if checked is not None and checked == line.price:
                    item.proof.number_check = "cross-checked"
                elif checked is not None:
                    flags.append(Flag(
                        field="price", code="NUMBER_CHECK",
                        message="we are not sure about this number"
                                " - please listen",
                        options=[str(line.price), str(checked)]))
                else:
                    flags.append(Flag(
                        field="price", code="NUMBER_CHECK",
                        message="we are not sure about this number"
                                " - please listen",
                        options=[str(line.price)]))
            else:
                flags.append(Flag(field="price", code="NOT_HEARD",
                                  message=f"price {line.price} not heard in quote"))
        if line.price is not None and line.price == int(line.price):
            for value, kind in heard:
                if (kind == "english" and value == int(value)
                        and int(value) in _PAIR_OF
                        and (value == line.price
                             or Decimal(_PAIR_OF[int(value)]) == line.price)):
                    alt_value = _PAIR_OF[int(value)]
                    pair = sorted([int(value), alt_value])
                    other = pair[1] if pair[0] == int(line.price) else pair[0]
                    message = f"did you say {pair[0]} or {pair[1]}?"
                    blocking = True
                    heard_rate, alt_rate, prev_rate = _sound_alike_rates(
                        item, line, other, previous)
                    if _non_blocking(heard_rate, alt_rate, prev_rate):
                        blocking = False
                        message += (f" {int(line.price)} matches the previous price"
                                    f" ({prev_rate[0]} per {prev_rate[1]})")
                    flags.append(Flag(
                        field="price", code="SOUND_ALIKE", message=message,
                        options=[str(pair[0]), str(pair[1])], blocking=blocking))
                    break
            for value, _ in heard:
                if value != int(value):
                    continue
                ivalue = int(value)
                alt_value = None
                if has_fifty and ivalue % 100 == 50:
                    alt_value = ivalue + 30
                elif has_eighty and ivalue % 100 == 80:
                    alt_value = ivalue - 30
                if alt_value is None:
                    continue
                if line.price == ivalue or line.price == alt_value:
                    pair = sorted([ivalue, alt_value])
                    other = pair[1] if pair[0] == int(line.price) else pair[0]
                    message = (f"did you say {pair[0]} or {pair[1]}?"
                               " (50 and 80 sound alike in Tamil)")
                    blocking = True
                    heard_rate, alt_rate, prev_rate = _sound_alike_rates(
                        item, line, other, previous)
                    if _non_blocking(heard_rate, alt_rate, prev_rate):
                        blocking = False
                        message += (f" {int(line.price)} matches the previous price"
                                    f" ({prev_rate[0]} per {prev_rate[1]})")
                    flags.append(Flag(
                        field="price", code="SOUND_ALIKE", message=message,
                        options=[str(pair[0]), str(pair[1])], blocking=blocking))
                    break
            for value, _ in heard:
                if value != int(value):
                    continue
                ivalue = int(value)
                alt_value = None
                if has_sixty and ivalue % 100 == 60:
                    alt_value = ivalue - 53
                elif has_seven and ivalue % 100 == 7:
                    alt_value = ivalue + 53
                if alt_value is None:
                    continue
                if line.price == ivalue or line.price == alt_value:
                    pair = sorted([ivalue, alt_value])
                    other = pair[1] if pair[0] == int(line.price) else pair[0]
                    if has_bengali_script or language == "bn":
                        pair_note = ("shaat and saat sound alike in Bengali")
                    elif language == "mr":
                        pair_note = ("saath and saat sound alike in Marathi")
                    else:
                        pair_note = ("saath and saat sound alike in Hindi")
                    message = (f"did you say {pair[0]} or {pair[1]}?"
                               f" ({pair_note})")
                    blocking = True
                    heard_rate, alt_rate, prev_rate = _sound_alike_rates(
                        item, line, other, previous)
                    if _non_blocking(heard_rate, alt_rate, prev_rate):
                        blocking = False
                        message += (f" {int(line.price)} matches the previous price"
                                    f" ({prev_rate[0]} per {prev_rate[1]})")
                    flags.append(Flag(
                        field="price", code="SOUND_ALIKE", message=message,
                        options=[str(pair[0]), str(pair[1])], blocking=blocking))
                    break

    for line in item.price_lines:
        if line.per_amount is None:
            continue
        triggers = (
            (line.per_amount == Decimal(6) and has_six)
            or (line.per_amount == Decimal("0.5") and has_half and has_six)
        )
        if not triggers:
            continue
        unit = line.unit or "unit"
        message = (
            f"did you say half a {unit} or 6 {unit}?"
            " (arai and aaru sound alike in Tamil)"
        )
        blocking = True
        other_per = (
            Decimal("0.5") if line.per_amount == Decimal(6) else Decimal(6)
        )
        heard_rate, alt_rate, prev_rate = _per_amount_sound_alike_rates(
            item, line, other_per, previous)
        if _non_blocking(heard_rate, alt_rate, prev_rate):
            blocking = False
            message += (f" {line.per_amount} matches the previous price"
                        f" ({prev_rate[0]} per {prev_rate[1]})")
        flags.append(Flag(
            field="per_amount", code="SOUND_ALIKE", message=message,
            options=["0.5", "6"], blocking=blocking))

    if len(item.price_lines) == 1:
        mismatch = _qty_word_mismatch_flag(
            _qty_word_pairs(quote_tokens), item.price_lines[0])
        if mismatch is not None:
            flags.append(mismatch)

    zh_confused = (_ZH_BUNCH_HEARD in quote and _ZH_DOZEN_WORD not in quote)
    th_confused = (_TH_DOZEN_WORD not in quote
                   and _TH_KILO_SHORT_RE.search(quote) is not None)
    if zh_confused or th_confused:
        for line in item.price_lines:
            if zh_confused and line.unit in ("dozen", "bunch"):
                flags.append(Flag(
                    field="unit", code="SOUND_ALIKE",
                    message=("did you say dozen or bunch?"
                             f" ({_ZH_DOZEN_WORD} and {_ZH_BUNCH_HEARD}"
                             " sound alike in Mandarin)"),
                    options=["dozen", "bunch"]))
            if th_confused and line.unit in ("dozen", "kg"):
                flags.append(Flag(
                    field="unit", code="SOUND_ALIKE",
                    message=("did you say dozen or kg?"
                             f" ({_TH_DOZEN_WORD} and โล sound alike in Thai)"),
                    options=["dozen", "kg"]))

    if item.qty is not None and item.qty not in heard_values:
        flags.append(Flag(field="qty", code="NOT_HEARD",
                          message=f"quantity {item.qty} not heard in quote"))

    lowered = quote.lower()
    marker = next((m for m in CORRECTION_MARKERS if m in lowered), None)
    if marker is not None:
        flags.append(Flag(field="quote", code="CORRECTION_SAID",
                          message=f'seller corrected themselves ("{marker}")'))

    if language in _PARSED_LANGUAGES or api_name is None:
        tokens = [t for t in _raw_tokens(quote) if t]
        for idx, token in enumerate(tokens):
            if token in _PARSED_CURRENCY_WORDS and idx > 0:
                before = tokens[idx - 1]
                if (before not in _PARSED_CURRENCY_WORDS
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
        if line.unit == "piece" and (getattr(item, "match_key", None)
            or item.name_en) in WEIGHT_ITEMS:
            flags.append(Flag(
                field="unit", code="UNIT_ODD",
                message="usually sold by weight - is per piece right?",
                blocking=False))
        if line.unit is not None and line.unit not in CANONICAL_UNITS:
            flags.append(Flag(field="unit", code="UNIT_CHECK",
                              message="please check the unit",
                              blocking=False))

    prev_line = (previous or {}).get(item.name_en)
    if prev_line is None:
        prev_line = (previous or {}).get(
            getattr(item, "match_key", None) or item.name_en)
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

    qty_as_price_fired = False
    pair = _qty_as_price_pair(item.price_lines)
    if pair is not None:
        suspect, other = pair
        assert suspect.price is not None and other.price is not None
        kinds = {kind for value, kind in heard if value == suspect.price}
        if (_number_before_count_unit(quote_tokens, suspect.price)
                or len(kinds) >= 2):
            number = _fmt_amount(suspect.price)
            if other.unit:
                assert other.per_amount is not None
                quoted = (f"{number} "
                          f"{_unit_plural(other.unit, other.per_amount)}"
                          f" for ₹{_fmt_amount(other.price)}")
            else:
                quoted = f"{number} for ₹{_fmt_amount(other.price)}"
            flags.append(Flag(
                field="price_line", code="QTY_AS_PRICE",
                message=(f"Is {number} a price, or the {number}"
                         f" in '{quoted}'?"),
                options=[_describe_line(other), _describe_line(suspect)]))
            qty_as_price_fired = True

    priced = [line for line in item.price_lines if line.price is not None]
    units = {line.unit for line in priced if line.unit is not None}
    if (len(priced) >= 2 and len(units) >= 2
            and not _is_clear_tier_list(priced)
            and not qty_as_price_fired):
        flags.append(Flag(
            field="price_line", code="MULTI_PRICE_UNCLEAR",
            message="Two different prices — which one is right?",
            options=[_describe_line(line) for line in priced]))

    if not any(line.price is not None for line in item.price_lines):
        flags.append(Flag(field="price", code="NO_PRICE", message="no price at all"))

    if item.qty is None:
        flags.append(Flag(field="qty", code="QTY_MISSING",
                          message="no quantity", blocking=False))
    return flags


def flag_same_name_two_prices(items: list[DraftItem], *,
                                language: str = "ta") -> None:
    """Flag repeated lines: same final title, different prices.

    Two lines headed for the same title (local + English, variety
    included) with different headline prices are never merged: every
    line gets a soft "Two prices for <name> — same item or different
    kinds?" note, and the seller renames one kind with the review
    card's rename box. Different titles are different kinds and never
    flag, whatever the price.
    """
    from app.pipeline.names import english_title, local_title

    groups: dict[tuple[str, str], list[DraftItem]] = {}
    for item in items or []:
        base = (item.name_en or "").strip().lower()
        if not base or base == "other":
            continue
        key = (
            local_title(item.name_local, item.variety, item.name_en,
                        language).strip().lower(),
            english_title(item.name_en, item.variety).strip().lower(),
        )
        groups.setdefault(key, []).append(item)
    for members in groups.values():
        if len(members) < 2:
            continue
        firsts = [
            next((line.price for line in member.price_lines
                  if line.price is not None), None)
            for member in members
        ]
        if len({price for price in firsts if price is not None}) < 2:
            continue
        name = (english_title(members[0].name_en, members[0].variety)
                or members[0].name_en)
        for member in members:
            member.flags.append(Flag(
                field="price", code="SAME_ITEM_TWO_PRICES",
                message=(f"Two prices for {name}"
                         " — same item or different kinds?"),
                blocking=False))
