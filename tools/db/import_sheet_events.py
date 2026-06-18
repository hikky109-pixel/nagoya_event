#!/usr/bin/env python3
"""イベントCSVをSQLiteへ取り込む。"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


DB_PATH = Path("data/nagoya_event.db")
CSV_PATHS = [
    Path("csv_events/misonoza.csv"),
    Path("csv_events/shiki.csv"),
    Path("csv_events/manual.csv"),
    Path("csv_events/spot.csv"),
]
COLUMNS = ("date", "time", "end_time", "venue", "title", "source", "status", "note", "url")


def normalize_row(row: dict[str, str], source_name: str) -> dict[str, str]:
    values = {column: (row.get(column) or "") for column in COLUMNS}
    values["source"] = values["source"] or source_name
    values["status"] = values["status"] or "confirmed"
    return values


def import_csv(conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        print(f"CSVなし: {path}")
        return 0

    count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            row = normalize_row(raw_row, path.stem)
            conn.execute(
                """
                INSERT INTO events (date, time, end_time, venue, title, source, status, note, url)
                VALUES (:date, :time, :end_time, :venue, :title, :source, :status, :note, :url)
                """,
                row,
            )
            count += 1

    print(f"取り込み完了: {path} / {count}件")
    return count


def main() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM events")
        total = sum(import_csv(conn, path) for path in CSV_PATHS)

    print(f"events 取り込み完了: {total}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
