#!/usr/bin/env python3
"""名駅繁忙ボタンがログで流れた時の遅延再確認state。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SIGNALS_DIR = ROOT / "data" / "signals"
FOLLOWUP_STATE_PATH = SIGNALS_DIR / "meieki_busy_followup_state.json"
JST = ZoneInfo("Asia/Tokyo")
FOLLOWUP_DELAY = timedelta(hours=1)
FOLLOWUP_REASON = "button_scrolled_by_5_messages"


def parse_jst_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def load_followup_state(path: Path = FOLLOWUP_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_followup_state(state: dict[str, Any], path: Path = FOLLOWUP_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_followup_state(button_state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    last_posted_at = parse_jst_time(str(button_state.get("last_posted_at", "")))
    if last_posted_at is None:
        return None
    scheduled_at = last_posted_at + FOLLOWUP_DELAY
    if now >= scheduled_at:
        return None
    return {
        "button_message_id": str(button_state.get("message_id", "")),
        "scheduled_at": scheduled_at.isoformat(timespec="seconds"),
        "reason": FOLLOWUP_REASON,
        "source_last_posted_at": last_posted_at.isoformat(timespec="seconds"),
        "done": False,
    }


def should_post_followup(state: dict[str, Any], now: datetime) -> bool:
    if not state or bool(state.get("done")):
        return False
    scheduled_at = parse_jst_time(str(state.get("scheduled_at", "")))
    return scheduled_at is not None and now >= scheduled_at


def followup_source_matches_button_state(state: dict[str, Any], button_state: dict[str, Any]) -> bool:
    if not state:
        return False
    return (
        str(state.get("button_message_id", "")) == str(button_state.get("message_id", ""))
        and str(state.get("source_last_posted_at", "")) == str(button_state.get("last_posted_at", ""))
    )


def mark_followup_done(
    state: dict[str, Any],
    *,
    message_id: str = "",
    posted_at: datetime,
    path: Path = FOLLOWUP_STATE_PATH,
) -> None:
    updated = dict(state)
    updated["done"] = True
    if message_id:
        updated["posted_message_id"] = message_id
    updated["posted_at"] = posted_at.isoformat(timespec="seconds")
    save_followup_state(updated, path)


def schedule_followup_if_needed(
    *,
    button_state: dict[str, Any],
    existing_followup_state: dict[str, Any],
    now: datetime,
    path: Path = FOLLOWUP_STATE_PATH,
) -> dict[str, Any] | None:
    if should_post_followup(existing_followup_state, now):
        return existing_followup_state

    pending = build_followup_state(button_state, now)
    if pending is None:
        return None

    if existing_followup_state and not bool(existing_followup_state.get("done")):
        existing_scheduled_at = parse_jst_time(str(existing_followup_state.get("scheduled_at", "")))
        pending_scheduled_at = parse_jst_time(str(pending.get("scheduled_at", "")))
        if existing_scheduled_at is not None and pending_scheduled_at == existing_scheduled_at:
            return existing_followup_state

    save_followup_state(pending, path)
    return pending
