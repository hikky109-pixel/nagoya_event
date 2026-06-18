#!/usr/bin/env python3
"""道路イベントCSVをSQLiteへ取り込む。"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


DB_PATH = Path("data/nagoya_event.db")
CSV_PATH = Path("csv_events/road.csv")
FALLBACK_CSV_PATH = Path("csv_events/road.example.csv")
COLUMNS = ("date", "time", "end_time", "venue", "title", "source", "status", "note", "url")


def pick_csv_path() -> Path | None:
    if CSV_PATH.exists():
        return CSV_PATH
    if FALLBACK_CSV_PATH.exists():
        return FALLBACK_CSV_PATH
    return None


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    values = {column: (row.get(column) or "") for column in COLUMNS}
    values["source"] = values["source"] or "road"
    values["status"] = values["status"] or "confirmed"
    return values


def main() -> int:
    csv_path = pick_csv_path()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM road_events")

        if csv_path is None:
            print(f"CSVなし: {CSV_PATH}")
            print(f"CSVなし: {FALLBACK_CSV_PATH}")
            print("road_events 取り込み完了: 0件")
            return 0

        count = 0
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for raw_row in reader:
                row = normalize_row(raw_row)
                conn.execute(
                    """
                    INSERT INTO road_events (date, time, end_time, venue, title, source, status, note, url)
                    VALUES (:date, :time, :end_time, :venue, :title, :source, :status, :note, :url)
                    """,
                    row,
                )
                count += 1

    print(f"road_events 取り込み完了: {csv_path} / {count}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
