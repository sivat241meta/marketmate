from __future__ import annotations

from app.meta.spark import SparkError, chat_json, image_part
from app.models import DraftItem, Frame, Turn


def item_window(item: DraftItem, turns: list[Turn]) -> tuple[int, int]:
    """Estimate when the item is spoken: ±3 s around the quote's midpoint."""
    ids = item.proof.turn_ids or []
    turn = next((t for t in turns if ids and t.id == ids[0]), None)
    if turn is None:
        turn = turns[0] if turns else None
    if turn is None:
        return (0, 0)
    duration = turn.end_ms - turn.start_ms
    quote = item.proof.quote or ""
    if duration > 8000 and quote and quote in turn.text:
        middle = turn.text.find(quote) + len(quote) / 2
        moment = turn.start_ms + middle / len(turn.text) * duration
        return (max(turn.start_ms, int(moment - 3000)),
                min(turn.end_ms, int(moment + 3000)))
    return (turn.start_ms, turn.end_ms)


def frames_for_window(frames: list[Frame], start_ms: int, end_ms: int,
                      k: int = 4) -> list[Frame]:
    """k evenly spaced frames inside [start_ms-500, end_ms+1500]."""
    in_window = sorted(
        (f for f in frames if start_ms - 500 <= f.t_ms <= end_ms + 1500),
        key=lambda f: f.t_ms,
    )
    if not in_window or len(in_window) <= k:
        return in_window
    if k == 1:
        return [in_window[len(in_window) // 2]]
    return [in_window[round(i * (len(in_window) - 1) / (k - 1))] for i in range(k)]


def _pick_summary(data: dict, of: int) -> str:
    try:
        index = int(data["best_index"])
    except (KeyError, TypeError, ValueError):
        return f"of {of} frames"
    match = "match" if data.get("matches") else "no match"
    return f"frame {index + 1} of {of} · {match}"


def pick_best_frame(item: DraftItem, candidates: list[Frame], *,
                    ledger, settings) -> tuple[Frame, bool]:
    """Ask Spark which candidate best shows the item and whether it matches."""
    if not candidates:
        raise SparkError("no candidate frames")
    prompt = (f"Which of these {len(candidates)} images best shows {item.name_en},"
              ' and does it match? Reply only JSON: {"best_index": int,'
              ' "matches": bool}.')
    content: list[dict] = [{"type": "text", "text": prompt}]
    content.extend(image_part(frame.path) for frame in candidates)
    count = len(candidates)
    reply = chat_json(
        [{"role": "user", "content": content}],
        ledger=ledger, settings=settings, reasoning_effort="low",
        step="find product frames",
        summary=lambda data, of=count: _pick_summary(data, of))
    try:
        index = int(reply["best_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SparkError(f"bad best_index in reply: {reply!r}") from exc
    if not 0 <= index < len(candidates):
        raise SparkError(f"best_index {index} out of range")
    return (candidates[index], bool(reply.get("matches", False)))
