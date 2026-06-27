import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.weather_severity import detect_weather_severity, is_minor_weather  # noqa: E402
from tools.weather.get_open_meteo_alerts import build_open_meteo_alerts  # noqa: E402


JST = timezone(timedelta(hours=9))


def _weather(current: float, next_hour: float) -> dict:
    return {
        "hourly": {
            "time": ["2026-06-28T09:00", "2026-06-28T10:00"],
            "precipitation": [current, next_hour],
            "weather_code": [3, 3],
            "snowfall": [0, 0],
        }
    }


def test_open_meteo_light_rain_threshold_alert() -> None:
    alerts = build_open_meteo_alerts(
        _weather(0, 0.5),
        datetime(2026, 6, 28, 9, 30, tzinfo=JST),
    )

    assert "名古屋中心部で1時間以内に小雨予測（0.5mm/h）" in alerts
    assert detect_weather_severity(alerts) == "weather_info"


def test_open_meteo_heavy_rain_threshold_alert() -> None:
    alerts = build_open_meteo_alerts(
        _weather(1, 10),
        datetime(2026, 6, 28, 9, 30, tzinfo=JST),
    )

    assert "名古屋中心部で1時間以内に強雨予測（10mm/h）" in alerts
    assert detect_weather_severity(alerts) == "weather_alert"


def test_open_meteo_torrential_rain_threshold_alert() -> None:
    alerts = build_open_meteo_alerts(
        _weather(10, 30),
        datetime(2026, 6, 28, 9, 30, tzinfo=JST),
    )

    assert "名古屋中心部で1時間以内に豪雨予測（30mm/h）" in alerts
    assert detect_weather_severity(alerts) == "weather_critical"


def test_open_meteo_rain_end_alert_is_not_minor_suppressed() -> None:
    alerts = build_open_meteo_alerts(
        _weather(1, 0),
        datetime(2026, 6, 28, 9, 30, tzinfo=JST),
    )

    assert "名古屋中心部の雨終了予測（1時間以内に0mm/h）" in alerts
    assert is_minor_weather(alerts) is False
