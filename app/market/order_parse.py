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
    VARIETY_ALIASES,
)
from app.pipeline.numbers import CURRENCY_WORDS, parse_number
from app.pipeline.units import normalize_unit

__all__ = [
    "FILLER_WORDS",
    "FRACTIONS",
    "SEPARATOR_WORDS",
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

# Words that split an order into one-item segments (Task 55). All are also
# filler, so they never surface as leftovers.
SEPARATOR_WORDS = frozenset({
    "and", "then", "um", "உம்", "அப்புறம்", "aur", "और",
})

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


def _build_variety_index() -> dict[str, tuple[str, str]]:
    """Normalized variety alias -> (name_en, variety), with plurals."""
    index: dict[str, tuple[str, str]] = {}
    for alias, pair in VARIETY_ALIASES.items():
        key = _norm(alias)
        if not key:
            continue
        for variant in _plural_variants(key):
            index.setdefault(variant, pair)
    return index


_VARIETY_INDEX = _build_variety_index()


def _shop_variety(item) -> str | None:
    raw = _field(item, "variety")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _display_name(item) -> str:
    name = str(_field(item, "name_en") or "")
    variety = _shop_variety(item)
    if variety:
        return f"{name} ({variety})"
    return name


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


def _lookup_variety(key: str, items) -> tuple[str, object]:
    """Match a variety nickname: ("item", idx), ("choose", [idx]) or none.

    An exact (name_en, variety) hit wins. With no exact hit a lone base
    item still matches (a "poovan" ask in a one-banana shop bills that
    banana); otherwise there is no match so the line is never guessed.
    """
    hit = _VARIETY_INDEX.get(key)
    if hit is None:
        return ("none", None)
    base, variety = hit
    want = variety.strip().lower()
    exact = [idx for idx, item in enumerate(items)
             if _shop_canon(item) == base
             and (_shop_variety(item) or "").strip().lower() == want]
    if len(exact) == 1:
        return ("item", exact[0])
    if len(exact) > 1:
        return ("choose", sorted(exact))
    lone = [idx for idx, item in enumerate(items)
            if _shop_canon(item) == base]
    if len(lone) == 1:
        return ("item", lone[0])
    return ("none", None)


def _lookup(key: str, exact: dict[str, int], items
            ) -> tuple[str, object]:
    """Match one normalized phrase: ("item", idx), ("choose", [idx]) or None.

    The phrase maps through the canonical names to name_en first; only
    then is the shop item found. A generic word shared by several shop
    items picks the item whose name_en is the generic canonical name
    (வெங்காயம் -> "onion"); with no exact one the caller asks "which
    one?" instead of dropping the line. The same item in several
    varieties always asks instead of picking one silently.
    """
    kind, payload = _lookup_variety(key, items)
    if kind != "none":
        return (kind, payload)
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
        varieties = {(_shop_variety(items[i]) or "").strip().lower()
                     for i in idxs}
        if len(varieties) == 1:
            return ("item", idxs[0])
        unique: list[int] = []
        seen: set[tuple[str, str]] = set()
        for idx in sorted(idxs):
            marker = (_norm(str(_field(items[idx], "name_en") or "")),
                      (_shop_variety(items[idx]) or "").strip().lower())
            if marker not in seen:
                seen.add(marker)
                unique.append(idx)
        return ("choose", unique)
    lasts = {_shop_canon(items[i]).split()[-1] for i in idxs}
    if len(lasts) == 1:
        shared = next(iter(lasts))
        if shared in CANONICAL_NAMES:
            for idx in idxs:
                if _shop_canon(items[idx]) == shared:
                    return ("item", idx)
    unique = []
    seen_names: set[str] = set()
    for idx in sorted(idxs):
        name = _norm(str(_field(items[idx], "name_en") or ""))
        if name not in seen_names:
            seen_names.add(name)
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


def _orig_segments(text: str) -> list[int]:
    """Segment id per whitespace-separated word of the raw text.

    A comma, a non-decimal full stop or a newline ends the segment
    after that word. Numeric commas ("2,000") and decimal points
    ("1.5") never split.
    """
    seg_ids: list[int] = []
    seg = 0
    for line_no, line in enumerate(text.splitlines()):
        if line_no > 0:
            seg += 1
        for raw in line.split():
            seg_ids.append(seg)
            word = raw.strip()
            stop = False
            if "," in word:
                head = word.replace(",", " ").strip()
                if not head or any(ch not in "0123456789. " for ch in head):
                    stop = True
            if _DOT_RE.search(word):
                stop = True
            if stop:
                seg += 1
    return seg_ids


def _split_segments(tokens: list[str], to_orig: list[int], text: str,
                    occ_spans: list[tuple[int, int]]) -> list[list[int]]:
    """Group token indexes into segments split on separators.

    Splits on commas, full stops and newlines (via the original
    words) and on SEPARATOR_WORDS. A separator word inside an item
    name ("then vazhai") never splits.
    """
    seg_ids = _orig_segments(text or "")
    inside = [False] * len(tokens)
    for begin, end in occ_spans:
        for idx in range(max(0, begin), min(len(tokens), end)):
            inside[idx] = True
    groups: dict[int, list[int]] = {}
    order: list[int] = []
    for idx in range(len(tokens)):
        owner = to_orig[idx] if idx < len(to_orig) else -1
        key = seg_ids[owner] if 0 <= owner < len(seg_ids) else -1
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(idx)
    segments: list[list[int]] = []
    for key in order:
        current: list[int] = []
        for idx in groups[key]:
            if _norm(tokens[idx]) in SEPARATOR_WORDS and not inside[idx]:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(idx)
        if current:
            segments.append(current)
    return segments


def _match_number_at(tokens: list[str], pos: int, end: int,
                     inside: list[bool], decimal_comma: bool,
                     ) -> tuple[Decimal, int] | None:
    """Longest number phrase starting exactly at pos, or None."""
    for width in (4, 3, 2, 1):
        stop = pos + width
        if stop > end:
            continue
        if any(inside[idx] for idx in range(pos, stop)):
            continue
        span = tokens[pos:stop]
        if any(tok in FILLER_WORDS for tok in span):
            continue
        if width == 1:
            single = span[0]
            if single in FRACTIONS:
                return (FRACTIONS[single], stop)
            if single in ("a", "an"):
                return (Decimal(1), stop)
        value = parse_number(" ".join(span), decimal_comma=decimal_comma)
        if value is not None:
            return (value, stop)
    return None


def _quantity_groups(tokens: list[str], idxs: list[int],
                     inside: list[bool], decimal_comma: bool,
                     ) -> list[tuple[str, Decimal, str | None, int, int]]:
    """Quantity groups in one segment, in token order.

    Each group is (kind, value, unit, begin, end) with kind "qty" or
    "amount". A number pairs with an adjacent unit ("2 kg") or with
    an adjacent currency word ("₹20", "20 ரூபாய்க்கு"); a lone unit
    word means one of that unit.
    """
    groups: list[tuple[str, Decimal, str | None, int, int]] = []
    seg_set = set(idxs)
    pos = 0
    while pos < len(idxs):
        tok_idx = idxs[pos]
        if inside[tok_idx] or tokens[tok_idx] in FILLER_WORDS:
            pos += 1
            continue
        hit = _match_number_at(tokens, tok_idx, idxs[-1] + 1, inside,
                               decimal_comma)
        if hit is not None:
            value, stop = hit
            if any(not inside[i] and _is_currency(tokens[i])
                   for i in range(tok_idx, stop)):
                groups.append(("amount", value, None, tok_idx, stop))
                while pos < len(idxs) and idxs[pos] < stop:
                    pos += 1
                continue
            followed = stop if stop in seg_set else None
            if followed is not None and not inside[followed]:
                got, scale = _unit_at(tokens[followed])
                if got is not None:
                    groups.append(("qty", value * scale, got, tok_idx,
                                   followed + 1))
                    while pos < len(idxs) and idxs[pos] <= followed:
                        pos += 1
                    continue
            if followed is not None and not inside[followed] and _is_currency(
                    tokens[followed]):
                groups.append(("amount", value, None, tok_idx, followed + 1))
                while pos < len(idxs) and idxs[pos] <= followed:
                    pos += 1
                continue
            prev = tok_idx - 1
            if (prev in seg_set and not inside[prev]
                    and _is_currency(tokens[prev])):
                groups.append(("amount", value, None, prev, stop))
                while pos < len(idxs) and idxs[pos] < stop:
                    pos += 1
                continue
            groups.append(("qty", value, None, tok_idx, stop))
            while pos < len(idxs) and idxs[pos] < stop:
                pos += 1
            continue
        got, scale = _unit_at(tokens[tok_idx])
        if got is not None:
            groups.append(("qty", Decimal(1) * scale, got, tok_idx,
                           tok_idx + 1))
        pos += 1
    return groups


def _pair_segment(occs, groups):
    """Pair each item occurrence with at most one quantity group.

    One item takes the nearest group on either side (ties go to the
    group before the item). Several items pair alternately: a
    quantity first means quantity-before, an item first means
    quantity-after. Unpaired groups stay out so they surface as
    leftovers; unpaired items bill one.
    """
    if not occs:
        return []
    if len(occs) == 1:
        start, stop, _, _ = occs[0]
        best = None
        best_key = None
        for group in groups:
            _, _, _, begin, end = group
            gap = start - end if end <= start else begin - stop
            key = (gap, 0 if end <= start else 1)
            if best_key is None or key < best_key:
                best_key = key
                best = group
        return [(occs[0], best)]
    # Alternating pairs serve both orders: quantity-first
    # ("2 kg onion, half kg ginger") and item-first
    # ("tomato 2 kg onion 1 kg").
    return [(occ, groups[pos] if pos < len(groups) else None)
            for pos, occ in enumerate(occs)]


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
    When nothing item-like remains, an unpaired quantity is shown
    as-is instead of being dropped silently.
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
    if out:
        return out
    return [word for word in leftover_words
            if _norm(word) and _norm(word) not in FILLER_WORDS
            and _norm(word) not in covered]


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
    inside = [False] * len(tokens)
    for begin, end in [(s, e) for s, e, _, _ in occurrences]:
        for idx in range(begin, end):
            inside[idx] = True
    lines: list[WantedLine] = []
    segments = _split_segments(tokens, to_orig, text or "",
                               [(s, e) for s, e, _, _ in occurrences])
    seg_of = [-1] * len(tokens)
    for seg_no, idxs in enumerate(segments):
        for idx in idxs:
            seg_of[idx] = seg_no
    for seg_no, seg_idxs in enumerate(segments):
        seg_occs = [occ for occ in occurrences if seg_of[occ[0]] == seg_no]
        groups = _quantity_groups(tokens, seg_idxs, inside, decimal_comma)
        pairs = _pair_segment(seg_occs, groups)
        for occ, group in pairs:
            start, stop, kind, payload = occ
            options: list[str] | None = None
            variety: str | None = None
            if kind == "choose":
                idxs = [i for i in payload  # type: ignore[union-attr]
                        if isinstance(i, int)]
                item = items[idxs[0]]
                name_en = " ".join(tokens[start:stop])
                options = [_display_name(items[i]) for i in idxs]
            else:
                item = items[payload]  # type: ignore[index]
                name_en = str(_field(item, "name_en") or "")
                variety = _shop_variety(item)
            for k in range(start, stop):
                consumed.add(k)
            if group is None:
                qty, unit = _default_for_single(item)
                lines.append(WantedLine(name_en=name_en, qty=qty,
                                        unit=unit, source="local",
                                        options=options, variety=variety))
                continue
            gkind, value, gunit, begin, end = group
            for k in range(begin, end):
                consumed.add(k)
            if gkind == "amount":
                if value > 0:
                    lines.append(WantedLine(name_en=name_en, qty=None,
                                            unit=None, source="local",
                                            amount=value, options=options,
                                            variety=variety))
                continue
            if gunit is not None:
                qty, unit = value, gunit
            else:
                qty, unit = _default_for_qty(item, value)
            if qty > 0:
                lines.append(WantedLine(name_en=name_en, qty=qty,
                                        unit=unit, source="local",
                                        options=options, variety=variety))
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
