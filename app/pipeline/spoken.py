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
  keeps the model's names. When the model name is itself a known item
  for something else (banana claimed, poosani heard), nothing is
  renamed: the blocking NAME_NOT_NEAR_PRICE check flags it instead.
  Prices are never touched.
"""

from __future__ import annotations

import re

from app.pipeline.names import (
    CANONICAL_NAMES,
    EN_TO_ROMAN,
    QUALIFIER_EN,
    SYNONYMS,
    TAMIL_SYNONYMS,
    VARIETY_ALIASES,
    alias_hit_in_text,
    canonical_local_name,
    collapse_repeated_runs,
    find_items_in_text,
    find_name_in_text,
    is_word_char,
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

# Filler words around the spoken name ("So, sev vazhai இன்னைக்கு rate
# rate 110"): skipped wherever they appear in the name portion, so the
# seller's item words stand alone. Never item names. Task 165: "date"
# is rate mis-heard, ரேட்/ரேட்டு its Tamil-script forms.
_FILLER_WORDS: frozenset[str] = frozenset({
    "so", "rate", "rates", "date", "dates", "today", "innikku",
    "innaikku", "இன்னைக்கு", "இன்று", "ரேட்", "ரேட்டு",
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


def _is_filler(token: str) -> bool:
    return token.casefold() in _FILLER_WORDS


def _is_leading_noise(token: str) -> bool:
    """Unit/currency/fraction/filler words opening a span.

    A per-item span can open with the previous price's tail ("kilo."
    after "110 ரூபாய் கிலோ. kilo"): those words are skipped until the
    item's own words begin. Numbers are never skipped, so a span that
    opens with a price still yields "".
    """
    word = _clean_token(token)
    if not word:
        return True
    lowered = word.lower()
    if lowered in _FILLER_WORDS:
        return True
    if (lowered in _UNIT_STOP_WORDS
            or lowered in _CURRENCY_STOP_WORDS
            or lowered in _FRACTION_STOP_WORDS):
        return True
    return normalise_unit(lowered) is not None


# Characters stripped around a per-item proof span.
SPAN_STRIP_CHARS = " .,;:!?\"'()[]{}।॥·/—–-"


def strip_span_leading(text: str, said_start: int) -> tuple[str, int]:
    """Drop a span's leading punctuation, fillers and price-tail words.

    Leading punctuation, filler words (So, rate) and unit/currency
    echoes from the previous price ("kilo.") are dropped, but never
    at or past said_start, so the item's own price phrase always
    stays. Returns (stripped text, dropped char count).
    """
    cut = 0
    pos = 0
    end = len(text)
    while pos < end:
        while pos < end and text[pos] in SPAN_STRIP_CHARS:
            pos += 1
        tok_start = pos
        while pos < end and text[pos] not in SPAN_STRIP_CHARS:
            pos += 1
        if pos == tok_start:
            cut = pos
            break
        token = text[tok_start:pos]
        if pos <= said_start and _is_leading_noise(token):
            cut = pos
            continue
        cut = tok_start
        break
    return (text[cut:], cut)


def _is_known_name_exact(text: str) -> bool:
    """True when text exactly names a known item (Task 165).

    Canonical, synonym, romanised and Tamil-script names plus
    variety nicknames ("sev vazhai") count; substring hits do not,
    so "sev vazhai மூத்திபத்து" is not a known name.
    """
    lowered = " ".join(text.lower().split())
    if lowered and (lowered in CANONICAL_NAMES or lowered in SYNONYMS
                    or lowered in _ROMAN_TO_EN
                    or lowered in VARIETY_ALIASES):
        return True
    stripped = " ".join(text.split())
    return bool(stripped) and (stripped in TAMIL_SYNONYMS
                               or stripped in _TAMIL_TO_EN)


def _is_unclear_number(token: str, kept: list[str], next_token: str) -> bool:
    """True when a token is a mis-heard number word (Task 165).

    Mirrors the UNCLEAR_NUMBER check: a token right before a
    currency word that parses as no number and no unit ("மூத்திபத்து"
    for 110 before ரூபா). A token naming a known item, alone or
    with the words kept so far ("sev vazhai" before a bare
    currency), is the item's own words, never a number.
    """
    if not next_token or next_token.casefold() not in _CURRENCY_STOP_WORDS:
        return False
    if _is_known_name_exact(token):
        return False
    return not _is_known_name_exact(" ".join([*kept, token]))


def spoken_item_name(span: str | None) -> str:
    """Item words of a spoken span, deterministically.

    The words before the first quantity/unit/price token, with
    punctuation stripped, merged repeats halved ("vazhaiwazhai" ->
    "vazhai") and consecutive repeats collapsed
    ("உருளைக்கிழங்கு,உருளைக்கிழங்கு" -> once, "கிறன் கிறன் ஃப்ரூட்"
    -> "கிறன் ஃப்ரூட்"). The seller's script and case are kept.
    Filler words (So, இன்னைக்கு, rate/date, today) are skipped, as
    is a previous price's tail opening the span ("kilo. Nendran" ->
    "Nendran"). A mis-heard number word before a currency word
    ("மூத்திபத்து ரூபா") ends the name like a heard number does.
    A span that opens with a price ("இருபத்தைந்து.") yields "".
    """
    if not span:
        return ""
    cleaned = [collapse_repeated_runs(_clean_token(raw))
               for raw in _SPLIT_RE.split(span)]
    kept: list[str] = []
    for idx, token in enumerate(cleaned):
        if not token:
            continue
        if _is_filler(token):
            continue
        if is_stop_token(token):
            if kept or not _is_leading_noise(token):
                break
            continue
        following = ""
        for later in cleaned[idx + 1:]:
            if later:
                following = later
                break
        if _is_unclear_number(token, kept, following):
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


def _alias_key_said(key: str, lowered: str, raw: str) -> bool:
    """True when a variety-nickname key occurs in the span text.

    Latin keys match at the start of a token case-insensitively;
    Tamil-script keys match as whole words only, so பூசணி inside
    தர்பூசணி does not count.
    """
    if key.isascii():
        wanted = key.lower()
        start = 0
        while True:
            idx = lowered.find(wanted, start)
            if idx < 0:
                return False
            before = lowered[idx - 1] if idx > 0 else " "
            if not is_word_char(before):
                return True
            start = idx + 1
    haystack = " ".join(raw.split())
    start = 0
    while True:
        idx = haystack.find(key, start)
        if idx < 0:
            return False
        before = haystack[idx - 1] if idx > 0 else " "
        end = idx + len(key)
        after = haystack[end] if end < len(haystack) else " "
        if not is_word_char(before) and not is_word_char(after):
            return True
        start = idx + 1


def _model_variety_said(model_variety: str, base_en: str | None,
                        text: str) -> bool:
    """True when the model's variety word is said in the span text.

    The model's variety may come from elsewhere in a shared turn
    (Task 156): only a variety word inside the item's own span — a
    qualifier token or one of the base's variety nicknames — keeps
    the model's variety against the span's own qualifier.
    """
    want = normalize_qualifier(model_variety) or model_variety.strip().lower()
    if not want or not (text or "").strip():
        return False
    for raw in _SPLIT_RE.split(text):
        token = _clean_token(raw).lower()
        if not token:
            continue
        if token == want or normalize_qualifier(token) == want:
            return True
    base = (base_en or "").strip().lower()
    if base:
        lowered = " ".join(text.lower().split())
        for key, (alias_base, alias_var) in VARIETY_ALIASES.items():
            if alias_base != base or alias_var != want:
                continue
            if _alias_key_said(key, lowered, text):
                return True
    return False


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


def _plain_poosani_without_yellow(*texts: str) -> bool:
    """True when the texts name plain poosani but never yellow pumpkin.

    Plain பூசணி/பூசணிக்காய்/poosani is ash gourd (white pumpkin) in
    Tamil Nadu markets; yellow pumpkin is மஞ்சள் பூசணி, parangi or
    பரங்கிக்காய். Whole-word glossary matching, so தர்பூசணி
    (watermelon) never counts as poosani and மஞ்சள் பூசணி reads as
    pumpkin, never ash gourd.
    """
    heard: set[str] = set()
    for text in texts:
        heard.update(name for _, name in find_items_in_text(text or ""))
    return "ash gourd" in heard and "pumpkin" not in heard


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
    poosani_fixed = False
    if (model_base == "pumpkin" and _plain_poosani_without_yellow(
            item.name_local, span, name_spoken)):
        # Task 160: the model called plain பூசணி "pumpkin"; it is ash
        # gourd. A naming fix only; the rest of this pass then runs
        # against the corrected base.
        item.name_en = "ash gourd"
        item.match_key = "ash gourd"
        model_base = "ash gourd"
        poosani_fixed = True
    if not span and not name_spoken:
        return poosani_fixed
    spoken, _, _ = _derive_from(span or name_spoken, model_base,
                                name_spoken or None)
    if not spoken:
        return poosani_fixed
    direct = _direct_base(spoken)
    alias = alias_hit_in_text(spoken)
    if (direct is not None and direct != model_base
            and model_base in CANONICAL_NAMES):
        # The span names a different known item than the model claimed
        # (poosani heard, banana claimed): never rename silently
        # across two known items; NAME_NOT_NEAR_PRICE flags it. A model
        # variety from elsewhere in the turn is dropped, so the flag
        # names the plain claimed item.
        claimed_variety = (item.variety or "").strip()
        if claimed_variety and not _model_variety_said(
                claimed_variety, model_base, span or name_spoken):
            item.variety = None
            return True
        return poosani_fixed
    if direct is None and alias is not None and alias[0] != model_base:
        return poosani_fixed
    final_base = direct if direct is not None else model_base
    base_changed = direct is not None and direct != model_base
    model_variety = (item.variety or "").strip()
    new_variety: str | None = None
    if alias is not None and alias[0] == final_base:
        if (alias[1] != _normalize(model_variety)
                and (not _model_variety_said(model_variety, final_base,
                                             span or name_spoken)
                     or _alias_var_wins(alias[1], model_variety))):
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
    return changed or poosani_fixed


def apply_spoken_names(items: list, *, language: str = "ta") -> int:
    """Apply :func:`apply_spoken_name` to each item; returns changed count."""
    count = 0
    for item in items or []:
        if apply_spoken_name(item, language=language):
            count += 1
    return count
