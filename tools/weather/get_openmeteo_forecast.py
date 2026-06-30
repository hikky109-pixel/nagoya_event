#!/usr/bin/env python3
"""Open-Meteoから名古屋駅の6時間天気予報を取得する。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
NAGOYA_STATION_LAT = 35.170915
NAGOYA_STATION_LON = 136.881537
JST = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = ROOT / "data" / "weather" / "openmeteo"
REQUEST_TIMEOUT_SECONDS = 15
TARGET_HOURS = {0, 6, 12, 18}


def now_jst() -> datetime:
    return datetime.now(JST)


def weather_code_label(code: int | None) -> str:
    if code is None:
        return "不明"
    if code == 0:
        return "晴れ"
    if 1 <= code <= 3:
        return "曇り"
    if code in {45, 48}:
        return "霧"
    if 51 <= code <= 67:
        return "雨"
    if 71 <= code <= 77:
        return "雪"
    if code >= 95:
        return "雷雨"
    return "曇り"


def save_raw_payload(payload: dict[str, Any], *, saved_at: datetime | None = None) -> Path:
    saved_at = saved_at or now_jst()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{saved_at:%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def openmeteo_url(*, hours: int) -> str:
    query = urllib.parse.urlencode(
        {
            "latitude": f"{NAGOYA_STATION_LAT:.6f}",
            "longitude": f"{NAGOYA_STATION_LON:.6f}",
            "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
            "forecast_hours": max(int(hours), 1),
            "timezone": "Asia/Tokyo",
        }
    )
    return f"{OPENMETEO_URL}?{query}"


def fetch_openmeteo_forecast(*, hours: int) -> dict[str, Any]:
    request = urllib.request.Request(openmeteo_url(hours=hours), headers={"User-Agent": "nagoya-event-openmeteo/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {"raw": payload}


def _list_at(values: Any, index: int) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_forecast(payload: dict[str, Any], *, hours: int, saved_at: datetime | None = None) -> dict[str, Any]:
    saved_at = saved_at or now_jst()
    raw_path = save_raw_payload(payload, saved_at=saved_at)
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    rows: list[dict[str, Any]] = []

    for index, value in enumerate(times):
        dt = _parse_time(value)
        if dt is None or dt.hour not in TARGET_HOURS:
            continue
        temp = _int_or_none(_list_at(hourly.get("temperature_2m"), index))
        precip = _int_or_none(_list_at(hourly.get("precipitation_probability"), index))
        code = _int_or_none(_list_at(hourly.get("weather_code"), index))
        wind = _float_or_none(_list_at(hourly.get("wind_speed_10m"), index))
        rows.append(
            {
                "time": dt.isoformat(timespec="minutes"),
                "label": f"{dt:%H:%M}",
                "temperature_2m": temp,
                "precipitation_probability": precip,
                "weather_code": code,
                "weather": weather_code_label(code),
                "wind_speed_10m": wind,
            }
        )
        if len(rows) >= 4:
            break

    return {
        "source": "Open-Meteo",
        "area": "名古屋駅",
        "lat": NAGOYA_STATION_LAT,
        "lon": NAGOYA_STATION_LON,
        "hours": hours,
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "forecast": rows,
    }


def get_openmeteo_forecast(*, hours: int = 24) -> dict[str, Any]:
    payload = fetch_openmeteo_forecast(hours=hours)
    return build_forecast(payload, hours=hours)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open-Meteoから名古屋駅の6時間天気予報を取得する。")
    parser.add_argument("--hours", type=int, default=24, help="取得する予報時間数。")
    parser.add_argument("--pretty", action="store_true", help="整形済みJSONを出力する。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = get_openmeteo_forecast(hours=args.hours)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
