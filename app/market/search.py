"""Customer search: turn words into a structured query, compare shop prices."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app import db
from app.meta.spark import chat_json
from app.models import UNITS, PriceLine
from app.pipeline.names import CANONICAL_NAMES
from app.pipeline.units import rate

STALE_AFTER_HOURS = 24

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


@dataclass
class Want:
    name_en: str
    amount: Decimal | None
    unit: str | None
    max_rate: Decimal | None


@dataclass
class Query:
    wants: list[Want]
    budget: Decimal | None
    area: str | None
    unknown: list[str] = field(default_factory=list)


@dataclass
class Listing:
    shop_name: str
    slug: str
    area: str
    is_demo: bool
    name_en: str
    variety: str | None
    line: PriceLine
    rate: Decimal | None
    rate_unit: str | None
    updated_at: datetime
    stale: bool


_SYSTEM_PROMPT = (
    "You turn a customer's market search into JSON. "
    "Rules: one want per produce item named; copy the customer's word for "
    "the name when you are unsure of the canonical name; amount/unit is the "
    "quantity the customer wants and is null when not said; max_rate is a "
    "price cap ('under 25') as a number, null otherwise; budget is the "
    "total money mentioned ('I have 300 rupees'), null otherwise; area is "
    "a neighbourhood mentioned ('in Anna Nagar'), null otherwise."
)

_CONTRACT = (
    '{"wants":[{"name":"tomato","amount":1,"unit":"kg","max_rate":25}],'
    '"budget":300,"area":"Anna Nagar"}'
)


def build_query_messages(text: str) -> list[dict]:
    """Prompt messages: canonical names plus the customer's raw words."""
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    user_content = (
        f"{_SYSTEM_PROMPT}\n\nCanonical names: {canonical}\n\n"
        f"Customer search: {text}\n\n"
        f"Return only JSON shaped like: {_CONTRACT}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _canonical_name(raw: str) -> str | None:
    key = raw.strip().lower()
    mapped = SYNONYMS.get(key, key)
    if mapped in CANONICAL_NAMES:
        return mapped
    if key.endswith("s") and key[:-1] in CANONICAL_NAMES:
        return key[:-1]
    return None


def parse_query_json(data: dict) -> Query:
    """Build a Query from model JSON; unknown names are dropped, not guessed."""
    wants: list[Want] = []
    unknown: list[str] = []
    for raw in data.get("wants") or []:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        canonical = _canonical_name(name)
        if canonical is None:
            unknown.append(name)
            continue
        unit = raw.get("unit")
        unit = unit if unit in UNITS else None
        wants.append(Want(
            name_en=canonical,
            amount=_decimal_or_none(raw.get("amount")),
            unit=unit,
            max_rate=_decimal_or_none(raw.get("max_rate")),
        ))
    area = data.get("area")
    area = str(area).strip() or None if area is not None else None
    return Query(
        wants=wants,
        budget=_decimal_or_none(data.get("budget")),
        area=area,
        unknown=unknown,
    )


def parse_query(text: str, *, ledger, settings) -> Query:
    """One low-reasoning Spark call turning a search into a Query."""
    data = chat_json(build_query_messages(text),
                     ledger=ledger, settings=settings,
                     reasoning_effort="low")
    return parse_query_json(data)


def _as_aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _display_line(lines: list[PriceLine]) -> PriceLine | None:
    """Pick the lowest-amount priced line; fall back to the first priced one."""
    priced = [line for line in lines if line.price is not None]
    if not priced:
        return None
    with_amount = [line for line in priced
                   if line.per_amount is not None and line.unit is not None]
    if with_amount:
        def sort_key(line: PriceLine):
            converted = rate(line)
            return (line.per_amount, line.unit, converted[0]
                    if converted else Decimal(0))
        return min(with_amount, key=sort_key)
    return priced[0]


def find_listings(conn: sqlite3.Connection, query: Query,
                  now: datetime) -> list[Listing]:
    """Compare published prices for the query's wants across listed shops.

    Only listed shops with a published version count; sold-out items are
    excluded. A max_rate filters on the per-kg/per-piece rate. Rows are
    fresh-first, then cheapest rate first.
    """
    now = _as_aware(now)
    shops = conn.execute(
        "SELECT * FROM shops WHERE listed = 1 ORDER BY id").fetchall()
    if query.area:
        needle = query.area.lower()
        shops = [shop for shop in shops if needle in (shop["area"] or "").lower()]
    listings: list[Listing] = []
    for want in query.wants:
        for shop in shops:
            version_id = db.latest_version(conn, shop["id"], published_only=True)
            if version_id is None:
                continue
            updated_at = db.version_time(conn, version_id)
            stale = ((now - _as_aware(updated_at)).total_seconds()
                     > STALE_AFTER_HOURS * 3600)
            for item in db.version_items(conn, version_id):
                if item.name_en != want.name_en or item.sold_out:
                    continue
                line = _display_line(item.price_lines)
                if line is None:
                    continue
                computed = rate(line)
                if (want.max_rate is not None
                        and (computed is None or computed[0] > want.max_rate)):
                    continue
                listings.append(Listing(
                    shop_name=shop["name"], slug=shop["slug"],
                    area=shop["area"], is_demo=bool(shop["is_demo"]),
                    name_en=item.name_en, variety=item.variety, line=line,
                    rate=computed[0] if computed else None,
                    rate_unit=computed[1] if computed else None,
                    updated_at=updated_at, stale=stale))
    listings.sort(key=lambda row: (row.stale, row.rate is None, row.rate))
    return listings
