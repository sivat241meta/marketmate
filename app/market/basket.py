"""Budget basket: cheapest fresh options per want, with a checked explanation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.costs import CostCapExceeded
from app.market.search import Listing, Want
from app.meta.spark import SparkError, chat_json
from app.pipeline.checks import WEIGHT_ITEMS
from app.pipeline.units import convert


@dataclass
class BasketLine:
    want: Want
    listing: Listing
    cost: Decimal
    assumed: bool


@dataclass
class BasketPlan:
    kind: str
    shop: str | None
    lines: list[BasketLine]
    total: Decimal
    missing: list[str] = field(default_factory=list)


def round_to_half(value: Decimal) -> Decimal:
    """Round a Decimal cost to the nearest 0.5 rupee (half up)."""
    stepped = (value * 2).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return stepped / 2


def _assumed_amount(name_en: str) -> tuple[Decimal, str]:
    if name_en in WEIGHT_ITEMS:
        return (Decimal(1), "kg")
    return (Decimal(1), "piece")


def _want_amount(want: Want) -> tuple[Decimal, str, bool]:
    if want.amount is not None and want.unit is not None:
        return (want.amount, want.unit, False)
    amount, unit = _assumed_amount(want.name_en)
    return (amount, unit, True)


def _line_cost(amount: Decimal, unit: str, listing: Listing) -> Decimal | None:
    line = listing.line
    if line.price is None or line.per_amount is None or line.unit is None:
        return None
    if line.per_amount == 0:
        return None
    converted = convert(amount, unit, line.unit)
    if converted is None:
        return None
    return round_to_half(line.price * converted / line.per_amount)


def plan_basket(wants: list[Want], listings: list[Listing],
                budget: Decimal | None) -> list[BasketPlan]:
    """Cheapest fresh plan per want (split) plus cheapest single shop.

    Only fresh listings are used. A want with no fresh convertible
    listing lands in ``missing``. Amounts default to 1 kg for
    WEIGHT_ITEMS else 1 piece, with ``assumed=True``.
    """
    _ = budget
    if not wants:
        return []
    fresh = [row for row in listings if not row.stale]
    split_lines: list[BasketLine] = []
    missing: list[str] = []
    for want in wants:
        amount, unit, assumed = _want_amount(want)
        best: tuple[tuple, Decimal, Listing] | None = None
        for row in fresh:
            if row.name_en != want.name_en:
                continue
            cost = _line_cost(amount, unit, row)
            if cost is None:
                continue
            key = (cost, row.shop_name, row.slug)
            if best is None or key < best[0]:
                best = (key, cost, row)
        if best is None:
            missing.append(want.name_en)
        else:
            _, cost, row = best
            split_lines.append(BasketLine(want, row, cost, assumed))
    total = sum((line.cost for line in split_lines), Decimal(0))
    plans = [BasketPlan(kind="split", shop=None, lines=split_lines,
                        total=total, missing=list(missing))]
    by_slug: dict[str, tuple[str, list[Listing]]] = {}
    for row in fresh:
        by_slug.setdefault(row.slug, (row.shop_name, []))[1].append(row)
    best_shop: tuple[Decimal, str, str, list[BasketLine]] | None = None
    for slug, (shop_name, rows) in by_slug.items():
        shop_lines: list[BasketLine] = []
        for want in wants:
            amount, unit, assumed = _want_amount(want)
            cheapest: tuple[Decimal, Listing] | None = None
            for row in rows:
                if row.name_en != want.name_en:
                    continue
                cost = _line_cost(amount, unit, row)
                if cost is None:
                    continue
                if cheapest is None or cost < cheapest[0]:
                    cheapest = (cost, row)
            if cheapest is None:
                break
            cost, row = cheapest
            shop_lines.append(BasketLine(want, row, cost, assumed))
        else:
            shop_total = sum((line.cost for line in shop_lines), Decimal(0))
            key = (shop_total, shop_name, slug)
            if best_shop is None or key < best_shop[:3]:
                best_shop = (shop_total, shop_name, slug, shop_lines)
    if best_shop is not None:
        shop_total, shop_name, _, shop_lines = best_shop
        plans.append(BasketPlan(kind="single_shop", shop=shop_name,
                                lines=shop_lines, total=shop_total,
                                missing=[]))
    return plans


def best_partial_shop(wants: list[Want],
                      listings: list[Listing]) -> BasketPlan | None:
    """Best shop that has some (not all) wants: most wants covered wins,
    ties go to the cheapest covered total, then the shop name. Returns None
    when no shop covers any want. Uncovered wants land in ``missing``."""
    if not wants:
        return None
    fresh = [row for row in listings if not row.stale]
    by_slug: dict[str, tuple[str, list[Listing]]] = {}
    for row in fresh:
        by_slug.setdefault(row.slug, (row.shop_name, []))[1].append(row)
    best: tuple[tuple, Decimal, str, str, list[BasketLine], list[str]] | None = None
    for slug, (shop_name, rows) in by_slug.items():
        shop_lines: list[BasketLine] = []
        missing: list[str] = []
        for want in wants:
            amount, unit, assumed = _want_amount(want)
            cheapest: tuple[Decimal, Listing] | None = None
            for row in rows:
                if row.name_en != want.name_en:
                    continue
                cost = _line_cost(amount, unit, row)
                if cost is None:
                    continue
                if cheapest is None or cost < cheapest[0]:
                    cheapest = (cost, row)
            if cheapest is None:
                missing.append(want.name_en)
            else:
                cost, row = cheapest
                shop_lines.append(BasketLine(want, row, cost, assumed))
        if not shop_lines:
            continue
        shop_total = sum((line.cost for line in shop_lines), Decimal(0))
        key = (-len(shop_lines), shop_total, shop_name, slug)
        if best is None or key < best[0]:
            best = (key, shop_total, shop_name, slug, shop_lines, missing)
    if best is None:
        return None
    _, shop_total, shop_name, _, shop_lines, missing = best
    return BasketPlan(kind="partial_shop", shop=shop_name, lines=shop_lines,
                      total=shop_total, missing=missing)


def _fmt_money(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _plans_payload(plans: list[BasketPlan], budget: Decimal | None) -> dict:
    return {
        "budget": str(budget) if budget is not None else None,
        "plans": [
            {
                "kind": plan.kind,
                "shop": plan.shop,
                "total": str(plan.total),
                "lines": [
                    {
                        "item": line.want.name_en,
                        "shop": line.listing.shop_name,
                        "cost": str(line.cost),
                        "rate": (str(line.listing.rate)
                                 if line.listing.rate is not None else None),
                        "rate_unit": line.listing.rate_unit,
                    }
                    for line in plan.lines
                ],
                "missing": list(plan.missing),
            }
            for plan in plans
        ],
    }


def build_basket_messages(plans: list[BasketPlan],
                          budget: Decimal | None) -> list[dict]:
    """Prompt asking for 2-3 friendly sentences as JSON."""
    payload = json.dumps(_plans_payload(plans, budget))
    system = (
        "You write a friendly 2-3 sentence explanation of a market "
        "budget basket. Use only the rupee numbers given; never invent prices."
    )
    user = (
        f"Basket plans JSON: {payload}\n\n"
        "Write 2-3 friendly sentences about the cheapest option and the "
        "budget. Reuse the rupee numbers from the JSON exactly. "
        'Return only JSON like {"explanation": "..."}.'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


_RUPEE_PATTERNS = (
    re.compile(r"₹\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"\bRs\.?\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\brupees?\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bINR\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"([\d,]+(?:\.\d+)?)\s*rupees?", re.IGNORECASE),
)


def _rupee_numbers(text: str) -> list[Decimal]:
    found: list[Decimal] = []
    for pattern in _RUPEE_PATTERNS:
        for match in pattern.findall(text):
            try:
                found.append(Decimal(str(match).replace(",", "")))
            except InvalidOperation:
                continue
    return found


def _allowed_numbers(plans: list[BasketPlan],
                     budget: Decimal | None) -> list[Decimal]:
    allowed: list[Decimal] = []
    for plan in plans:
        allowed.append(plan.total)
        for line in plan.lines:
            allowed.append(line.cost)
            if line.listing.rate is not None:
                allowed.append(line.listing.rate)
    if budget is not None:
        allowed.append(budget)
    return allowed


def _explanation_ok(text: str, allowed: list[Decimal]) -> bool:
    for number in _rupee_numbers(text):
        if not any(number == each for each in allowed):
            return False
    return True


def template_explanation(plans: list[BasketPlan],
                         budget: Decimal | None) -> str:
    """Fallback sentence built in code from the computed plans."""
    if not plans:
        return "No fresh prices found for your basket today."
    split = next((plan for plan in plans if plan.kind == "split"), plans[0])
    if not split.lines:
        base = f"No fresh prices for {', '.join(split.missing)} today."
        if budget is not None:
            base += f" Your budget is ₹{_fmt_money(budget)}."
        return base
    single = next((plan for plan in plans if plan.kind == "single_shop"), None)
    first = f"Cheapest split costs ₹{_fmt_money(split.total)}"
    if single is not None and single.shop:
        first += f"; {single.shop} alone costs ₹{_fmt_money(single.total)}"
    first += "."
    parts = [first]
    if budget is not None:
        if split.total <= budget:
            parts.append(f"That fits your ₹{_fmt_money(budget)} budget.")
        else:
            parts.append(f"That is over your ₹{_fmt_money(budget)} budget.")
    if split.missing:
        parts.append(f"No fresh prices for: {', '.join(split.missing)}.")
    return " ".join(parts)


def explain_basket(plans: list[BasketPlan], budget: Decimal | None, *,
                   ledger, settings) -> str:
    """Friendly explanation; falls back to a template on foreign numbers."""
    allowed = _allowed_numbers(plans, budget)
    try:
        data = chat_json(build_basket_messages(plans, budget),
                         ledger=ledger, settings=settings,
                         reasoning_effort="low", step="market search")
    except (SparkError, CostCapExceeded):
        return template_explanation(plans, budget)
    text = ""
    if isinstance(data, dict):
        for key in ("explanation", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
    if not text:
        return template_explanation(plans, budget)
    if _explanation_ok(text, allowed):
        return text
    return template_explanation(plans, budget)
