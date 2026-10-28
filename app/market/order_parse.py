"""Fast local order parser (no AI) for live voice billing (Task 36).

Matches item names from today's published price list (name_en, name_local,
romanised Tamil and SYNONYMS), numbers via the existing parsers, fractions,
units via normalize_unit, and amount-based orders ("Rs 20 worth").
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.market.quote import WantedLine
from app.pipeline.names import EN_TO_ROMAN, SYNONYMS
from app.pipeline.numbers import CURRENCY_WORDS, parse_number
from app.pipeline.units import normalize_unit

__all__ = [
    "FILLER_WORDS",
    "FRACTIONS",
    "leftover_needs_spark",
    "parse_order",
]

FILLER_EN = frozenset({
    "and", "also", "plus", "with", "then", "next", "please", "give", "me",
    "want", "need", "take", "add", "some", "the", "of", "for", "to",
    "worth", "um", "uh",
})

FILLER_TA = frozenset({
    "உம்", "மற்றும்", "அப்புறம்", "அப்புறமா", "கொஞ்சம்", "கொடு",
    "கொடுங்க", "வேணும்", "வேண்டும்", "எடு", "சேர்", "பிறகு", "கூட",
    "சரி", "அது", "இது", "வந்து", "ம்", "appuram", "apram",
})

FILLER_HI = frozenset({
    "भी", "और", "फिर", "अगला", "कृपया", "चाहिए", "दीजिए", "थोड़ा",
    "का", "के", "की", "को", "से", "में", "पर", "ने", "bhi", "aur",
})

FILLER_WORDS = frozenset(FILLER_EN | FILLER_TA | FILLER_HI)

FRACTIONS: dict[str, Decimal] = {
    "half": Decimal("0.5"),
    "அரை": Decimal("0.5"),
    "arai": Decimal("0.5"),
    "आधा": Decimal("0.5"),
    "aadha": Decimal("0.5"),
    "adha": Decimal("0.5"),
    "ஒன்றரை": Decimal("1.5"),
    "ondrai": Decimal("1.5"),
    "onrai": Decimal("1.5"),
    "ondarai": Decimal("1.5"),
    "डेढ़": Decimal("1.5"),
    "देढ़": Decimal("1.5"),
    "dedh": Decimal("1.5"),
    "derh": Decimal("1.5"),
    "கால்": Decimal("0.25"),
    "kaal": Decimal("0.25"),
    "पाव": Decimal("0.25"),
    "pav": Decimal("0.25"),
    "paav": Decimal("0.25"),
    "quarter": Decimal("0.25"),
    "முக்கால்": Decimal("0.75"),
    "mukkaal": Decimal("0.75"),
    "mukkal": Decimal("0.75"),
    "पौना": Decimal("0.75"),
    "पौने": Decimal("0.75"),
    "पौणे": Decimal("0.75"),
    "pauna": Decimal("0.75"),
    "paune": Decimal("0.75"),
    "paone": Decimal("0.75"),
}

_TAMIL_SUFFIXES = ("க்காக", "க்கு")
_HINDI_SUFFIXES = ("को", "का", "के", "की", "से", "में", "पर", "ने")
_BENGALI_SUFFIXES = ("কে", "তে")

_STRIP_CHARS = ".,;:!?\"'()[]{}"
_TOKEN_SPLIT_RE = re.compile(r"\d[\d.,]*|[^\d\s]+", re.UNICODE)
_DOT_RE = re.compile(r"(?<!\d)\.(?!\d)", re.UNICODE)


def _norm(text: str) -> str:
    return text.lower().replace("\u093c", "").strip()


def strip_suffix(word: str) -> str:
    """Remove one stuck case suffix (Tamil/Hindi/Bengali) or English 's."""
    low = word.lower()
    if low.endswith("'s") and len(low) > 3:
        return word[:-2]
    for suf in _TAMIL_SUFFIXES:
        if low.endswith(suf) and len(low) > len(suf) + 1:
            return word[:-len(suf)]
    for suf in _HINDI_SUFFIXES:
        if low.endswith(suf) and len(low) > len(suf) + 1:
            return word[:-len(suf)]
    for suf in _BENGALI_SUFFIXES:
        if low.endswith(suf) and len(low) > len(suf) + 1:
            return word[:-len(suf)]
    return word


def _field(item, name: str):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _shop_unit(item) -> str | None:
    lines = _field(item, "price_lines") or []
    for line in lines:
        price = _field(line, "price")
        per_amount = _field(line, "per_amount")
        unit = _field(line, "unit")
        if price is not None and per_amount is not None and unit is not None:
            try:
                if per_amount == 0:
                    continue
            except TypeError:
                continue
            return unit
    return None


def _build_aliases(price_list_items) -> dict[str, int]:
    """Normalized alias -> price-list index. Ambiguous aliases are dropped."""
    candidates: dict[str, list[int]] = {}

    def add(alias: str | None, idx: int) -> None:
        if not alias:
            return
        key = _norm(alias)
        if not key:
            return
        candidates.setdefault(key, []).append(idx)
        if key.isascii():
            if not key.endswith("s"):
                candidates.setdefault(key + "s", []).append(idx)
            elif len(key) > 2:
                candidates.setdefault(key[:-1], []).append(idx)

    for idx, item in enumerate(price_list_items):
        en = str(_field(item, "name_en") or "")
        local = str(_field(item, "name_local") or "")
        add(en, idx)
        if local and _norm(local) != _norm(en):
            add(local, idx)
        roman = EN_TO_ROMAN.get(en.strip().lower())
        if roman:
            add(roman, idx)
            bits = roman.split()
            if len(bits) > 1:
                add(bits[-1], idx)
        for name in (en, local):
            bits = name.split()
            if len(bits) > 1:
                add(bits[-1], idx)
    for syn, canon in SYNONYMS.items():
        key = _norm(canon)
        for idx, item in enumerate(price_list_items):
            en = str(_field(item, "name_en") or "")
            if _norm(en) == key:
                add(syn, idx)
    resolved: dict[str, int] = {}
    for alias, indices in candidates.items():
        unique = sorted(set(indices))
        if len(unique) == 1:
            resolved[alias] = unique[0]
            continue
        names = {_norm(str(_field(price_list_items[i], "name_en") or ""))
                 for i in unique}
        if len(names) == 1:
            resolved[alias] = unique[0]
    return resolved


def _tokenize(text: str) -> tuple[list[str], list[int], list[str]]:
    """Split text into parse tokens with original-word mapping."""
    orig_words = text.split()
    display = [w.strip(_STRIP_CHARS) for w in orig_words]
    parse_tokens: list[str] = []
    to_orig: list[int] = []
    for pos, raw in enumerate(orig_words):
        piece = raw.lower().replace("/-", " rupees ")
        piece = piece.replace("/", " ").replace("-", " ")
        piece = piece.replace("—", " ").replace("–", " ")
        piece = piece.replace("₹", " ₹ ")
        piece = _DOT_RE.sub(" ", piece)
        for chunk in piece.split():
            for sub in _TOKEN_SPLIT_RE.findall(chunk):
                cleaned = sub.strip(_STRIP_CHARS)
                if cleaned:
                    parse_tokens.append(cleaned)
                    to_orig.append(pos)
    return parse_tokens, to_orig, display


def _is_currency(token: str) -> bool:
    if token in CURRENCY_WORDS:
        return True
    return strip_suffix(token) in CURRENCY_WORDS


def _find_number(tokens: list[str], start: int, end: int,
                 decimal_comma: bool,
                 ) -> tuple[Decimal, int, int] | None:
    for stop in range(end, start, -1):
        for width in (4, 3, 2, 1):
            begin = stop - width
            if begin < start:
                continue
            if width == 1:
                single = tokens[begin]
                if single in FRACTIONS:
                    return (FRACTIONS[single], begin, stop)
                if single in ("a", "an"):
                    return (Decimal(1), begin, stop)
            value = parse_number(" ".join(tokens[begin:stop]),
                                 decimal_comma=decimal_comma)
            if value is not None:
                return (value, begin, stop)
    return None


def _unit_at(token: str) -> tuple[str | None, Decimal]:
    return normalize_unit(token)


def _default_for_qty(item, qty: Decimal) -> tuple[Decimal, str | None]:
    shop_unit = _shop_unit(item)
    if shop_unit is None:
        return (qty, None)
    if shop_unit in ("kg", "g"):
        return (qty, "g" if qty >= 10 else "kg")
    if shop_unit in ("l", "ml"):
        return (qty, "ml" if qty >= 10 else "l")
    if shop_unit == "dozen":
        return (qty / Decimal(12), "dozen")
    return (qty, shop_unit)


def _default_for_single(item) -> tuple[Decimal, str | None]:
    shop_unit = _shop_unit(item)
    if shop_unit is None:
        return (Decimal(1), None)
    if shop_unit in ("kg", "g"):
        return (Decimal(1), "kg")
    if shop_unit in ("l", "ml"):
        return (Decimal(1), "l")
    return (Decimal(1), shop_unit)


def leftover_needs_spark(leftover_words: list[str]) -> bool:
    """True when leftovers hold anything beyond filler words."""
    for word in leftover_words:
        if _norm(word) not in FILLER_WORDS:
            return True
    return False


def parse_order(text: str, price_list_items, language: str | None = "en",
                ) -> tuple[list[WantedLine], list[str]]:
    """Parse an order into wanted lines plus leftover original words."""
    items = list(price_list_items or [])
    decimal_comma = False
    try:
        from app.languages import get_language

        decimal_comma = bool(get_language(language or "en").decimal_comma)
    except (KeyError, ImportError, AttributeError):
        decimal_comma = False
    aliases = _build_aliases(items)
    tokens, to_orig, display = _tokenize(text or "")
    occurrences: list[tuple[int, int, int]] = []
    pos = 0
    while pos < len(tokens):
        hit = None
        for width in (3, 2, 1):
            if pos + width > len(tokens):
                continue
            phrase = " ".join(tokens[pos:pos + width])
            key = _norm(phrase)
            if key in aliases:
                hit = (width, aliases[key])
                break
            words = phrase.split()
            stripped = strip_suffix(words[-1])
            if stripped != words[-1]:
                alt = " ".join([*words[:-1], stripped])
                key2 = _norm(alt)
                if key2 in aliases:
                    hit = (width, aliases[key2])
                    break
        if hit is None:
            pos += 1
        else:
            width, idx = hit
            occurrences.append((pos, pos + width, idx))
            pos += width
    consumed: set[int] = {i for i, tok in enumerate(tokens)
                          if tok in FILLER_WORDS}
    lines: list[WantedLine] = []
    prev_end = 0
    for start, stop, idx in occurrences:
        item = items[idx]
        name_en = str(_field(item, "name_en") or "")
        found = _find_number(tokens, prev_end, start, decimal_comma)
        currencies = [k for k in range(prev_end, start)
                      if _is_currency(tokens[k])]
        if found is not None and currencies:
            amount = found[0]
            for k in range(found[1], found[2]):
                consumed.add(k)
            for k in currencies:
                consumed.add(k)
            for k in range(start, stop):
                consumed.add(k)
            if amount > 0:
                lines.append(WantedLine(name_en=name_en, qty=None,
                                        unit=None, source="local",
                                        amount=amount))
            prev_end = stop
            continue
        if found is not None:
            qty, begin, end = found
            unit_idx = None
            canonical = None
            factor = Decimal(1)
            for k in range(end, start):
                got, scale = _unit_at(tokens[k])
                if got is not None:
                    unit_idx, canonical, factor = k, got, scale
                    break
            if canonical is not None:
                qty = qty * factor
                unit: str | None = canonical
                consumed.add(unit_idx)  # type: ignore[arg-type]
            else:
                qty, unit = _default_for_qty(item, qty)
            for k in range(begin, end):
                consumed.add(k)
            for k in range(start, stop):
                consumed.add(k)
            if qty > 0:
                lines.append(WantedLine(name_en=name_en, qty=qty,
                                        unit=unit, source="local"))
            prev_end = stop
            continue
        unit_idx = None
        canonical = None
        factor = Decimal(1)
        for k in range(prev_end, start):
            got, scale = _unit_at(tokens[k])
            if got is not None:
                unit_idx, canonical, factor = k, got, scale
        if canonical is not None:
            for k in range(start, stop):
                consumed.add(k)
            consumed.add(unit_idx)  # type: ignore[arg-type]
            lines.append(WantedLine(name_en=name_en, qty=Decimal(1) * factor,
                                    unit=canonical, source="local"))
            prev_end = stop
            continue
        for k in range(start, stop):
            consumed.add(k)
        qty, unit = _default_for_single(item)
        lines.append(WantedLine(name_en=name_en, qty=qty, unit=unit,
                                source="local"))
        prev_end = stop
    leftover: list[str] = []
    for orig_idx, word in enumerate(display):
        if not word:
            continue
        owned = [i for i, owner in enumerate(to_orig) if owner == orig_idx]
        if not owned:
            continue
        if any(i not in consumed for i in owned):
            leftover.append(word)
    return (lines, leftover)
