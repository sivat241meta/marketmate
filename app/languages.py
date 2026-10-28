"""Registry of the 25 Muse Voice languages.

Names in ``languageBias`` must be the API names exactly as Muse Voice
expects them (see docs/build-plan-2.md ground rules).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    api_name: str
    native_name: str
    script: str
    default_currency: str
    currency_words: tuple[str, ...]
    decimal_comma: bool


LANGUAGES: tuple[Language, ...] = (
    Language("ar", "Arabic", "العربية", "Arabic", "AED",
             ("dirham", "dirhams", "dh", "dhs", "aed", "درهم", "دراهم"),
             False),
    Language("bn", "Bengali", "বাংলা", "Bengali", "INR",
             ("rupee", "rupees", "taka", "takas", "rs", "inr", "₹",
              "টাকা", "রুপি"),
             False),
    Language("nl", "Dutch", "Nederlands", "Latin", "EUR",
             ("euro", "euros", "€"), True),
    Language("en", "English", "English", "Latin", "INR",
             ("rupee", "rupees", "rs", "inr", "₹"), False),
    Language("fr", "French", "Français", "Latin", "EUR",
             ("euro", "euros", "€"), True),
    Language("de", "German", "Deutsch", "Latin", "EUR",
             ("euro", "euros", "€"), True),
    Language("he", "Hebrew", "עברית", "Hebrew", "ILS",
             ("shekel", "shekels", "sheqel", "shkalim", "shekalim",
              "nis", "ils", "₪", "שקל", "שקלים"),
             False),
    Language("hi", "Hindi", "हिन्दी", "Devanagari", "INR",
             ("rupee", "rupees", "rupay", "rupaye", "rupai", "rupaya",
              "rs", "inr", "₹", "रुपया", "रुपये", "रुपए", "रू"),
             False),
    Language("id", "Indonesian", "Bahasa Indonesia", "Latin", "IDR",
             ("rupiah", "rp", "idr"), True),
    Language("it", "Italian", "Italiano", "Latin", "EUR",
             ("euro", "euri", "euros", "€"), True),
    Language("ja", "Japanese", "日本語", "Japanese", "JPY",
             ("yen", "en", "jpy", "¥", "円", "えん"), False),
    Language("kn", "Kannada", "ಕನ್ನಡ", "Kannada", "INR",
             ("rupee", "rupees", "rupayi", "rupayigalu", "rs", "inr",
              "₹", "ರೂಪಾಯಿ", "ರೂಪಾಯಿಗಳು", "ರೂ"),
             False),
    Language("ko", "Korean", "한국어", "Korean", "KRW",
             ("won", "krw", "₩", "원"), False),
    Language("ms", "Malay", "Bahasa Melayu", "Latin", "MYR",
             ("ringgit", "rm", "myr"), False),
    Language("zh", "Mandarin Chinese", "中文", "Han", "CNY",
             ("yuan", "kuai", "cny", "¥", "元", "块"), False),
    Language("mr", "Marathi", "मराठी", "Devanagari", "INR",
             ("rupee", "rupees", "rupay", "rupaye", "rs", "inr", "₹",
              "रुपया", "रुपये", "रू"),
             False),
    Language("pl", "Polish", "Polski", "Latin", "PLN",
             ("zloty", "zlote", "zlotych", "zlotys", "zl", "zł", "pln"),
             True),
    Language("pt", "Portuguese", "Português", "Latin", "BRL",
             ("real", "reais", "r$", "brl"), True),
    Language("es", "Spanish", "Español", "Latin", "EUR",
             ("euro", "euros", "€"), True),
    Language("tl", "Tagalog", "Tagalog", "Latin", "PHP",
             ("peso", "pesos", "piso", "php", "₱"), False),
    Language("ta", "Tamil", "தமிழ்", "Tamil", "INR",
             ("rupee", "rupees", "rupai", "rupay", "ruba", "rs", "inr",
              "₹", "ரூபாய்", "ரூபா"),
             False),
    Language("te", "Telugu", "తెలుగు", "Telugu", "INR",
             ("rupee", "rupees", "rupayi", "rupayalu", "rs", "inr", "₹",
              "రూపాయి", "రూపాయలు", "రూ"),
             False),
    Language("th", "Thai", "ไทย", "Thai", "THB",
             ("baht", "thb", "฿", "บาท"), False),
    Language("tr", "Turkish", "Türkçe", "Latin", "TRY",
             ("lira", "liras", "tl", "try", "₺"), True),
    Language("vi", "Vietnamese", "Tiếng Việt", "Latin", "VND",
             ("dong", "dongs", "vnd", "₫", "đồng"), True),
)

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}
_BY_API_NAME: dict[str, Language] = {lang.api_name: lang for lang in LANGUAGES}


def get_language(code: str) -> Language:
    """Language for a stored shop code such as "ta"."""
    return _BY_CODE[code]


def by_api_name(api_name: str) -> Language:
    """Language for a Muse Voice API name such as "Tamil"."""
    return _BY_API_NAME[api_name]


def language_bias(code: str) -> list[str]:
    """Voice Transcribe languageBias: [shop language, English], deduplicated."""
    api_name = get_language(code).api_name
    if api_name == "English":
        return ["English"]
    return [api_name, "English"]


def shop_bias(code: str | None) -> tuple[str, ...]:
    """languageBias for a stored shop code; unknown codes keep Tamil+English."""
    try:
        return tuple(language_bias(code or "ta"))
    except KeyError:
        return ("Tamil", "English")


def all_currencies() -> list[str]:
    """Distinct registry currencies, sorted for the shop form."""
    return sorted({lang.default_currency for lang in LANGUAGES})


def currency_words_for(code: str) -> tuple[str, ...]:
    """Spoken currency words for a shop language code."""
    return get_language(code).currency_words
