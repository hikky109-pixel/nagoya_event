#!/usr/bin/env python3
"""Classify weather beta alerts for concise notifications."""

from __future__ import annotations


WEATHER_CRITICAL_KEYWORDS = (
    "大雨警報",
    "線状降水帯",
    "記録的短時間大雨",
    "特別警報",
    "豪雨予測",
)
WEATHER_ALERT_KEYWORDS = (
    "雷注意",
    "雷の可能性",
    "強雨",
    "短時間強雨",
    "大雨注意報",
)
WEATHER_INFO_KEYWORDS = (
    "雨開始",
    "雨が降り始める",
    "雨が強まる可能性",
    "小雨予測",
    "雨終了予測",
)
WEATHER_MINOR_KEYWORDS = (
    "雨は1時間以内に弱まる",
    "雨は1時間以内に弱まる/止む",
    "雨が弱まる可能性",
    "雨需要ピークアウト",
)


def detect_weather_severity(alerts: list[str]) -> str:
    texts = [" ".join(str(alert or "").split()) for alert in alerts]
    if any(keyword in text for text in texts for keyword in WEATHER_CRITICAL_KEYWORDS):
        return "weather_critical"
    if any(keyword in text for text in texts for keyword in WEATHER_ALERT_KEYWORDS):
        return "weather_alert"
    if any(keyword in text for text in texts for keyword in WEATHER_INFO_KEYWORDS):
        return "weather_info"
    if texts and all(
        any(keyword in text for keyword in WEATHER_MINOR_KEYWORDS)
        for text in texts
    ):
        return "weather_minor"
    return "weather_info" if texts else "none"


def is_minor_weather(alerts: list[str]) -> bool:
    return detect_weather_severity(alerts) == "weather_minor"
