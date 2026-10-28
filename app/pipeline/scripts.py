"""Unicode-script guard for transcripts (Task 53).

When the shop language and the spoken language differ, Voice Transcribe can
write the speech in the wrong script (Tamil speech in Kannada letters on an
English shop). The proof check then finds no numbers and blocks every price
as NOT_HEARD. This module detects that mismatch cheaply, before any Spark
call, so the seller gets a question instead of a stuck session.
"""

from __future__ import annotations

import unicodedata

# First word of the Unicode character name -> script label. Anything else
# (Hebrew, CJK, Hangul, ...) is "other": dominant_script only names the
# scripts this guard reasons about.
_NAME_PREFIX: dict[str, str] = {
    "LATIN": "Latin",
    "TAMIL": "Tamil",
    "DEVANAGARI": "Devanagari",
    "BENGALI": "Bengali",
    "TELUGU": "Telugu",
    "KANNADA": "Kannada",
    "MALAYALAM": "Malayalam",
    "GUJARATI": "Gujarati",
    "GURMUKHI": "Gurmukhi",
    "ORIYA": "Odia",
    "ARABIC": "Arabic",
    "THAI": "Thai",
}

#: Every label dominant_script can return.
SCRIPTS = frozenset(_NAME_PREFIX.values()) | {"other"}

MIN_GUARD_LETTERS = 12


def _char_script(char: str) -> str:
    try:
        name = unicodedata.name(char)
    except ValueError:
        return "other"
    return _NAME_PREFIX.get(name.split(" ", 1)[0], "other")


def count_letters(text: str) -> int:
    """Number of Unicode letters, ignoring digits, punctuation and spaces."""
    return sum(1 for char in text or ""
               if unicodedata.category(char).startswith("L"))


def dominant_script(text: str) -> str:
    """Script of most letters: Latin, Tamil, Devanagari, Bengali, Telugu,
    Kannada, Malayalam, Gujarati, Gurmukhi, Odia, Arabic, Thai or other.

    Digits, punctuation, spaces and combining marks are ignored. Ties go to
    the first-seen script; text without letters is "other".
    """
    counts: dict[str, int] = {}
    for char in text or "":
        if not unicodedata.category(char).startswith("L"):
            continue
        script = _char_script(char)
        counts[script] = counts.get(script, 0) + 1
    if not counts:
        return "other"
    return max(counts.items(), key=lambda item: item[1])[0]


def expected_scripts(bias) -> set[str]:
    """Scripts allowed for a Voice languageBias list.

    Each bias language contributes its registry script; Latin is always
    allowed because sellers romanise. Registry scripts outside the guard
    vocabulary (Hebrew, Japanese, Korean, Han) map to "other" so those
    shops never trip the guard on their own script.
    """
    from app.languages import by_api_name

    scripts = {"Latin"}
    for name in bias or []:
        try:
            script = by_api_name(name).script
        except KeyError:
            continue
        scripts.add(script if script in SCRIPTS else "other")
    return scripts


def script_mismatch(text: str, bias, *, min_letters: int = MIN_GUARD_LETTERS,
                    ) -> str | None:
    """Dominant script when text is confidently in an unexpected script.

    Returns None when the text is too short (fewer than ``min_letters``
    letters) or its dominant script is expected for ``bias``.
    """
    if count_letters(text) < min_letters:
        return None
    dominant = dominant_script(text)
    if dominant in expected_scripts(bias):
        return None
    return dominant
