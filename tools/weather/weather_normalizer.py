#!/usr/bin/env python3
"""天気ベータ候補を利用者向けアラートに正規化する。"""

from __future__ import annotations

from datetime import datetime

try:
    from get_jma_alerts import get_jma_weather_alerts, get_jma_weather_snapshot
    from get_yahoo_weather import get_yahoo_weather_snapshot
    # Lv14.4: Open-Meteo取得は天気速報βでは廃止方針。
    # 予報系の実験コードとして get_open_meteo_alerts.py は残置するが、
    # 通常の天気速報βには合流しない。
    # from get_open_meteo_alerts import get_open_meteo_alerts, get_open_meteo_snapshot
except ModuleNotFoundError:
    from tools.weather.get_jma_alerts import get_jma_weather_alerts, get_jma_weather_snapshot
    from tools.weather.get_yahoo_weather import get_yahoo_weather_snapshot
    # Lv14.4: Open-Meteo取得は天気速報βでは廃止方針。
    # from tools.weather.get_open_meteo_alerts import get_open_meteo_alerts, get_open_meteo_snapshot


WEATHER_BETA_EXCLUDE_MARKERS = (
    "取得失敗",
    "提供停止",
)
YAHOO_HEAVY_RAIN_THRESHOLD_MM = 5.0
YAHOO_TORRENTIAL_RAIN_THRESHOLD_MM = 10.0


def public_weather_alerts(alerts: list[str]) -> list[str]:
    public_alerts: list[str] = []
    for alert in alerts:
        text = " ".join(str(alert or "").split())
        if not text:
            continue
        if any(marker in text for marker in WEATHER_BETA_EXCLUDE_MARKERS):
            continue
        public_alerts.append(text)
    return list(dict.fromkeys(public_alerts))


def yahoo_weather_alerts(snapshot: dict) -> list[str]:
    max_precip = snapshot.get("max_precip_mm")
    try:
        max_precip_value = float(max_precip)
    except (TypeError, ValueError):
        max_precip_value = 0.0

    alerts: list[str] = []
    if max_precip_value > YAHOO_TORRENTIAL_RAIN_THRESHOLD_MM:
        alerts.append(f"⚠️ 大雨注意: 名古屋中心部で1時間以内に{max_precip_value:g}mm/h予測")
    elif max_precip_value > YAHOO_HEAVY_RAIN_THRESHOLD_MM:
        alerts.append(f"☔ 強雨注意: 名古屋中心部で1時間以内に{max_precip_value:g}mm/h予測")

    if snapshot.get("thunder"):
        alerts.append("⛈️ 雷注意: 名古屋中心部で雷情報あり")
    return alerts


def get_all_weather_alerts(now: datetime | None = None) -> list[str]:
    alerts: list[str] = []
    alerts.extend(get_jma_weather_alerts(now))
    alerts.extend(yahoo_weather_alerts(get_yahoo_weather_snapshot(now)))
    # Lv14.4: Open-Meteo alerts are intentionally disabled.
    # alerts.extend(get_open_meteo_alerts(now))
    return public_weather_alerts(alerts)


def get_all_weather_snapshot(now: datetime | None = None) -> dict:
    jma = get_jma_weather_snapshot(now)
    yahoo = get_yahoo_weather_snapshot(now)
    # Lv14.4: Open-Meteo snapshot is intentionally disabled.
    # open_meteo = get_open_meteo_snapshot(now)
    raw_alerts: list[str] = []
    raw_alerts.extend(jma.get("alerts") if isinstance(jma.get("alerts"), list) else [])
    raw_alerts.extend(yahoo_weather_alerts(yahoo))
    # raw_alerts.extend(open_meteo.get("alerts") if isinstance(open_meteo.get("alerts"), list) else [])
    errors: list[dict[str, str]] = []
    errors.extend(jma.get("errors") if isinstance(jma.get("errors"), list) else [])
    if yahoo.get("error"):
        errors.append({"source": "YahooWeather", "error": str(yahoo.get("error"))})
    # errors.extend(open_meteo.get("errors") if isinstance(open_meteo.get("errors"), list) else [])
    return {
        "source": ["JMA", "YahooWeather"],
        "raw_jma": jma.get("raw", {}),
        "raw_yahoo": yahoo,
        "raw_openmeteo": {},
        "normalized_alerts": public_weather_alerts(raw_alerts),
        "source_errors": errors,
        "sources": {
            "JMA": jma,
            "YahooWeather": yahoo,
            # "Open-Meteo": open_meteo,
        },
    }


if __name__ == "__main__":
    print(get_all_weather_alerts())
