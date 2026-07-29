import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.weather.get_open_meteo_alerts import (  # noqa: E402
    build_rain_transition_forecast,
)
from tools.weather.weather_state import (  # noqa: E402
    empty_rain_transition_component,
    evaluate_rain_transition,
)


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 30, 9, 0, tzinfo=JST)


def _forecast(*, current: bool, start: bool = False, end: bool = False) -> dict:
    return {
        "valid": True,
        "current_raining": current,
        "start_predicted_within_15m": start,
        "end_predicted_within_30m": end,
    }


def _initialized_state() -> dict:
    state, _messages, _logs = evaluate_rain_transition(
        empty_rain_transition_component(),
        _forecast(current=False),
        NOW,
    )
    return state


def test_start_predicted_within_15_minutes() -> None:
    state, messages, logs = evaluate_rain_transition(
        _initialized_state(),
        _forecast(current=False, start=True),
        NOW,
    )
    assert messages == ["🌧️ 15分以内に雨が降り始める見込みです"]
    assert state["start_notice_sent"] is True
    assert "rain_transition: start predicted within 15m" in logs


def test_no_start_when_next_15_minutes_are_dry() -> None:
    _state, messages, logs = evaluate_rain_transition(
        _initialized_state(),
        _forecast(current=False),
        NOW,
    )
    assert messages == []
    assert logs == ["rain_transition: no transition"]


def test_end_predicted_within_30_minutes() -> None:
    state = _initialized_state()
    state["rain_event_active"] = True
    state["rain_observed"] = True
    _state, messages, logs = evaluate_rain_transition(
        state,
        _forecast(current=True, end=True),
        NOW,
    )
    assert messages == ["🌤️ 30分以内に雨が止む見込みです"]
    assert "rain_transition: end predicted within 30m" in logs


def test_no_end_when_rain_continues_30_minutes() -> None:
    _state, messages, logs = evaluate_rain_transition(
        _initialized_state(),
        _forecast(current=True),
        NOW,
    )
    assert messages == []
    assert logs == ["rain_transition: no transition"]


def test_duplicate_start_is_suppressed() -> None:
    state = _initialized_state()
    state, first, _logs = evaluate_rain_transition(
        state, _forecast(current=False, start=True), NOW
    )
    _state, second, logs = evaluate_rain_transition(
        state, _forecast(current=False, start=True), NOW
    )
    assert first
    assert second == []
    assert "rain_transition: skipped duplicate start" in logs


def test_duplicate_end_is_suppressed() -> None:
    state = _initialized_state()
    state["rain_event_active"] = True
    state, first, _logs = evaluate_rain_transition(
        state, _forecast(current=True, end=True), NOW
    )
    _state, second, logs = evaluate_rain_transition(
        state, _forecast(current=True, end=True), NOW
    )
    assert first
    assert second == []
    assert "rain_transition: skipped duplicate end" in logs


def test_next_rain_event_can_send_start_again_after_confirmed_dry() -> None:
    state = _initialized_state()
    state, first, _logs = evaluate_rain_transition(
        state, _forecast(current=False, start=True), NOW
    )
    state, _messages, _logs = evaluate_rain_transition(
        state, _forecast(current=False), NOW
    )
    state, _messages, _logs = evaluate_rain_transition(
        state, _forecast(current=False), NOW
    )
    _state, second, _logs = evaluate_rain_transition(
        state, _forecast(current=False, start=True), NOW
    )
    assert first and second


def test_initial_startup_does_not_send_end_notice() -> None:
    state, messages, _logs = evaluate_rain_transition(
        empty_rain_transition_component(),
        _forecast(current=True, end=True),
        NOW,
    )
    assert messages == []
    assert state["rain_event_active"] is True


def test_missing_api_data_does_not_raise() -> None:
    state, messages, logs = evaluate_rain_transition(
        empty_rain_transition_component(),
        {"valid": False},
        NOW,
    )
    assert messages == []
    assert state["initialized"] is False
    assert logs == ["rain_transition: no transition reason=data_unavailable"]


def test_forecast_wobble_does_not_repeat_start_notice() -> None:
    state = _initialized_state()
    state, first, _logs = evaluate_rain_transition(
        state, _forecast(current=False, start=True), NOW
    )
    state, _messages, _logs = evaluate_rain_transition(
        state, _forecast(current=False), NOW
    )
    _state, repeated, logs = evaluate_rain_transition(
        state, _forecast(current=False, start=True), NOW
    )
    assert first
    assert repeated == []
    assert "rain_transition: skipped duplicate start" in logs


def test_minutely_parser_reuses_existing_rain_threshold_and_requires_dry_points() -> None:
    data = {
        "minutely_15": {
            "time": [
                "2026-07-30T09:00",
                "2026-07-30T09:15",
                "2026-07-30T09:30",
            ],
            "precipitation": [0.2, 0.0, 0.0],
        }
    }
    forecast = build_rain_transition_forecast(data, NOW)
    assert forecast["current_raining"] is True
    assert forecast["end_predicted_within_30m"] is True


def test_minutely_parser_confirms_dry_through_30_minutes_off_grid() -> None:
    data = {
        "minutely_15": {
            "time": [
                "2026-07-30T09:00",
                "2026-07-30T09:15",
                "2026-07-30T09:30",
                "2026-07-30T09:45",
            ],
            "precipitation": [0.2, 0.0, 0.0, 0.0],
        }
    }
    forecast = build_rain_transition_forecast(
        data,
        datetime(2026, 7, 30, 9, 7, tzinfo=JST),
    )
    assert forecast["end_predicted_within_30m"] is True
