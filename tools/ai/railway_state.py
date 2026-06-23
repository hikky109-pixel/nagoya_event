#!/usr/bin/env python3
"""鉄道ベータ通知の前回状態を読み書きする。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RAILWAY_COOLDOWN_SECONDS = {
    "info": 30 * 60,
    "warning": 15 * 60,
    "critical": 5 * 60,
}


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


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_railway_last_notify(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    last_sent_at = parse_datetime(data.get("last_sent_at"))
    severity = str(data.get("severity") or "").strip()
    result: dict[str, Any] = {}
    if last_sent_at is not None:
        result["last_sent_at"] = last_sent_at
    if severity:
        result["severity"] = severity
    return result


def save_railway_last_notify(path: Path, severity: str, sent_at: datetime | str) -> None:
    if isinstance(sent_at, datetime):
        sent_at_text = sent_at.isoformat(timespec="seconds")
    else:
        sent_at_text = str(sent_at)

    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_sent_at": sent_at_text,
        "severity": severity,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def railway_notify_allowed(
    last_notify: dict[str, Any],
    severity: str,
    now: datetime,
    change_type: str,
) -> tuple[bool, int]:
    if change_type != "unchanged":
        return True, 0

    cooldown_seconds = RAILWAY_COOLDOWN_SECONDS.get(severity, RAILWAY_COOLDOWN_SECONDS["info"])
    last_sent_at = last_notify.get("last_sent_at")

    if not isinstance(last_sent_at, datetime):
        return True, 0

    elapsed_seconds = int((now - last_sent_at.astimezone(now.tzinfo)).total_seconds())
    remaining_seconds = cooldown_seconds - elapsed_seconds
    if remaining_seconds > 0:
        return False, remaining_seconds
    return True, 0


def diff_alerts(previous: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    previous_clean = clean_alerts(previous)
    current_clean = clean_alerts(current)
    previous_set = set(previous_clean)
    current_set = set(current_clean)
    added = [alert for alert in current_clean if alert not in previous_set]
    removed = [alert for alert in previous_clean if alert not in current_set]
    return added, removed
