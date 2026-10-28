"""One money formatter for every price shown to sellers and customers.

Symbols cover the Task 29 language-registry currencies. Whole numbers print
without decimals, otherwise with 2 decimals; INR uses Indian digit grouping.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",  # U+20B9
    "EUR": "€",  # U+20AC
    "JPY": "¥",  # U+00A5
    "CNY": "¥",  # U+00A5
    "KRW": "₩",  # U+20A9
    "THB": "฿",  # U+0E3F
    "PHP": "₱",  # U+20B1
    "VND": "₫",  # U+20AB
    "ILS": "₪",  # U+20AA
    "TRY": "₺",  # U+20BA
    "PLN": "zl",
    "BRL": "R$",
    "MYR": "RM",
    "IDR": "Rp",
    "AED": "AED ",
}


def _group_indian(digits: str) -> str:
    """Indian digit grouping: last 3 digits, then groups of 2 (1,25,000)."""
    if len(digits) <= 3:
        return digits
    last3 = digits[-3:]
    rest = digits[:-3]
    groups = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    return ",".join(reversed(groups)) + "," + last3


def format_money(value, currency: str | None = "INR") -> str:
    """Format a price with its currency symbol, e.g. "₹1,25,000" or "€18.50".

    Unknown currencies fall back to "CODE amount". None and "" stay empty.
    """
    if value is None or value == "":
        return ""
    code = (currency or "INR") if isinstance(currency, str) else "INR"
    code = code.strip() or "INR"
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return str(value)
    if amount.is_nan():
        return str(value)
    negative = amount < 0
    amount = abs(amount)
    if amount == amount.to_integral_value():
        figures = str(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        int_part, frac_part = figures, ""
    else:
        figures = str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        int_part, _, frac_part = figures.partition(".")
    if code == "INR":
        grouped = _group_indian(int_part)
    else:
        grouped = f"{int(int_part):,}"
    if frac_part:
        grouped = f"{grouped}.{frac_part}"
    if negative:
        grouped = f"-{grouped}"
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol is None:
        return f"{code} {grouped}"
    return f"{symbol}{grouped}"
