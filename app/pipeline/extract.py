from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.languages import currency_words_for, get_language
from app.meta.spark import chat_json
from app.models import DraftItem, Flag, PriceLine, Proof, Transcript
from app.pipeline.names import (
    CANONICAL_NAMES,
    VARIETY_ALIASES,
    canonical_local_name,
    find_name_in_text,
    repair_local_name,
    repair_variety_local_name,
    resolve_name,
    restore_spoken_local_name,
)
from app.pipeline.spoken import apply_spoken_name
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
    "(for example bengaluru), never in a non-Latin script; "
    "a qualifier is the plain English word (new, small, big, red, "
    "green, country, sweet), never a transliteration."
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


def _same_price_key(first: PriceLine, second: PriceLine) -> bool:
    """True when two lines share price and (per_amount, unit)."""
    if first.unit != second.unit:
        return False
    if (first.price is None) != (second.price is None):
        return False
    if (first.price is not None and second.price is not None
            and first.price != second.price):
        return False
    if (first.per_amount is None) != (second.per_amount is None):
        return False
    return not (first.per_amount is not None and second.per_amount is not None
                and first.per_amount != second.per_amount)


def _append_said(item: DraftItem, said: str) -> None:
    if not said or not said.strip() or said in item.proof.quote:
        return
    if item.proof.quote:
        item.proof.quote = f"{item.proof.quote} {said}"
    else:
        item.proof.quote = said


def merge_repeated_prices(item: DraftItem) -> None:
    """Collapse one price said several times into a single line.

    Lines with the same price and the same (per_amount, unit) merge, with
    missing counting as equal to missing. A missing unit beside a known
    unit for the same price merges into the known unit only when that is
    the only other line with that price; otherwise both stay for the
    seller. The first line's ``said`` is kept; other quotes join the proof
    quote when not already in it.
    """
    lines = item.price_lines
    if len(lines) < 2:
        return
    deduped: list[PriceLine] = []
    for line in lines:
        if next((kept for kept in deduped
                 if _same_price_key(kept, line)), None) is None:
            deduped.append(line)
        else:
            _append_said(item, line.said)
    groups: list[tuple[Decimal, list[int]]] = []
    for index, line in enumerate(deduped):
        if line.price is None:
            continue
        placed = next(
            (indices for price, indices in groups if price == line.price),
            None)
        if placed is None:
            groups.append((line.price, [index]))
        else:
            placed.append(index)
    replacements: dict[int, PriceLine] = {}
    dropped: set[int] = set()
    for _, indices in groups:
        if len(indices) != 2:
            continue
        first, second = deduped[indices[0]], deduped[indices[1]]
        if first.unit is None and second.unit is not None:
            missing, known = first, second
        elif second.unit is None and first.unit is not None:
            missing, known = second, first
        else:
            continue
        if (missing.per_amount is not None and known.per_amount is not None
                and missing.per_amount != known.per_amount):
            continue
        per = (known.per_amount if known.per_amount is not None
               else missing.per_amount)
        replacements[indices[0]] = PriceLine(
            price=first.price, per_amount=per, unit=known.unit,
            said=first.said)
        dropped.add(indices[1])
        _append_said(item, second.said)
    if replacements:
        item.price_lines = [
            replacements.get(index, line)
            for index, line in enumerate(deduped) if index not in dropped
        ]
    else:
        item.price_lines = deduped


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
    """Model's name_local, falling back to the canonical list or said words.

    A local name that is really the spoken variety becomes the item's
    canonical local name; Tamil names stored without vowel signs are
    repaired to the canonical spelling; seller-chosen names are applied
    later by apply_chosen_names, so they always win.
    """
    said_local = raw.get("name_local")
    if isinstance(said_local, str) and said_local.strip():
        local = said_local.strip()
        if language == "ta":
            local = repair_local_name(name_en, local) or local
        return repair_variety_local_name(name_en, local, language=language) or local
    canonical = canonical_local_name(name_en, language)
    if canonical is not None:
        return canonical
    return name_spoken


def _alias_in_text(text: str) -> tuple[str, str] | None:
    """First (name_en, variety) whose alias key appears in lower text.

    Longest keys win so "ujala krishnagiri" beats bare "ujala".
    """
    lowered = f" {text.lower()} " if text else " "
    stripped = lowered.strip()
    best: tuple[str, str] | None = None
    best_len = -1
    for alias, pair in VARIETY_ALIASES.items():
        key = alias.lower()
        if not key or len(key) <= best_len:
            continue
        if " " in key:
            found = key in stripped
        else:
            found = (
                f" {key} " in lowered
                or stripped == key
                or (not key.isascii() and key in text))
        if found:
            best, best_len = pair, len(key)
    return best


def _banana_varieties_in_order(text: str) -> list[str]:
    """Distinct banana varieties in spoken order for a dual-variety line."""
    lowered = (text or "").lower()
    hits: list[tuple[int, str]] = []
    for alias, (base, variety) in VARIETY_ALIASES.items():
        if base != "banana":
            continue
        key = alias.lower()
        idx = lowered.find(key)
        if idx >= 0 and " " not in key and key.isascii():
            # Latin keys need word bounds; Tamil script matches as substring.
            before = lowered[idx - 1] if idx > 0 else " "
            after = (lowered[idx + len(key)]
                     if idx + len(key) < len(lowered) else " ")
            if before.isalnum() or after.isalnum():
                continue
        if idx >= 0:
            hits.append((idx, variety))
    hits.sort(key=lambda h: h[0])
    ordered: list[str] = []
    for _, variety in hits:
        if variety not in ordered:
            ordered.append(variety)
    return ordered


def parse_extract_json(data: dict, transcript: Transcript, *,
                       language: str = "ta") -> list[DraftItem]:
    """Build DraftItems from model JSON; unknown turns fall back to quote search."""
    items: list[DraftItem] = []
    for raw in data.get("items") or []:
        raw_name = raw.get("name_en") or "other"
        if isinstance(raw_name, str):
            raw_name = raw_name.strip().lower() or "other"
        else:
            raw_name = "other"
        name_spoken = raw.get("name_spoken") or ""
        quote_early = raw.get("quote") or ""
        raw_local = raw.get("name_local") or ""
        raw_variety = raw.get("variety")
        if not isinstance(raw_variety, str):
            raw_variety = None
        extra = f"{name_spoken} {quote_early}".strip() or None
        name_en, variety = resolve_name(raw_name, raw_variety,
                                        extra_text=extra)
        if name_en == "other":
            for fallback in (name_spoken, raw_local):
                text = (fallback or "").strip()
                if not text:
                    continue
                cand_en, cand_var = resolve_name(
                    text.lower(), raw_variety, extra_text=extra)
                if cand_en != "other":
                    name_en, variety = cand_en, cand_var
                    break
        if name_en == "other" and extra:
            hit = _alias_in_text(extra)
            if hit is not None:
                name_en, variety = hit
            else:
                found_name = find_name_in_text(extra)
                if found_name is not None:
                    name_en = found_name
        if name_en == "banana" and extra:
            found = _banana_varieties_in_order(extra)
            if len(found) >= 2:
                variety = " / ".join(found)
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
        flags = _backfill_units(price_lines)
        for line in price_lines:
            normalize_price_line(line)
        qty_unit, qty = normalize_qty_unit(raw.get("qty_unit"),
                                           _decimal_or_none(raw.get("qty")))
        local_name = _local_name(raw, name_en, name_spoken, language)
        # Keep a qualifier the extracted name dropped (Task 136): the
        # seller's own item words win over the bare canonical name.
        repaired = restore_spoken_local_name(
            local_name, name_spoken=name_spoken, quote=quote,
            variety=variety, name_en=name_en, language=language)
        if repaired:
            local_name = repaired
        item = DraftItem(
            name_spoken=name_spoken,
            name_local=local_name,
            name_en=name_en,
            variety=variety,
            match_key=name_en,
            price_lines=price_lines,
            qty=qty,
            qty_unit=qty_unit,
            proof=Proof(quote=quote, turn_ids=turn_ids,
                        start_ms=start_ms, end_ms=end_ms),
            range_said=bool(raw.get("range_said", False)),
            flags=flags,
        )
        # Names come from the seller's own span (Task 139), before price
        # merging appends other lines' words to the quote.
        apply_spoken_name(item, language=language)
        merge_repeated_prices(item)
        items.append(item)
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
    total = len(chunks)
    for number, chunk in enumerate(chunks, start=1):
        if progress is not None:
            progress(number, total)
        data = chat_json(
            build_extract_messages(chunk, language=language),
            ledger=ledger, settings=settings, reasoning_effort="low",
            step="extract prices",
            summary=lambda reply, part=number, of=total: _part_summary(
                reply, part, of))
        items.extend(parse_extract_json(data, transcript, language=language))
    return items


def _part_summary(reply: dict, part: int, total: int) -> str:
    found = reply.get("items")
    count = len(found) if isinstance(found, list) else 0
    noun = "item" if count == 1 else "items"
    text = f"{count} {noun}"
    if total > 1:
        text += f" (part {part} of {total})"
    return text
