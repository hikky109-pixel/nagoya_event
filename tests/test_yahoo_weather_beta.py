from datetime import datetime, timedelta, timezone

from tools.ai.weather_severity import detect_weather_severity
from tools.weather.get_yahoo_weather import build_yahoo_weather_snapshot
from tools.weather.weather_normalizer import yahoo_weather_alerts


JST = timezone(timedelta(hours=9))


def _payload(rainfall: float) -> dict:
    return {
        "Feature": [
            {
                "Property": {
                    "WeatherList": {
                        "Weather": [
                            {"Type": "observation", "Date": "202606300930", "Rainfall": 1.0},
                            {"Type": "forecast", "Date": "202606301000", "Rainfall": rainfall},
                        ]
                    }
                }
            }
        ]
    }


def test_build_yahoo_weather_snapshot_detects_heavy_rain() -> None:
    snapshot = build_yahoo_weather_snapshot(_payload(8.5), datetime(2026, 6, 30, 9, 30, tzinfo=JST))

    assert snapshot["rain_now"] is True
    assert snapshot["max_precip_mm"] == 8.5
    assert snapshot["heavy_rain"] is True
    assert snapshot["thunder"] is False
    assert snapshot["summary"] == "1時間以内に強い雨の可能性"


def test_yahoo_weather_alerts_apply_thresholds() -> None:
    heavy = yahoo_weather_alerts({"max_precip_mm": 5.1, "thunder": False})
    torrential = yahoo_weather_alerts({"max_precip_mm": 10.1, "thunder": False})
    thunder = yahoo_weather_alerts({"max_precip_mm": 0, "thunder": True})

    assert heavy == ["☔ 強雨注意: 名古屋中心部で1時間以内に5.1mm/h予測"]
    assert torrential == ["⚠️ 大雨注意: 名古屋中心部で1時間以内に10.1mm/h予測"]
    assert thunder == ["⛈️ 雷注意: 名古屋中心部で雷情報あり"]
    assert detect_weather_severity(torrential) == "weather_critical"
