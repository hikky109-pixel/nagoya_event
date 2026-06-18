#!/usr/bin/env python3
"""SQLite DBを初期化する。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("data/nagoya_event.db")


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            end_time TEXT,
            venue TEXT,
            title TEXT,
            source TEXT,
            status TEXT,
            note TEXT,
            url TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS road_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            end_time TEXT,
            venue TEXT,
            title TEXT,
            source TEXT,
            status TEXT,
            note TEXT,
            url TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS railway_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line TEXT,
            station TEXT,
            title TEXT,
            status TEXT
        )
        """
    )

    conn.commit()
    conn.close()

    print("DB初期化完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())