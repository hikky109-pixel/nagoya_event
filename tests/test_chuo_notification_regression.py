import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.run_gemma_ollama import (  # noqa: E402
    build_railway_state_comment,
    log_zairai_notification_diagnostics,
)


JST = timezone(timedelta(hours=9))
PREVIOUS_ALERT = (
    "JR東海在来線 中央線: 折り返し列車の遅れのため、"
    "一部の列車に遅れが発生しています。"
)
CURRENT_ALERT = (
    "JR東海在来線 中央線: 勝川駅～春日井駅間で、"
    "踏切内で障害物を検知したため、一部の列車に遅れが発生しています。"
)


def _event(
    alert: str,
    *,
    cause: str,
    section_from: str = "",
    section_to: str = "",
) -> dict:
    message = alert.split(": ", 1)[1]
    return {
        "alert": alert,
        "incident_key": (
            f"中央線\x1f{cause}\x1f{section_from}\x1f{section_to}"
            "\x1f上下線\x1f"
        ),
        "line": "中央線",
        "status_id": "0006",
        "cause": cause,
        "section_from": section_from,
        "section_to": section_to,
        "direction": "上下線",
        "message": message,
        "prospect_time": "",
        "resume_time": "",
        "recover_message": "",
        "trans_info_started": False,
        "has_supplement_info": False,
    }


def test_chuo_new_cause_and_section_builds_new_discord_comment() -> None:
    previous_event = _event(PREVIOUS_ALERT, cause="折り返し列車の遅れ")
    current_event = _event(
        CURRENT_ALERT,
        cause="踏切内障害物",
        section_from="勝川",
        section_to="春日井",
    )

    comment, change_type, added, removed = build_railway_state_comment(
        True,
        [PREVIOUS_ALERT],
        [CURRENT_ALERT],
        checked_at=datetime(2026, 7, 30, 21, 54, tzinfo=JST),
        previous_zairai_events=[previous_event],
        current_zairai_events=[current_event],
    )

    assert change_type == "changed"
    assert added == [CURRENT_ALERT]
    assert removed == [PREVIOUS_ALERT]
    assert "勝川駅～春日井駅間" in comment
    assert "踏切内で障害物を検知" in comment


def test_chuo_diagnostics_logs_bodies_diff_and_notification(capsys) -> None:
    previous_event = _event(PREVIOUS_ALERT, cause="折り返し列車の遅れ")
    current_event = _event(
        CURRENT_ALERT,
        cause="踏切内障害物",
        section_from="勝川",
        section_to="春日井",
    )

    log_zairai_notification_diagnostics(
        [previous_event],
        [current_event],
        pre_notify_allowed=True,
        pre_notify_reason="official_incident_changed",
    )

    output = capsys.readouterr().out
    assert "railway_zairai_fetched_body: line=中央線" in output
    assert "railway_zairai_previous_body: line=中央線" in output
    assert "fields=cause,section_from,section_to,message" in output
    assert "railway_zairai_notification_target: line=中央線 accepted=true" in output
    assert "railway_zairai_not_notified_reason: line=中央線 reason=none" in output
