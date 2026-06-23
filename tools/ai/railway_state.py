#!/usr/bin/env python3
"""鉄道ベータ通知の前回状態を読み書きする。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def clean_alerts(alerts: list[str]) -> list[str]:
    cleaned: list[str] = []
    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def load_railway_state(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, []

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, []

    if not isinstance(data, dict):
        return False, []

    alerts = data.get("alerts")
    if not isinstance(alerts, list):
        return True, []

    return True, clean_alerts(alerts)


def save_railway_state(path: Path, alerts: list[str], updated_at: datetime | str) -> None:
    if isinstance(updated_at, datetime):
        updated_at_text = updated_at.isoformat(timespec="seconds")
    else:
        updated_at_text = str(updated_at)

    path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "updated_at": updated_at_text,
        "alerts": clean_alerts(alerts),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def diff_alerts(previous: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    previous_clean = clean_alerts(previous)
    current_clean = clean_alerts(current)
    previous_set = set(previous_clean)
    current_set = set(current_clean)
    added = [alert for alert in current_clean if alert not in previous_set]
    removed = [alert for alert in previous_clean if alert not in current_set]
    return added, removed
