import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.run_gemma_ollama import (  # noqa: E402
    build_railway_beta_comment,
    build_railway_change_comment,
    format_railway_current_time,
    is_minor_weather_only,
)


JST = timezone(timedelta(hours=9))
UTC = timezone.utc


def test_railway_current_time_omits_date_for_today_in_jst() -> None:
    assert format_railway_current_time(
        datetime(2026, 6, 26, 9, 30, tzinfo=JST),
        datetime(2026, 6, 26, 12, 0, tzinfo=JST),
    ) == "（09:30現在）"


def test_railway_current_time_includes_date_for_previous_day_in_jst() -> None:
    assert format_railway_current_time(
        datetime(2026, 6, 25, 9, 30, tzinfo=JST),
        datetime(2026, 6, 26, 5, 0, tzinfo=JST),
    ) == "（6月25日 09:30現在）"


def test_railway_current_time_compares_dates_after_jst_conversion() -> None:
    assert format_railway_current_time(
        datetime(2026, 6, 25, 23, 30, tzinfo=UTC),
        datetime(2026, 6, 26, 9, 0, tzinfo=JST),
    ) == "（08:30現在）"


def test_aonami_comment_includes_date_for_old_published_time() -> None:
    alert = "あおなみ線: 台風7号の状況によっては遅れが発生する恐れがあります。"
    comment = build_railway_beta_comment(
        [alert],
        checked_at=datetime(2026, 6, 26, 9, 0, tzinfo=JST),
        updated_at_by_alert={
            alert: datetime(2026, 6, 25, 9, 30, tzinfo=JST),
        },
    )

    assert "（6月25日 09:30現在）" in comment


def test_jrc_zairai_comment_keeps_time_only_for_today() -> None:
    alert = "JR東海在来線 東海道線: 一部の列車に遅れがあります。"
    comment = build_railway_beta_comment(
        [alert],
        checked_at=datetime(2026, 6, 26, 12, 0, tzinfo=JST),
        updated_at_by_alert={
            alert: datetime(2026, 6, 26, 9, 30, tzinfo=JST),
        },
    )

    assert "（09:30現在）" in comment
    assert "6月26日" not in comment


def test_shinkansen_change_comment_includes_date_for_old_update() -> None:
    alert = "東海道新幹線: 一部の上り列車に遅れが発生しています。"
    comment = build_railway_change_comment(
        [alert],
        [alert],
        checked_at=datetime(2026, 6, 26, 9, 0, tzinfo=JST),
        updated_at_by_alert={
            alert: datetime(2026, 6, 25, 23, 45, tzinfo=JST),
        },
    )

    assert "（6月25日 23:45現在）" in comment


def test_weather_minor_only_suppression_remains_enabled() -> None:
    assert is_minor_weather_only(
        [],
        ["雨は1時間以内に弱まる/止む"],
    ) is True
