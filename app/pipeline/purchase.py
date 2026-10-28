"""Purchase extraction: what the seller bought this morning, and for how much.

Voice example: "vengayam 50 kilo 1200 rupees". Every number (qty and total
cost) must be heard in the transcript, like price checks; otherwise a
blocking flag asks the seller to confirm.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.languages import currency_words_for, get_language, shop_bias
from app.meta.spark import chat_json
from app.meta.transcribe import transcribe_wav
from app.models import Flag, Proof, PurchaseDraft, Transcript
from app.pipeline.media import extract_audio
from app.pipeline.names import CANONICAL_NAMES, keywords_for
from app.pipeline.numbers import find_numbers
from app.pipeline.units import normalize_unit

PURCHASE_INSTRUCTION = (
    "You extract a produce seller's morning purchases into JSON. "
    "Rules: use only what was said, null when it wasn't said; "
    "quote must be copied exactly from one or more turn texts; "
    "name_en is the lower-case English name, from the canonical list "
    "when it matches, otherwise the plain English name; "
    "unit uses only the canonical set: kg, g, l, ml, piece, dozen, "
    "bunch, packet; "
    "name_local is the same item's name in the shop language's script; "
    "qty is how much was bought, total_cost is the total money paid; "
    "never estimate quantities or costs."
)

PURCHASE_CONTRACT = (
    '{"items":[{"name_spoken":"vengayam","name_en":"onion",'
    '"name_local":"வெங்காயம்","qty":50,"unit":"kg","total_cost":1200,'
    '"turn_ids":[1],"quote":"vengayam 50 kilo 1200 rupees"}]}'
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


def build_purchase_messages(transcript: Transcript, *,
                            language: str = "ta") -> list[dict]:
    lines = "\n".join(f"[{turn.id}] {turn.text}" for turn in transcript.turns)
    canonical = ", ".join(sorted(CANONICAL_NAMES))
    user_content = (
        f"{PURCHASE_INSTRUCTION}\n\n{_language_line(language)}\n\n"
        f"Canonical names: {canonical}\n\n"
        f"Transcript (one line per turn as [id] text):\n{lines}\n\n"
        f"Return only JSON shaped like: {PURCHASE_CONTRACT}"
    )
    return [
        {"role": "system", "content": PURCHASE_INSTRUCTION},
        {"role": "user", "content": user_content},
    ]


def _decimal_or_none(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _proof_times(quote: str, turn_ids: list, transcript: Transcript):
    by_id = {turn.id: turn for turn in transcript.turns}
    known = [by_id[tid] for tid in turn_ids if tid in by_id]
    if known:
        return (min(t.start_ms for t in known), max(t.end_ms for t in known))
    if quote:
        hit = next((t for t in transcript.turns if quote in t.text), None)
        if hit is not None:
            return (hit.start_ms, hit.end_ms)
    return (0, 0)


def check_purchase(draft: PurchaseDraft, *, language: str = "ta"
                   ) -> list[Flag]:
    """Every number (qty and total) must be heard, else a blocking flag."""
    try:
        decimal_comma = get_language(language).decimal_comma
    except KeyError:
        decimal_comma = False
    heard = find_numbers(draft.proof.quote or "",
                         decimal_comma=decimal_comma)
    heard_values = {value for value, _ in heard}
    flags: list[Flag] = []
    if draft.qty is not None and draft.qty not in heard_values:
        flags.append(Flag(field="qty", code="NOT_HEARD",
                          message=f"quantity {draft.qty} not heard in quote"))
    if draft.total_cost is not None and draft.total_cost not in heard_values:
        flags.append(Flag(field="total_cost", code="NOT_HEARD",
                          message=f"total {draft.total_cost} not heard in quote"))
    if draft.qty is None:
        flags.append(Flag(field="qty", code="QTY_MISSING",
                          message="no quantity heard"))
    if draft.total_cost is None:
        flags.append(Flag(field="total_cost", code="NO_PRICE",
                          message="no total paid heard"))
    if draft.unit is None and draft.qty is not None:
        flags.append(Flag(field="unit", code="UNIT_MISSING",
                          message="quantity is missing its unit"))
    return flags


def parse_purchase_json(data: dict, transcript: Transcript, *,
                        language: str = "ta") -> list[PurchaseDraft]:
    items: list[PurchaseDraft] = []
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        spoken = str(raw.get("name_spoken") or "").strip()
        raw_name = raw.get("name_en") or "other"
        name_en = (raw_name.strip().lower() if isinstance(raw_name, str)
                   else "other") or "other"
        said_local = raw.get("name_local")
        if isinstance(said_local, str) and said_local.strip():
            name_local = said_local.strip()
        elif name_en in CANONICAL_NAMES:
            name_local = CANONICAL_NAMES[name_en]
        else:
            name_local = spoken
        qty = _decimal_or_none(raw.get("qty"))
        total_cost = _decimal_or_none(raw.get("total_cost"))
        unit_raw = raw.get("unit")
        unit: str | None = None
        if isinstance(unit_raw, str) and unit_raw.strip():
            canonical, factor = normalize_unit(unit_raw)
            if canonical is not None:
                unit = canonical
                if factor != 1 and qty is not None:
                    qty = qty * factor
            else:
                unit = unit_raw.strip()
        quote = raw.get("quote") or ""
        turn_ids = list(raw.get("turn_ids") or [])
        start_ms, end_ms = _proof_times(quote, turn_ids, transcript)
        draft = PurchaseDraft(
            name_spoken=spoken or name_en,
            name_local=name_local,
            name_en=name_en,
            qty=qty,
            unit=unit,
            total_cost=total_cost,
            proof=Proof(quote=quote, turn_ids=turn_ids,
                        start_ms=start_ms, end_ms=end_ms),
        )
        draft.flags.extend(check_purchase(draft, language=language))
        items.append(draft)
    return items


def extract_purchases(transcript: Transcript, *, ledger, settings,
                      language: str = "ta") -> list[PurchaseDraft]:
    data = chat_json(build_purchase_messages(transcript, language=language),
                     ledger=ledger, settings=settings,
                     reasoning_effort="low")
    if not isinstance(data, dict):
        return []
    return parse_purchase_json(data, transcript, language=language)


def purchase_meta_path(data_dir: Path, session_id: int) -> Path:
    return Path(data_dir) / "sessions" / str(session_id) / "purchase.json"


def read_purchase_meta(data_dir: Path, session_id: int) -> dict:
    try:
        return json.loads(purchase_meta_path(data_dir, session_id).read_text())
    except (OSError, ValueError):
        return {}


def write_purchase_meta(data_dir: Path, session_id: int, payload: dict) -> None:
    path = purchase_meta_path(data_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _draft_to_dict(draft: PurchaseDraft) -> dict:
    return {
        "name_spoken": draft.name_spoken, "name_local": draft.name_local,
        "name_en": draft.name_en,
        "qty": str(draft.qty) if draft.qty is not None else None,
        "unit": draft.unit,
        "total_cost": (str(draft.total_cost)
                       if draft.total_cost is not None else None),
        "proof": {"quote": draft.proof.quote,
                  "turn_ids": draft.proof.turn_ids,
                  "start_ms": draft.proof.start_ms,
                  "end_ms": draft.proof.end_ms},
        "flags": [{"field": f.field, "code": f.code, "message": f.message,
                   "options": f.options, "blocking": f.blocking}
                  for f in draft.flags],
    }


def _draft_from_dict(raw: dict) -> PurchaseDraft:
    proof = raw.get("proof") or {}
    return PurchaseDraft(
        name_spoken=raw.get("name_spoken", ""),
        name_local=raw.get("name_local", ""),
        name_en=raw.get("name_en", ""),
        qty=_decimal_or_none(raw.get("qty")),
        unit=raw.get("unit"),
        total_cost=_decimal_or_none(raw.get("total_cost")),
        proof=Proof(quote=proof.get("quote", ""),
                    turn_ids=list(proof.get("turn_ids") or []),
                    start_ms=proof.get("start_ms", 0),
                    end_ms=proof.get("end_ms", 0)),
        flags=[Flag(field=f["field"], code=f["code"], message=f["message"],
                    options=f.get("options", []),
                    blocking=f.get("blocking", True))
               for f in raw.get("flags") or []],
    )


def process_purchase_session(conn, session_id: int, audio: Path, *,
                             settings, ledger) -> None:
    """Transcribe a spoken purchase list; records stages, never raises."""
    from app import db
    from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded
    from app.pipeline.run import friendly_error_message

    try:
        db.set_session_status(conn, session_id, "processing",
                              "Listening to your purchases...")
        db.set_stage(conn, session_id, "listening")
        shop_id = conn.execute(
            "SELECT shop_id FROM sessions WHERE id = ?",
            (session_id,)).fetchone()["shop_id"]
        shop_row = conn.execute("SELECT language FROM shops WHERE id = ?",
                                (shop_id,)).fetchone()
        shop_lang = shop_row["language"] if shop_row else "ta"
        session_dir = Path(settings.data_dir) / "sessions" / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        wav = extract_audio(Path(audio), session_dir / "audio.wav")
        transcript = transcribe_wav(
            wav, keywords=keywords_for(shop_lang), ledger=ledger,
            settings=settings, languages=shop_bias(shop_lang))
        db.set_stage(conn, session_id, "items")
        drafts = extract_purchases(transcript, ledger=ledger,
                                   settings=settings, language=shop_lang)
        db.set_stage(conn, session_id, "checking")
        write_purchase_meta(Path(settings.data_dir), session_id, {
            "transcript": transcript.text,
            "drafts": [_draft_to_dict(d) for d in drafts]})
        db.set_stage(conn, session_id, "ready")
        noun = "item" if len(drafts) == 1 else "items"
        db.set_session_status(conn, session_id, "review",
                              f"{len(drafts)} {noun} heard")
    except CostCapExceeded:
        db.set_session_status(conn, session_id, "failed",
                              BUDGET_EXHAUSTED_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a status
        db.set_session_status(conn, session_id, "failed",
                              friendly_error_message(exc, media="recording"))


def run_purchase_job(settings, session_id: int, audio: str) -> None:
    """Background entry: opens its own connection, never the request's."""
    from app import db
    from app.costs import CostLedger

    conn = db.connect(Path(settings.data_dir))
    try:
        ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                            settings.daily_budget_usd)
        process_purchase_session(conn, session_id, Path(audio),
                                 settings=settings, ledger=ledger)
    finally:
        conn.close()
