#!/usr/bin/env python3
"""Small logging helpers for scheduled Gemma scripts."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")


def log(message: str) -> None:
    now = datetime.now(JST)
    print(f"[{now:%Y-%m-%d %H:%M:%S}] {message}")
