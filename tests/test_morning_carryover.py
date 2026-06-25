import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.railway_state import (  # noqa: E402
    load_railway_state_metadata,
    morning_carryover_repost_allowed,
    save_railway_state,
)


JST = timezone(timedelta(hours=9))
ALERT = "あおなみ線: 強風のため運転を見合わせています。"


def test_morning_carryover_allows_continuing_alert_once() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 5, tzinfo=JST),
        morning_reposted_date="",
        last_notify={},
    )

    assert allowed is True
    assert reason == "continuing_abnormal_after_quiet_hours"


def test_morning_carryover_suppresses_second_repost_same_day() -> None:
    allowed, reason = morning_carryover_repost_allowed(
        previous_alerts=[ALERT],
        current_alerts=[ALERT],
        now=datetime(2026, 6, 26, 5, 10, tzinfo=JST),
        morning_reposted_date="2026-06-26",
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
    )

    assert load_railway_state_metadata(state_path) == {
        "morning_reposted_date": "2026-06-26"
    }
