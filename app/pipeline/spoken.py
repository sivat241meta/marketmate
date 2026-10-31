"""Seller's-words names: deterministic post-extraction renaming (Task 139).

The model's item names vary run to run, so after extraction each draft
item's names are re-derived from its own spoken span (the transcript
words behind "Play what you said", kept in ``proof.quote``):

* :func:`spoken_item_name` takes the words before the first
  quantity/unit/price token, stripping number words, units, currency,
  repeated words and punctuation.
* :func:`apply_spoken_name` compares that spoken name with the model's
  names. A spoken qualifier the model dropped (புது, சின்ன, sweet, ...),
  a spoken name for a different known item (கிறன் ஃப்ரூட் is muskmelon),
  or a garbled model name (செவ்வாழ வாழை) is replaced with the seller's
  own words; the variety becomes the English qualifier and the English
  name its base, so titles read "new potato" via the Task 136 helpers.
  A canonical model name for the same item is kept, and a missing span
  keeps the model's names. Prices are never touched.
"""

from __future__ import annotations

import re

from app.pipeline.names import (
    CANONICAL_NAMES,
    EN_TO_ROMAN,
    QUALIFIER_EN,
    SYNONYMS,
    TAMIL_SYNONYMS,
    alias_hit_in_text,
    canonical_local_name,
    find_name_in_text,
    normalize_qualifier,
)
from app.pipeline.numbers import parse_number
from app.pipeline.units import normalise_unit

_SPLIT_RE = re.compile(r"[\s,]+")
_STRIP_CHARS = ".,;:!?\"'()[]{}।॥·/—–-"

# Unit words that end the spoken name. normalise_unit() is also consulted,
# so this only lists the Tamil forms it does not cover plus common spoken
# variants (Task 139 contract list first).
_UNIT_STOP_WORDS: frozenset[str] = frozenset({
    "கிலோ", "kilo", "kilos", "kg", "kgs",
    "கிராம்", "gram", "grams", "gm", "g",
    "பீஸ்", "pees", "piece", "pieces", "pc", "pcs",
    "டஜன்", "dozen", "dozens",
    "கட்டு", "kattu", "kathu", "bunch", "bunches",
    "லிட்டர்", "liter", "liters", "litre", "litres", "l", "ml",
    "packet", "packets", "pack", "pkt", "பாக்கெட்",
    "மில்லி", "milli",
})

# Currency words that end the spoken name.
_CURRENCY_STOP_WORDS: frozenset[str] = frozenset({
    "ரூபா", "ரூபாய்", "rupees", "rupee", "rupai", "rs", "₹",
    "रुपया", "रुपये", "रुपए", "रूपए",
})

# Half/quarter words: quantities, never item names.
_FRACTION_STOP_WORDS: frozenset[str] = frozenset({
    "அரை", "arai", "ara", "half",
    "கால்", "kaal", "kal", "quarter",
    "முக்கால்", "mukkaal", "பாதி", "paathi",
})


def _clean_token(raw: str) -> str:
    return raw.strip(_STRIP_CHARS)


def is_stop_token(token: str) -> bool:
    """True when a span token starts the quantity/price tail.

    Number words in Tamil/Hindi/English (via the shared parser, so
    இருபத்தைந்து and முப்பத்தி stop), digits in any fused form (20,
    25.00, 1/2), units, currency and half/quarter words all stop.
    """
    word = _clean_token(token)
    if not word:
        return True
    lowered = word.lower()
    if (lowered in _UNIT_STOP_WORDS
            or lowered in _CURRENCY_STOP_WORDS
            or lowered in _FRACTION_STOP_WORDS):
        return True
    if normalise_unit(lowered) is not None:
        return True
    if any(char.isdigit() for char in word):
        return True
    return parse_number(word) is not None


def spoken_item_name(span: str | None) -> str:
    """Item words of a spoken span, deterministically.

    The words before the first quantity/unit/price token, with
    punctuation stripped and consecutive repeats collapsed
    ("உருளைக்கிழங்கு,உருளைக்கிழங்கு" -> once, "கிறன் கிறன் ஃப்ரூட்"
    -> "கிறன் ஃப்ரூட்"). The seller's script and case are kept.
    A span that opens with a price ("இருபத்தைந்து.") yields "".
    """
    if not span:
        return ""
    kept: list[str] = []
    for raw in _SPLIT_RE.split(span):
        token = _clean_token(raw)
        if not token:
            continue
        if is_stop_token(token):
            break
        if kept and token.casefold() == kept[-1].casefold():
            continue
        kept.append(token)
    return " ".join(kept)


_TAMIL_TO_EN: dict[str, str] = {ta: en for en, ta in CANONICAL_NAMES.items()}
_ROMAN_TO_EN: dict[str, str] = {roman.strip().lower(): en
                               for en, roman in EN_TO_ROMAN.items()}


def _direct_base(spoken: str) -> str | None:
    """Item named outright by the spoken words, if any.

    Canonical English names, synonyms, Tamil-script and romanised Tamil
    names count; variety nicknames (ujala, poovan, செவ்வாழை) do not.
    Unknown words yield None so the model's base is kept.
    """
    text = (spoken or "").strip()
    if not text:
        return None
    lowered = " ".join(text.lower().split())
    candidates = [lowered]
    if lowered.isascii() and lowered.endswith("s") and len(lowered) > 2:
        candidates.append(lowered[:-1])
    for cand in candidates:
        if cand in CANONICAL_NAMES:
            return cand
        if cand in SYNONYMS:
            return SYNONYMS[cand]
        if cand in _ROMAN_TO_EN:
            return _ROMAN_TO_EN[cand]
    stripped = " ".join(text.split())
    if stripped in TAMIL_SYNONYMS:
        return TAMIL_SYNONYMS[stripped]
    if stripped in _TAMIL_TO_EN:
        return _TAMIL_TO_EN[stripped]
    found = find_name_in_text(text)
    return found if found in CANONICAL_NAMES else None


def _token_qualifier(spoken: str, base_en: str | None) -> str | None:
    """English qualifier for qualifier words inside spoken words, if any.

    The first qualifier token wins (புது -> new, sweet -> sweet). A
    qualifier already inside the base name ("small" in "small onion")
    is dropped.
    """
    text = (spoken or "").strip()
    if not text:
        return None
    candidate: str | None = None
    for raw in _SPLIT_RE.split(text):
        token = _clean_token(raw).lower()
        if not token:
            continue
        hit = QUALIFIER_EN.get(token)
        if hit is not None:
            candidate = hit
            break
    if candidate is None:
        return None
    base_words = set((base_en or "").strip().lower().split())
    if candidate.lower() in base_words:
        return None
    return candidate


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def derive_spoken_name(span: str | None) -> tuple[str, str | None, str | None]:
    """(Spoken name, known base item, qualifier) for a span.

    The base is the item named outright, or the variety nickname's item
    when no outright name is heard. The qualifier is the nickname's
    variety first, else the first qualifier token, validated against
    the base (falling back to no base when nothing known is named).
    """
    spoken = spoken_item_name(span)
    direct = _direct_base(spoken)
    alias = alias_hit_in_text(spoken) if spoken else None
    if direct is not None:
        base: str | None = direct
    elif alias is not None:
        base = alias[0]
    else:
        base = None
    if alias is not None and alias[0] == base:
        qualifier = alias[1]
    else:
        qualifier = _token_qualifier(spoken, base)
    return (spoken, base, qualifier)


def _derive_from(span: str | None, model_base: str,
                 name_spoken: str | None = None
                 ) -> tuple[str, str | None, str | None]:
    """Derive from the span, rescued by name_spoken on conflict.

    The span is the contract; but when it names a different known item
    than the model while name_spoken agrees with the model (a quote
    spanning two items), name_spoken is the item's own words.
    """
    _, base, _ = derive_spoken_name(span)
    if base is not None and base != model_base and name_spoken:
        rescue = spoken_item_name(name_spoken)
        rescue_base, _ = _known_for(rescue)
        if rescue and rescue_base == model_base:
            return derive_spoken_name(name_spoken)
    return derive_spoken_name(span)


def _known_for(spoken: str) -> tuple[str | None, str | None]:
    """(Base, variety) the spoken words name outright or by nickname."""
    _, base, qualifier = derive_spoken_name(spoken)
    return (base, qualifier)


def _alias_var_wins(alias_var: str, model_variety: str) -> bool:
    """True when a nickname's variety replaces the model's.

    An explicitly said different variety (Krishnagiri over ujala) and a
    dual-variety line ("karpooravalli / thenvazhai") always win; an
    empty variety is filled, and an unmapped transliteration ("Sevvazh")
    is canonicalised to the nickname's English variety.
    """
    if not model_variety:
        return True
    if "/" in model_variety:
        return False
    mapped = normalize_qualifier(model_variety)
    return mapped is None or mapped == alias_var


def apply_spoken_name(item, *, language: str = "ta") -> bool:
    """Re-derive one draft item's names from its spoken span.

    Returns True when any of name_local, name_en, variety or match_key
    changed. The span is proof.quote, falling back to name_spoken; a
    missing span keeps the model's names. A variety nickname naming a
    different item than the model (ujala vs carrot) is left to the
    Task 97 flagged rename, which also protects seller-chosen names.
    Price lines, quantities and flags are never touched.
    """
    model_base = (item.name_en or "").strip().lower()
    span = (getattr(item.proof, "quote", "") or "").strip()
    name_spoken = (item.name_spoken or "").strip()
    if not span and not name_spoken:
        return False
    spoken, _, _ = _derive_from(span or name_spoken, model_base,
                                name_spoken or None)
    if not spoken:
        return False
    direct = _direct_base(spoken)
    alias = alias_hit_in_text(spoken)
    if direct is None and alias is not None and alias[0] != model_base:
        return False
    final_base = direct if direct is not None else model_base
    base_changed = direct is not None and direct != model_base
    model_variety = (item.variety or "").strip()
    new_variety: str | None = None
    if alias is not None and alias[0] == final_base:
        if (alias[1] != _normalize(model_variety)
                and _alias_var_wins(alias[1], model_variety)):
            new_variety = alias[1]
    else:
        token_var = _token_qualifier(spoken, final_base)
        if token_var is not None and token_var != _normalize(model_variety):
            new_variety = token_var
    same_item = ((direct is not None and direct == model_base)
                 or (alias is not None and alias[0] == model_base))
    canonical = canonical_local_name(final_base, language)
    model_garbled = (same_item and canonical is not None
                     and _normalize(item.name_local) != _normalize(canonical))
    changed = False
    if new_variety is not None:
        item.variety = new_variety
        changed = True
    elif model_variety:
        mapped = normalize_qualifier(model_variety)
        if mapped is not None and mapped != model_variety:
            item.variety = mapped
            changed = True
    if base_changed:
        assert direct is not None
        item.name_en = direct
        item.match_key = direct
        changed = True
    if (_normalize(spoken) != _normalize(item.name_local)
            and (base_changed or new_variety is not None or model_garbled)):
        item.name_local = spoken
        changed = True
    return changed


def apply_spoken_names(items: list, *, language: str = "ta") -> int:
    """Apply :func:`apply_spoken_name` to each item; returns changed count."""
    count = 0
    for item in items or []:
        if apply_spoken_name(item, language=language):
            count += 1
    return count
