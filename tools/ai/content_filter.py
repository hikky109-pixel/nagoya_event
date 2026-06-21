#!/usr/bin/env python3
"""Discordログに残さない内容を判定する軽量フィルタ。"""

from __future__ import annotations

import re


FILTER_PATTERNS = [
    r"(?i)\b(sex|porn|nude|nsfw)\b",
    r"(?i)\bfuck(?:ing)?\b",
    r"(?i)\bkill\s+yourself\b",
    r"(?i)\b死ね\b",
    r"(?i)(?:荒らし|スパム|連投荒らし)",
    r"(?i)(?:下ネタ|性的|エロ|わいせつ|猥褻)",
    r"(?i)(?:バカ|ばか|アホ|あほ|クソ|くそ).*(?:死ね|消えろ|黙れ)",
]

COMPILED_PATTERNS = [re.compile(pattern) for pattern in FILTER_PATTERNS]


def is_filtered(text: str) -> bool:
    if not text:
        return False
    normalized = text.strip()
    return any(pattern.search(normalized) for pattern in COMPILED_PATTERNS)


def filter_status(text: str) -> str:
    return "filtered" if is_filtered(text) else "ok"
