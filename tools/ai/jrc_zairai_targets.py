#!/usr/bin/env python3
"""JR東海在来線ベータで扱う名古屋圏対象路線。"""

from __future__ import annotations

from typing import Any


JR_CENTRAL_TARGET_LINES: dict[str, dict[str, Any]] = {
    "東海道線": {
        "match": ["東海道線"],
        "display": "東海道線\n(豊橋～米原)",
        "url": "https://traininfo.jr-central.co.jp/zairaisen/train_information.html?line=10001&lang=ja",
    },
    "中央線": {
        "match": ["中央線"],
        "display": "中央線",
        "url": "https://traininfo.jr-central.co.jp/zairaisen/train_information.html?line=10003&lang=ja",
    },
    "関西線": {
        "match": ["関西線"],
        "display": "関西線",
        "url": "https://traininfo.jr-central.co.jp/zairaisen/train_information.html?line=10006&lang=ja",
    },
}


def jrc_target_line_key(line_name: str) -> str | None:
    text = str(line_name or "")
    for key, meta in JR_CENTRAL_TARGET_LINES.items():
        if any(pattern in text for pattern in meta["match"]):
            return key
    return None


def jrc_target_line_display(line_name: str) -> str | None:
    key = jrc_target_line_key(line_name)
    if key is None:
        return None
    return str(JR_CENTRAL_TARGET_LINES[key]["display"])


def jrc_target_line_url(line_name: str) -> str | None:
    key = jrc_target_line_key(line_name)
    if key is None:
        return None
    return str(JR_CENTRAL_TARGET_LINES[key]["url"])
