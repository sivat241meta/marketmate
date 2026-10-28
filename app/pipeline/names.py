"""Canonical produce names: English key -> (Tamil script, romanised Tamil)."""

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
)

CANONICAL_NAMES: dict[str, str] = {name_en: name_ta for name_en, name_ta, _ in _ITEMS}

EN_TO_ROMAN: dict[str, str] = {name_en: roman for name_en, _, roman in _ITEMS}

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
    "பச்சை": ("banana", "green"),
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


def _normalize_variety(variety: str | None) -> str | None:
    if variety is None:
        return None
    text = str(variety).strip().lower()
    if not text:
        return None
    return _VARIETY_WORDS.get(text, text)


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
    else:
        singular = raw[:-1] if raw.isascii() and raw.endswith("s") else raw
        if singular in CANONICAL_NAMES:
            base_name = singular
        elif singular in SYNONYMS:
            base_name = SYNONYMS[singular]
        elif singular in _ROMAN_TO_CANON:
            base_name = _ROMAN_TO_CANON[singular]
    if base_name is None:
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
}

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
}


def variety_local_name(variety: str | None) -> str | None:
    """Tamil display word for an English variety, or None if unknown."""
    if variety is None:
        return None
    key = str(variety).strip().lower()
    if not key:
        return None
    return VARIETY_LOCAL.get(key)


def _title(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def display_name_en(name_en: str | None, variety: str | None = None) -> str:
    """English display name: "Banana (Poovan)", or plain "Banana"."""
    base = _title((name_en or "").strip())
    text = str(variety or "").strip()
    if base and text:
        return f"{base} ({_title(text)})"
    return base


def display_name_local(name_local: str | None,
                       variety: str | None = None) -> str:
    """Local display name: "வாழைப்பழம் (பூவன்)", or the plain name.

    When the local name already contains the variety's local word
    ("பூவன் பழம்" holds "பூவன்"), it is returned as-is, never doubled.
    """
    base = (name_local or "").strip()
    if not base:
        return ""
    text = str(variety or "").strip()
    if not text:
        return base
    local_word = variety_local_name(text)
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
