from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.languages import currency_words_for, get_language
from app.meta.spark import chat_json
from app.models import DraftItem, Flag, PriceLine, Proof, Transcript
from app.pipeline.names import CANONICAL_NAMES
from app.pipeline.units import normalize_price_line, normalize_qty_unit

_SYSTEM_PROMPT = (
    "You extract a produce seller's spoken items and prices into JSON. "
    "Rules: use only what was said, null when it wasn't said; "
    "quote must be copied exactly from one or more turn texts; "
    "said must quote the exact words used for the price and amount, "
    "copied word for word from the quote; "
    "list every price said for one item in spoken order; "
    "a spoken range sets range_said true and price null; "
    "name_en is the lower-case English name, from the canonical list "
    "when it matches, otherwise the plain English name of the item; "
    '"other" only when the item truly cannot be named; '
    "unit and qty_unit use only the canonical set: kg, g, l, ml, piece, "
    "dozen, bunch, packet; "
    "name_local is the same item's name in the shop language's script; "
    "never estimate quantities; "
    "variety is written in English letters, lower case, as spoken "
    "(for example bengaluru), never in a non-Latin script."
)

_CONTRACT = (
    '{"items":[{"name_spoken":"bengaluru thakkali","name_en":"tomato",'
    '"name_local":"தக்காளி","variety":"bengaluru",'
    '"prices":[{"said":"kilo pathinettu","price":18,'
    '"per_amount":1,"unit":"kg"}],"range_said":false,"qty_said":"40 kilo",'
    '"qty":40,"qty_unit":"kg","turn_ids":[3],'
    '"quote":"bengaluru thakkali kilo pathinettu"}]}'
)


def _language_line(language: str) -> str:
    try:
        info = get_language(language)
    except KeyError:
        info = get_language("en")
    words = ", ".join(currency_words_for(info.code))
    return (
        f"Shop language: {info.api_name} ({info.native_name}, "
        f"{info.script} script). Currency words in {info.api_name}: {words}."
    )


def build_extract_messages(transcript: Transcript, *,
                           language: str = "ta") -> list[dict]:
    """Prompt messages showing each turn as `[id] text`."""
    lines = "\n".join(f"[{turn.id}] {turn.text}" for turn in transcript.turns)
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    user_content = (
        f"{_SYSTEM_PROMPT}\n\n{_language_line(language)}\n\n"
        f"Canonical names: {canonical}\n\n"
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


def _local_name(raw: dict, name_en: str, name_spoken: str,
                language: str) -> str:
    """Model's name_local, falling back to the Tamil list or what was said."""
    said_local = raw.get("name_local")
    if isinstance(said_local, str) and said_local.strip():
        return said_local.strip()
    if language == "ta" and name_en in CANONICAL_NAMES:
        return CANONICAL_NAMES[name_en]
    return name_spoken


def parse_extract_json(data: dict, transcript: Transcript, *,
                       language: str = "ta") -> list[DraftItem]:
    """Build DraftItems from model JSON; unknown turns fall back to quote search."""
    items: list[DraftItem] = []
    for raw in data.get("items") or []:
        raw_name = raw.get("name_en") or "other"
        if isinstance(raw_name, str):
            name_en = raw_name.strip().lower() or "other"
        else:
            name_en = "other"
        name_spoken = raw.get("name_spoken") or ""
        price_lines = [
            PriceLine(
                price=_decimal_or_none(line.get("price")),
                per_amount=_decimal_or_none(line.get("per_amount")),
                unit=line.get("unit"),
                said=line.get("said", ""),
            )
            for line in raw.get("prices") or []
        ]
        quote = raw.get("quote") or ""
        turn_ids = list(raw.get("turn_ids") or [])
        start_ms, end_ms = _proof_times(quote, turn_ids, transcript)
        variety = raw.get("variety")
        if isinstance(variety, str):
            variety = variety.lower()
        flags = _backfill_units(price_lines)
        for line in price_lines:
            normalize_price_line(line)
        qty_unit, qty = normalize_qty_unit(raw.get("qty_unit"),
                                           _decimal_or_none(raw.get("qty")))
        items.append(DraftItem(
            name_spoken=name_spoken,
            name_local=_local_name(raw, name_en, name_spoken, language),
            name_en=name_en,
            variety=variety,
            price_lines=price_lines,
            qty=qty,
            qty_unit=qty_unit,
            proof=Proof(quote=quote, turn_ids=turn_ids,
                        start_ms=start_ms, end_ms=end_ms),
            range_said=bool(raw.get("range_said", False)),
            flags=flags,
        ))
    return items


_CHUNK_TURNS = 6


def chunk_transcript(transcript: Transcript) -> list[Transcript]:
    """Split into groups of at most 6 whole turns; a turn is never split."""
    if not transcript.turns:
        return [transcript]
    return [
        Transcript(text=transcript.text, duration_ms=transcript.duration_ms,
                   turns=transcript.turns[index:index + _CHUNK_TURNS])
        for index in range(0, len(transcript.turns), _CHUNK_TURNS)
    ]


def extract_items(transcript: Transcript, *, ledger, settings,
                  language: str = "ta", progress=None) -> list[DraftItem]:
    """One low-reasoning Spark call per turn group; items merged in order.

    ``progress`` is called as ``progress(part, total)`` before each chunk so
    callers can report "part 2 of 3" while long transcripts are extracted.
    """
    chunks = chunk_transcript(transcript)
    items: list[DraftItem] = []
    for number, chunk in enumerate(chunks, start=1):
        if progress is not None:
            progress(number, len(chunks))
        data = chat_json(build_extract_messages(chunk, language=language),
                         ledger=ledger, settings=settings,
                         reasoning_effort="low")
        items.extend(parse_extract_json(data, transcript, language=language))
    return items
