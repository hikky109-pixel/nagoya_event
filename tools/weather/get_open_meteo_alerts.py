#!/usr/bin/env python3
"""Open-Meteo から名古屋中心部の1時間以内天気変化を取得する。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
NAGOYA_LATITUDE = 35.1709
NAGOYA_LONGITUDE = 136.8815
REQUEST_TIMEOUT_SECONDS = 15
RAIN_THRESHOLD_MM = 0.1
PRECIP_TREND_THRESHOLD_MM = 0.1
LIGHT_RAIN_NOTIFY_THRESHOLD_MM = 0.5
HEAVY_RAIN_NOTIFY_THRESHOLD_MM = 10.0
TORRENTIAL_RAIN_NOTIFY_THRESHOLD_MM = 30.0


def open_meteo_url() -> str:
    query = urllib.parse.urlencode(
        {
            "latitude": NAGOYA_LATITUDE,
            "longitude": NAGOYA_LONGITUDE,
            "hourly": "precipitation,weather_code,snowfall",
            "timezone": "Asia/Tokyo",
            "forecast_days": 1,
            "past_days": 1,
        }
    )
    return f"https://api.open-meteo.com/v1/forecast?{query}"


def fetch_open_meteo() -> dict[str, Any]:
    request = urllib.request.Request(open_meteo_url(), headers={"User-Agent": "nagoya-event-weather-beta/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def parse_hour(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _number_at(values: list[Any], index: int) -> float:
    try:
        return float(values[index] or 0)
    except (IndexError, TypeError, ValueError):
        return 0.0


def _current_and_next_indices(times: list[Any], now: datetime) -> tuple[int, int] | None:
    parsed_times = [parse_hour(str(value)) for value in times]
    current_index: int | None = None
    for index, parsed in enumerate(parsed_times):
        if parsed is None:
            continue
        if parsed <= now:
            current_index = index
            continue
        if parsed <= now + timedelta(hours=1):
            return (current_index if current_index is not None else index, index)
        break
    if current_index is not None and current_index + 1 < len(parsed_times):
        return current_index, current_index + 1
    return None


def build_open_meteo_alerts(data: dict[str, Any], now: datetime | None = None) -> list[str]:
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)

    hourly = data.get("hourly")
    if not isinstance(hourly, dict):
        return []

    times = hourly.get("time")
    if not isinstance(times, list):
        return []

    indices = _current_and_next_indices(times, now)
    if indices is None:
        return []
    current_index, next_index = indices

    precipitation = hourly.get("precipitation") if isinstance(hourly.get("precipitation"), list) else []
    weather_codes = hourly.get("weather_code") if isinstance(hourly.get("weather_code"), list) else []
    snowfall = hourly.get("snowfall") if isinstance(hourly.get("snowfall"), list) else []

    current_rain = _number_at(precipitation, current_index)
    next_rain = _number_at(precipitation, next_index)
    current_snow = _number_at(snowfall, current_index)
    next_snow = _number_at(snowfall, next_index)
    next_weather_code = int(_number_at(weather_codes, next_index))

    alerts: list[str] = []
    if next_rain >= TORRENTIAL_RAIN_NOTIFY_THRESHOLD_MM:
        alerts.append(f"名古屋中心部で1時間以内に豪雨予測（{next_rain:g}mm/h）")
    elif next_rain >= HEAVY_RAIN_NOTIFY_THRESHOLD_MM:
        alerts.append(f"名古屋中心部で1時間以内に強雨予測（{next_rain:g}mm/h）")
    elif next_rain >= LIGHT_RAIN_NOTIFY_THRESHOLD_MM:
        alerts.append(f"名古屋中心部で1時間以内に小雨予測（{next_rain:g}mm/h）")

    if current_rain > 0 and next_rain <= 0:
        alerts.append("名古屋中心部の雨終了予測（1時間以内に0mm/h）")

    if current_rain < RAIN_THRESHOLD_MM <= next_rain:
        alerts.extend(
            [
                "名古屋中心部で1時間以内に雨開始予測",
                "錦・栄・名駅周辺で短距離需要が増える可能性",
            ]
        )
    elif current_rain >= RAIN_THRESHOLD_MM and next_rain < RAIN_THRESHOLD_MM:
        alerts.extend(
            [
                "名古屋中心部の雨は1時間以内に弱まる/止む可能性",
                "錦・栄周辺の雨需要ピークアウトに注意",
            ]
        )
    elif current_rain >= RAIN_THRESHOLD_MM or next_rain >= RAIN_THRESHOLD_MM:
        if next_rain - current_rain >= PRECIP_TREND_THRESHOLD_MM:
            alerts.append("名古屋中心部で1時間以内に雨が強まる可能性")
        elif current_rain - next_rain >= PRECIP_TREND_THRESHOLD_MM:
            alerts.append("名古屋中心部で1時間以内に雨が弱まる可能性")

    if 95 <= next_weather_code <= 99:
        alerts.append("名古屋中心部で1時間以内に雷の可能性")
    if current_snow > 0 or next_snow > 0:
        alerts.append("名古屋中心部で1時間以内に積雪・降雪の可能性")

    return list(dict.fromkeys(alerts))


def get_open_meteo_alerts(now: datetime | None = None) -> list[str]:
    try:
        return build_open_meteo_alerts(fetch_open_meteo(), now)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []


def get_open_meteo_snapshot(now: datetime | None = None) -> dict[str, Any]:
    try:
        raw = fetch_open_meteo()
        errors: list[dict[str, str]] = []
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raw = {}
        errors = [{"source": "Open-Meteo", "error": type(exc).__name__}]
    return {
        "source": "Open-Meteo",
        "raw": raw,
        "alerts": build_open_meteo_alerts(raw, now) if raw else [],
        "errors": errors,
    }


if __name__ == "__main__":
    print(get_open_meteo_alerts())
