#!/usr/bin/env python3
"""画像付き案件を data/ai/image_case に保存する。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
IMAGE_CASE_DIR = ROOT / "data" / "ai" / "image_case"
ATTACHMENT_DIR = ROOT / "data" / "ai" / "attachments"


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def case_path(timestamp: str, message_id: str) -> Path:
    safe_timestamp = timestamp.replace(":", "").replace("-", "").replace("+", "_")
    return IMAGE_CASE_DIR / f"{safe_timestamp}_{message_id}.json"


def save_image_case(case: dict[str, Any]) -> Path:
    IMAGE_CASE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = str(case.get("timestamp") or now_local().isoformat(timespec="minutes"))
    message_id = str(case.get("message_id") or "unknown")
    path = case_path(timestamp, message_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def attachment_path(message_id: int | str, filename: str) -> Path:
    safe_filename = Path(filename).name or "attachment"
    return ATTACHMENT_DIR / f"{message_id}_{safe_filename}"


def load_recent_cases(limit: int = 5) -> list[dict[str, Any]]:
    if not IMAGE_CASE_DIR.exists():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(IMAGE_CASE_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            cases.append(data)
    return cases
