"""MISSED_PRICE coverage check (Task 157).

The extract model can skip a price entirely: owner 2's live run
returned 14 items for chunk 1's 15 spoken prices, and the Mannur
₹70/kg line never entered the pipeline. After extraction every
spoken price phrase in the transcript (a number word or digits with
a nearby currency or unit word, in Tamil, English or mixed) must lie
inside some item's proof span — its quote or one of its price
phrases. Each phrase outside every span becomes a draft item that
needs the seller: price and unit filled from the words, the name
left empty, and a blocking MISSED_PRICE flag whose options are the
glossary items heard nearby plus the previous item's name, with
"Remove" available. Filler amounts that are not prices ("ஒரு
கிலோ" alone, "kaal kilo" alone) never count.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import NamedTuple

from app.models import DraftItem, Flag, PriceLine, Proof, Transcript
from app.pipeline.names import (
    CANONICAL_NAMES,
    find_items_in_text,
    is_word_char,
)
from app.pipeline.numbers import parse_number

_TOKEN_RE = re.compile(r"\S+")
_STRIP_CHARS = ".,;:!?\"'()[]{}।॥·/—–-"

_CURRENCY_WORDS: frozenset[str] = frozenset({
    "ரூபா", "ரூபாய்", "rupees", "rupee", "rupai", "rs", "₹",
})

_UNIT_WORDS: dict[str, str] = {
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "கிலோ": "kg",
    "g": "g", "gm": "g", "gram": "g", "grams": "g", "கிராம்": "g",
    "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
    "pees": "piece", "பீஸ்": "piece",
    "dozen": "dozen", "dozens": "dozen", "டஜன்": "dozen",
    "bunch": "bunch", "bunches": "bunch", "kattu": "bunch",
    "kathu": "bunch", "கட்டு": "bunch",
    "packet": "packet", "packets": "packet", "pack": "packet",
    "pkt": "packet", "பாக்கெட்": "packet",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "ml": "ml", "லிட்டர்": "l",
}

_FRACTIONS: dict[str, Decimal] = {
    "கால்": Decimal("0.25"), "kaal": Decimal("0.25"),
    "kal": Decimal("0.25"), "quarter": Decimal("0.25"),
    "அரை": Decimal("0.5"), "arai": Decimal("0.5"),
    "ara": Decimal("0.5"), "half": Decimal("0.5"),
    "முக்கால்": Decimal("0.75"), "mukkaal": Decimal("0.75"),
}

#: Token distance for a currency/unit word to belong to a number.
_ANCHOR_WINDOW = 2
#: Token gap up to which two price numbers form one phrase.
_MERGE_GAP = 3


class PricePhrase(NamedTuple):
    """One spoken price: char span, value, amount, unit and said words."""

    start: int
    end: int
    price: Decimal
    per_amount: Decimal | None
    unit: str | None
    said: str


def _tokens(text: str) -> list[dict]:
    """Whitespace tokens with stripped words and char offsets."""
    found: list[dict] = []
    for match in _TOKEN_RE.finditer(text or ""):
        start, end = match.start(), match.end()
        while start < end and text[start] in _STRIP_CHARS:
            start += 1
        while end > start and text[end - 1] in _STRIP_CHARS:
            end -= 1
        word = text[start:end]
        if not word:
            continue
        found.append({"word": word, "lower": word.lower(),
                      "start": start, "end": end})
    return found


def _number_hits(tokens: list[dict]) -> list[tuple]:
    """(value, first, last) number phrases, longest windows first."""
    hits: list[tuple] = []
    pos = 0
    while pos < len(tokens):
        matched = False
        for width in (3, 2, 1):
            if pos + width > len(tokens):
                continue
            words = [tok["lower"] for tok in tokens[pos:pos + width]]
            value = parse_number(" ".join(words))
            if value is not None:
                hits.append((value, pos, pos + width - 1))
                pos += width
                matched = True
                break
        if not matched:
            pos += 1
    return hits


def _is_currency(token: dict) -> bool:
    return token["lower"] in _CURRENCY_WORDS or "₹" in token["word"]


def _near(tokens: list[dict], first: int, last: int) -> list[int]:
    """Token positions within the anchor window, outside [first, last]."""
    return [pos for pos in range(max(0, first - _ANCHOR_WINDOW),
                                 min(len(tokens), last + 1 + _ANCHOR_WINDOW))
            if pos < first or pos > last]


def _phrase_for(tokens: list[dict], group: list[tuple],
                numbers: list[tuple]) -> PricePhrase:
    """Build one phrase from merged price numbers and nearby anchors."""
    first = min(hit[1] for hit in group)
    last = max(hit[2] for hit in group)
    edges = {first, last}
    for _, hit_first, hit_last in group:
        for pos in _near(tokens, hit_first, hit_last):
            word = tokens[pos]["lower"]
            if (_is_currency(tokens[pos]) or word in _UNIT_WORDS
                    or word in _FRACTIONS):
                edges.add(pos)
    start_tok, end_tok = min(edges), max(edges)
    priced = [hit for hit in group if any(
        _is_currency(tokens[pos]) for pos in _near(tokens, hit[1], hit[2]))]
    if priced:
        price = max(hit[0] for hit in priced)
    else:
        price = max(hit[0] for hit in group)
    unit: str | None = None
    for pos in range(start_tok, end_tok + 1):
        unit = _UNIT_WORDS.get(tokens[pos]["lower"])
        if unit is not None:
            break
    per_amount: Decimal | None = None
    for pos in range(start_tok, end_tok + 1):
        fraction = _FRACTIONS.get(tokens[pos]["lower"])
        if fraction is not None:
            per_amount = fraction
            break
    if per_amount is None:
        others = {hit[0] for hit in numbers
                  if start_tok <= hit[1] and hit[2] <= end_tok
                  and hit[0] != price}
        if others:
            per_amount = min(others)
        elif unit is not None:
            per_amount = Decimal(1)
    text_start = tokens[start_tok]["start"]
    text_end = tokens[end_tok]["end"]
    return PricePhrase(start=text_start, end=text_end, price=price,
                       per_amount=per_amount, unit=unit, said="")


def find_price_phrases(text: str) -> list[PricePhrase]:
    """Every spoken price phrase in the text, in spoken order.

    A number word or digits followed or preceded by a currency or
    unit word counts; a bare 1 before a unit ("ஒரு கிலோ") and a
    fraction with a unit but no number ("kaal kilo") do not. Numbers
    a few tokens apart share one phrase ("அஞ்சு பீஸ் நூறு" is ₹100
    for 5 pieces); the currency-near number wins as the price,
    otherwise the largest.
    """
    raw = text or ""
    tokens = _tokens(raw)
    if not tokens:
        return []
    numbers = _number_hits(tokens)
    price_hits = []
    for value, first, last in numbers:
        nearby = _near(tokens, first, last)
        currency = any(_is_currency(tokens[pos]) for pos in nearby)
        unit = (value != 1 and any(tokens[pos]["lower"] in _UNIT_WORDS
                                   for pos in nearby))
        if currency or unit:
            price_hits.append((value, first, last))
    groups: list[list[tuple]] = []
    for hit in price_hits:
        if groups and hit[1] - groups[-1][-1][2] <= _MERGE_GAP:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    phrases = []
    for group in groups:
        built = _phrase_for(tokens, group, numbers)
        phrases.append(built._replace(
            said=raw[built.start:built.end]))
    return phrases


def _find_spans(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Whole-word occurrence spans of needle in haystack."""
    key = " ".join((needle or "").split())
    if not key or not haystack:
        return []
    lowered, wanted = haystack.lower(), key.lower()
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = lowered.find(wanted, start)
        if idx < 0:
            return spans
        end = idx + len(wanted)
        before = lowered[idx - 1] if idx > 0 else " "
        after = lowered[end] if end < len(lowered) else " "
        if not is_word_char(before) and not is_word_char(after):
            spans.append((idx, end))
        start = idx + 1


def _covered_ranges(items: list[DraftItem], turn_text: str) -> list[tuple[int, int]]:
    """Char ranges an item's proof covers: its quote and price phrases."""
    covered: list[tuple[int, int]] = []
    for item in items or []:
        snippets = [item.proof.quote or ""]
        snippets.extend(line.said or "" for line in item.price_lines)
        for snippet in snippets:
            covered.extend(_find_spans(turn_text, snippet))
    return covered


def _fmt_price(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _insertion_point(items: list[DraftItem], turn_id: int) -> int:
    """Index keeping turn order: before the first later-turn item."""
    for pos, item in enumerate(items):
        turn_ids = list(getattr(item.proof, "turn_ids", []) or [])
        if turn_ids and min(turn_ids) > turn_id:
            return pos
    return len(items)


def add_missed_price_items(items: list[DraftItem], transcript: Transcript, *,
                           language: str = "ta") -> list[DraftItem]:
    """Append a NEEDS-YOU item per price phrase outside every proof span.

    Each missed phrase becomes an unnamed draft item (price and unit
    from the words, clip times from its turn) with a blocking
    MISSED_PRICE flag; options are the glossary items heard in the
    turn plus the previous item's name, with "Remove" available. The
    name is never invented: it stays empty until the seller picks
    one. Items stay in spoken order.
    """
    result = list(items or [])
    turns = list(getattr(transcript, "turns", []) or [])
    for turn in turns:
        text = turn.text or ""
        phrases = find_price_phrases(text)
        if not phrases:
            continue
        covered = _covered_ranges(result, text)
        for phrase in phrases:
            if any(start < phrase.end and phrase.start < end
                   for start, end in covered):
                continue
            options: list[str] = []
            for _, name in find_items_in_text(text):
                if name not in options:
                    options.append(name)
            pos = _insertion_point(result, turn.id)
            previous = result[pos - 1] if pos > 0 else None
            prev_name = ((previous.name_en or "").strip().lower()
                         if previous is not None else "")
            if prev_name in CANONICAL_NAMES and prev_name not in options:
                options.append(prev_name)
            options.append("Remove")
            quote = text.strip()
            missed = DraftItem(
                name_spoken="",
                name_local="",
                name_en="other",
                variety=None,
                match_key="other",
                price_lines=[PriceLine(
                    price=phrase.price, per_amount=phrase.per_amount,
                    unit=phrase.unit, said=phrase.said)],
                qty=None,
                qty_unit=None,
                proof=Proof(quote=quote, turn_ids=[turn.id],
                            start_ms=turn.start_ms, end_ms=turn.end_ms),
                range_said=False,
                flags=[Flag(
                    field="name", code="MISSED_PRICE",
                    message=(f"We heard ₹{_fmt_price(phrase.price)} here — "
                             f"'{quote}'. Which item is it?"),
                    options=options,
                    blocking=True)],
            )
            result.insert(pos, missed)
            covered = _covered_ranges(result, text)
    return result
