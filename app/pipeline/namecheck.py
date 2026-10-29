"""Seller-chosen product names (Task 66).

One shared validator for both rename paths (the check page and the live
list). A name change never carries a price: anything price-like is
rejected, and the caller keeps prices, proofs and "said" text untouched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LOCAL_MAX = 40
ENGLISH_MAX = 40
VARIETY_MAX = 30

_PRICE_RE = re.compile(r"""
    ₹                                   # rupee sign anywhere
  | \d\s*/                              # 60/kg, 60 / kg
  | /\s*\d                              # /60
  | \b\d[\d.,]*\s*(?:rs\.?|rupees?|inr)\b   # 60 rs, 60 rupees
  | \b(?:rs\.?|rupees?|inr)\s*\d        # rs 60
""", re.IGNORECASE | re.VERBOSE)


@dataclass
class NameValidationError(ValueError):
    """Invalid seller name; ``key`` is a t() key, ``params`` its format vars."""

    key: str
    params: dict | None = None

    def __post_init__(self) -> None:
        super().__init__(self.key)
        if self.params is None:
            self.params = {}


def clean_text(text: str | None) -> str:
    """Strip control characters, trim, collapse inner whitespace."""
    cleaned = "".join(
        char for char in (text or "")
        if unicodedata.category(char) != "Cc")
    return " ".join(cleaned.split())


def _has_letter(text: str) -> bool:
    return any(unicodedata.category(char).startswith("L") for char in text)


def _check_one(text: str, *, field: str, max_len: int) -> str:
    if not text:
        raise NameValidationError("rename.err_empty", {"field": field})
    if len(text) > max_len:
        raise NameValidationError(
            "rename.err_too_long", {"field": field, "max": max_len})
    if not _has_letter(text):
        raise NameValidationError("rename.err_letters", {"field": field})
    if _PRICE_RE.search(text):
        raise NameValidationError("rename.err_price", {"field": field})
    return text


def validate_names(name_local: str | None, name_en: str | None,
                   variety: str | None, shop_lang: str | None = None,
                   ) -> tuple[str, str, str | None]:
    """Clean and validate a seller-chosen (local, English, variety) triple.

    Returns the cleaned triple with variety None when blank. The local
    name must be in the shop language's script (Task 53 guard) or Latin,
    which sellers use for romanised names.
    """
    from app.languages import shop_bias
    from app.pipeline.scripts import dominant_script, expected_scripts

    local = _check_one(clean_text(name_local), field="local",
                       max_len=LOCAL_MAX)
    english = _check_one(clean_text(name_en), field="en",
                         max_len=ENGLISH_MAX)
    varied = clean_text(variety)
    if len(varied) > VARIETY_MAX:
        raise NameValidationError(
            "rename.err_too_long", {"field": "variety", "max": VARIETY_MAX})
    if varied:
        if not _has_letter(varied):
            raise NameValidationError(
                "rename.err_letters", {"field": "variety"})
        if _PRICE_RE.search(varied):
            raise NameValidationError(
                "rename.err_price", {"field": "variety"})
    try:
        allowed = expected_scripts(shop_bias(shop_lang or "en"))
    except (KeyError, ImportError, AttributeError):
        allowed = {"Latin"}
    if dominant_script(local) not in allowed:
        raise NameValidationError("rename.err_script")
    return (local, english, varied or None)
