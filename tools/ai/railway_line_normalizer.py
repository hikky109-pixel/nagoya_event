#!/usr/bin/env python3
"""鉄道会社込みの表記を月報向けの路線名へ正規化する。"""

from __future__ import annotations

import re

try:
    from jrc_zairai_targets import jrc_target_line_key
except ModuleNotFoundError:
    from tools.ai.jrc_zairai_targets import jrc_target_line_key


SINGLE_LINE_NAMES = (
    "あおなみ線",
    "リニモ",
    "城北線",
)


def normalize_line_name(raw_line: str) -> str:
    text = " ".join(str(raw_line or "").split())
    if not text:
        return "鉄道運行情報"

    if "東海道新幹線" in text:
        return "東海道新幹線"

    jrc_line = jrc_target_line_key(text)
    if jrc_line is not None:
        return jrc_line

    meitetsu_match = re.search(r"名鉄\s*([^\s]+線)", text)
    if meitetsu_match:
        return f"名鉄{meitetsu_match.group(1)}"

    subway_match = re.search(r"名古屋市営地下鉄\s*([^\s]+線)", text)
    if subway_match:
        return subway_match.group(1)

    kintetsu_match = re.search(r"近鉄\s*([^\s]+線)", text)
    if kintetsu_match:
        return f"近鉄{kintetsu_match.group(1)}"

    for line_name in SINGLE_LINE_NAMES:
        if line_name in text:
            return line_name

    return text
