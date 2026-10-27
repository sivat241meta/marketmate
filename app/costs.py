from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SPARK_USD_PER_1M_INPUT = 1.25
SPARK_USD_PER_1M_OUTPUT = 4.25


class CostCapExceeded(Exception):
    pass


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
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS costs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "day TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, "
                "usd REAL NOT NULL, detail TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL)"
            )

    def check(self) -> None:
        if self.today_usd("meta") >= self._cap:
            raise CostCapExceeded(
                f"daily Meta budget reached: ${self.today_usd('meta'):.4f} >= ${self._cap:.2f}")

    def add(self, provider: str, model: str, usd: float, detail: str = "") -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO costs (day, provider, model, usd, detail, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (_today_ist(), provider, model, float(usd), detail,
                 datetime.now(IST).isoformat()),
            )

    def today_usd(self, provider: str = "meta") -> float:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(usd), 0) FROM costs WHERE day = ? AND provider = ?",
                (_today_ist(), provider),
            ).fetchone()
        return float(row[0])
