#!/usr/bin/env python3
"""天気ベータ候補を利用者向けアラートに正規化する。"""

from __future__ import annotations

from datetime import datetime

try:
    from get_jma_alerts import get_jma_weather_alerts, get_jma_weather_snapshot
    from get_open_meteo_alerts import get_open_meteo_alerts, get_open_meteo_snapshot
except ModuleNotFoundError:
    from tools.weather.get_jma_alerts import get_jma_weather_alerts, get_jma_weather_snapshot
    from tools.weather.get_open_meteo_alerts import get_open_meteo_alerts, get_open_meteo_snapshot


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


def get_all_weather_snapshot(now: datetime | None = None) -> dict:
    jma = get_jma_weather_snapshot(now)
    open_meteo = get_open_meteo_snapshot(now)
    raw_alerts: list[str] = []
    raw_alerts.extend(jma.get("alerts") if isinstance(jma.get("alerts"), list) else [])
    raw_alerts.extend(open_meteo.get("alerts") if isinstance(open_meteo.get("alerts"), list) else [])
    errors: list[dict[str, str]] = []
    errors.extend(jma.get("errors") if isinstance(jma.get("errors"), list) else [])
    errors.extend(open_meteo.get("errors") if isinstance(open_meteo.get("errors"), list) else [])
    return {
        "source": ["JMA", "Open-Meteo"],
        "raw_jma": jma.get("raw", {}),
        "raw_openmeteo": open_meteo.get("raw", {}),
        "normalized_alerts": public_weather_alerts(raw_alerts),
        "source_errors": errors,
        "sources": {
            "JMA": jma,
            "Open-Meteo": open_meteo,
        },
    }


if __name__ == "__main__":
    print(get_all_weather_alerts())
