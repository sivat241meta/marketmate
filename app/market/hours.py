"""Opening hours, pincode and shop coordinates (Task 63).

One helper — :func:`shop_open_status` — decides the open/closed chip shown
on the shop page, market cards and the customer order page. All decisions
use IST. Hours are stored as JSON on the shop row::

    {"closed": [6], "slots": {"0": [["06:00", "13:00"], ["16:30", "21:30"]]}}

Days are ``datetime.weekday()`` numbers (0 = Monday). A day holds at most
two slots. A slot whose close is at or before its open runs overnight into
the next day; open == close means open 24 hours. Days in ``closed`` stay
shut all day.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_PINCODE_RE = re.compile(r"^\d{6}$")
_DAY_COUNT = 7


def _to_minutes(value: str) -> int:
    match = _TIME_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"bad time: {value!r} (use HH:MM)")
    return int(match.group(1)) * 60 + int(match.group(2))


def minutes_to_hhmm(minutes: int) -> str:
    """Minutes since midnight -> '06:00' for time inputs."""
    total = int(minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def format_time_12(minutes: int) -> str:
    """Minutes since midnight -> '9:30 pm' style label."""
    total = int(minutes) % (24 * 60)
    hour, minute = divmod(total, 60)
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def parse_hours_form(form: Any) -> str:
    """Canonical hours JSON from settings fields, or '' when unset.

    Reads ``closed_{d}`` plus ``open_{d}_{n}``/``close_{d}_{n}`` for day
    ``d`` (0 = Monday) and slot ``n`` (1 or 2). Raises ValueError on a bad
    time or a half-filled slot.
    """
    get = form.get if hasattr(form, "get") else (lambda k, d="": d)
    closed: list[int] = []
    slots: dict[str, list[list[str]]] = {}
    any_value = False
    for day in range(_DAY_COUNT):
        if str(get(f"closed_{day}", "") or "").strip().lower() in (
                "1", "on", "true", "yes"):
            closed.append(day)
            any_value = True
        day_slots: list[list[str]] = []
        for num in (1, 2):
            opened = str(get(f"open_{day}_{num}", "") or "").strip()
            shut = str(get(f"close_{day}_{num}", "") or "").strip()
            if not opened and not shut:
                continue
            any_value = True
            if not opened or not shut:
                raise ValueError("fill both open and close, or neither")
            _to_minutes(opened)
            _to_minutes(shut)
            day_slots.append([opened, shut])
        if day_slots:
            slots[str(day)] = day_slots
    if not any_value:
        return ""
    return json.dumps({"closed": closed, "slots": slots})


def _normalize_hours(data: Any) -> dict:
    """Shape-check decoded hours JSON (TypeError/ValueError when corrupt)."""
    if not isinstance(data, dict):
        raise TypeError("corrupt hours")
    closed_raw = data.get("closed", [])
    slots_raw = data.get("slots", {})
    if not isinstance(closed_raw, list) or not isinstance(slots_raw, dict):
        raise TypeError("corrupt hours")
    closed = set()
    for day in closed_raw:
        if isinstance(day, bool) or not isinstance(day, int):
            raise TypeError("corrupt hours")
        if not 0 <= day < _DAY_COUNT:
            raise ValueError("corrupt hours")
        closed.add(day)
    slots: dict[int, list[tuple[int, int]]] = {}
    for key, value in slots_raw.items():
        day = int(key)
        if not 0 <= day < _DAY_COUNT or not isinstance(value, list):
            raise TypeError("corrupt hours")
        if len(value) > 2:
            raise ValueError("at most two slots per day")
        parsed = []
        for slot in value:
            if (not isinstance(slot, (list, tuple)) or len(slot) != 2):
                raise TypeError("corrupt hours")
            parsed.append((_to_minutes(slot[0]), _to_minutes(slot[1])))
        slots[day] = parsed
    return {"closed": closed, "slots": slots}


def parse_hours_json(raw: str | None) -> dict:
    """Normalized hours: {'closed': set[int], 'slots': {int: [(o, c)]}}.

    Raises ValueError when the stored JSON is corrupt or out of shape.
    """
    if raw is None or not str(raw).strip():
        raise ValueError("no hours set")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError("corrupt hours") from exc
    try:
        return _normalize_hours(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("corrupt hours") from exc


def has_hours(raw: str | None) -> bool:
    """True when the shop has usable opening hours stored."""
    try:
        parse_hours_json(raw)
    except ValueError:
        return False
    return True


def _now_ist(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def open_status(hours_raw: str | None,
               now: datetime | None = None) -> dict:
    """Open/closed decision for one moment (IST).

    Returns ``{'state': 'open'|'closed'|'unknown', 'time': '9:30 pm'}``
    where ``time`` is the closing time when open, the next opening time
    when closed, and '' when hours are unset or no time applies.
    """
    try:
        hours = parse_hours_json(hours_raw)
    except ValueError:
        return {"state": "unknown", "time": ""}
    moment = _now_ist(now)
    weekday = moment.weekday()
    minute = moment.hour * 60 + moment.minute
    closed = hours["closed"]
    slots = hours["slots"]

    def spans(day: int) -> list[tuple[int, int]]:
        """Open minute-spans covering ``day`` (overnight spills in)."""
        out = []
        if day not in closed:
            for opened, shut in slots.get(day, []):
                if shut == opened:
                    return [(0, 24 * 60)]
                if shut > opened:
                    out.append((opened, shut))
                else:
                    out.append((opened, 24 * 60))
        prev = (day - 1) % _DAY_COUNT
        if prev not in closed and day not in closed:
            for opened, shut in slots.get(prev, []):
                if shut < opened:
                    out.append((0, shut))
        return out

    if weekday not in closed:
        for start, end in spans(weekday):
            if start <= minute < end:
                return {"state": "open",
                        "time": format_time_12(end % (24 * 60))}
    # Next opening within the coming week (closed days skipped).
    for ahead in range(8):
        day = (weekday + ahead) % _DAY_COUNT
        if day in closed:
            continue
        for opened, shut in slots.get(day, []):
            if shut == opened:
                return {"state": "closed", "time": ""}
            if ahead == 0:
                if minute < opened:
                    return {"state": "closed",
                            "time": format_time_12(opened)}
            else:
                return {"state": "closed",
                        "time": format_time_12(opened)}
    return {"state": "closed", "time": ""}


def shop_open_status(shop: Any, now: datetime | None = None) -> dict:
    """Open/closed chip data for a shop row (the one helper for all pages)."""
    try:
        raw = shop["hours_json"]
    except (KeyError, IndexError, TypeError):
        return {"state": "unknown", "time": ""}
    return open_status(raw, now)


def validate_pincode(value: str | None) -> str | None:
    """Cleaned 6-digit pincode or None when blank. Raises ValueError."""
    text = str(value or "").strip()
    if not text:
        return None
    if not _PINCODE_RE.match(text):
        raise ValueError("pincode must be 6 digits")
    return text


def round_coord(value: Any, *, kind: str = "lat") -> float | None:
    """Coordinate rounded to 3 decimals (~100 m), or None when blank."""
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise ValueError("bad location") from exc
    limit = 90 if kind == "lat" else 180
    if not -limit <= number <= limit:
        raise ValueError("bad location")
    return round(number, 3)
