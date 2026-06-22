#!/usr/bin/env python3
"""気象庁の警報・注意報と気象情報から名古屋向け天気ベータ候補を取得する。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


JMA_WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/230000.json"
JMA_INFORMATION_URL = "https://www.jma.go.jp/bosai/information/data/information.json"
JMA_TYPHOON_URL = "https://www.jma.go.jp/bosai/information/data/typhoon.json"
NAGOYA_CITY_CODE = "2310000"
AICHI_OFFICE_CODE = "230000"
TOKAI_CENTER_CODE = "010400"
REQUEST_TIMEOUT_SECONDS = 15
JST = ZoneInfo("Asia/Tokyo")
WARNING_FRESHNESS_HOURS = 12
TYPHOON_FRESHNESS_DAYS = 7

WARNING_CODE_NAMES = {
    "02": "暴風雪警報",
    "03": "大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "高潮警報",
    "10": "大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "18": "洪水注意報",
    "19": "高潮注意報",
    "20": "濃霧注意報",
    "26": "着雪注意報",
}
WEATHER_IMPACT_WARNING_NAMES = (
    "大雨",
    "洪水",
    "暴風",
    "大雪",
    "雷",
    "強風",
    "着雪",
)
SEVERE_INFORMATION_KEYWORDS = (
    "線状降水帯",
    "記録的短時間大雨",
)


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "nagoya-event-weather-beta/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _is_recent(value: Any, now: datetime, max_age: timedelta) -> bool:
    parsed = parse_datetime(value)
    if parsed is None:
        return False
    return now - max_age <= parsed <= now + timedelta(minutes=10)


def _warning_name(warning: dict[str, Any]) -> str:
    name = str(warning.get("name") or "").strip()
    if name:
        return name
    code = str(warning.get("code") or "").zfill(2)
    return WARNING_CODE_NAMES.get(code, "")


def _nagoya_warning_alerts(data: Any, now: datetime) -> list[str]:
    if not isinstance(data, dict):
        return []
    if not _is_recent(data.get("reportDatetime"), now, timedelta(hours=WARNING_FRESHNESS_HOURS)):
        return []

    for area_type in data.get("areaTypes", []):
        if not isinstance(area_type, dict):
            continue
        for area in area_type.get("areas", []):
            if not isinstance(area, dict) or str(area.get("code")) != NAGOYA_CITY_CODE:
                continue
            alerts: list[str] = []
            for warning in area.get("warnings", []):
                if not isinstance(warning, dict) or warning.get("status") != "発表":
                    continue
                name = _warning_name(warning)
                if not name or not any(keyword in name for keyword in WEATHER_IMPACT_WARNING_NAMES):
                    continue
                alerts.append(f"名古屋市に{name}が発表中")
            return alerts
    return []


def _is_relevant_area(item: dict[str, Any]) -> bool:
    area_codes = item.get("areaCodes")
    if not isinstance(area_codes, list):
        area_codes = [item.get("areaCode")]
    codes = {str(code) for code in area_codes if code is not None}
    return bool(codes & {AICHI_OFFICE_CODE, TOKAI_CENTER_CODE})


def _is_information_active(item: dict[str, Any], now: datetime) -> bool:
    valid = parse_datetime(item.get("valid") or item.get("validDatetime") or item.get("validMap"))
    if valid is not None:
        return valid >= now
    return _is_recent(item.get("reportDatetime") or item.get("datetime"), now, timedelta(hours=WARNING_FRESHNESS_HOURS))


def _severe_information_alerts(data: Any, now: datetime) -> list[str]:
    if not isinstance(data, list):
        return []

    alerts: list[str] = []
    for item in data:
        if not isinstance(item, dict) or not _is_relevant_area(item) or not _is_information_active(item, now):
            continue
        title = str(item.get("headTitle") or item.get("controlTitle") or "").strip()
        if not title:
            continue
        for keyword in SEVERE_INFORMATION_KEYWORDS:
            if keyword in title:
                alerts.append(f"東海・愛知周辺で{title}が発表中")
                break
    return alerts


def _typhoon_alerts(data: Any, now: datetime) -> list[str]:
    if not isinstance(data, list) or not data:
        return []

    active_titles: list[str] = []
    for item in data[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("headTitle") or "").strip()
        info_type = str(item.get("infoType") or "").strip()
        if title and info_type != "取消" and _is_recent(item.get("reportDatetime"), now, timedelta(days=TYPHOON_FRESHNESS_DAYS)):
            active_titles.append(title)

    if not active_titles:
        return []
    return [f"台風情報あり: {active_titles[0]}"]


def get_jma_weather_alerts(now: datetime | None = None) -> list[str]:
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)

    alerts: list[str] = []
    try:
        alerts.extend(_nagoya_warning_alerts(fetch_json(JMA_WARNING_URL), now))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass

    try:
        information = fetch_json(JMA_INFORMATION_URL)
        alerts.extend(_severe_information_alerts(information, now))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass

    try:
        alerts.extend(_typhoon_alerts(fetch_json(JMA_TYPHOON_URL), now))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass

    return list(dict.fromkeys(alerts))


if __name__ == "__main__":
    print(get_jma_weather_alerts())
