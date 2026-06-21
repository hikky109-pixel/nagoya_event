#!/usr/bin/env python3
"""Oracle記憶をGemma課長プロンプトへ渡すための軽量ヘルパー。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def _matches_query(item: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    text = json.dumps(item, ensure_ascii=False)
    words = [word for word in query.replace("？", " ").replace("?", " ").split() if word]
    return any(word in text for word in words) if words else True


def compact_oracle_memory(query: str = "", max_items: int = 4) -> dict[str, Any]:
    memory = load_oracle_memory()
    if not memory:
        return {}

    successes = [item for item in memory.get("success_cases", []) if isinstance(item, dict) and _matches_query(item, query)]
    failures = [item for item in memory.get("failure_cases", []) if isinstance(item, dict) and _matches_query(item, query)]
    cautions = [item for item in memory.get("cautions", []) if isinstance(item, dict) and _matches_query(item, query)]

    if not successes:
        successes = [item for item in memory.get("success_cases", []) if isinstance(item, dict)]
    if not failures:
        failures = [item for item in memory.get("failure_cases", []) if isinstance(item, dict)]
    if not cautions:
        cautions = [item for item in memory.get("cautions", []) if isinstance(item, dict)]

    return {
        "generated_at": memory.get("generated_at", ""),
        "success_cases": successes[:max_items],
        "failure_cases": failures[:max_items],
        "cautions": cautions[:max_items],
    }


def format_oracle_memory(query: str = "", max_items: int = 4) -> str:
    compact = compact_oracle_memory(query, max_items=max_items)
    if not compact:
        return "Oracle記憶なし"
    return json.dumps(compact, ensure_ascii=False, indent=2)
