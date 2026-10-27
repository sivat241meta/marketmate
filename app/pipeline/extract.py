from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.meta.spark import chat_json
from app.models import DraftItem, Flag, PriceLine, Proof, Transcript
from app.pipeline.names import CANONICAL_NAMES

_SYSTEM_PROMPT = (
    "You extract a produce seller's spoken items and prices into JSON. "
    "Rules: use only what was said, null when it wasn't said; "
    "quote must be copied exactly from one or more turn texts; "
    "list every price said for one item in spoken order; "
    "a spoken range sets range_said true and price null; "
    "name_en must be a key of the canonical list, or \"other\"; "
    "never estimate quantities; "
    "variety is written in English letters, lower case, as spoken "
    "(for example bengaluru), never in Tamil script."
)

_CONTRACT = (
    '{"items":[{"name_spoken":"bengaluru thakkali","name_en":"tomato",'
    '"variety":"bengaluru","prices":[{"said":"kilo pathinettu","price":18,'
    '"per_amount":1,"unit":"kg"}],"range_said":false,"qty_said":"40 kilo",'
    '"qty":40,"qty_unit":"kg","turn_ids":[3],'
    '"quote":"bengaluru thakkali kilo pathinettu"}]}'
)


def build_extract_messages(transcript: Transcript) -> list[dict]:
    """Prompt messages showing each turn as `[id] text`."""
    lines = "\n".join(f"[{turn.id}] {turn.text}" for turn in transcript.turns)
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    user_content = (
        f"{_SYSTEM_PROMPT}\n\nCanonical names: {canonical}\n\n"
        f"Transcript (one line per turn as [id] text):\n{lines}\n\n"
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


def _backfill_units(price_lines: list[PriceLine]) -> list[Flag]:
    """Copy amount+unit from an earlier line onto a bare follow-up price."""
    flags: list[Flag] = []
    for index, line in enumerate(price_lines):
        if line.price is None or line.unit is not None or line.per_amount is not None:
            continue
        donor = next((earlier for earlier in price_lines[:index]
                      if earlier.per_amount is not None and earlier.unit is not None),
                     None)
        if donor is None:
            continue
        line.per_amount = donor.per_amount
        line.unit = donor.unit
        flags.append(Flag(
            field="unit", code="UNIT_FROM_EARLIER",
            message="unit was taken from the earlier price in the same sentence",
            blocking=False))
    return flags


def _proof_times(quote: str, turn_ids: list, transcript: Transcript) -> tuple[int, int]:
    by_id = {turn.id: turn for turn in transcript.turns}
    known = [by_id[tid] for tid in turn_ids if tid in by_id]
    if known:
        return (min(t.start_ms for t in known), max(t.end_ms for t in known))
    if quote:
        hit = next((t for t in transcript.turns if quote in t.text), None)
        if hit is not None:
            return (hit.start_ms, hit.end_ms)
    return (0, 0)


def parse_extract_json(data: dict, transcript: Transcript) -> list[DraftItem]:
    """Build DraftItems from model JSON; unknown turns fall back to quote search."""
    items: list[DraftItem] = []
    for raw in data.get("items", []):
        name_en = raw.get("name_en", "other")
        name_spoken = raw.get("name_spoken", "")
        price_lines = [
            PriceLine(
                price=_decimal_or_none(line.get("price")),
                per_amount=_decimal_or_none(line.get("per_amount")),
                unit=line.get("unit"),
                said=line.get("said", ""),
            )
            for line in raw.get("prices", [])
        ]
        quote = raw.get("quote", "")
        turn_ids = list(raw.get("turn_ids", []))
        start_ms, end_ms = _proof_times(quote, turn_ids, transcript)
        variety = raw.get("variety")
        if isinstance(variety, str):
            variety = variety.lower()
        flags = _backfill_units(price_lines)
        items.append(DraftItem(
            name_spoken=name_spoken,
            name_ta=CANONICAL_NAMES.get(name_en, name_spoken),
            name_en=name_en,
            variety=variety,
            price_lines=price_lines,
            qty=_decimal_or_none(raw.get("qty")),
            qty_unit=raw.get("qty_unit"),
            proof=Proof(quote=quote, turn_ids=turn_ids,
                        start_ms=start_ms, end_ms=end_ms),
            range_said=bool(raw.get("range_said", False)),
            flags=flags,
        ))
    return items


def extract_items(transcript: Transcript, *, ledger, settings) -> list[DraftItem]:
    """Run the Spark extraction prompt and parse the result."""
    data = chat_json(build_extract_messages(transcript), ledger=ledger, settings=settings)
    return parse_extract_json(data, transcript)
