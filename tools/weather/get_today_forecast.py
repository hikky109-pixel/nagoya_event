#!/usr/bin/env python3
"""気象庁の名古屋向け今日・明日予報を取得する。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo


JMA_FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/230000.json"
JST = ZoneInfo("Asia/Tokyo")
REQUEST_TIMEOUT_SECONDS = 15
WESTERN_AICHI_CODE = "230010"
NAGOYA_CODE = "51106"


def fetch_forecast_json() -> Any:
    request = urllib.request.Request(JMA_FORECAST_URL, headers={"User-Agent": "nagoya-event-weather-beta/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_jma_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def _area_by_code(series: dict[str, Any], code: str) -> dict[str, Any]:
    areas = series.get("areas")
    if not isinstance(areas, list):
        return {}
    for area in areas:
        if not isinstance(area, dict):
            continue
        area_meta = area.get("area")
        if isinstance(area_meta, dict) and str(area_meta.get("code")) == code:
            return area
    return {}


def _date_key(value: Any) -> date | None:
    parsed = parse_jma_datetime(value)
    return parsed.date() if parsed is not None else None


def _value_for_date(time_defines: list[Any], values: Any, target_date: date) -> str:
    if not isinstance(values, list):
        return ""
    for index, time_define in enumerate(time_defines):
        if _date_key(time_define) == target_date:
            try:
                return str(values[index]).strip()
            except IndexError:
                return ""
    return ""


def _values_for_date(time_defines: list[Any], values: Any, target_date: date) -> list[str]:
    if not isinstance(values, list):
        return []
    matched: list[str] = []
    for index, time_define in enumerate(time_defines):
        if _date_key(time_define) != target_date:
            continue
        try:
            value = str(values[index]).strip()
        except IndexError:
            continue
        if value:
            matched.append(value)
    return matched


def _pops_for_date(time_defines: list[Any], values: Any, target_date: date) -> list[str]:
    if not isinstance(values, list):
        return []
    pops: list[str] = []
    for index, time_define in enumerate(time_defines):
        if _date_key(time_define) != target_date:
            continue
        try:
            pop = str(values[index]).strip()
        except IndexError:
            continue
        if pop:
            pops.append(f"{pop}%")
    return pops


def _normalize_weather(text: str) -> str:
    return " ".join(text.split())


def build_today_forecast(data: Any, now: datetime | None = None) -> dict[str, Any]:
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)

    if not isinstance(data, list) or not data:
        return {}

    short_term = data[0] if isinstance(data[0], dict) else {}
    weekly = data[1] if len(data) > 1 and isinstance(data[1], dict) else {}
    today = now.date()
    tomorrow = date.fromordinal(today.toordinal() + 1)

    result: dict[str, Any] = {
        "area": "名古屋",
        "source": "気象庁",
        "report_datetime": short_term.get("reportDatetime") or weekly.get("reportDatetime") or "",
        "today": {"date": today.isoformat()},
        "tomorrow": {"date": tomorrow.isoformat()},
    }

    short_series = short_term.get("timeSeries") if isinstance(short_term.get("timeSeries"), list) else []
    if len(short_series) >= 1 and isinstance(short_series[0], dict):
        weather_series = short_series[0]
        time_defines = weather_series.get("timeDefines") if isinstance(weather_series.get("timeDefines"), list) else []
        area = _area_by_code(weather_series, WESTERN_AICHI_CODE)
        result["today"]["weather"] = _normalize_weather(_value_for_date(time_defines, area.get("weathers"), today))
        result["tomorrow"]["weather"] = _normalize_weather(_value_for_date(time_defines, area.get("weathers"), tomorrow))

    if len(short_series) >= 2 and isinstance(short_series[1], dict):
        pop_series = short_series[1]
        time_defines = pop_series.get("timeDefines") if isinstance(pop_series.get("timeDefines"), list) else []
        area = _area_by_code(pop_series, WESTERN_AICHI_CODE)
        result["today"]["precipitation_probability"] = _pops_for_date(time_defines, area.get("pops"), today)
        result["tomorrow"]["precipitation_probability"] = _pops_for_date(time_defines, area.get("pops"), tomorrow)

    if len(short_series) >= 3 and isinstance(short_series[2], dict):
        temp_series = short_series[2]
        time_defines = temp_series.get("timeDefines") if isinstance(temp_series.get("timeDefines"), list) else []
        area = _area_by_code(temp_series, NAGOYA_CODE)
        for target_name, target_date in (("today", today), ("tomorrow", tomorrow)):
            temps = _values_for_date(time_defines, area.get("temps"), target_date)
            temps.extend(_values_for_date(time_defines, area.get("tempsMin"), target_date))
            temps.extend(_values_for_date(time_defines, area.get("tempsMax"), target_date))
            if temps:
                if len(temps) >= 2:
                    result[target_name]["min_temperature"] = f"{temps[0]}℃"
                    result[target_name]["max_temperature"] = f"{temps[1]}℃"
                else:
                    result[target_name]["temperature_values"] = [f"{value}℃" for value in temps]

    weekly_series = weekly.get("timeSeries") if isinstance(weekly.get("timeSeries"), list) else []
    if len(weekly_series) >= 1 and isinstance(weekly_series[0], dict):
        weekly_weather = weekly_series[0]
        time_defines = weekly_weather.get("timeDefines") if isinstance(weekly_weather.get("timeDefines"), list) else []
        area = _area_by_code(weekly_weather, "230000")
        tomorrow_pop = _value_for_date(time_defines, area.get("pops"), tomorrow)
        if tomorrow_pop and not result["tomorrow"].get("precipitation_probability"):
            result["tomorrow"]["precipitation_probability"] = [f"{tomorrow_pop}%"]

    if len(weekly_series) >= 2 and isinstance(weekly_series[1], dict):
        weekly_temp = weekly_series[1]
        time_defines = weekly_temp.get("timeDefines") if isinstance(weekly_temp.get("timeDefines"), list) else []
        area = _area_by_code(weekly_temp, NAGOYA_CODE)
        for target_name, target_date in (("today", today), ("tomorrow", tomorrow)):
            if result[target_name].get("temperature_values"):
                continue
            min_temp = _value_for_date(time_defines, area.get("tempsMin"), target_date)
            max_temp = _value_for_date(time_defines, area.get("tempsMax"), target_date)
            if min_temp:
                result[target_name]["min_temperature"] = f"{min_temp}℃"
            if max_temp:
                result[target_name]["max_temperature"] = f"{max_temp}℃"

    return result


def get_today_forecast(now: datetime | None = None) -> dict[str, Any]:
    try:
        return build_today_forecast(fetch_forecast_json(), now)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


if __name__ == "__main__":
    print(json.dumps(get_today_forecast(), ensure_ascii=False, indent=2))
