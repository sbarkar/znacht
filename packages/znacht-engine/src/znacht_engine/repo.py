"""SQLite persistence: runs, learned facts, pantry edits, todo state, price history."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from znacht.services.pipeline import WeekResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  household_id TEXT NOT NULL,
  week TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prices (
  product_id TEXT NOT NULL, channel TEXT NOT NULL, price TEXT NOT NULL, seen_on TEXT NOT NULL,
  PRIMARY KEY (product_id, channel, seen_on)
);
CREATE TABLE IF NOT EXISTS ledger (
  week TEXT PRIMARY KEY, savings TEXT NOT NULL, online_total TEXT NOT NULL, applied_at TEXT NOT NULL
);
"""


class Repo:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    # -- runs ---------------------------------------------------------------------------
    def save_run(self, result: WeekResult) -> int:
        cur = self._db.execute(
            "INSERT INTO runs (household_id, week, status, created_at, result) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                result.household_id,
                result.week.start.isoformat(),
                str(result.status),
                _now(),
                result.model_dump_json(),
            ),
        )
        self._db.commit()
        return int(cur.lastrowid or 0)

    def update_run(self, run_id: int, result: WeekResult) -> None:
        self._db.execute(
            "UPDATE runs SET status = ?, result = ? WHERE id = ?",
            (str(result.status), result.model_dump_json(), run_id),
        )
        self._db.commit()

    def get_run(self, run_id: int) -> WeekResult | None:
        row = self._db.execute("SELECT result FROM runs WHERE id = ?", (run_id,)).fetchone()
        return WeekResult.model_validate_json(row["result"]) if row else None

    def latest_run(self, household_id: str) -> tuple[int, WeekResult] | None:
        row = self._db.execute(
            "SELECT id, result FROM runs WHERE household_id = ? ORDER BY id DESC LIMIT 1",
            (household_id,),
        ).fetchone()
        return (int(row["id"]), WeekResult.model_validate_json(row["result"])) if row else None

    def runs(self, household_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, week, status, created_at FROM runs "
            "WHERE household_id = ? ORDER BY id DESC LIMIT ?",
            (household_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- key/value ------------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        row = self._db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value))
        )
        self._db.commit()

    # -- prices and ledger -------------------------------------------------------------------
    def record_prices(self, rows: list[tuple[str, str, str]]) -> None:
        today = datetime.now(tz=UTC).date().isoformat()
        self._db.executemany(
            "INSERT OR REPLACE INTO prices (product_id, channel, price, seen_on) "
            "VALUES (?, ?, ?, ?)",
            [(pid, ch, price, today) for pid, ch, price in rows],
        )
        self._db.commit()

    def price_history(self, product_id: str, channel: str) -> list[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT seen_on, price FROM prices "
            "WHERE product_id = ? AND channel = ? ORDER BY seen_on",
            (product_id, channel),
        ).fetchall()
        return [(r["seen_on"], r["price"]) for r in rows]

    def record_applied(self, week: str, savings: str, online_total: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO ledger (week, savings, online_total, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (week, savings, online_total, _now()),
        )
        self._db.commit()

    def ledger(self) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self._db.execute("SELECT * FROM ledger ORDER BY week DESC").fetchall()
        ]


def _now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
