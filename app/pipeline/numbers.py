from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.languages import LANGUAGES

_DIGIT_RE = re.compile(r"^\d+(?:\.\d+)?$")
_DIGIT_SPAN_RE = re.compile(r"\d[\d,.\u066B\u066C \u00A0\u2009\u202F]*\d|\d")
_ASCII_RUN_RE = re.compile(r"[A-Za-z]+")
_TAMIL_RUN_RE = re.compile(r"[\u0B80-\u0BFF]+")
_DEVANAGARI_RUN_RE = re.compile(r"[\u0900-\u097F]+")
_BENGALI_RUN_RE = re.compile(r"[\u0980-\u09FF]+")
_INTER_DIGIT_SPACE_RE = re.compile(r"(?<=\d)[ \u00A0\u2009\u202F]+(?=\d)")

# Non-ASCII decimal digits, mapped to 0-9: Devanagari, Bengali, Tamil,
# Telugu, Kannada, Arabic-Indic (+ Eastern/Extended), Thai.
_DIGIT_SOURCES = (
    "\u0966\u0967\u0968\u0969\u096A\u096B\u096C\u096D\u096E\u096F"
    "\u09E6\u09E7\u09E8\u09E9\u09EA\u09EB\u09EC\u09ED\u09EE\u09EF"
    "\u0BE6\u0BE7\u0BE8\u0BE9\u0BEA\u0BEB\u0BEC\u0BED\u0BEE\u0BEF"
    "\u0C66\u0C67\u0C68\u0C69\u0C6A\u0C6B\u0C6C\u0C6D\u0C6E\u0C6F"
    "\u0CE6\u0CE7\u0CE8\u0CE9\u0CEA\u0CEB\u0CEC\u0CED\u0CEE\u0CEF"
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9"
    "\u0E50\u0E51\u0E52\u0E53\u0E54\u0E55\u0E56\u0E57\u0E58\u0E59"
)
_DIGIT_TABLE = str.maketrans(
    _DIGIT_SOURCES, "0123456789" * (len(_DIGIT_SOURCES) // 10))

# Tamil spelling variants in speech transcripts: ண/ன/ந, ள/ல/ழ and ற/ர
# sound alike, so realtime may write என்பத்தேழு for எண்பத்தேழு (87).
# Number-word lookup compares on this folded form; stored text is untouched.
_TAMIL_FOLD_TABLE = str.maketrans({
    "ண": "ந", "ன": "ந",
    "ள": "ல", "ழ": "ல",
    "ற": "ர",
})


def fold_tamil(word: str) -> str:
    """Fold confusable Tamil consonants for number-word comparison only."""
    return word.translate(_TAMIL_FOLD_TABLE)


def normalise_digits(text: str, decimal_comma: bool = False) -> str:
    """Map Indic/Arabic/Thai digits to ASCII and resolve separators.

    With ``decimal_comma=False`` (English, Tamil, Hindi, ...) a comma is a
    thousands separator ("15,000" -> "15000") and the dot stays decimal.
    With ``decimal_comma=True`` (French, German, ...) the dot and spaces
    are thousands separators and the comma becomes the decimal dot.
    """
    out = text.translate(_DIGIT_TABLE)
    out = out.replace("\u066C", "")
    out = out.replace("\u066B", ".")
    out = _INTER_DIGIT_SPACE_RE.sub("", out)
    if decimal_comma:
        out = out.replace(".", "").replace(",", ".")
    else:
        out = out.replace(",", "")
    return out


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

CURRENCY_WORDS = frozenset(
    {"rupai", "rupees", "rupee", "rs", "₹", "ரூபாய்", "ரூபா"}
    | {word.lower() for lang in LANGUAGES for word in lang.currency_words}
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
    "onpathu": 9, "onbadhu": 9, "ombathu": 9, "onbathu": 9,
    "ஒன்பது": 9,
    "pathu": 10, "pattu": 10, "பத்து": 10,
    "pathinonnu": 11, "பதினொன்று": 11,
    "pannendu": 12, "pannirendu": 12, "pannirandu": 12, "பன்னிரண்டு": 12,
    "pathimoonu": 13, "பதிமூன்று": 13,
    "pathinaalu": 14, "பதினான்கு": 14,
    "pathinainju": 15, "pathinanchu": 15, "pathinanju": 15,
    "pathinaindhu": 15, "pathinaindu": 15, "பதினைந்து": 15, "பதினைஞ்சு": 15,
    "pathinaaru": 16, "பதினாறு": 16,
    "pathinezhu": 17, "pathineyezhu": 17, "பதினேழு": 17,
    "pathinettu": 18, "padhinettu": 18, "padinettu": 18, "பதினெட்டு": 18,
    "pathonbathu": 19, "பத்தொன்பது": 19,
    "irupathu": 20, "iruvathu": 20, "இருபது": 20, "இருவது": 20,
    "muppathu": 30, "முப்பது": 30,
    "naapathu": 40, "narpathu": 40, "nalupathu": 40, "naarpathu": 40,
    "naappathu": 40, "நாற்பது": 40, "நாப்பது": 40,
    "ambathu": 50, "aimbathu": 50, "ambadhu": 50, "aimbadhu": 50,
    "ஐம்பது": 50, "அம்பது": 50,
    "arupathu": 60, "aruvathu": 60, "அறுபது": 60, "அறுவது": 60,
    "ezhupathu": 70, "yezhupathu": 70, "ezhuvathu": 70,
    "எழுபது": 70, "எழுவது": 70,
    "enbathu": 80, "embadhu": 80, "enpathu": 80, "embathu": 80,
    "enbadhu": 80, "yenbadhu": 80,
    "எண்பது": 80, "எம்பது": 80,
    "thonnooru": 90, "thonnuru": 90, "தொண்ணூறு": 90,
    "irubathi": 20, "இருபத்தி": 20, "இருவத்தி": 20,
    "muppathi": 30, "முப்பத்தி": 30, "முப்பத்து": 30,
    "naapathi": 40, "நாப்பத்தி": 40, "நாற்பத்தி": 40,
    "நாப்பத்து": 40,
    "aimbathi": 50, "ambathi": 50, "ஐம்பத்தி": 50,
    "அம்பத்தி": 50, "ஐம்பத்து": 50,
    "arubathi": 60, "அறுபத்தி": 60, "அறுவத்தி": 60,
    "ezhubathi": 70, "எழுபத்தி": 70, "எழுவத்தி": 70,
    "enbathi": 80, "embathi": 80, "எண்பத்தி": 80, "எம்பத்தி": 80,
    "thonnoothi": 90, "தொண்ணூத்தி": 90, "தொண்ணூற்றி": 90,
    "இருவத்தஞ்சு": 25,
    "nooru": 100, "nuru": 100, "noothi": 100, "nootri": 100,
    "நூறு": 100, "நூற்றி": 100, "நூத்தி": 100, "நூற்று": 100,
    "irunooru": 200, "இருநூறு": 200,
    "இருநூத்தி": 200, "இருநூற்றி": 200,
    "moonnooru": 300, "முந்நூறு": 300,
    "naanooru": 400, "நானூறு": 400,
    "ainnooru": 500, "ஐநூறு": 500,
}

# Hindi 0-99: highly irregular, one fused word each. Devanagari plus the
# common romanised spellings heard in markets.
_HINDI: dict[str, int] = {
    "shunya": 0, "shoonya": 0, "sunya": 0, "शून्य": 0,
    "ek": 1, "एक": 1,
    "do": 2, "दो": 2,
    "teen": 3, "तीन": 3,
    "chaar": 4, "char": 4, "चार": 4,
    "paanch": 5, "panch": 5, "पाँच": 5, "पांच": 5,
    "chhah": 6, "chheh": 6, "cheh": 6, "छह": 6, "छः": 6,
    "saat": 7, "sat": 7, "सात": 7,
    "aath": 8, "ath": 8, "आठ": 8,
    "nau": 9, "nao": 9, "नौ": 9,
    "das": 10, "दस": 10,
    "gyaarah": 11, "gyarah": 11, "ग्यारह": 11,
    "baarah": 12, "barah": 12, "बारह": 12,
    "terah": 13, "teraha": 13, "तेरह": 13,
    "chaudah": 14, "chaudaha": 14, "chodah": 14, "चौदह": 14,
    "pandrah": 15, "pandraha": 15, "पंद्रह": 15,
    "solah": 16, "solaha": 16, "सोलह": 16,
    "satrah": 17, "satraha": 17, "सत्रह": 17,
    "athaarah": 18, "atharah": 18, "अठारह": 18,
    "unnees": 19, "unnis": 19, "उन्नीस": 19,
    "bees": 20, "bis": 20, "बीस": 20,
    "ikkees": 21, "ikkis": 21, "इक्कीस": 21,
    "baais": 22, "bais": 22, "बाईस": 22,
    "teis": 23, "तेईस": 23,
    "chaubees": 24, "chaubis": 24, "चौबीस": 24,
    "pachchees": 25, "pachees": 25, "pachis": 25, "पच्चीस": 25,
    "chhabbees": 26, "chhabbis": 26, "छब्बीस": 26,
    "sattaais": 27, "sattais": 27, "सत्ताईस": 27,
    "atthaais": 28, "atthais": 28, "अट्ठाईस": 28,
    "untees": 29, "untis": 29, "उनतीस": 29,
    "tees": 30, "tis": 30, "तीस": 30,
    "iktees": 31, "iktis": 31, "इकतीस": 31, "इकत्तीस": 31,
    "battees": 32, "battis": 32, "बत्तीस": 32,
    "tentees": 33, "tentis": 33, "taintees": 33, "तैंतीस": 33,
    "तेंतीस": 33,
    "chauntees": 34, "chauntis": 34, "चौंतीस": 34,
    "pentees": 35, "pentis": 35, "paintees": 35, "पैंतीस": 35,
    "chhattees": 36, "chhattis": 36, "छत्तीस": 36,
    "sentees": 37, "sentis": 37, "saintees": 37, "सैंतीस": 37,
    "adtees": 38, "adtis": 38, "अड़तीस": 38,
    "untaalis": 39, "untalis": 39, "उनतालीस": 39,
    "chaalis": 40, "chalis": 40, "चालीस": 40,
    "iktaalis": 41, "iktalis": 41, "इकतालीस": 41,
    "beyaalis": 42, "beyalis": 42, "बयालीस": 42,
    "tentaalis": 43, "tentalis": 43, "तैंतालीस": 43,
    "chavaalis": 44, "chavalis": 44, "चवालीस": 44,
    "paintaalis": 45, "paintalis": 45, "पैंतालीस": 45,
    "chhiyaalis": 46, "chhiyalis": 46, "छियालीस": 46,
    "sentaalis": 47, "sentalis": 47, "सैंतालीस": 47,
    "adtaalis": 48, "adtalis": 48, "अड़तालीस": 48,
    "unchaas": 49, "unchas": 49, "उनचास": 49,
    "pachaas": 50, "pachas": 50, "पचास": 50,
    "ikyaavan": 51, "ikyavan": 51, "इक्यावन": 51,
    "baavan": 52, "bavan": 52, "बावन": 52,
    "tirapan": 53, "tirpan": 53, "तिरपन": 53,
    "chauvan": 54, "chouvan": 54, "चौवन": 54,
    "pachpan": 55, "पचपन": 55,
    "chhappan": 56, "छप्पन": 56,
    "sattaavan": 57, "sattavan": 57, "सत्तावन": 57,
    "atthaavan": 58, "atthavan": 58, "अट्ठावन": 58,
    "unsath": 59, "उनसठ": 59,
    "saath": 60, "sath": 60, "साठ": 60,
    "iksath": 61, "इकसठ": 61,
    "baasath": 62, "basath": 62, "बासठ": 62,
    "tirsath": 63, "tirasath": 63, "तिरसठ": 63,
    "chaunsath": 64, "chonsath": 64, "चौंसठ": 64,
    "painsath": 65, "पैंसठ": 65,
    "chhiyaasath": 66, "chhiyasath": 66, "छियासठ": 66,
    "sadsath": 67, "sarsath": 67, "सड़सठ": 67,
    "adsath": 68, "अड़सठ": 68,
    "unhattar": 69, "उनहत्तर": 69,
    "sattar": 70, "सत्तर": 70,
    "ikhattar": 71, "इकहत्तर": 71,
    "bahattar": 72, "बहत्तर": 72,
    "tihattar": 73, "तिहत्तर": 73,
    "chauhattar": 74, "चौहत्तर": 74,
    "pachhattar": 75, "पचहत्तर": 75,
    "chhihattar": 76, "छिहत्तर": 76,
    "satahattar": 77, "सत्तहत्तर": 77,
    "athhahattar": 78, "atthattar": 78, "अट्ठहत्तर": 78,
    "unyaasi": 79, "unyasi": 79, "उन्यासी": 79,
    "assi": 80, "asi": 80, "अस्सी": 80,
    "ikyaasi": 81, "ikyasi": 81, "इक्यासी": 81,
    "beyaasi": 82, "beyasi": 82, "बयासी": 82,
    "tiraasi": 83, "tirasi": 83, "तिरासी": 83,
    "chauraasi": 84, "chaurasi": 84, "चौरासी": 84,
    "pachaasi": 85, "pachasi": 85, "पचासी": 85,
    "chhiyaasi": 86, "chhiyasi": 86, "छियासी": 86,
    "sattaasi": 87, "sattasi": 87, "सत्तासी": 87,
    "atthaasi": 88, "atthasi": 88, "अट्ठासी": 88,
    "navaasi": 89, "navasi": 89, "नवासी": 89,
    "nabbe": 90, "नब्बे": 90,
    "ikyaanve": 91, "ikyanve": 91, "इक्यानवे": 91,
    "baanve": 92, "banve": 92, "बानवे": 92,
    "tiraanve": 93, "tiranve": 93, "तिरानवे": 93,
    "chauraanve": 94, "chauranve": 94, "चौरानवे": 94,
    "pachaanve": 95, "pachanve": 95, "पचानवे": 95,
    "chhiyaanve": 96, "chhiyanve": 96, "छियानवे": 96,
    "sattaanve": 97, "sattanve": 97, "सत्तानवे": 97,
    "atthaanve": 98, "atthanve": 98, "अट्ठानवे": 98,
    "ninyaanve": 99, "ninyanve": 99, "निन्यानवे": 99,
}

_HINDI_HUNDRED = {"sau": 100, "sao": 100, "सौ": 100}
_HINDI_THOUSAND = {"hazaar": 1000, "hazar": 1000, "hajaar": 1000,
                   "हज़ार": 1000, "हजार": 1000}
_HINDI_FRACTIONS: dict[str, Decimal] = {
    "dedh": Decimal("1.5"), "derh": Decimal("1.5"),
    "डेढ़": Decimal("1.5"), "देढ़": Decimal("1.5"),
    "dhai": Decimal("2.5"), "dhaai": Decimal("2.5"),
    "ढाई": Decimal("2.5"),
}
_HINDI_SAWA = {"sawa", "sava", "सवा"}
_HINDI_PAUNE = {"paune", "paone", "पौने", "पौणे"}

_HINDI_WORDS = (
    set(_HINDI) | set(_HINDI_HUNDRED) | set(_HINDI_THOUSAND)
    | set(_HINDI_FRACTIONS) | _HINDI_SAWA | _HINDI_PAUNE
)

# Bengali sound-alike pair only (ষাট/shaat 60 vs সাত/saat 7): the full
# language is cross-checked, but this pair needs local parsing so the
# SOUND_ALIKE check can offer both values. saat/sat already parse as 7
# through the Hindi table.
_BENGALI: dict[str, int] = {
    "ষাট": 60, "সাত": 7, "shaat": 60, "shat": 60,
}
_BENGALI_WORDS = set(_BENGALI)

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

# Folded Tamil-script keys for spelling variants. Exact keys always win;
# a folded key shared by two values is ambiguous and stays unmatched.
_TAMIL_FOLDED: dict[str, int] = {}
_FOLDED_AMBIGUOUS: set[str] = set()
for _key, _value in _TAMIL_ALL.items():
    if _key.isascii():
        continue
    _folded = fold_tamil(_key)
    if _folded in _TAMIL_FOLDED and _TAMIL_FOLDED[_folded] != _value:
        _FOLDED_AMBIGUOUS.add(_folded)
    else:
        _TAMIL_FOLDED.setdefault(_folded, _value)
for _bad in _FOLDED_AMBIGUOUS:
    _TAMIL_FOLDED.pop(_bad, None)
_FOLDED_MUNCH_KEYS = sorted(_TAMIL_FOLDED, key=len, reverse=True)

_WORD_SPLIT_RE = re.compile(r"[^\s]+")
_STRIP_CHARS = ".,;:!?\"'()[]{}₹।॥"
_CURRENCY_STRIP_CHARS = ".,;:!?\"'()[]{}"
_DEVANAGARI_STRIP = "।॥.,;:!?\"'()[]{}"


def _words(text: str) -> list[str]:
    return [
        t.strip(_STRIP_CHARS)
        for t in _WORD_SPLIT_RE.findall(text.lower())
    ]


def _hindi_single(word: str) -> int | Decimal | None:
    if word in _HINDI:
        return _HINDI[word]
    if word in _HINDI_HUNDRED:
        return 100
    if word in _HINDI_THOUSAND:
        return 1000
    if word in _HINDI_FRACTIONS:
        return _HINDI_FRACTIONS[word]
    if word in _HINDI_SAWA:
        return Decimal("1.25")
    if word in _HINDI_PAUNE:
        return Decimal("0.75")
    return None


def _hindi_span_value(words: list[str]) -> int | Decimal | None:
    """Multi-word Hindi: sau/hazaar groups, dedh/dhai, sawa/paune."""
    if not words or any(w not in _HINDI_WORDS for w in words):
        return None
    head, rest = words[0], words[1:]
    if head in _HINDI_FRACTIONS:
        mult = _HINDI_FRACTIONS[head]
        if not rest:
            return mult
        if rest == ["sau"] or rest == ["सौ"] or rest == ["sao"]:
            return mult * 100
        if rest[0] in _HINDI_THOUSAND and len(rest) == 1:
            return mult * 1000
        return None
    if head in _HINDI_SAWA:
        if not rest:
            return Decimal("1.25")
        if len(rest) == 1:
            if rest[0] in _HINDI_HUNDRED:
                return 125
            if rest[0] in _HINDI_THOUSAND:
                return 1250
            value = _HINDI.get(rest[0])
            if value is not None and value < 100:
                return Decimal(value) + Decimal("0.25")
        return None
    if head in _HINDI_PAUNE:
        if not rest:
            return Decimal("0.75")
        if len(rest) == 1:
            if rest[0] in _HINDI_HUNDRED:
                return 75
            if rest[0] in _HINDI_THOUSAND:
                return 750
            value = _HINDI.get(rest[0])
            if value is not None and 1 <= value < 100:
                return Decimal(value) - Decimal("0.25")
        return None
    if head in _HINDI_HUNDRED:
        if not rest:
            return 100
        if len(rest) == 1 and rest[0] in _HINDI and _HINDI[rest[0]] < 100:
            return 100 + _HINDI[rest[0]]
        return None
    if head in _HINDI_THOUSAND:
        if not rest:
            return 1000
        tail = _hindi_span_value(rest)
        if tail is not None and tail < 1000:
            return 1000 + tail
        return None
    count = _HINDI.get(head)
    if count is None:
        return None
    if not rest:
        return count
    if rest[0] in _HINDI_HUNDRED:
        base = count * 100
        if len(rest) == 1:
            return base
        if len(rest) == 2 and rest[1] in _HINDI and _HINDI[rest[1]] < 100:
            return base + _HINDI[rest[1]]
        return None
    if rest[0] in _HINDI_THOUSAND:
        base = count * 1000
        if len(rest) == 1:
            return base
        tail = _hindi_span_value(rest[1:])
        if tail is not None and tail < 1000:
            return base + tail
        return None
    return None


def _single_value(word: str) -> tuple[int | Decimal, str] | None:
    """Value of one token: digits, English, Tamil, Hindi or a compound."""
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
    if not word.isascii():
        folded = fold_tamil(word)
        if folded in _TAMIL_FOLDED:
            return (_TAMIL_FOLDED[folded], "tamil")
    hindi = _hindi_single(word)
    if hindi is not None:
        return (hindi, "hindi")
    if word in _BENGALI:
        return (_BENGALI[word], "bengali")
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


def _span_value(words: list[str]) -> int | Decimal | None:
    """Value of 2+ words, or None. Only tens+unit (or hundred-headed) combine."""
    if "hundred" in words:
        return _english_hundred(words)
    hindi = _hindi_span_value(words)
    if hindi is not None:
        return hindi
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
        value = _span_value(words)
        return int(value) if isinstance(value, int) else None
    return None


def _words_value(words: list[str]) -> int | Decimal | None:
    if len(words) == 1:
        single = _single_value(words[0])
        if single is None:
            return None
        return single[0]
    return _span_value(words)


def parse_number(token: str, decimal_comma: bool = False) -> Decimal | None:
    """Parse digits (any supported script), English, Tamil, Hindi words,
    and the Bengali sixty/seven sound-alike pair."""
    text = token.strip().lower().strip(_STRIP_CHARS)
    if not text:
        return None
    normalised = normalise_digits(text, decimal_comma)
    if _DIGIT_RE.match(normalised):
        try:
            return Decimal(normalised)
        except InvalidOperation:
            return None
    words = [w for w in _words(text) if w]
    if not words:
        return None
    value = _words_value(words)
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(value)


def _segment_tamil(run: str) -> list[tuple[str, int, int]]:
    """Split a spaceless Tamil run into (word, value, offset), skipping noise."""
    out: list[tuple[str, int, int]] = []
    folded_run = fold_tamil(run)
    i = 0
    while i < len(run):
        hit = None
        for key in _MUNCH_KEYS:
            if run.startswith(key, i):
                hit = key
                break
        if hit is not None:
            out.append((hit, _TAMIL_ALL[hit], i))
            i += len(hit)
            continue
        folded_hit = None
        for key in _FOLDED_MUNCH_KEYS:
            if folded_run.startswith(key, i):
                folded_hit = key
                break
        if folded_hit is None:
            i += 1
            continue
        out.append((run[i:i + len(folded_hit)],
                    _TAMIL_FOLDED[folded_hit], i))
        i += len(folded_hit)
    return out


def _currency_ahead(seg: str, rel_end: int) -> bool:
    """True when the next whitespace-separated token is a currency word."""
    rest = seg[rel_end:].split(None, 1)
    if not rest:
        return False
    token = rest[0].strip(_CURRENCY_STRIP_CHARS)
    return token in CURRENCY_WORDS


def _span_kind(span: list[str]) -> str:
    if all(w in _ENGLISH_NUMBER_WORDS for w in span):
        return "english"
    if all(w in _HINDI_WORDS for w in span):
        return "hindi"
    if all(w in _BENGALI_WORDS for w in span):
        return "bengali"
    return "tamil"


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
            kind = None
            if value is not None:
                kind = _span_kind(span)
            elif (width == 2 and span[0] in _ENGLISH_ONES
                    and 1 <= _ENGLISH_ONES[span[0]] <= 9
                    and span[1] in _ENGLISH_TENS
                    and _currency_ahead(seg, ascii_words[i + 1][1]
                                        + len(span[1]) - base)):
                value = _ENGLISH_ONES[span[0]] * 100 + _ENGLISH_TENS[span[1]]
                kind = "english"
            if value is not None and kind is not None:
                hits.append((ascii_words[i][1], value, kind))
                i += width
                matched = True
                break
        if not matched:
            i += 1
    deva_words = [
        (m.group(0).strip(_DEVANAGARI_STRIP).lower(), base + m.start())
        for m in _DEVANAGARI_RUN_RE.finditer(seg)
    ]
    deva_words = [(w, pos) for w, pos in deva_words if w]
    i = 0
    while i < len(deva_words):
        matched = False
        for width in range(min(4, len(deva_words) - i), 0, -1):
            span = [w for w, _ in deva_words[i:i + width]]
            value = _words_value(span)
            if value is not None and all(w in _HINDI_WORDS for w in span):
                hits.append((deva_words[i][1], value, "hindi"))
                i += width
                matched = True
                break
        if not matched:
            i += 1
    benga_words = [
        (m.group(0).strip(_DEVANAGARI_STRIP).lower(), base + m.start())
        for m in _BENGALI_RUN_RE.finditer(seg)
    ]
    benga_words = [(w, pos) for w, pos in benga_words if w]
    i = 0
    while i < len(benga_words):
        matched = False
        for width in range(min(4, len(benga_words) - i), 0, -1):
            span = [w for w, _ in benga_words[i:i + width]]
            value = _words_value(span)
            if value is not None and all(w in _BENGALI_WORDS for w in span):
                hits.append((benga_words[i][1], value, "bengali"))
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


def find_numbers(text: str, decimal_comma: bool = False
                 ) -> list[tuple[Decimal, str]]:
    """Find numbers in spoken order; multi-word numbers count as one."""
    lowered = text.lower()
    hits: list[tuple[int, Decimal, str]] = []
    digit_spans: list[tuple[int, int]] = []
    for m in _DIGIT_SPAN_RE.finditer(lowered):
        try:
            value = Decimal(normalise_digits(m.group(0), decimal_comma))
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
