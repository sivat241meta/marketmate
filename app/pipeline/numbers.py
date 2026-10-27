from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_DIGIT_RE = re.compile(r"^\d+(?:\.\d+)?$")
_DIGIT_SPAN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ASCII_RUN_RE = re.compile(r"[A-Za-z]+")
_TAMIL_RUN_RE = re.compile(r"[\u0B80-\u0BFF]+")

_ENGLISH_ONES: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}

_ENGLISH_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_ENGLISH_NUMBER_WORDS = (
    set(_ENGLISH_ONES) | set(_ENGLISH_TENS) | {"hundred", "a", "an"}
)

# Romanised Tamil and Tamil-script number words. Spoken markets mix
# spellings, so common variants share one value.
_TAMIL: dict[str, int] = {
    "oru": 1, "onnu": 1, "ஒரு": 1, "ஒன்று": 1, "ஒன்னு": 1,
    "rendu": 2, "irandu": 2, "ரெண்டு": 2, "இரண்டு": 2,
    "moonu": 3, "moondru": 3, "moonru": 3, "மூணு": 3, "மூன்று": 3,
    "naalu": 4, "naanku": 4, "nangu": 4, "நாலு": 4, "நான்கு": 4,
    "anju": 5, "ainthu": 5, "anchu": 5, "அஞ்சு": 5, "ஐந்து": 5,
    "aaru": 6, "ஆறு": 6,
    "ezhu": 7, "yezhu": 7, "ஏழு": 7,
    "ettu": 8, "எட்டு": 8,
    "onpathu": 9, "onbadhu": 9, "ombathu": 9, "ஒன்பது": 9,
    "pathu": 10, "pattu": 10, "பத்து": 10,
    "pathinonnu": 11, "பதினொன்று": 11,
    "pannendu": 12, "pannirendu": 12, "pannirandu": 12, "பன்னிரண்டு": 12,
    "pathimoonu": 13, "பதிமூன்று": 13,
    "pathinaalu": 14, "பதினான்கு": 14,
    "pathinainju": 15, "pathinanchu": 15, "pathinanju": 15,
    "pathinaindhu": 15, "pathinaindu": 15, "பதினைந்து": 15,
    "pathinaaru": 16, "பதினாறு": 16,
    "pathinezhu": 17, "pathineyezhu": 17, "பதினேழு": 17,
    "pathinettu": 18, "padhinettu": 18, "padinettu": 18, "பதினெட்டு": 18,
    "pathonbathu": 19, "பத்தொன்பது": 19,
    "irupathu": 20, "இருபது": 20,
    "muppathu": 30, "முப்பது": 30,
    "naapathu": 40, "narpathu": 40, "nalupathu": 40, "naarpathu": 40,
    "நாற்பது": 40,
    "ambathu": 50, "aimbathu": 50, "ஐம்பது": 50, "அம்பது": 50,
    "arupathu": 60, "அறுபது": 60,
    "ezhupathu": 70, "yezhupathu": 70, "எழுபது": 70,
    "enbathu": 80, "embadhu": 80, "enpathu": 80, "எண்பது": 80,
    "thonnooru": 90, "thonnuru": 90, "தொண்ணூறு": 90,
    "nooru": 100, "nuru": 100, "நூறு": 100,
    "irunooru": 200, "இருநூறு": 200,
    "moonnooru": 300, "முந்நூறு": 300,
    "naanooru": 400, "நானூறு": 400,
    "ainnooru": 500, "ஐநூறு": 500,
}

_TENS_VALUES = {20, 30, 40, 50, 60, 70, 80, 90}
_HUNDRED_VALUES = {100, 200, 300, 400, 500}

# Independent vowel -> dependent sign, for building sandhi compounds such as
# முப்பத்தைந்து (முப்பது + ஐந்து).
_VOWEL_SIGN = {
    "அ": "", "ஆ": "ா", "இ": "ி", "ஈ": "ீ", "உ": "ு", "ஊ": "ூ",
    "எ": "ெ", "ஏ": "ே", "ஐ": "ை", "ஒ": "ொ", "ஓ": "ோ", "ஔ": "ௌ",
}


def _script_compounds() -> dict[str, int]:
    """Tamil-script tens+unit sandhi forms: முப்பத்தைந்து, இருபத்தைந்து, ..."""
    out: dict[str, int] = {}
    tens = {20: "இருபது", 30: "முப்பது", 40: "நாற்பது", 50: "ஐம்பது",
            60: "அறுபது", 70: "எழுபது", 80: "எண்பது"}
    units = {1: ["ஒன்று", "ஒன்னு"], 2: ["இரண்டு"], 3: ["மூன்று", "மூணு"],
             4: ["நான்கு", "நாலு"], 5: ["ஐந்து", "அஞ்சு"], 6: ["ஆறு"],
             7: ["ஏழு"], 8: ["எட்டு"], 9: ["ஒன்பது"]}
    for ten, ten_word in tens.items():
        stem = ten_word[:-1]
        for unit_value, forms in units.items():
            for form in forms:
                first = form[0]
                if first in _VOWEL_SIGN:
                    out[stem + "்த" + _VOWEL_SIGN[first] + form[1:]] = ten + unit_value
                else:
                    out[stem + "்து" + form] = ten + unit_value
    return out


_TAMIL_ALL: dict[str, int] = dict(_TAMIL)
_TAMIL_ALL.update(_script_compounds())
# Bound stems: fast speech drops a tens word's final ு before a consonant
# (முப்பது ரூபாய் -> முப்பதரூபாய்). Only for script tens words.
for _stem_word, _stem_value in list(_TAMIL_ALL.items()):
    if (not _stem_word.isascii() and _stem_value in _TENS_VALUES
            and _stem_word.endswith("ு")):
        _TAMIL_ALL.setdefault(_stem_word[:-1], _stem_value)

_ROMAN_TENS = {w: v for w, v in _TAMIL_ALL.items() if w.isascii() and v in _TENS_VALUES}
_ROMAN_ONES = {w: v for w, v in _TAMIL_ALL.items() if w.isascii() and 1 <= v <= 9}
_MUNCH_KEYS = sorted(_TAMIL_ALL, key=len, reverse=True)

_WORD_SPLIT_RE = re.compile(r"[^\s]+")
_STRIP_CHARS = ".,;:!?\"'()[]{}₹"


def _words(text: str) -> list[str]:
    return [
        t.strip(_STRIP_CHARS)
        for t in _WORD_SPLIT_RE.findall(text.lower())
    ]


def _single_value(word: str) -> tuple[int | Decimal, str] | None:
    """Value of one token: digits, English, Tamil or a joined compound."""
    if _DIGIT_RE.match(word):
        try:
            return (Decimal(word), "digits")
        except InvalidOperation:
            return None
    if word in _ENGLISH_ONES:
        return (_ENGLISH_ONES[word], "english")
    if word in _ENGLISH_TENS:
        return (_ENGLISH_TENS[word], "english")
    if word in _TAMIL_ALL:
        return (_TAMIL_ALL[word], "tamil")
    return _split_joined(word)


def _split_joined(word: str) -> tuple[int, str] | None:
    """Split joined tens+unit compounds: irupathanju, twentyfive."""
    for tens, value in sorted(_ROMAN_TENS.items(), key=lambda kv: -len(kv[0])):
        for stem in (tens, tens[:-1]):
            if stem and word.startswith(stem) and len(word) > len(stem):
                rest = word[len(stem):]
                if rest in _ROMAN_ONES:
                    return (value + _ROMAN_ONES[rest], "tamil")
    for tens, value in sorted(_ENGLISH_TENS.items(), key=lambda kv: -len(kv[0])):
        for stem in (tens, tens[:-1]):
            if stem and word.startswith(stem) and len(word) > len(stem):
                rest = word[len(stem):]
                if rest in _ENGLISH_ONES and 1 <= _ENGLISH_ONES[rest] <= 9:
                    return (value + _ENGLISH_ONES[rest], "english")
    return None


def _english_hundred(words: list[str]) -> int | None:
    """[ones|a] hundred [tens [ones]]. Anything else is not one number."""
    if any(w not in _ENGLISH_NUMBER_WORDS for w in words):
        return None
    idx = words.index("hundred")
    head, tail = words[:idx], words[idx + 1:]
    if len(head) > 1:
        return None
    mult = 1
    if head:
        if head[0] in ("a", "an"):
            mult = 1
        elif head[0] in _ENGLISH_ONES:
            mult = _ENGLISH_ONES[head[0]]
        else:
            return None
    base = mult * 100
    if not tail:
        return base
    if len(tail) == 1 and (tail[0] in _ENGLISH_TENS or tail[0] in _ENGLISH_ONES):
        return base + _number_word_value(tail[0])
    if (len(tail) == 2 and tail[0] in _ENGLISH_TENS
            and tail[1] in _ENGLISH_ONES and _ENGLISH_ONES[tail[1]] <= 9):
        return base + _ENGLISH_TENS[tail[0]] + _ENGLISH_ONES[tail[1]]
    return None


def _number_word_value(word: str) -> int | None:
    if word in _ENGLISH_ONES:
        return _ENGLISH_ONES[word]
    if word in _ENGLISH_TENS:
        return _ENGLISH_TENS[word]
    return None


def _span_value(words: list[str]) -> int | None:
    """Value of 2+ words, or None. Only tens+unit (or hundred-headed) combine."""
    if "hundred" in words:
        return _english_hundred(words)
    first = _single_value(words[0])
    if first is None or isinstance(first[0], Decimal):
        return None
    first_value = int(first[0])
    if first_value in _HUNDRED_VALUES and 1 <= len(words) - 1 <= 2:
        tail = _tens_group_value(words[1:])
        return first_value + tail if tail is not None else None
    if len(words) == 2 and first_value in _TENS_VALUES:
        second = _single_value(words[1])
        if (second is not None and not isinstance(second[0], Decimal)
                and 1 <= int(second[0]) <= 9):
            return first_value + int(second[0])
    return None


def _tens_group_value(words: list[str]) -> int | None:
    """A tens word with an optional unit, or a single number below 100."""
    if len(words) == 1:
        single = _single_value(words[0])
        if single is not None and not isinstance(single[0], Decimal) and int(single[0]) < 100:
            return int(single[0])
        return None
    if len(words) == 2:
        return _span_value(words)
    return None


def _words_value(words: list[str]) -> int | None:
    if len(words) == 1:
        single = _single_value(words[0])
        if single is None:
            return None
        return int(single[0])
    return _span_value(words)


def parse_number(token: str) -> Decimal | None:
    """Parse digits, English words or Tamil words (script or romanised)."""
    text = token.strip().lower().strip(_STRIP_CHARS)
    if not text:
        return None
    if _DIGIT_RE.match(text):
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    words = [w for w in _words(text) if w]
    if not words:
        return None
    value = _words_value(words)
    return Decimal(value) if value is not None else None


def _segment_tamil(run: str) -> list[tuple[str, int, int]]:
    """Split a spaceless Tamil run into (word, value, offset), skipping noise."""
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(run):
        hit = None
        for key in _MUNCH_KEYS:
            if run.startswith(key, i):
                hit = key
                break
        if hit is None:
            i += 1
            continue
        out.append((hit, _TAMIL_ALL[hit], i))
        i += len(hit)
    return out


def _word_hits(seg: str, base: int) -> list[tuple[int, int, str]]:
    """Number hits in digit-free text: ascii spans plus Tamil segmentation."""
    hits: list[tuple[int, int, str]] = []
    ascii_words = [(m.group(0), base + m.start()) for m in _ASCII_RUN_RE.finditer(seg)]
    i = 0
    while i < len(ascii_words):
        matched = False
        for width in range(min(4, len(ascii_words) - i), 0, -1):
            span = [w for w, _ in ascii_words[i:i + width]]
            value = _words_value(span)
            if value is not None:
                kind = ("english" if all(w in _ENGLISH_NUMBER_WORDS for w in span)
                        else "tamil")
                hits.append((ascii_words[i][1], value, kind))
                i += width
                matched = True
                break
        if not matched:
            i += 1
    seq: list[tuple[int, int, int]] = []
    for m in _TAMIL_RUN_RE.finditer(seg):
        run, rbase = m.group(0), base + m.start()
        for word, value, off in _segment_tamil(run):
            seq.append((value, rbase + off, rbase + off + len(word)))
    i = 0
    while i < len(seq):
        value, start, end = seq[i]
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        gap_ok = nxt is not None and re.fullmatch(r"\s*", seg[end - base:nxt[1] - base])
        if gap_ok and value in _TENS_VALUES and 1 <= nxt[0] <= 9:
            hits.append((start, value + nxt[0], "tamil"))
            i += 2
        elif gap_ok and value in _HUNDRED_VALUES and nxt[0] < 100:
            total, j = value + nxt[0], i + 2
            following = seq[j] if j < len(seq) else None
            if (nxt[0] in _TENS_VALUES and following is not None
                    and 1 <= following[0] <= 9
                    and re.fullmatch(r"\s*", seg[nxt[2] - base:following[1] - base])):
                total += following[0]
                j += 1
            hits.append((start, total, "tamil"))
            i = j
        else:
            hits.append((start, value, "tamil"))
            i += 1
    return hits


def find_numbers(text: str) -> list[tuple[Decimal, str]]:
    """Find numbers in spoken order; multi-word numbers count as one."""
    lowered = text.lower()
    hits: list[tuple[int, Decimal, str]] = []
    digit_spans: list[tuple[int, int]] = []
    for m in _DIGIT_SPAN_RE.finditer(lowered):
        try:
            value = Decimal(m.group(0).replace(",", ""))
        except InvalidOperation:
            continue
        hits.append((m.start(), value, "digits"))
        digit_spans.append((m.start(), m.end()))
    prev = 0
    for start, end in sorted(digit_spans):
        if prev < start:
            for pos, value, kind in _word_hits(lowered[prev:start], prev):
                hits.append((pos, Decimal(value), kind))
        prev = max(prev, end)
    if prev < len(lowered):
        for pos, value, kind in _word_hits(lowered[prev:], prev):
            hits.append((pos, Decimal(value), kind))
    hits.sort(key=lambda hit: hit[0])
    return [(value, kind) for _, value, kind in hits]
