"""Customer quotation: wanted lines from text or photo, priced from the shop list.

Golden rule: a quote only uses the shop's own published price lines. Never
invent or estimate a price; items not on the list are shown as
"not on this shop's list".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from app.market.search import SYNONYMS, parse_query
from app.meta.spark import chat_json, image_part
from app.pipeline.checks import WEIGHT_ITEMS
from app.pipeline.names import CANONICAL_NAMES
from app.pipeline.units import convert, normalize_unit
from app.pipeline.vision import analyse_photo

__all__ = [
    "Quote",
    "QuoteLine",
    "WantedLine",
    "build_quote",
    "wanted_from_photo",
    "wanted_from_text",
]


@dataclass
class WantedLine:
    name_en: str
    qty: Decimal | None
    unit: str | None
    source: str
    amount: Decimal | None = None


@dataclass
class QuoteLine:
    name_en: str
    name_local: str
    qty: Decimal
    unit: str | None
    unit_price: Decimal | None
    per_amount: Decimal | None
    line_total: Decimal | None
    status: str
    note: str | None = None


@dataclass
class Quote:
    lines: list[QuoteLine]
    total: Decimal
    priced_count: int
    unpriced_count: int
    prices_set_at: datetime | None


def _canonical(name: str | None) -> str:
    key = (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def _wanted_name(raw: str) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return ""
    mapped = SYNONYMS.get(key, key)
    if mapped in CANONICAL_NAMES:
        return mapped
    if key.endswith("s") and key[:-1] in CANONICAL_NAMES:
        return key[:-1]
    if mapped.endswith("s") and mapped[:-1] in CANONICAL_NAMES:
        return mapped[:-1]
    return key


def _positive(value: Decimal | None) -> Decimal | None:
    if value is None or value <= 0:
        return None
    return value


def wanted_from_text(text: str, *, ledger, settings) -> list[WantedLine]:
    """Parse a typed or spoken list via parse_query; keep unknown words."""
    query = parse_query(text, ledger=ledger, settings=settings)
    wanted: list[WantedLine] = []
    for want in query.wants:
        wanted.append(WantedLine(
            name_en=want.name_en,
            qty=_positive(want.amount),
            unit=want.unit,
            source="text",
        ))
    for unknown in query.unknown:
        name = (unknown or "").strip().lower()
        if not name:
            continue
        wanted.append(WantedLine(name_en=name, qty=None, unit=None,
                                 source="text"))
    return wanted


_PHOTO_INSTRUCTION = (
    "Look at this photo. It is either (A) fresh produce items laid out, or "
    "(B) a handwritten or printed shopping list. "
    'If (A), return {"kind": "items", "products": '
    '[{"name_en": "tomato", "countable": true}], "lines": []} with one entry '
    "per distinct produce product visible (name_en is the common English "
    "name, lower case). "
    'If (B), return {"kind": "shopping_list", "products": [], '
    '"lines": [{"name": "tomato", "qty": 2, "unit": "kg"}]} with one entry '
    "per list line, copied exactly as written (qty is a number or null, "
    "unit is the word as written or null). "
    "Do not guess any prices."
)

_LIST_KINDS = {"shopping_list", "shopping-list", "list",
               "handwritten_list", "printed_list"}


def _photo_unit(raw) -> str | None:
    """Canonical unit for a shopping-list photo line, or None if unknown."""
    if raw is None:
        return None
    canonical, _ = normalize_unit(str(raw))
    return canonical


def _decimal_or_none(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None
    return _positive(result)


def wanted_from_photo(image: Path | str, *, ledger, settings
                      ) -> list[WantedLine]:
    """One vision call: items photo -> counts, list photo -> lines as written.

    For an items photo the quantities come from the reconciled counts in
    vision.analyse_photo; for a shopping-list photo the qty/unit are read
    from the list itself.
    """
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    messages = [{"role": "user", "content": [
        {"type": "text", "text": (
            f"{_PHOTO_INSTRUCTION}\n\nCanonical names: {canonical}\n\n"
            "Return only JSON.")},
        image_part(Path(image)),
    ]}]
    data = chat_json(messages, ledger=ledger, settings=settings,
                     reasoning_effort="low")
    if not isinstance(data, dict):
        return []
    kind = str(data.get("kind") or "").strip().lower()
    raw_lines = data.get("lines") or []
    raw_products = data.get("products") or []
    is_list = kind in _LIST_KINDS or (
        not kind and isinstance(raw_lines, list) and raw_lines
        and not raw_products)
    if is_list:
        wanted: list[WantedLine] = []
        if not isinstance(raw_lines, list):
            return []
        for raw in raw_lines:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            qty = _decimal_or_none(raw.get("qty"))
            canonical, factor = normalize_unit(raw.get("unit"))
            if qty is not None and factor != 1:
                qty = _positive(qty * factor)
            wanted.append(WantedLine(
                name_en=_wanted_name(name),
                qty=qty,
                unit=canonical,
                source="photo_list",
            ))
        return wanted
    report = analyse_photo(Path(image), shop_items=[], ledger=ledger,
                           settings=settings)
    wanted = []
    for product in report.products:
        qty: Decimal | None = None
        if product.count is not None:
            qty = Decimal(product.count)
        elif (product.needs_check and product.count_range is not None
                and len(product.count_range) == 2):
            low, high = product.count_range
            qty = Decimal(round((low + high) / 2))
        unit = "piece" if product.countable else None
        wanted.append(WantedLine(
            name_en=product.name_en, qty=_positive(qty), unit=unit,
            source="photo_items"))
    return wanted


def _line_total(unit_price: Decimal, qty: Decimal, unit: str,
                per_amount: Decimal, per_unit: str) -> Decimal | None:
    converted = convert(qty, unit, per_unit)
    if converted is None:
        return None
    return (unit_price * converted / per_amount).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt_amt(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _plural(noun: str, count: int) -> str:
    if count == 1:
        return noun
    return {"bunch": "bunches"}.get(noun, noun + "s")


def _amount_line(amount: Decimal, picked) -> tuple[Decimal, str, Decimal, str]:
    """Quantity, unit, total and note for a "Rs N worth" order line."""
    price, per_amount, per_unit = picked.price, picked.per_amount, picked.unit
    base = amount * per_amount / price
    if per_unit in ("kg", "g"):
        grams = convert(base, per_unit, "g")
        rounded = (grams / Decimal(10)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP) * Decimal(10)
        if rounded <= 0:
            rounded = Decimal(10)
        qty = convert(rounded, "g", per_unit)
        total = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return (qty, per_unit, total,
                f"₹{_fmt_amt(amount)} worth (≈ {_fmt_amt(qty)} {per_unit})")
    if per_unit in ("l", "ml"):
        mls = convert(base, per_unit, "ml")
        rounded = (mls / Decimal(10)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP) * Decimal(10)
        if rounded <= 0:
            rounded = Decimal(10)
        qty = convert(rounded, "ml", per_unit)
        total = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return (qty, per_unit, total,
                f"₹{_fmt_amt(amount)} worth (≈ {_fmt_amt(qty)} {per_unit})")
    if per_unit in ("piece", "dozen"):
        pieces = convert(base, per_unit, "piece")
        whole = int(pieces.to_integral_value(rounding=ROUND_FLOOR))
        whole = max(1, whole)
        qty = convert(Decimal(whole), "piece", per_unit)
        total = _line_total(price, qty, per_unit, per_amount, per_unit)
        note = (f"₹{_fmt_amt(amount)} worth (≈ {whole}"
                f" {_plural('piece', whole)}")
        return (qty, per_unit, total, note)
    whole = int(base.to_integral_value(rounding=ROUND_FLOOR))
    whole = max(1, whole)
    qty = Decimal(whole)
    total = _line_total(price, qty, per_unit, per_amount, per_unit)
    note = (f"₹{_fmt_amt(amount)} worth (≈ {whole}"
            f" {_plural(per_unit, whole)}")
    return (qty, per_unit, total, note)


def build_quote(conn: sqlite3.Connection, shop_id: int,
                wanted: list[WantedLine]) -> Quote:
    """Price wanted lines from the shop's latest published version only."""
    from app import db as _db

    version_id = _db.latest_version(conn, shop_id, published_only=True)
    if version_id is None:
        lines = [
            QuoteLine(
                name_en=item.name_en, name_local="",
                qty=item.qty if item.qty is not None else Decimal(1),
                unit=item.unit, unit_price=None, per_amount=None,
                line_total=None, status="not_on_list", note=None)
            for item in wanted
        ]
        return Quote(lines=lines, total=Decimal("0.00"),
                     priced_count=0, unpriced_count=len(lines),
                     prices_set_at=None)
    prices_set_at = _db.version_time(conn, version_id)
    shop_items = _db.version_items(conn, version_id)
    by_name: dict[str, object] = {}
    for item in shop_items:
        key = _canonical(item.name_en)
        if key not in by_name:
            by_name[key] = item
    lines: list[QuoteLine] = []
    for item in wanted:
        want_key = _canonical(item.name_en)
        shop_item = by_name.get(want_key)
        if shop_item is None:
            local = CANONICAL_NAMES.get(_wanted_name(item.name_en), "")
            lines.append(QuoteLine(
                name_en=item.name_en, name_local=local,
                qty=item.qty if item.qty is not None else Decimal(1),
                unit=item.unit, unit_price=None, per_amount=None,
                line_total=None, status="not_on_list", note=None))
            continue
        if shop_item.sold_out:
            fallback_unit = None
            if shop_item.price_lines:
                fallback_unit = shop_item.price_lines[0].unit
            lines.append(QuoteLine(
                name_en=shop_item.name_en, name_local=shop_item.name_local,
                qty=item.qty if item.qty is not None else Decimal(1),
                unit=item.unit or fallback_unit,
                unit_price=None, per_amount=None, line_total=None,
                status="sold_out", note=None))
            continue
        priced = [line for line in shop_item.price_lines
                  if line.price is not None and line.per_amount is not None
                  and line.unit is not None and line.per_amount != 0]
        if not priced:
            lines.append(QuoteLine(
                name_en=shop_item.name_en, name_local=shop_item.name_local,
                qty=item.qty if item.qty is not None else Decimal(1),
                unit=item.unit, unit_price=None, per_amount=None,
                line_total=None, status="not_on_list", note=None))
            continue
        picked = None
        if item.unit is not None:
            if item.unit in ("kg", "g"):
                exact = [line for line in priced if line.unit == item.unit]
                convertible = [line for line in priced
                               if line.unit in ("kg", "g")]
                picked = exact[0] if exact else (
                    convertible[0] if convertible else None)
            elif item.unit in ("l", "ml"):
                exact = [line for line in priced if line.unit == item.unit]
                convertible = [line for line in priced
                               if line.unit in ("l", "ml")]
                picked = exact[0] if exact else (
                    convertible[0] if convertible else None)
            elif item.unit in ("piece", "dozen", "bunch", "packet"):
                exact = [line for line in priced if line.unit == item.unit]
                picked = exact[0] if exact else None
            else:
                picked = None
            if picked is None:
                sold_units = sorted({line.unit for line in priced})
                lines.append(QuoteLine(
                    name_en=shop_item.name_en, name_local=shop_item.name_local,
                    qty=item.qty if item.qty is not None else Decimal(1),
                    unit=item.unit, unit_price=None, per_amount=None,
                    line_total=None, status="not_on_list",
                    note=f"sold per {', '.join(sold_units)}"))
                continue
        else:
            picked = priced[0]
        if item.amount is not None and item.amount > 0:
            qty, unit, total, note = _amount_line(item.amount, picked)
            lines.append(QuoteLine(
                name_en=shop_item.name_en, name_local=shop_item.name_local,
                qty=qty, unit=unit, unit_price=picked.price,
                per_amount=picked.per_amount, line_total=total,
                status="priced", note=note))
            continue
        is_weight = _canonical(shop_item.name_en) in WEIGHT_ITEMS
        qty = item.qty
        unit = item.unit or picked.unit
        if qty is None:
            qty = Decimal(1)
            status = "needs_qty" if is_weight else "priced"
        elif item.unit is None and is_weight:
            status = "needs_qty"
        else:
            status = "priced"
            if item.unit is None:
                unit = picked.unit
        total = _line_total(picked.price, qty, unit, picked.per_amount,
                            picked.unit)
        if total is None:
            sold_units = sorted({line.unit for line in priced})
            lines.append(QuoteLine(
                name_en=shop_item.name_en, name_local=shop_item.name_local,
                qty=qty, unit=item.unit, unit_price=None, per_amount=None,
                line_total=None, status="not_on_list",
                note=f"sold per {', '.join(sold_units)}"))
            continue
        note = None
        if status == "needs_qty":
            note = "Quantity assumed — please check"
        lines.append(QuoteLine(
            name_en=shop_item.name_en, name_local=shop_item.name_local,
            qty=qty, unit=unit, unit_price=picked.price,
            per_amount=picked.per_amount, line_total=total,
            status=status, note=note))
    total = sum((line.line_total for line in lines
                 if line.line_total is not None), Decimal("0.00"))
    if total == 0:
        total = Decimal("0.00")
    else:
        total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    priced_count = sum(1 for line in lines if line.status == "priced")
    return Quote(lines=lines, total=total, priced_count=priced_count,
                 unpriced_count=len(lines) - priced_count,
                 prices_set_at=prices_set_at)
