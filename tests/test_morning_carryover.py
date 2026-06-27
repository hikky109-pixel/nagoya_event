import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.railway_state import (  # noqa: E402
    load_railway_incident_first_seen,
    load_railway_state_metadata,
    morning_carryover_repost_candidates,
    morning_carryover_repost_allowed,
    save_railway_state,
    update_railway_incident_first_seen,
)


JST = timezone(timedelta(hours=9))
ALERT = "あおなみ線: 強風のため運転を見合わせています。"


def test_morning_carryover_allows_continuing_alert_once() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 5, tzinfo=JST),
        morning_reposted_date="",
        incident_first_seen_at={
            ALERT: "2026-06-25T23:00:00+09:00",
        },
        last_notify={},
    )

    assert allowed is True
    assert reason == "continuing_from_before_quiet_hours"


def test_morning_carryover_excludes_incident_first_seen_after_0500() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 55, tzinfo=JST),
        morning_reposted_date="",
        incident_first_seen_at={
            ALERT: "2026-06-26T05:01:00+09:00",
        },
        last_notify={},
    )

    assert allowed is False
    assert reason == "incident_started_after_quiet_hours"


def test_morning_carryover_includes_incident_first_seen_before_0500() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 55, tzinfo=JST),
        morning_reposted_date="",
        incident_first_seen_at={
            ALERT: "2026-06-26T04:59:59+09:00",
        },
        last_notify={},
    )

    assert allowed is True
    assert reason == "continuing_from_before_quiet_hours"


def test_morning_carryover_candidates_exclude_new_morning_incident() -> None:
    new_alert = "JR東海道線: 雨のため列車に遅れが発生しています。"
    candidates, reason = morning_carryover_repost_candidates(
        previous_alerts=[ALERT, new_alert],
        current_alerts=[ALERT, new_alert],
        now=datetime(2026, 6, 26, 5, 55, tzinfo=JST),
        morning_reposted_date="",
        incident_first_seen_at={
            ALERT: "2026-06-25T23:00:00+09:00",
            new_alert: "2026-06-26T05:01:00+09:00",
        },
        last_notify={},
    )

    assert candidates == [ALERT]
    assert reason == "continuing_from_before_quiet_hours"


def test_morning_carryover_suppresses_second_repost_same_day() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 10, tzinfo=JST),
        morning_reposted_date="2026-06-26",
        incident_first_seen_at={
            ALERT: "2026-06-25T23:00:00+09:00",
        },
        last_notify={},
    )

    assert allowed is False
    assert reason == "already_reposted_today"


def test_morning_carryover_suppresses_recent_normal_notification() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 10, tzinfo=JST),
        morning_reposted_date="",
        incident_first_seen_at={
            ALERT: "2026-06-25T23:00:00+09:00",
        },
        last_notify={
            "last_sent_at": datetime(2026, 6, 26, 5, 2, tzinfo=JST),
        },
    )

    assert allowed is False
    assert reason == "recent_normal_notification"


def test_morning_carryover_suppresses_outside_window() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 6, 0, tzinfo=JST),
        morning_reposted_date="",
        incident_first_seen_at={
            ALERT: "2026-06-25T23:00:00+09:00",
        },
        last_notify={},
    )

    assert allowed is False
    assert reason == "outside_morning_window"


def test_railway_state_persists_morning_reposted_date(tmp_path: Path) -> None:
    state_path = tmp_path / "railway_state.json"
    save_railway_state(
        state_path,
        [ALERT],
        datetime(2026, 6, 26, 5, 5, tzinfo=JST),
        morning_reposted_date="2026-06-26",
        incident_first_seen_at={
            ALERT: "2026-06-25T23:00:00+09:00",
        },
    )

    assert load_railway_state_metadata(state_path) == {
        "morning_reposted_date": "2026-06-26",
        "critical_transport_recovered_at": "",
    }
    assert load_railway_incident_first_seen(state_path) == {
        ALERT: "2026-06-25T23:00:00+09:00"
    }


def test_incident_first_seen_preserves_existing_and_stamps_new_alert() -> None:
    new_alert = "JR東海道線: 雨のため列車に遅れが発生しています。"
    first_seen = update_railway_incident_first_seen(
        [ALERT, new_alert],
        {ALERT: "2026-06-25T23:00:00+09:00"},
        datetime(2026, 6, 26, 5, 1, tzinfo=JST),
    )

    assert first_seen == {
        ALERT: "2026-06-25T23:00:00+09:00",
        new_alert: "2026-06-26T05:01:00+09:00",
    }


def test_legacy_state_without_first_seen_remains_readable(tmp_path: Path) -> None:
    state_path = tmp_path / "legacy_railway_state.json"
    state_path.write_text(
        '{"alerts":["' + ALERT + '"],"morning_reposted_date":"2026-06-25"}',
        encoding="utf-8",
    )

    assert load_railway_state_metadata(state_path) == {
        "morning_reposted_date": "2026-06-25",
        "critical_transport_recovered_at": "",
    }
    assert load_railway_incident_first_seen(state_path) == {}
