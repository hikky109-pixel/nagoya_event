import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.get_jrc_shinkansen_plan_notice import (  # noqa: E402
    EMPTY_SHA256,
    parse_plan_notice_payload,
)
from tools.ai.railway_state import (  # noqa: E402
    critical_transport_overnight_monitoring_active,
)
from tools.ai.run_gemma_ollama import (  # noqa: E402
    monitoring_public_railway_alerts,
    save_weather_debug,
    weather_change_type,
)


JST = timezone(timedelta(hours=9))


def test_critical_transport_continues_after_0100_when_incident_exists() -> None:
    active, reason = critical_transport_overnight_monitoring_active(
        now=datetime(2026, 6, 27, 1, 30, tzinfo=JST),
        previous_alerts=["名鉄 犬山線: 運転見合わせ / 犬山〜岩倉"],
    )

    assert active is True
    assert reason == "critical_transport_incident_continuing"


def test_critical_transport_stops_after_30_min_stable_recovery() -> None:
    active, reason = critical_transport_overnight_monitoring_active(
        now=datetime(2026, 6, 27, 1, 45, tzinfo=JST),
        previous_alerts=[],
        critical_transport_recovered_at="2026-06-27T01:10:00+09:00",
    )

    assert active is False
    assert reason == "overnight_no_critical_transport_incident"


def test_shinkansen_is_filtered_between_midnight_and_0500() -> None:
    alerts = monitoring_public_railway_alerts(
        [
            "東海道新幹線: 運転見合わせ",
            "JR東海在来線 東海道線: 遅延",
        ],
        datetime(2026, 6, 27, 0, 30, tzinfo=JST),
    )

    assert alerts == ["JR東海在来線 東海道線: 遅延"]


def test_plan_notice_empty_hash_is_not_available() -> None:
    result = parse_plan_notice_payload({"screen": {"message": ""}})

    assert result["content_hash"] == EMPTY_SHA256
    assert result["message_text"] == ""


def test_plan_notice_fallback_extracts_service_stop_message() -> None:
    result = parse_plan_notice_payload(
        {
            "service-stop": {
                "html": (
                    "計画運休について<br>"
                    "次回のお知らせは、６月２７日（土）５時００分頃を予定しています。"
                )
            }
        }
    )

    assert "計画運休" in result["message_text"]
    assert result["next_update_text"] == (
        "次回のお知らせは、６月２７日（土）５時００分頃を予定しています。"
    )


def test_weather_debug_records_suppression_reason(tmp_path: Path) -> None:
    snapshot = {
        "source": ["JMA", "Open-Meteo"],
        "raw_jma": {"warning": []},
        "raw_openmeteo": {"hourly": {}},
        "normalized_alerts": ["名古屋中心部で1時間以内に雨開始予測"],
        "source_errors": [],
    }

    result = save_weather_debug(
        snapshot,
        now=datetime(2026, 6, 27, 1, 30, tzinfo=JST),
        severity="weather_info",
        notify_allowed=False,
        suppress_reason="quiet_hours",
        debug_dir=tmp_path,
    )

    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "20260627_013000.json").exists()
    assert result["notify_allowed"] is False
    assert result["suppress_reason"] == "quiet_hours"
    assert result["suppressed_reason"] == "quiet_hours"
    assert len(result["hash"]) == 64


def test_weather_change_type_changed_no_change_removed() -> None:
    assert weather_change_type([], ["台風情報あり"]) == "changed"
    assert weather_change_type(["台風情報あり"], ["台風情報あり"]) == "no change"
    assert weather_change_type(["台風情報あり"], []) == "removed_silent"
