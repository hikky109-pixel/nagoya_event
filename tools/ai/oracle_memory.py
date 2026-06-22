#!/usr/bin/env python3
"""Oracle記憶をGemma課長プロンプトへ渡すための軽量ヘルパー。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.ai.oracle_search import search_oracle


ROOT = Path(__file__).resolve().parents[2]
ORACLE_MEMORY_PATH = ROOT / "data" / "ai" / "oracle_memory.json"


def load_oracle_memory() -> dict[str, Any]:
    if not ORACLE_MEMORY_PATH.exists():
        return {}
    try:
        with ORACLE_MEMORY_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def compact_oracle_memory(query: str = "", max_items: int = 4) -> dict[str, Any]:
    matches = search_oracle(query, limit=max_items)
    if not matches:
        return {}
    return {
        "matches": matches,
    }


def format_oracle_matches(matches: list[dict[str, str]]) -> str:
    if not matches:
        return "過去事例なし"

    lines = ["過去事例:"]
    for item in matches:
        lines.append(f"・{item.get('title', '')}")
        summary = str(item.get("summary", "")).strip()
        lesson = str(item.get("lesson", "")).strip()
        if summary:
            lines.append(summary)
        if lesson:
            lines.append(lesson)
    return "\n".join(lines)


def format_oracle_memory(query: str = "", max_items: int = 4) -> str:
    matches = search_oracle(query, limit=max_items)
    return format_oracle_matches(matches)


def oracle_log_values_from_matches(matches: list[dict[str, str]]) -> tuple[int, str]:
    titles = ",".join(str(item.get("title", "")) for item in matches)
    return len(matches), titles


def oracle_log_values(query: str, max_items: int = 5) -> tuple[int, str]:
    return oracle_log_values_from_matches(search_oracle(query, limit=max_items))
