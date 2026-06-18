#!/usr/bin/env python3
"""SQLite DBの中身を確認する。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path("data/nagoya_event.db")


def print_rows(conn: sqlite3.Connection, table_name: str) -> None:
    print(f"=== {table_name} ===")

    cursor = conn.execute(
        f"""
        SELECT date, time, end_time, venue, title, source, status, note, url
        FROM {table_name}
        ORDER BY date, time, venue, title
        LIMIT 10
        """
    )
    rows = cursor.fetchall()

    if not rows:
        print("なし")
    else:
        for row in rows:
            print(row)

    print()


def main() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        print_rows(conn, "events")
        print_rows(conn, "road_events")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
