"""Fast local order parser (no AI) for live voice billing (Task 36).

Matches item names from today's published price list (name_en, name_local,
romanised Tamil and SYNONYMS), numbers via the existing parsers, fractions,
units via normalize_unit, and amount-based orders ("Rs 20 worth").
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.market.quote import WantedLine
from app.pipeline.names import (
    CANONICAL_NAMES,
    EN_TO_ROMAN,
    SYNONYMS,
)
from app.pipeline.numbers import CURRENCY_WORDS, parse_number
from app.pipeline.units import normalize_unit

__all__ = [
    "FILLER_WORDS",
    "FRACTIONS",
    "item_like_leftovers",
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


def _plural_variants(key: str):
    """A normalized alias plus its English singular/plural twin."""
    yield key
    if key.isascii():
        if not key.endswith("s"):
            yield key + "s"
        elif len(key) > 2:
            yield key[:-1]


def _build_canonical_index() -> dict[str, set[str]]:
    """Normalized alias -> canonical name_en set, from names.py only.

    Every canonical item contributes its full English, local-script and
    romanised names plus the last word of each multi-word name (so a
    generic வெங்காயம் maps to both onion and small onion). SYNONYMS map
    to their canonical name.
    """
    index: dict[str, set[str]] = {}

    def add(alias: str | None, canon: str) -> None:
        if not alias:
            return
        key = _norm(alias)
        if not key:
            return
        for variant in _plural_variants(key):
            index.setdefault(variant, set()).add(canon)

    for canon, local in CANONICAL_NAMES.items():
        add(canon, canon)
        add(local, canon)
        roman = EN_TO_ROMAN.get(canon.strip().lower())
        if roman:
            add(roman, canon)
            bits = roman.split()
            if len(bits) > 1:
                add(bits[-1], canon)
        for name in (canon, local):
            bits = name.split()
            if len(bits) > 1:
                add(bits[-1], canon)
    for syn, canon in SYNONYMS.items():
        if canon in CANONICAL_NAMES:
            add(syn, canon)
    return index


_CANONICAL_INDEX = _build_canonical_index()


def _shop_canon(item) -> str:
    """An item's canonical name_en (synonym-aware, normalized)."""
    key = _norm(str(_field(item, "name_en") or ""))
    return SYNONYMS.get(key, key)


def _shop_exact(items) -> dict[str, int]:
    """Normalized full shop name (English or local) -> item index."""
    exact: dict[str, int] = {}
    for idx, item in enumerate(items):
        for name in (str(_field(item, "name_en") or ""),
                     str(_field(item, "name_local") or "")):
            key = _norm(name)
            if not key:
                continue
            for variant in _plural_variants(key):
                exact.setdefault(variant, idx)
    return exact


def _lookup(key: str, exact: dict[str, int], items
            ) -> tuple[str, object]:
    """Match one normalized phrase: ("item", idx), ("choose", [idx]) or None.

    The phrase maps through the canonical names to name_en first; only
    then is the shop item found. A generic word shared by several shop
    items picks the item whose name_en is the generic canonical name
    (வெங்காயம் -> "onion"); with no exact one the caller asks "which
    one?" instead of dropping the line.
    """
    idxs: list[int] = []
    if key in exact:
        idxs.append(exact[key])
    for canon in _CANONICAL_INDEX.get(key, ()):
        for idx, item in enumerate(items):
            if _shop_canon(item) == canon and idx not in idxs:
                idxs.append(idx)
    if not idxs:
        return ("none", None)
    if len(idxs) == 1:
        return ("item", idxs[0])
    names = {_norm(str(_field(items[i], "name_en") or "")) for i in idxs}
    if len(names) == 1:
        return ("item", idxs[0])
    lasts = {_shop_canon(items[i]).split()[-1] for i in idxs}
    if len(lasts) == 1:
        shared = next(iter(lasts))
        if shared in CANONICAL_NAMES:
            for idx in idxs:
                if _shop_canon(items[idx]) == shared:
                    return ("item", idx)
    unique: list[int] = []
    seen: set[str] = set()
    for idx in sorted(idxs):
        name = _norm(str(_field(items[idx], "name_en") or ""))
        if name not in seen:
            seen.add(name)
            unique.append(idx)
    return ("choose", unique)


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


def item_like_leftovers(leftover_words: list[str],
                        wanted_names=()) -> list[str]:
    """Leftover words that look like an item, for the "Not understood" note.

    Drops filler words, numbers, units, currency words and anything
    already on the bill, so only genuinely unheard words are shown.
    """
    covered: set[str] = set()
    for name in wanted_names or ():
        for bit in str(name or "").lower().split():
            covered.add(bit)
            if bit.endswith("s") and len(bit) > 2:
                covered.add(bit[:-1])
            else:
                covered.add(bit + "s")
    out: list[str] = []
    for word in leftover_words:
        norm = _norm(word)
        if not norm or norm in FILLER_WORDS or norm in covered:
            continue
        if parse_number(word) is not None:
            continue
        unit, _ = normalize_unit(word)
        if unit is not None:
            continue
        if _is_currency(norm):
            continue
        out.append(word)
    return out


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
    exact = _shop_exact(items)
    tokens, to_orig, display = _tokenize(text or "")
    occurrences: list[tuple[int, int, str, object]] = []
    pos = 0
    while pos < len(tokens):
        hit = None
        for width in (3, 2, 1):
            if pos + width > len(tokens):
                continue
            phrase = " ".join(tokens[pos:pos + width])
            kind, payload = _lookup(_norm(phrase), exact, items)
            if kind != "none":
                hit = (width, kind, payload)
                break
            words = phrase.split()
            stripped = strip_suffix(words[-1])
            if stripped != words[-1]:
                alt = " ".join([*words[:-1], stripped])
                kind, payload = _lookup(_norm(alt), exact, items)
                if kind != "none":
                    hit = (width, kind, payload)
                    break
        if hit is None:
            pos += 1
        else:
            width, kind, payload = hit
            occurrences.append((pos, pos + width, kind, payload))
            pos += width
    consumed: set[int] = {i for i, tok in enumerate(tokens)
                          if tok in FILLER_WORDS}
    lines: list[WantedLine] = []
    prev_end = 0
    for start, stop, kind, payload in occurrences:
        options: list[str] | None = None
        if kind == "choose":
            idxs = [i for i in payload if isinstance(i, int)]  # type: ignore[union-attr]
            item = items[idxs[0]]
            name_en = " ".join(tokens[start:stop])
            options = [str(_field(items[i], "name_en") or "") for i in idxs]
        else:
            item = items[payload]  # type: ignore[index]
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
                                        amount=amount, options=options))
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
                                        unit=unit, source="local",
                                        options=options))
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
                                    unit=canonical, source="local",
                                    options=options))
            prev_end = stop
            continue
        for k in range(start, stop):
            consumed.add(k)
        qty, unit = _default_for_single(item)
        lines.append(WantedLine(name_en=name_en, qty=qty, unit=unit,
                                source="local", options=options))
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
