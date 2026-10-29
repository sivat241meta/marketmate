from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import SAM_MODEL, SPARK_MODEL, SPARK_OPEN_MODEL, VOICE_MODEL

IST = ZoneInfo("Asia/Kolkata")
SPARK_USD_PER_1M_INPUT = 1.25
SPARK_USD_PER_1M_OUTPUT = 4.25

#: Task 78 columns added to the ledger's own SQLite file (all nullable).
_NEW_COLUMNS = (
    ("shop_id", "INTEGER"),
    ("session_id", "INTEGER"),
    ("step", "TEXT"),
    ("latency_ms", "INTEGER"),
    ("ok", "INTEGER"),
    ("summary", "TEXT"),
)

#: Spark steps that use vision (image input); every other Spark step is text.
VISION_STEPS = frozenset({
    "find product frames",
    "verify photo",
    "read board",
    "scan photo",
})

MAX_SUMMARY_CHARS = 140
_PHONE_RE = re.compile(r"\+?\d[\d\s\-.()]{5,}\d")
_DIGITS_RE = re.compile(r"\d{7,}")


def sanitize_summary(text: str | None) -> str | None:
    """Short non-sensitive summary: phones redacted, whitespace folded."""
    if text is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    if not cleaned:
        return None
    cleaned = _PHONE_RE.sub("[…]", cleaned)
    cleaned = _DIGITS_RE.sub("[…]", cleaned)
    return cleaned[:MAX_SUMMARY_CHARS]


class CostCapExceeded(Exception):
    pass


BUDGET_EXHAUSTED_MESSAGE = (
    "Today's demo budget is used up - please try the sample shops."
)


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def spark_cost(usage: dict) -> float:
    """Meta cost of one Spark call. completion_tokens includes reasoning."""
    prompt = usage.get("prompt_tokens", 0) or 0
    completion = usage.get("completion_tokens", 0) or 0
    return prompt / 1e6 * SPARK_USD_PER_1M_INPUT + completion / 1e6 * SPARK_USD_PER_1M_OUTPUT


class CostLedger:
    """App-level daily spend ledger in its own SQLite file."""

    def __init__(self, db_path: Path, daily_cap_usd: float) -> None:
        self._db_path = Path(db_path)
        self._cap = daily_cap_usd
        self._shop_id: int | None = None
        self._session_id: int | None = None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS costs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "day TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, "
                "usd REAL NOT NULL, detail TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL)"
            )
            have = {row[1] for row in conn.execute("PRAGMA table_info(costs)")}
            for name, ddl in _NEW_COLUMNS:
                if name not in have:
                    conn.execute(f"ALTER TABLE costs ADD COLUMN {name} {ddl}")

    def bind(self, *, shop_id: int | None = None,
             session_id: int | None = None) -> None:
        """Default shop/session stamped on later add() calls (job entries)."""
        self._shop_id = shop_id
        self._session_id = session_id

    def check(self) -> None:
        if self.today_usd("meta") >= self._cap:
            raise CostCapExceeded(
                f"daily Meta budget reached: ${self.today_usd('meta'):.4f} >= ${self._cap:.2f}")

    def add(self, provider: str, model: str, usd: float, detail: str = "",
            *, shop_id: int | None = None, session_id: int | None = None,
            step: str | None = None, latency_ms: int | None = None,
            ok: int | None = None, summary: str | None = None) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO costs (day, provider, model, usd, detail,"
                " created_at, shop_id, session_id, step, latency_ms, ok,"
                " summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_today_ist(), provider, model, float(usd), detail,
                 datetime.now(IST).isoformat(),
                 shop_id if shop_id is not None else self._shop_id,
                 session_id if session_id is not None else self._session_id,
                 step, latency_ms,
                 None if ok is None else int(bool(ok)),
                 sanitize_summary(summary)),
            )

    def today_usd(self, provider: str = "meta") -> float:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(usd), 0) FROM costs WHERE day = ? AND provider = ?",
                (_today_ist(), provider),
            ).fetchone()
        return float(row[0])

    def rows_for_shop(self, shop_id: int, *, day: str | None = None,
                      session_id: int | None = None, since_id: int = 0,
                      kind: str | None = None, limit: int = 500) -> list[dict]:
        """Newest-first ledger rows for one shop (the Meta AI calls page)."""
        query = ("SELECT id, day, provider, model, usd, detail, created_at,"
                 " shop_id, session_id, step, latency_ms, ok, summary"
                 " FROM costs WHERE shop_id = ?")
        params: list = [shop_id]
        if day is not None:
            query += " AND day = ?"
            params.append(day)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if since_id:
            query += " AND id > ?"
            params.append(since_id)
        if kind == "voice":
            query += " AND model = ?"
            params.append(VOICE_MODEL)
        elif kind == "spark":
            query += " AND (model = ? OR model = ?)"
            params.extend([SPARK_MODEL, SPARK_OPEN_MODEL])
        elif kind == "sam":
            query += " AND model = ?"
            params.append(SAM_MODEL)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params)]

    def today_stats(self, shop_id: int) -> dict:
        """Calls today by model, total cost and average latency, one shop."""
        rows = self.rows_for_shop(shop_id, day=_today_ist(), limit=100000)
        by_model = {"voice": 0, "spark_text": 0, "spark_vision": 0,
                    "sam": 0, "baseten": 0}
        cost = 0.0
        latencies: list[int] = []
        for row in rows:
            cost += float(row["usd"] or 0.0)
            if row["latency_ms"] is not None:
                latencies.append(int(row["latency_ms"]))
            if row["provider"] == "baseten":
                by_model["baseten"] += 1
            elif row["model"] == VOICE_MODEL:
                by_model["voice"] += 1
            elif row["model"] == SPARK_MODEL:
                if (row["step"] or "") in VISION_STEPS:
                    by_model["spark_vision"] += 1
                else:
                    by_model["spark_text"] += 1
            elif row["model"] == SAM_MODEL:
                by_model["sam"] += 1
        return {
            "calls": len(rows),
            "by_model": by_model,
            "cost_usd": cost,
            "avg_latency_ms": (sum(latencies) // len(latencies)
                               if latencies else None),
        }
