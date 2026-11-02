"""Canonical produce names: English key -> (Tamil script, romanised Tamil)."""

from __future__ import annotations

import unicodedata

from app.models import Flag

_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("tomato", "தக்காளி", "thakkali"),
    ("onion", "பெரிய வெங்காயம்", "vengayam"),
    ("small onion", "சின்ன வெங்காயம்", "chinna vengayam"),
    ("potato", "உருளைக்கிழங்கு", "urulaikizhangu"),
    ("carrot", "கேரட்", "carrot"),
    ("banana", "வாழைப்பழம்", "vazhaipazham"),
    ("coconut", "தேங்காய்", "thengai"),
    ("beans", "பீன்ஸ்", "beans"),
    ("cabbage", "முட்டைகோஸ்", "muttaikose"),
    ("cauliflower", "காலிஃபிளவர்", "cauliflower"),
    ("brinjal", "கத்திரிக்காய்", "kathirikkai"),
    ("okra", "வெண்டைக்காய்", "vendaikkai"),
    ("drumstick", "முருங்கைக்காய்", "murungaikkai"),
    ("pumpkin", "பரங்கிக்காய்", "parangikkai"),
    ("bottle gourd", "சுரைக்காய்", "suraikkai"),
    ("bitter gourd", "பாகற்காய்", "paagarkaai"),
    ("snake gourd", "புடலங்காய்", "pudalangaai"),
    ("ridge gourd", "பீர்க்கங்காய்", "peerkangaai"),
    ("ash gourd", "வெண்பூசணி", "venpoosani"),
    ("cucumber", "வெள்ளரிக்காய்", "vellarikkai"),
    ("mango", "மாம்பழம்", "maambazham"),
    ("papaya", "பப்பாளி", "pappaali"),
    ("guava", "கொய்யா", "koyya"),
    ("watermelon", "தர்பூசணி", "tharpoosani"),
    ("muskmelon", "முலாம்பழம்", "mulaampazham"),
    ("pomegranate", "மாதுளை", "maadhulai"),
    ("grapes", "திராட்சை", "thiraatchai"),
    ("orange", "ஆரஞ்சு", "orange"),
    ("apple", "ஆப்பிள்", "apple"),
    ("pineapple", "அன்னாசி", "annaasi"),
    ("lemon", "எலுமிச்சை", "elumichai"),
    ("green chilli", "பச்சை மிளகாய்", "pachai milagaai"),
    ("red chilli", "வரமிளகாய்", "vara milagaai"),
    ("ginger", "இஞ்சி", "inji"),
    ("garlic", "பூண்டு", "poondu"),
    ("coriander", "கொத்தமல்லி", "kothamalli"),
    ("curry leaves", "கறிவேப்பிலை", "karuveppilai"),
    ("mint", "புதினா", "pudhina"),
    ("spinach", "பசலைக்கீரை", "pasalaikeerai"),
    ("amaranth", "அரைக்கீரை", "araikeerai"),
    ("fenugreek leaves", "வெந்தயக்கீரை", "vendhayakeerai"),
    ("radish", "முள்ளங்கி", "mullangi"),
    ("beetroot", "பீட்ரூட்", "beetroot"),
    ("sweet potato", "சர்க்கரைவள்ளிக்கிழங்கு", "sakkaraivallikizhangu"),
    ("tapioca", "மரவள்ளிக்கிழங்கு", "maravallikizhangu"),
    ("yam", "சேனைக்கிழங்கு", "senaikizhangu"),
    ("colocasia", "சேப்பங்கிழங்கு", "seppankizhangu"),
    ("raw banana", "வாழைக்காய்", "vazhaikkai"),
    ("jackfruit", "பலாப்பழம்", "palaapazham"),
    ("sapota", "சப்போட்டா", "sappotta"),
    ("custard apple", "சீதாப்பழம்", "seethaapazham"),
    ("gooseberry", "நெல்லிக்காய்", "nellikkai"),
    ("cluster beans", "கொத்தவரங்காய்", "kothavarangaai"),
    ("broad beans", "அவரைக்காய்", "avaraikkai"),
    ("capsicum", "குடைமிளகாய்", "kudamilagaai"),
    ("spring onion", "வெங்காயத்தாள்", "vengayathaazh"),
    ("ladies finger", "வெண்டைக்காய்", "vendaikkai"),
    ("mushroom", "காளான்", "kaalaan"),
    ("corn", "சோளம்", "sozham"),
    ("peas", "பட்டாணி", "pattaani"),
    ("banana stem", "வாழைத்தண்டு", "vazhaithandu"),
    ("banana flower", "வாழைப்பூ", "vazhaipoo"),
    ("sweet lime", "சாத்துக்குடி", "saathukudi"),
    ("ivy gourd", "கோவக்காய்", "kovakkai"),
    ("raw mango", "மாங்காய்", "maangaai"),
)

CANONICAL_NAMES: dict[str, str] = {name_en: name_ta for name_en, name_ta, _ in _ITEMS}

EN_TO_ROMAN: dict[str, str] = {name_en: roman for name_en, _, roman in _ITEMS}

# Canonical Hindi (Devanagari) produce names (Task 103), keyed by the
# same English keys as _ITEMS. Only Tamil and Hindi shops have a
# canonical local name; every other language falls back to English.
CANONICAL_NAMES_HI: dict[str, str] = {
    "tomato": "टमाटर",
    "onion": "प्याज़",
    "small onion": "छोटी प्याज़",
    "potato": "आलू",
    "carrot": "गाजर",
    "banana": "केला",
    "coconut": "नारियल",
    "beans": "बीन्स",
    "cabbage": "पत्ता गोभी",
    "cauliflower": "फूल गोभी",
    "brinjal": "बैंगन",
    "okra": "भिंडी",
    "drumstick": "सहजन",
    "pumpkin": "कद्दू",
    "bottle gourd": "लौकी",
    "bitter gourd": "करेला",
    "snake gourd": "चिचिंडा",
    "ridge gourd": "तोरई",
    "ash gourd": "पेठा",
    "cucumber": "खीरा",
    "mango": "आम",
    "papaya": "पपीता",
    "guava": "अमरूद",
    "watermelon": "तरबूज",
    "muskmelon": "खरबूजा",
    "pomegranate": "अनार",
    "grapes": "अंगूर",
    "orange": "संतरा",
    "apple": "सेब",
    "pineapple": "अनानास",
    "lemon": "नींबू",
    "green chilli": "हरी मिर्च",
    "red chilli": "लाल मिर्च",
    "ginger": "अदरक",
    "garlic": "लहसुन",
    "coriander": "धनिया",
    "curry leaves": "करी पत्ता",
    "mint": "पुदीना",
    "spinach": "पालक",
    "amaranth": "चौलाई",
    "fenugreek leaves": "मेथी",
    "radish": "मूली",
    "beetroot": "चुकंदर",
    "sweet potato": "शकरकंद",
    "tapioca": "टैपियोका",
    "yam": "जिमीकंद",
    "colocasia": "अरबी",
    "raw banana": "कच्चा केला",
    "jackfruit": "कटहल",
    "sapota": "चीकू",
    "custard apple": "सीताफल",
    "gooseberry": "आंवला",
    "cluster beans": "ग्वार फली",
    "broad beans": "सेम",
    "capsicum": "शिमला मिर्च",
    "spring onion": "हरा प्याज़",
    "ladies finger": "भिंडी",
    "mushroom": "मशरूम",
    "corn": "मक्का",
    "peas": "मटर",
    "banana stem": "केले का तना",
    "banana flower": "केले का फूल",
    "sweet lime": "मौसंबी",
    "ivy gourd": "कुंदरू",
    "raw mango": "कच्चा आम",
}


def canonical_local_name(name_en: str | None,
                         language: str = "ta") -> str | None:
    """Canonical local name of an item for a shop language, or None.

    Tamil and Hindi have canonical names; every other language (and
    unknown items) returns None so callers fall back to English.
    """
    base = (name_en or "").strip().lower()
    if not base:
        return None
    if language == "ta":
        return CANONICAL_NAMES.get(base)
    if language == "hi":
        return CANONICAL_NAMES_HI.get(base)
    return None


def is_word_char(char: str) -> bool:
    """True for characters that continue a word: letters, digits, "_",
    and Tamil vowel signs (category M* in the Tamil block), so பூசணி
    inside தர்பூசணி never counts as a whole-word match."""
    if not char:
        return False
    if char == "_" or char.isalnum():
        return True
    return ("\u0B80" <= char <= "\u0BFF"
            and unicodedata.category(char).startswith("M"))


# Tamil spelling variants (Task 157): speech transcripts vary ற/ர, ண/ன,
# ள/ல/ழ and short/long vowels, and sellers say கா for காய். Folding
# both sides makes தற்பூசணி == தர்பூசணி and கத்தரிக்கா ==
# கத்தரிக்காய், so a claimed name is found despite the variants.
_TAMIL_CONSONANT_FOLD = str.maketrans({
    "ற": "ர",
    "ண": "ன",
    "ள": "ல", "ழ": "ல",
})
_TAMIL_VOWEL_FOLD = str.maketrans({
    "ஆ": "அ", "ஈ": "இ", "ஊ": "உ", "ஏ": "எ", "ஓ": "ஒ",
})


def normalize_tamil_spelling(text: str | None) -> str:
    """Fold common Tamil spelling variants for name comparison.

    Dependent vowel signs (including the ் pulli) are dropped,
    confusable consonants (ற→ர, ண→ன, ள/ழ→ல) and independent vowels
    (ஆ→அ, ஈ→இ, ஊ→உ, ஏ→எ, ஓ→ஒ) are folded, and a word-final ய is
    dropped so the spoken கா ending matches காய். Latin and other
    scripts pass through case-folded. Both sides of a comparison must
    be normalized; the stored text is never changed.
    """
    words: list[str] = []
    for word in (text or "").split():
        bare = "".join(
            char for char in word
            if not ("\u0B80" <= char <= "\u0BFF"
                    and unicodedata.category(char).startswith("M")))
        folded = bare.translate(_TAMIL_CONSONANT_FOLD).translate(
            _TAMIL_VOWEL_FOLD)
        words.append(folded.removesuffix("ய"))
    return " ".join(words).casefold()


def _runs_equal(first: str, second: str) -> bool:
    """True when two halves repeat: case-insensitively, with Tamil's
    v/w alternation folded (வ is written either way)."""
    if first.casefold() == second.casefold():
        return True
    fold = lambda run: run.casefold().replace("w", "v")
    return fold(first) == fold(second)


def _collapse_token(token: str) -> str:
    """Halve an immediately repeated run: vazhaiwazhai -> vazhai."""
    word = token or ""
    while len(word) >= 2 and len(word) % 2 == 0:
        half = len(word) // 2
        if _runs_equal(word[:half], word[half:]):
            word = word[:half]
        else:
            break
    return word


def collapse_repeated_runs(text: str | None) -> str:
    """Collapse immediately repeated syllable runs in each token.

    Speech transcripts merge a repeated word ("sev vazhaiwazhai" for
    sev vazhai); halving the doubled token before matching lets the
    glossary aliases match. Adjacent repeated words are the caller's
    own collapse.
    """
    if not text:
        return ""
    return " ".join(_collapse_token(token) for token in text.split())

# Real-shop variety nicknames (Task 47): normalized alias -> (name_en, variety).
# Keys are lower-cased; Tamil script keys stay as-is for exact matching.
VARIETY_ALIASES: dict[str, tuple[str, str]] = {
    # Shiny violet brinjal nickname (Tamil Nadu market usage, owner-confirmed).
    "உஜாலா": ("brinjal", "ujala"),
    "ujala": ("brinjal", "ujala"),
    "ujjala": ("brinjal", "ujala"),
    # Place-of-origin variety said next to the nickname.
    "krishnagiri": ("brinjal", "krishnagiri"),
    "கிருஷ்ணகிரி": ("brinjal", "krishnagiri"),
    "ujjala krishnagiri": ("brinjal", "krishnagiri"),
    "krishnagiri ujjala": ("brinjal", "krishnagiri"),
    "ujala krishnagiri": ("brinjal", "krishnagiri"),
    "krishnagiri ujala": ("brinjal", "krishnagiri"),
    # Banana varieties.
    "பூவன்": ("banana", "poovan"),
    "poovan": ("banana", "poovan"),
    "பூவன் பழம்": ("banana", "poovan"),
    "poovan banana": ("banana", "poovan"),
    "poovan pazham": ("banana", "poovan"),
    "ஏலக்கி": ("banana", "yelakki"),
    "ஏலகி": ("banana", "yelakki"),
    "yelakki": ("banana", "yelakki"),
    "elakki": ("banana", "yelakki"),
    "yelaki": ("banana", "yelakki"),
    "elaki": ("banana", "yelakki"),
    "elaki mathi": ("banana", "yelakki"),
    "ஏலக்கி பழம்": ("banana", "yelakki"),
    "ஏலகி பழம்": ("banana", "yelakki"),
    "yelakki banana": ("banana", "yelakki"),
    "elakki banana": ("banana", "yelakki"),
    "கற்பூரவள்ளி": ("banana", "karpooravalli"),
    "karpooravalli": ("banana", "karpooravalli"),
    "karpuravalli": ("banana", "karpooravalli"),
    "கற்பூரவள்ளி பழம்": ("banana", "karpooravalli"),
    "karpooravalli banana": ("banana", "karpooravalli"),
    "தேன்வாழை": ("banana", "thenvazhai"),
    "thenvazhai": ("banana", "thenvazhai"),
    "தேன் வாழை": ("banana", "thenvazhai"),
    "then vazhai": ("banana", "thenvazhai"),
    "then vaazhai": ("banana", "thenvazhai"),
    "செவ்வாழை": ("banana", "red"),
    "sevvazhai": ("banana", "red"),
    "chevvazhai": ("banana", "red"),
    "chevvalai": ("banana", "red"),
    "sev vazhai": ("banana", "red"),
    "red banana": ("banana", "red"),
    "பச்சை வாழை": ("banana", "green"),
    "பச்சைவாழை": ("banana", "green"),
    "பச்சை பழம்": ("banana", "green"),
    "பச்சை": ("banana", "green"),
    "pachai pazham": ("banana", "green"),
    "pachai vazhai": ("banana", "green"),
    "pachaivazhai": ("banana", "green"),
    "pachai": ("banana", "green"),
    "pacha": ("banana", "green"),
    "pachchai": ("banana", "green"),
    "green banana": ("banana", "green"),
    "நேந்திரன்": ("banana", "nendran"),
    "nendran": ("banana", "nendran"),
    "நேந்திரன் பழம்": ("banana", "nendran"),
    "nendran banana": ("banana", "nendran"),
    "ரஸ்தாளி": ("banana", "rasthali"),
    "rasthali": ("banana", "rasthali"),
    "rastali": ("banana", "rasthali"),
    "ரஸ்தாளி பழம்": ("banana", "rasthali"),
    "rasthali banana": ("banana", "rasthali"),
    # Ooty carrot (includes a heard misspelling ஊத்தி for ஊட்டி).
    "ஊட்டி கேரட்": ("carrot", "ooty"),
    "ooty carrot": ("carrot", "ooty"),
    "ஊட்டி": ("carrot", "ooty"),
    "ooty": ("carrot", "ooty"),
    "ஊத்தி": ("carrot", "ooty"),
    "ஊத்தி கேரட்": ("carrot", "ooty"),
}

# Variety word -> English variety, for normalising an explicitly said variety.
_VARIETY_WORDS: dict[str, str] = {
    "உஜாலா": "ujala",
    "ujala": "ujala",
    "ujjala": "ujala",
    "krishnagiri": "krishnagiri",
    "கிருஷ்ணகிரி": "krishnagiri",
    "பூவன்": "poovan",
    "poovan": "poovan",
    "ஏலக்கி": "yelakki",
    "ஏலகி": "yelakki",
    "yelakki": "yelakki",
    "elakki": "yelakki",
    "yelaki": "yelakki",
    "elaki": "yelakki",
    "கற்பூரவள்ளி": "karpooravalli",
    "karpooravalli": "karpooravalli",
    "karpuravalli": "karpooravalli",
    "தேன்வாழை": "thenvazhai",
    "thenvazhai": "thenvazhai",
    "தேன் வாழை": "thenvazhai",
    "then vazhai": "thenvazhai",
    "then vaazhai": "thenvazhai",
    "செவ்வாழை": "red",
    "sevvazhai": "red",
    "chevvazhai": "red",
    "chevvalai": "red",
    "sev vazhai": "red",
    "பச்சை வாழை": "green",
    "பச்சைவாழை": "green",
    "பச்சை பழம்": "green",
    "pachai pazham": "green",
    "பச்சை": "green",
    "pachai vazhai": "green",
    "pachaivazhai": "green",
    "pachai": "green",
    "pacha": "green",
    "pachchai": "green",
    "elaki mathi": "yelakki",
    "நேந்திரன்": "nendran",
    "nendran": "nendran",
    "ரஸ்தாளி": "rasthali",
    "rasthali": "rasthali",
    "rastali": "rasthali",
    "ஊட்டி": "ooty",
    "ooty": "ooty",
    "ஊத்தி": "ooty",
}

_ROMAN_TO_CANON: dict[str, str] = {}
_TAMIL_TO_CANON: dict[str, str] = {}
for _name_en, _name_ta, _roman in _ITEMS:
    _ROMAN_TO_CANON.setdefault(_roman.strip().lower(), _name_en)
    _TAMIL_TO_CANON.setdefault(_name_ta, _name_en)


def _alias_hit_with_key(text: str) -> tuple[str, tuple[str, str]] | None:
    """Longest (alias key, pair) found in text, else None.

    Repeated runs collapse first ("sev vazhaiwazhai" -> "sev
    vazhai"). Latin keys match at the start of a token, so "sev
    vazhai" matches "sev vazhaiwazhai"; a key never matches
    mid-token. Tamil-script keys match as whole words only: no Tamil
    letter or vowel sign may touch either side, so பூசணி inside
    தர்பூசணி does not count.
    """
    lowered = " ".join(collapse_repeated_runs(text or "").lower().split())
    if not lowered:
        return None
    best: tuple[str, tuple[str, str]] | None = None
    best_len = -1
    for alias, pair in VARIETY_ALIASES.items():
        key = alias.lower()
        if not key or len(key) <= best_len:
            continue
        start = 0
        found = False
        while True:
            idx = lowered.find(key, start)
            if idx < 0:
                break
            before = lowered[idx - 1] if idx > 0 else " "
            end = idx + len(key)
            after = lowered[end] if end < len(lowered) else " "
            if key.isascii():
                if not is_word_char(before):
                    found = True
                    break
            elif not is_word_char(before) and not is_word_char(after):
                found = True
                break
            start = idx + 1
        if found:
            best, best_len = (alias, pair), len(key)
    return best


def _alias_hit_in_text(text: str) -> tuple[str, str] | None:
    """Longest alias pair found as whole word(s) in text, else None."""
    hit = _alias_hit_with_key(text)
    return hit[1] if hit is not None else None


def alias_hit_in_text(text: str) -> tuple[str, str] | None:
    """Longest variety-nickname (name_en, variety) named in text, else None."""
    return _alias_hit_in_text(text)


def _key_in_text(lowered: str, raw: str, key: str) -> bool:
    """True when key appears in the text as whole word(s).

    Both Latin and Tamil-script keys need word bounds on both sides;
    Tamil vowel signs count as word characters, so பூசணி inside
    தர்பூசணி does not count. ``lowered`` is the space-normalized
    lower-cased text, ``raw`` the original for Tamil-script search.
    """
    if not key:
        return False
    if key.isascii():
        haystack = lowered
    else:
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


def find_name_in_text(text: str) -> str | None:
    """Canonical name_en for an item named inside free text, else None.

    Longest match wins over Tamil market synonyms, canonical Tamil
    names and English synonyms, so "கிறன் கிறன் ஃப்ரூட்" finds
    muskmelon and "எலுமிச்சை பழம்" finds lemon.
    """
    raw = text or ""
    lowered = " ".join(raw.lower().split())
    if not lowered:
        return None
    best: str | None = None
    best_len = -1
    for key, canon in TAMIL_SYNONYMS.items():
        if len(key) > best_len and _key_in_text(lowered, raw, key):
            best, best_len = canon, len(key)
    for name_ta, canon in _TAMIL_TO_CANON.items():
        if len(name_ta) > best_len and _key_in_text(lowered, raw, name_ta):
            best, best_len = canon, len(name_ta)
    for syn, canon in SYNONYMS.items():
        if len(syn) > best_len and _key_in_text(lowered, raw, syn):
            best, best_len = canon, len(syn)
    return best


def _match_spans(text: str, key: str) -> list[tuple[int, int]]:
    """All (start, end) spans where key occurs in text as whole word(s).

    Every script matches whole words case-insensitively; Tamil vowel
    signs count as word characters, so பூசணி inside தர்பூசணி and
    poosani inside tharpoosani never match.
    """
    if not key or not text:
        return []
    lowered = text.lower()
    wanted = key.lower()
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = lowered.find(wanted, start)
        if idx < 0:
            return spans
        end = idx + len(wanted)
        before = lowered[idx - 1] if idx > 0 else " "
        after = lowered[end] if end < len(lowered) else " "
        if is_word_char(before) or is_word_char(after):
            start = idx + 1
            continue
        spans.append((idx, end))
        start = idx + 1


def find_items_in_text(text: str) -> list[tuple[str, str]]:
    """Every known item named in free text, in spoken order.

    Returns (matched words, name_en) pairs: canonical English and
    Tamil names, romanised names, synonyms and variety nicknames all
    count. Every key matches whole words only, so தர்பூசணி names
    watermelon only, never ash gourd via பூசணி.
    """
    raw = text or ""
    if not raw.strip():
        return []
    scored: list[tuple[int, int, str, str]] = []
    seen: set[tuple[int, int, str]] = set()

    def _add(key: str, name_en: str) -> None:
        for span_start, span_end in _match_spans(raw, key):
            tag = (span_start, span_end, name_en)
            if tag in seen:
                continue
            seen.add(tag)
            scored.append(
                (span_start, span_end, raw[span_start:span_end], name_en))

    for name_en, name_ta in CANONICAL_NAMES.items():
        _add(name_en, name_en)
        _add(name_ta, name_en)
    for name_en, roman in EN_TO_ROMAN.items():
        _add(roman, name_en)
    for syn, name_en in SYNONYMS.items():
        _add(syn, name_en)
    for syn, name_en in TAMIL_SYNONYMS.items():
        _add(syn, name_en)
    for alias, (name_en, _variety) in VARIETY_ALIASES.items():
        _add(alias, name_en)
    scored.sort(key=lambda match: (match[0], -(match[1] - match[0])))
    kept: list[tuple[int, int, str, str]] = []
    for match in scored:
        if any(keep[0] <= match[0] and match[1] <= keep[1]
               for keep in kept):
            continue
        kept.append(match)
    kept.sort(key=lambda match: (match[0], match[1]))
    return [(match[2], match[3]) for match in kept]


def _normalized_words_in(norm_words: list[str], norm_form: str) -> bool:
    """True when the normalized form's words run inside the text words."""
    wanted = norm_form.split()
    if not wanted:
        return False
    if len(wanted) == 1:
        return wanted[0] in norm_words
    return any(norm_words[pos:pos + len(wanted)] == wanted
               for pos in range(len(norm_words) - len(wanted) + 1))


def item_name_in_text(name_en: str | None, text: str, *,
                      name_local: str | None = None) -> bool:
    """True when any of the item's name forms occurs in the text.

    The English name, the given local name, its canonical Tamil and
    Hindi names, its transliteration and every glossary synonym and
    variety nickname count, all as whole words. When no exact form
    matches, both sides compare again on the spelling-variant
    normalized form, so தர்பூசணி is found in தற்பூசணி and
    கத்தரிக்காய் in கத்தரிக்கா.
    """
    base = (name_en or "").strip().lower()
    if not base or not (text or "").strip():
        return False
    forms: set[str] = {base}
    if name_local and name_local.strip():
        forms.add(name_local.strip())
    forms.add(CANONICAL_NAMES.get(base, ""))
    forms.add(CANONICAL_NAMES_HI.get(base, ""))
    forms.add(EN_TO_ROMAN.get(base, ""))
    forms |= {syn for syn, canon in SYNONYMS.items() if canon == base}
    forms |= {syn for syn, canon in TAMIL_SYNONYMS.items()
              if canon == base}
    forms |= {alias for alias, (canon, _variety) in VARIETY_ALIASES.items()
              if canon == base}
    if any(_match_spans(text, form)
           for form in forms if form and form.strip()):
        return True
    norm_words = normalize_tamil_spelling(text).split()
    return any(_normalized_words_in(
        norm_words, normalize_tamil_spelling(form))
        for form in forms if form and form.strip())


def normalize_qualifier(variety: str | None) -> str | None:
    """English qualifier for a said variety word, else None.

    Transliterations (puthu, sinna) and Tamil/Hindi script qualifiers
    map to English; anything else (cultivar names, origins, None)
    returns None so the caller's own word is kept.
    """
    if variety is None:
        return None
    text = " ".join(str(variety).split()).lower()
    if not text:
        return None
    return _VARIETY_WORDS.get(text) or QUALIFIER_EN.get(text)


def _normalize_variety(variety: str | None) -> str | None:
    if variety is None:
        return None
    text = str(variety).strip().lower()
    if not text:
        return None
    known = normalize_qualifier(text)
    if known is not None:
        return known
    if text.isascii():
        return text
    # Non-Latin variety: salvage a known word inside, else drop it, so
    # Tamil is never stored as the English variety.
    hit = _alias_hit_in_text(text)
    if hit is not None:
        return hit[1]
    for token in text.split():
        salvaged = QUALIFIER_EN.get(token)
        if salvaged is not None:
            return salvaged
    return None


def normalize_variety(variety: str | None) -> str | None:
    """Public normaliser: English variety word, else None when blank."""
    return _normalize_variety(variety)


def _variety_in_text(base: str, text: str) -> str | None:
    """Known variety for base mentioned in lower-cased text, if any."""
    found: str | None = None
    for alias, (name_en, variety) in VARIETY_ALIASES.items():
        if name_en != base:
            continue
        if " " in alias:
            continue
        if alias in text:
            if base == "brinjal" and variety == "ujala":
                if found is None:
                    found = variety
                continue
            return variety
    return found


def resolve_name(spoken: str, variety: str | None = None,
                 extra_text: str | None = None) -> tuple[str, str | None]:
    """Map a heard item name to (name_en, variety).

    Variety nicknames (ujala brinjal, banana varieties, ooty carrot)
    resolve to their canonical item with the English variety. An
    explicitly said variety wins over the nickname default, so
    "ujjala" next to "Krishnagiri" keeps "krishnagiri".
    """
    raw = (spoken or "").strip().lower()
    if not raw:
        return ("other", _normalize_variety(variety))
    hit = VARIETY_ALIASES.get(raw)
    if hit is None and raw.isascii() and raw.endswith("s") and len(raw) > 2:
        hit = VARIETY_ALIASES.get(raw[:-1])
    if hit is not None:
        base, default = hit
        said = _normalize_variety(variety)
        if said:
            return (base, said)
        if base == "brinjal" and default == "ujala" and extra_text:
            found = _variety_in_text(base, extra_text.lower())
            if found and found != "ujala":
                return (base, found)
        return (base, default)
    base_name: str | None = None
    if raw in CANONICAL_NAMES:
        base_name = raw
    elif raw in SYNONYMS:
        base_name = SYNONYMS[raw]
    elif raw in _ROMAN_TO_CANON:
        base_name = _ROMAN_TO_CANON[raw]
    elif (spoken or "").strip() in _TAMIL_TO_CANON:
        base_name = _TAMIL_TO_CANON[(spoken or "").strip()]
    elif (spoken or "").strip() in TAMIL_SYNONYMS:
        base_name = TAMIL_SYNONYMS[(spoken or "").strip()]
    else:
        singular = raw[:-1] if raw.isascii() and raw.endswith("s") else raw
        if singular in CANONICAL_NAMES:
            base_name = singular
        elif singular in SYNONYMS:
            base_name = SYNONYMS[singular]
        elif singular in _ROMAN_TO_CANON:
            base_name = _ROMAN_TO_CANON[singular]
    if base_name is None:
        hit = _alias_hit_in_text(raw)
        if hit is not None:
            base, default = hit
            said = _normalize_variety(variety)
            if said:
                return (base, said)
            if base == "brinjal" and default == "ujala" and extra_text:
                found = _variety_in_text(base, extra_text.lower())
                if found and found != "ujala":
                    return (base, found)
            return (base, default)
        found_name = find_name_in_text(spoken or "")
        if found_name is not None:
            return (found_name, _normalize_variety(variety))
        if not raw.isascii():
            # Unknown non-Latin name: "other" keeps Tamil out of name_en;
            # the spoken word stays in name_local via the caller.
            return ("other", _normalize_variety(variety))
        return (raw, _normalize_variety(variety))
    said = _normalize_variety(variety)
    if said:
        return (base_name, said)
    if extra_text:
        found = _variety_in_text(base_name, extra_text.lower())
        if found:
            return (base_name, found)
    return (base_name, None)

SYNONYMS: dict[str, str] = {
    "shallot": "small onion",
    "shallots": "small onion",
    "eggplant": "brinjal",
    "bhindi": "okra",
    "ladyfinger": "okra",
    "lady finger": "okra",
    "big onion": "onion",
    "tomatoes": "tomato",
    "onions": "onion",
    "potatoes": "potato",
    "carrots": "carrot",
    "bananas": "banana",
    "cucumber": "cucumber",
    "bell pepper": "capsicum",
    "cilantro": "coriander",
    "green chilly": "green chilli",
    "green chili": "green chilli",
    "red chilly": "red chilli",
    "red chili": "red chilli",
    "cauli": "cauliflower",
    "sweet corn": "corn",
    "kirni": "muskmelon",
    "kiran": "muskmelon",
    "kirni fruit": "muskmelon",
    "kiran fruit": "muskmelon",
    "kiran kiran fruit": "muskmelon",
    "kirni kirni fruit": "muskmelon",
    "thenga": "coconut",
    "maanga": "raw mango",
    "poosani": "ash gourd",
    "parangi": "pumpkin",
}

# Tamil-script market spellings heard in real stall videos (Task 136):
# truncated qualifiers (தேங்கா, வெள்ளரிக்கா), the ash-gourd word
# sellers actually say (பூசணிக்காய், not the textbook வெண்பூசணி),
# spoken raw mango (மாங்கா) and muskmelon (கிர்ணி/கிறணி/கிறன்).
# Task 156 adds the spoken capsicum spelling (குடமிளகாய்) and the
# snake-gourd variant (பொடலங்காய்). Task 157: plain பூசணி is ash
# gourd (white pumpkin) in Tamil Nadu markets; yellow pumpkin is
# பரங்கிக்காய் / parangi / மஞ்சள் பூசணி.
TAMIL_SYNONYMS: dict[str, str] = {
    "பூசணிக்காய்": "ash gourd",
    "பூசணி": "ash gourd",
    "மஞ்சள் பூசணி": "pumpkin",
    "குடமிளகாய்": "capsicum",
    "பொடலங்காய்": "snake gourd",
    "மாங்கா": "raw mango",
    "கிர்ணி": "muskmelon",
    "கிறணி": "muskmelon",
    "கிறன்": "muskmelon",
    "கிர்ணி பழம்": "muskmelon",
    "கிர்ணி ஃப்ரூட்": "muskmelon",
    "கிறணி பழம்": "muskmelon",
    "கிறணி ஃப்ரூட்": "muskmelon",
    "கிறன் பழம்": "muskmelon",
    "கிறன் ஃப்ரூட்": "muskmelon",
    "கிறன் கிறன்": "muskmelon",
    "கிறன் கிறன் பழம்": "muskmelon",
    "கிறன் கிறன் ஃப்ரூட்": "muskmelon",
    "தேங்கா": "coconut",
    "வெள்ளரிக்கா": "cucumber",
}

# Spoken qualifier word -> English variety (Task 136). The model often
# transliterates the seller's qualifier (puthu, sinna); the variety must
# be the English word instead. Keys are lower-cased; Tamil and Hindi
# script keys stay as-is.
QUALIFIER_EN: dict[str, str] = {
    "புது": "new",
    "புதிய": "new",
    "புதுசு": "new",
    "puthu": "new",
    "pudhu": "new",
    "puthusu": "new",
    "new": "new",
    "नया": "new",
    "naya": "new",
    "சின்ன": "small",
    "சிறிய": "small",
    "sinna": "small",
    "chinna": "small",
    "small": "small",
    "छोटा": "small",
    "छोटी": "small",
    "chhota": "small",
    "chhoti": "small",
    "பெரிய": "big",
    "periya": "big",
    "peria": "big",
    "big": "big",
    "बड़ा": "big",
    "बड़ी": "big",
    "bada": "big",
    "badi": "big",
    "பச்சை": "green",
    "pachai": "green",
    "pacha": "green",
    "pachchai": "green",
    "green": "green",
    "हरा": "green",
    "हरी": "green",
    "hara": "green",
    "hari": "green",
    "சிவப்பு": "red",
    "செவ்": "red",
    "செவ்வாழ": "red",
    "sivappu": "red",
    "red": "red",
    "लाल": "red",
    "lal": "red",
    "நாட்டு": "country",
    "nattu": "country",
    "naatu": "country",
    "natu": "country",
    "naati": "country",
    "country": "country",
    "देसी": "country",
    "desi": "country",
    "ஸ்வீட்": "sweet",
    "sweet": "sweet",
    "मीठा": "sweet",
    "meetha": "sweet",
}

# English varieties that prefix the item in titles: "new potato".
QUALIFIER_VARIETIES: frozenset[str] = frozenset(
    {"new", "small", "big", "red", "green", "country", "sweet"})

# English qualifier -> local display word for titles (Task 136).
QUALIFIER_LOCAL: dict[str, dict[str, str]] = {
    "ta": {
        "new": "புது",
        "small": "சின்ன",
        "big": "பெரிய",
        "green": "பச்சை",
        "red": "சிவப்பு",
        "country": "நாட்டு",
        "sweet": "ஸ்வீட்",
    },
    "hi": {
        "new": "नया",
        "small": "छोटा",
        "big": "बड़ा",
        "green": "हरा",
        "red": "लाल",
        "country": "देसी",
        "sweet": "मीठा",
    },
}


def _mentions_item(text: str, name_en: str | None) -> bool:
    """True when the text names the item itself.

    Matches the English name (plus a plural "s"), its Tamil script and
    romanised names, and its synonyms, all with word bounds. Guards the
    variety-wins rule: "pachai milagaai" must not become banana, and
    "ooty potato" must not become carrot.
    """
    lowered = " ".join((text or "").lower().split())
    if not lowered:
        return False
    base = (name_en or "").strip().lower()
    if not base or base == "other":
        return False
    words = {base, CANONICAL_NAMES.get(base, ""), EN_TO_ROMAN.get(base, "")}
    words |= {syn for syn, canon in SYNONYMS.items() if canon == base}
    padded = f" {lowered} "
    for word in words:
        word = (word or "").strip().lower()
        if not word:
            continue
        if word.isascii():
            if f" {word} " in padded or f" {word}s " in padded:
                return True
        elif word in lowered:
            return True
    return False


# Filler words said around a variety ("வரி krishnagiri வரி"): dropped
# before checking whether a local name is just a variety alias.
_VARIETY_LOCAL_FILLERS: frozenset[str] = frozenset({"வரி", "vari", "variety"})


def repair_variety_local_name(name_en: str | None, name_local: str | None,
                              *, language: str = "ta") -> str | None:
    """Replace a local name that is really the spoken variety (Task 103).

    When name_local is just a known variety alias (any script) of this
    item, or an alias plus filler words, and the item has a canonical
    local name for the shop language, the canonical name is returned.
    Names that already equal the canonical name, the English name, the
    romanised name or a known synonym of the item pass through, as does
    an alias for a different item (the Task 97 rename path owns that).
    """
    if name_local is None:
        return None
    base = (name_en or "").strip().lower()
    canonical = canonical_local_name(base, language) if base else None
    if not canonical:
        return name_local
    local = str(name_local)
    normalized = " ".join(local.lower().split())
    if not normalized:
        return name_local
    known = {canonical.lower(), base, EN_TO_ROMAN.get(base, "").lower()}
    known |= {syn for syn, canon in SYNONYMS.items() if canon == base}
    if normalized in known:
        return name_local
    kept = [tok for tok in normalized.split()
            if tok not in _VARIETY_LOCAL_FILLERS]
    remainder = " ".join(kept)
    if remainder:
        pair = VARIETY_ALIASES.get(remainder)
        if pair is not None and pair[0] == base:
            return canonical
    return name_local


def decide_name_from_variety(name_en: str | None, variety: str | None,
                             spoken: str | None, extra: str | None = None,
                             *, language: str = "ta"
                             ) -> tuple[str, str | None, str | None,
                                        str | None]:
    """Apply the variety-decides-the-item rule (Task 97).

    When the variety or the spoken words match a VARIETY_ALIASES entry
    for a different item, the variety wins: returns that item, its
    variety, the canonical local name for the shop language (English
    name when the language has no canonical name), and the matched
    alias word for the check-page note. Otherwise, when no variety was
    said but the words hold a known variety of the same item, returns
    the filled variety with no note word. With nothing to do, returns
    the inputs unchanged (local name and note word None).
    """
    base = (name_en or "").strip().lower() or "other"
    said_variety = (variety or "").strip()
    spoken_text = f"{spoken or ''} {extra or ''}".strip()
    trigger: tuple[str, str, str] | None = None
    if said_variety:
        key = " ".join(said_variety.lower().split())
        pair = VARIETY_ALIASES.get(key)
        if pair is not None:
            trigger = (key, pair[0], pair[1])
        else:
            hit = _alias_hit_with_key(said_variety)
            if hit is not None:
                trigger = (hit[0], hit[1][0], hit[1][1])
    if trigger is None and spoken_text:
        hit = _alias_hit_with_key(spoken_text)
        if hit is not None:
            trigger = (hit[0], hit[1][0], hit[1][1])
    if trigger is not None:
        word, alias_item, alias_variety = trigger
        if alias_item != base and not _mentions_item(spoken_text, base):
            local = canonical_local_name(alias_item, language) or alias_item
            return (alias_item, alias_variety, local, word)
    if not said_variety and spoken_text:
        found = _variety_in_text(base, spoken_text.lower())
        if found:
            return (name_en or base, found, None, None)
    return (name_en or base, variety, None, None)


def correct_draft_from_variety(item, *, language: str = "ta"):
    """Rename a draft when its variety or spoken words name another item.

    Mutates name_en, variety, name_local and match_key; price lines and
    proof are untouched. A rename appends a soft VARIETY_NAMED flag
    ("named from the variety you said (ujala → brinjal)") and returns
    it; a same-item variety fill or no change returns None. Callers
    must skip items carrying a seller-chosen name.
    """
    spoken = getattr(item, "name_spoken", "") or ""
    proof = getattr(item, "proof", None)
    quote = getattr(proof, "quote", "") or ""
    name_en, variety, local, word = decide_name_from_variety(
        item.name_en, item.variety, spoken, quote, language=language)
    if word is None:
        item.variety = variety
        return None
    item.name_en = name_en
    item.variety = variety
    if local is not None:
        item.name_local = local
    item.match_key = name_en
    flag = Flag(field="name", code="VARIETY_NAMED",
                message=(f"named from the variety you said"
                         f" ({word} → {name_en})"),
                blocking=False)
    item.flags.append(flag)
    return flag

PRODUCE_KEYWORDS: list[str] = sorted(
    {name_en for name_en, _, _ in _ITEMS}
    | {name_ta for _, name_ta, _ in _ITEMS}
    | {roman for _, _, roman in _ITEMS}
    | set(VARIETY_ALIASES)
)

_ENGLISH_KEYWORDS: list[str] = sorted(
    {name_en for name_en, _, _ in _ITEMS}
    | {alias for alias in VARIETY_ALIASES if alias.isascii()}
)


def keywords_for(language_code: str | None) -> list[str]:
    """Voice Transcribe keywords for a shop language.

    Tamil shops get the full list (English + Tamil script + romanised
    Tamil). Every other language gets only the English names: Tamil
    script in the keywords biases the speech model into writing Tamil
    inside other languages' transcripts.
    """
    if language_code == "ta":
        return list(PRODUCE_KEYWORDS)
    return list(_ENGLISH_KEYWORDS)


# English variety -> Tamil display word (Task 55). Each variety below is
# only sold for one item, so the variety alone picks the Tamil word.
VARIETY_LOCAL: dict[str, str] = {
    "ujala": "உஜாலா",
    "krishnagiri": "கிருஷ்ணகிரி",
    "poovan": "பூவன்",
    "yelakki": "ஏலக்கி",
    "karpooravalli": "கற்பூரவள்ளி",
    "thenvazhai": "தேன்வாழை",
    "red": "செவ்வாழை",
    "green": "பச்சை வாழை",
    "nendran": "நேந்திரன்",
    "rasthali": "ரஸ்தாளி",
    "ooty": "ஊட்டி",
    "new": "புது",
    "small": "சின்ன",
    "big": "பெரிய",
    "country": "நாட்டு",
    "sweet": "ஸ்வீட்",
}


def variety_local_name(variety: str | None, *,
                       language: str = "ta") -> str | None:
    """Local display word for an English variety, or None if unknown.

    Only Tamil has local variety words; every other shop language keeps
    the English variety.
    """
    if variety is None or language != "ta":
        return None
    key = str(variety).strip().lower()
    if not key:
        return None
    return VARIETY_LOCAL.get(key)


def _title(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def display_name_en(name_en: str | None, variety: str | None = None) -> str:
    """English display name: "Banana (Poovan)", or plain "Banana".

    Unknown items ("other") show nothing: customers never see "other".
    """
    base_raw = (name_en or "").strip()
    if base_raw.lower() == "other":
        return ""
    base = _title(base_raw)
    text = str(variety or "").strip()
    if base and text:
        return f"{base} ({_title(text)})"
    return base


def display_name_local(name_local: str | None,
                       variety: str | None = None, *,
                       language: str = "ta") -> str:
    """Local display name: "வாழைப்பழம் (பூவன்)", or the plain name.

    When the local name already contains the variety's local word
    ("பூவன் பழம்" holds "பூவன்"), it is returned as-is, never doubled.
    Shop languages without local variety words keep the English variety.
    """
    base = (name_local or "").strip()
    if not base:
        return ""
    text = str(variety or "").strip()
    if not text:
        return base
    local_word = variety_local_name(text, language=language)
    if local_word:
        if local_word in base:
            return base
        return f"{base} ({local_word})"
    if text.casefold() in base.casefold():
        return base
    return f"{base} ({_title(text)})"


def qualified_name(name_en: str | None, variety: str | None = None) -> str:
    """Bill-form value carrying the variety: "banana (poovan)"."""
    base = (name_en or "").strip()
    text = str(variety or "").strip()
    if base and text:
        return f"{base} ({text})"
    return base


def english_title(name_en: str | None, variety: str | None = None) -> str:
    """Item title in English with the variety: "new potato".

    Qualifier varieties (new, small, big, red, green, country, sweet)
    prefix the name so two kinds never read the same; every other
    variety keeps the parenthetical display form ("Banana (Poovan)").
    Unknown items ("other") show nothing.
    """
    base = (name_en or "").strip()
    if not base or base.lower() == "other":
        return ""
    text = str(variety or "").strip()
    if not text:
        return base
    if text.lower() in QUALIFIER_VARIETIES:
        return f"{text.lower()} {base.lower()}"
    return display_name_en(base, text)


def local_title(name_local: str | None, variety: str | None = None,
                name_en: str | None = None, language: str = "ta") -> str:
    """Item title in the shop language with the variety.

    Qualifier varieties prefix the local qualifier word ("புது
    உருளைக்கிழங்கு"); a red banana is just "செவ்வாழை". Any other
    variety falls back to the parenthetical display form.
    """
    base = (name_local or "").strip()
    if not base:
        return ""
    text = str(variety or "").strip().lower()
    if not text:
        return base
    words = QUALIFIER_LOCAL.get(language, {})
    if text in QUALIFIER_VARIETIES and text in words:
        if (text == "red" and language == "ta"
                and (name_en or "").strip().lower() == "banana"):
            return VARIETY_LOCAL["red"]
        word = words[text]
        if word in base:
            return base
        base_words = [chunk.strip(".,;:!?\"'()[]{}")
                      for chunk in base.lower().split()]
        if text in base_words:
            # The seller's own local name already holds the qualifier in
            # English ("Sweet corn"): never prefix it again.
            return base
        return f"{word} {base}"
    return display_name_local(base, variety, language=language)


def _qualifier_said(spoken: str, variety: str, name_en: str | None,
                    language: str) -> bool:
    """True when the spoken text holds the qualifier in any spelling."""
    lowered = " ".join((spoken or "").lower().split())
    if not lowered:
        return False
    word = QUALIFIER_LOCAL.get(language, {}).get(variety)
    if word and word in spoken:
        return True
    base = (name_en or "").strip().lower()
    for alias, (item, var) in VARIETY_ALIASES.items():
        if var == variety and item == base and alias in lowered:
            return True
    for key, val in QUALIFIER_EN.items():
        if val == variety and _key_in_text(lowered, spoken, key):
            return True
    return _key_in_text(lowered, spoken, variety)


def restore_spoken_local_name(
        name_local: str | None, *, name_spoken: str | None = None,
        quote: str | None = None, variety: str | None = None,
        name_en: str | None = None, language: str = "ta") -> str | None:
    """Keep a qualifier the extracted local name dropped (Task 136).

    When the seller's own item words hold a qualifier missing from
    name_local ("புது உருளைக்கிழங்கு" heard, plain "உருளைக்கிழங்கு"
    extracted), the spoken words become the local name. A spoken
    variety nickname ("செவ்வாழை") is kept whole. Only words that were
    actually said are ever used; anything else passes through.
    """
    base = (name_local or "").strip()
    if not base:
        return name_local
    text = str(variety or "").strip().lower()
    if text not in QUALIFIER_VARIETIES:
        return base
    words = QUALIFIER_LOCAL.get(language, {})
    word = words.get(text)
    if word and word in base:
        return base
    spoken = f"{name_spoken or ''} {quote or ''}"
    if not _qualifier_said(spoken, text, name_en, language):
        return base
    cand = " ".join((name_spoken or "").split()).strip(
        ".,;:!?\"'()[]{}।॥ ")
    if cand:
        base_key = (name_en or "").strip().lower()
        if VARIETY_ALIASES.get(cand.lower()) == (base_key, text):
            return cand
        if word and word in cand and base in cand:
            return cand
    if word:
        return f"{word} {base}"
    return base


def _strip_marks(text: str) -> str:
    """Text without combining marks (unicodedata category M*)."""
    return "".join(
        char for char in text
        if not unicodedata.category(char).startswith("M"))


def _has_marks(text: str) -> bool:
    return any(unicodedata.category(char).startswith("M")
               for char in text)


def _has_indic(text: str) -> bool:
    """True when any character sits in the Indic script blocks."""
    return any(0x0900 <= ord(char) <= 0x0DFF for char in text)


def repair_local_name(name_en: str | None,
                      name_local: str | None) -> str | None:
    """Fix a local name stored without its vowel signs (Task 68).

    The speech model sometimes drops combining marks, storing e.g.
    "அவரககய" for broad beans instead of "அவரைக்காய்". When the English
    name maps to a canonical entry and the local name equals the
    canonical name with its combining marks removed — or is an Indic
    string with no combining marks at all while the canonical one has
    some — the canonical local name is returned. Anything else,
    including every seller-chosen name, passes through untouched.
    """
    if name_local is None:
        return None
    canonical = CANONICAL_NAMES.get(str(name_en or "").strip().lower())
    if not canonical:
        return name_local
    local = str(name_local)
    if local.strip() == _strip_marks(canonical):
        return canonical
    if (_has_marks(canonical) and _has_indic(local)
            and not _has_marks(local)):
        return canonical
    return name_local
