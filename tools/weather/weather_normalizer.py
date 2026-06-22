#!/usr/bin/env python3
"""天気ベータ候補を利用者向けアラートに正規化する。"""

from __future__ import annotations

from datetime import datetime

try:
    from get_jma_alerts import get_jma_weather_alerts
    from get_open_meteo_alerts import get_open_meteo_alerts
except ModuleNotFoundError:
    from tools.weather.get_jma_alerts import get_jma_weather_alerts
    from tools.weather.get_open_meteo_alerts import get_open_meteo_alerts


WEATHER_BETA_EXCLUDE_MARKERS = (
    "取得失敗",
    "提供停止",
)


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


def get_all_weather_alerts(now: datetime | None = None) -> list[str]:
    alerts: list[str] = []
    alerts.extend(get_jma_weather_alerts(now))
    alerts.extend(get_open_meteo_alerts(now))
    return public_weather_alerts(alerts)


if __name__ == "__main__":
    print(get_all_weather_alerts())
