from datetime import datetime, timezone

from tools.railway.railway_incident_manager import evaluate_event, load_state


NOW = datetime(2026, 7, 9, 21, 0, tzinfo=timezone.utc)


def shinkansen_event(**overrides):
    event = {
        "operator": "jrcentral",
        "line": "tokaido_shinkansen",
        "status": "active",
        "reason": "earthquake",
        "affected_section": "東京-新大阪",
        "message": "地震の影響により東京駅～新大阪駅間で遅れが発生しています。",
        "severity": "info",
        "max_delay_min": 20,
        "terminal_connection_risks": [],
    }
    event.update(overrides)
    return event


def test_first_incident_creates_id_and_notifies(tmp_path):
    state_path = tmp_path / "railway_incidents.json"

    result = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)

    assert result["should_notify"] is True
    assert result["reason"] == "created"
    assert result["incident_id"].startswith("jrcentral_tokaido_shinkansen_20260709_earthquake_")
    assert result["incident"]["notification_count"] == 1


def test_same_incident_same_content_is_suppressed(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)

    second = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)

    assert second["incident_id"] == first["incident_id"]
    assert second["should_notify"] is False
    assert second["reason"] == "no_meaningful_change"
    assert second["incident"]["notification_count"] == 1


def test_same_incident_minor_text_change_is_suppressed(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(message="地震の影響により遅れが発生しています。最大20分程度です。"), state_path=state_path, now=NOW)

    second = evaluate_event(
        shinkansen_event(message="地震の影響により遅れが発生しています。最大25分程度です。対象列車数：8"),
        state_path=state_path,
        now=NOW,
    )

    assert second["incident_id"] == first["incident_id"]
    assert second["should_notify"] is False
    assert second["reason"] == "no_meaningful_change"


def test_delay_crossing_thirty_minutes_notifies_same_incident(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(max_delay_min=20), state_path=state_path, now=NOW)

    second = evaluate_event(shinkansen_event(max_delay_min=35), state_path=state_path, now=NOW)

    assert second["incident_id"] == first["incident_id"]
    assert second["should_notify"] is True
    assert second["reason"] == "severity_increased"
    assert second["incident"]["max_delay_min"] == 35


def test_terminal_connection_risk_start_notifies_same_incident(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(max_delay_min=5), state_path=state_path, now=NOW)

    second = evaluate_event(
        shinkansen_event(
            max_delay_min=10,
            terminal_connection_risks=[
                {
                    "train_name": "ひかり",
                    "train_number": "669",
                    "direction": "down",
                    "delay_min": 10,
                    "risk_area": "名東方面",
                    "reason": "ひかり669号は名古屋23:49着想定。",
                }
            ],
        ),
        state_path=state_path,
        now=NOW,
    )

    assert second["incident_id"] == first["incident_id"]
    assert second["should_notify"] is True
    assert second["reason"] == "terminal_connection_risk_started"


def test_same_line_different_reason_creates_different_incident(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(reason="earthquake"), state_path=state_path, now=NOW)

    second = evaluate_event(shinkansen_event(reason="heavy_rain", message="雨規制により遅れが発生しています。"), state_path=state_path, now=NOW)

    assert second["incident_id"] != first["incident_id"]
    assert second["should_notify"] is True
    assert second["reason"] == "created"


def test_recovery_resolves_same_incident_and_notifies(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)

    recovered = evaluate_event(
        shinkansen_event(status="resolved", message="東海道新幹線は平常運転に戻りました。", max_delay_min=0),
        state_path=state_path,
        now=NOW,
    )

    assert recovered["incident_id"] == first["incident_id"]
    assert recovered["should_notify"] is True
    assert recovered["reason"] == "resolved"
    assert recovered["incident"]["status"] == "resolved"


def test_new_incident_after_recovery_gets_new_id(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    first = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)
    evaluate_event(shinkansen_event(status="resolved", max_delay_min=0), state_path=state_path, now=NOW)

    second = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)

    assert second["incident_id"] != first["incident_id"]
    assert second["incident_id"].endswith("_002")
    assert second["should_notify"] is True


def test_corrupt_state_is_treated_as_empty(tmp_path):
    state_path = tmp_path / "railway_incidents.json"
    state_path.write_text("{broken", encoding="utf-8")

    result = evaluate_event(shinkansen_event(), state_path=state_path, now=NOW)
    state = load_state(state_path)

    assert result["should_notify"] is True
    assert len(state["incidents"]) == 1
