#!/usr/bin/env python3
"""Yahoo天気APIから名古屋中心部の短時間降雨情報を取得する。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import YAHOO_CLIENT_ID  # noqa: E402


YAHOO_WEATHER_URL = "https://map.yahooapis.jp/weather/V1/place"
NAGOYA_LAT = 35.1815
NAGOYA_LON = 136.9066
REQUEST_TIMEOUT_SECONDS = 15
JST = ZoneInfo("Asia/Tokyo")
HEAVY_RAIN_THRESHOLD_MM = 5.0
TORRENTIAL_RAIN_THRESHOLD_MM = 10.0


def _empty_result(*, error: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": "YahooWeather",
        "rain_now": False,
        "max_precip_mm": 0.0,
        "heavy_rain": False,
        "thunder": False,
        "summary": "",
        "forecast_window_minutes": 60,
        "points": [],
    }
    if error:
        result["error"] = error
    return result


def _parse_yahoo_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%d%H%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=JST)
        return parsed.astimezone(JST)
    return None


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_yahoo_weather(client_id: str | None = None) -> dict[str, Any]:
    client_id = (client_id if client_id is not None else YAHOO_CLIENT_ID) or ""
    client_id = client_id.strip()
    if not client_id:
        return _empty_result(error="missing_yahoo_client_id")

    query = urllib.parse.urlencode(
        {
            "appid": client_id,
            "coordinates": f"{NAGOYA_LON},{NAGOYA_LAT}",
            "output": "json",
            "past": 2,
        }
    )
    request = urllib.request.Request(
        f"{YAHOO_WEATHER_URL}?{query}",
        headers={"User-Agent": "nagoya-event-weather-beta/1.0"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _weather_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    features = payload.get("Feature")
    if not isinstance(features, list) or not features:
        return []
    property_data = features[0].get("Property") if isinstance(features[0], dict) else {}
    weather_list = property_data.get("WeatherList") if isinstance(property_data, dict) else {}
    rows = weather_list.get("Weather") if isinstance(weather_list, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def build_yahoo_weather_snapshot(payload: Any, now: datetime | None = None) -> dict[str, Any]:
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)

    points: list[dict[str, Any]] = []
    forecast_points: list[dict[str, Any]] = []
    now_rain = 0.0
    forecast_until = now + timedelta(minutes=60)

    for row in _weather_rows(payload):
        timestamp = _parse_yahoo_datetime(row.get("Date"))
        rainfall = _float_value(row.get("Rainfall"))
        kind = str(row.get("Type") or "").strip()
        point = {
            "time": timestamp.isoformat(timespec="minutes") if timestamp else "",
            "type": kind,
            "rainfall": rainfall,
        }
        points.append(point)
        if kind == "observation" and timestamp and abs((timestamp - now).total_seconds()) <= 10 * 60:
            now_rain = max(now_rain, rainfall)
        if kind == "forecast" and timestamp and now <= timestamp <= forecast_until:
            forecast_points.append(point)

    max_precip = max([_float_value(point.get("rainfall")) for point in forecast_points] or [0.0])
    rain_now = now_rain > 0
    heavy_rain = max_precip > HEAVY_RAIN_THRESHOLD_MM
    if max_precip > TORRENTIAL_RAIN_THRESHOLD_MM:
        summary = "1時間以内に大雨の可能性"
    elif heavy_rain:
        summary = "1時間以内に強い雨の可能性"
    elif rain_now:
        summary = "名古屋中心部で雨を観測"
    else:
        summary = ""

    result = _empty_result()
    result.update(
        {
            "rain_now": rain_now,
            "max_precip_mm": max_precip,
            "heavy_rain": heavy_rain,
            "thunder": False,
            "summary": summary,
            "points": points,
        }
    )
    return result


def get_yahoo_weather_snapshot(now: datetime | None = None) -> dict[str, Any]:
    try:
        payload = fetch_yahoo_weather()
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return _empty_result(error=type(exc).__name__)
    return build_yahoo_weather_snapshot(payload, now)


def main() -> int:
    print(json.dumps(get_yahoo_weather_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
