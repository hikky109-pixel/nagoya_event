#!/usr/bin/env python3
"""Web検索結果をGemmaへ渡す前に秘書向けに整形する。"""

from __future__ import annotations

import json
import sys
from typing import Any


def format_results(search_result: dict[str, Any]) -> dict[str, Any]:
    results = search_result.get("results", [])
    if not isinstance(results, list):
        results = []

    official: list[dict[str, Any]] = []
    candidate: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        formatted = {
            "title": str(item.get("title", "")).strip(),
            "official": bool(item.get("official")),
        }
        if not formatted["title"]:
            continue
        if formatted["official"]:
            official.append(formatted)
        else:
            candidate.append(formatted)

    official = official[:2]
    candidate = candidate[:1]
    return {
        "query": search_result.get("query", ""),
        "category": search_result.get("category", ""),
        "official": official,
        "candidate": candidate,
        "official_status": search_result.get("official_status", ""),
    }


def main() -> int:
    text = sys.stdin.read().strip()
    if not text:
        print(json.dumps(format_results({}), ensure_ascii=False, indent=2))
        return 0
    data = json.loads(text)
    if not isinstance(data, dict):
        data = {}
    print(json.dumps(format_results(data), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
