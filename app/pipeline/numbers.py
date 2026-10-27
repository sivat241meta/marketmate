from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_DIGIT_RE = re.compile(r"^\d+(?:\.\d+)?$")

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

# Romanised Tamil and Tamil-script number words. Spoken markets mix
# spellings, so common variants share one value.
_TAMIL: dict[str, int] = {
    "oru": 1, "ஒரு": 1, "ஒன்று": 1, "ஒன்னு": 1,
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
    "pathinainju": 15, "pathinanchu": 15, "பதினைந்து": 15,
    "pathinaaru": 16, "பதினாறு": 16,
    "pathinezhu": 17, "pathineyezhu": 17, "பதினேழு": 17,
    "pathinettu": 18, "padhinettu": 18, "பதினெட்டு": 18,
    "pathonbathu": 19, "பத்தொன்பது": 19,
    "irupathu": 20, "இருபது": 20,
    "muppathu": 30, "முப்பது": 30,
    "naapathu": 40, "narpathu": 40, "நாற்பது": 40,
    "ambathu": 50, "aimbathu": 50, "ஐம்பது": 50,
    "arupathu": 60, "அறுபது": 60,
    "ezhupathu": 70, "yezhupathu": 70, "எழுபது": 70,
    "enbathu": 80, "எண்பது": 80,
    "thonnooru": 90, "thonnuru": 90, "தொண்ணூறு": 90,
    "nooru": 100, "nuru": 100, "நூறு": 100,
    "irunooru": 200, "இருநூறு": 200,
    "moonnooru": 300, "முந்நூறு": 300,
    "naanooru": 400, "நானூறு": 400,
    "ainnooru": 500, "ஐநூறு": 500,
}

_TAMIL_HUNDREDS = ("nooru", "nuru", "நூறு")

# Tens words used to split joined compounds such as "irupathanju".
_TAMIL_TENS: dict[str, int] = {
    w: v for w, v in _TAMIL.items()
    if v in (20, 30, 40, 50, 60, 70, 80, 90) and " " not in w
}

_WORD_SPLIT_RE = re.compile(r"[^\s]+")
_STRIP_CHARS = ".,;:!?\"'()[]{}₹"


def _words(text: str) -> list[str]:
    return [
        t.strip(_STRIP_CHARS)
        for t in _WORD_SPLIT_RE.findall(text.lower())
    ]


def _parse_english(words: list[str]) -> int | None:
    """Parse e.g. ["twenty", "five"] or ["one", "hundred", "twenty"]."""
    current = 0
    seen = False
    for w in words:
        if w in _ENGLISH_ONES:
            current += _ENGLISH_ONES[w]
            seen = True
        elif w in _ENGLISH_TENS:
            current += _ENGLISH_TENS[w]
            seen = True
        elif w == "hundred":
            if not seen or current == 0:
                current = 1
            current *= 100
            seen = True
        elif w in ("a", "an"):
            continue
        else:
            return None
    return current if seen else None


def _parse_tamil(words: list[str]) -> int | None:
    """Parse e.g. ["irupathu", "anju"]. Single words hit the table first."""
    if len(words) == 1:
        w = words[0]
        if w in _TAMIL:
            return _TAMIL[w]
        for tens, value in sorted(_TAMIL_TENS.items(), key=lambda kv: -len(kv[0])):
            for stem in (tens, tens[:-1]):
                if stem and w.startswith(stem) and len(w) > len(stem):
                    rest = _TAMIL.get(w[len(stem):])
                    if rest is not None and rest < 10:
                        return value + rest
        return None
    current = 0
    seen = False
    for w in words:
        if w not in _TAMIL:
            return None
        value = _TAMIL[w]
        seen = True
        if w in _TAMIL_HUNDREDS or value in (100, 200, 300, 400, 500):
            if current == 0:
                current = 1
            current *= value
        else:
            current += value
    return current if seen else None


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
    words = _words(text)
    if not words or any(not w for w in words):
        return None
    if all(w in _ENGLISH_ONES or w in _ENGLISH_TENS or w in ("hundred", "a", "an")
           for w in words):
        value = _parse_english(words)
        return Decimal(value) if value is not None else None
    value = _parse_tamil(words)
    return Decimal(value) if value is not None else None


def _kind_of(span: list[str]) -> str:
    if len(span) == 1 and _DIGIT_RE.match(span[0]):
        return "digits"
    if all(w in _ENGLISH_ONES or w in _ENGLISH_TENS or w in ("hundred", "a", "an")
           for w in span):
        return "english"
    return "tamil"


def find_numbers(text: str) -> list[tuple[Decimal, str]]:
    """Find numbers in spoken order; multi-word numbers count as one."""
    words = [w for w in _words(text) if w]
    found: list[tuple[Decimal, str]] = []
    i = 0
    while i < len(words):
        match: tuple[Decimal, list[str]] | None = None
        for width in range(min(4, len(words) - i), 0, -1):
            span = words[i:i + width]
            value = parse_number(" ".join(span))
            if value is not None:
                match = (value, span)
                break
        if match is None:
            i += 1
        else:
            value, span = match
            found.append((value, _kind_of(span)))
            i += len(span)
    return found
