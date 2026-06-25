#!/usr/bin/env python3
"""鉄道ベータアラートの重大度を判定する。"""

from __future__ import annotations


INFO_KEYWORDS = (
    "遅れ",
    "折り返し列車の遅れ",
    "車両点検",
    "踏切安全確認",
)
WARNING_KEYWORDS = (
    "人が立ち入った",
    "人立入り",
    "線路点検",
    "信号確認",
    "架線点検",
)
CRITICAL_KEYWORDS = (
    "運転見合わせ",
    "運休",
    "再開見込みなし",
    "再開見込み未定",
)
AONAMI_CRITICAL_KEYWORDS = (
    "強風",
    "台風",
    "運転見合わせ",
    "運転を見合わせ",
    "運休",
)


def detect_railway_severity(alerts: list[str]) -> str:
    texts = [" ".join(str(alert or "").split()) for alert in alerts]
    if any(
        "あおなみ線" in text and keyword in text
        for text in texts
        for keyword in AONAMI_CRITICAL_KEYWORDS
    ):
        return "critical"
    if any(keyword in text for text in texts for keyword in CRITICAL_KEYWORDS):
        return "critical"
    if any(keyword in text for text in texts for keyword in WARNING_KEYWORDS):
        return "warning"
    if any(keyword in text for text in texts for keyword in INFO_KEYWORDS):
        return "info"
    return "info"
