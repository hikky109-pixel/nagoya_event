#!/usr/bin/env python3
"""名駅繁忙ボタン押下ログを直近集計する。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from tools.ai.meieki_busy_buttons import JST, LOG_PATH, MEIEKI_BUSY_PLACES


PLACE_LABELS = {
    "sakuradori": "🌸 桜通口",
    "taiko": "🚄 太閤通口",
    "meitetsu_kintetsu": "🚃 名鉄/近鉄",
    "midland": "🏢 ミッドランド",
}
PLACE_ALERT_ICONS = {
    "sakuradori": "🔥",
    "taiko": "⚡",
    "meitetsu_kintetsu": "⚡",
    "midland": "⚡",
}


def parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def read_recent_busy(minutes: int = 10) -> dict[str, int]:
    counts = {place["place"]: 0 for place in MEIEKI_BUSY_PLACES}
    if not LOG_PATH.exists():
        return counts

    now = datetime.now(JST)
    since = now - timedelta(minutes=minutes)
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return counts

    for line in lines:
        if not line.strip():
            continue
        try:
            row: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        ts = parse_ts(str(row.get("ts", "")))
        if ts is None or ts < since or ts > now:
            continue
        place = str(row.get("place", ""))
        if place in counts:
            counts[place] += 1
    return counts


def build_busy_alert_message(counts: dict[str, int]) -> str | None:
    lines: list[str] = []
    for place in ("sakuradori", "taiko", "meitetsu_kintetsu", "midland"):
        count = int(counts.get(place, 0))
        if count < 2:
            continue
        label = PLACE_LABELS.get(place, place)
        label_without_emoji = " ".join(label.split()[1:]) or label
        icon = PLACE_ALERT_ICONS.get(place, "⚡")
        lines.append(f"{icon} {label_without_emoji} {count}件")

    if not lines:
        return None
    return "\n".join(
        [
            "ジェンマ課長メモ😇",
            "",
            *lines,
            "",
            "送迎待機の方はご注意ください🚕",
        ]
    )
