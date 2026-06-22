#!/usr/bin/env python3
"""チャンネルごとの短期会話履歴を保存する。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "data" / "ai" / "chat_memory"
MAX_ITEMS = 20

try:
    import config  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - 単体実行時の保険
    config = None  # type: ignore[assignment]


def max_items() -> int:
    value = getattr(config, "GEMMA_CHAT_HISTORY_LIMIT", MAX_ITEMS) if config is not None else MAX_ITEMS
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return MAX_ITEMS


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def memory_path(channel_id: int | str) -> Path:
    safe_id = str(channel_id).strip() or "unknown"
    return MEMORY_DIR / f"{safe_id}.json"


def load_history(channel_id: int | str) -> list[dict[str, Any]]:
    path = memory_path(channel_id)
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)][-max_items():]


def save_history(channel_id: int | str, history: list[dict[str, Any]]) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = memory_path(channel_id)
    trimmed = history[-max_items():]
    with path.open("w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_message(channel_id: int | str, user_name: str, message: str, role: str) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("role must be user or assistant.")

    history = load_history(channel_id)
    history.append(
        {
            "timestamp": now_iso(),
            "user_name": user_name,
            "message": message,
            "role": role,
        }
    )
    save_history(channel_id, history)


def format_history(history: list[dict[str, Any]], limit: int | None = None) -> str:
    item_limit = max_items() if limit is None else max(1, int(limit))
    lines: list[str] = []
    for item in history[-item_limit:]:
        role = item.get("role", "")
        user_name = item.get("user_name", "")
        message = item.get("message", "")
        timestamp = item.get("timestamp", "")
        lines.append(f"- [{timestamp}] {role} {user_name}: {message}")
    return "\n".join(lines)
