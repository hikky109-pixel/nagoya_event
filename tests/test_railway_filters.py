import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai.railway_filters import (  # noqa: E402
    classify_railway_pre_llm_notification,
    classify_shinkansen_change,
    classify_zairai_change,
)


def test_shinkansen_suppresses_rain_amount_only_update() -> None:
    previous = (
        "東海道新幹線: 運転見合わせのお知らせ "
        "徳山駅～新山口駅間での雨規制により運転を見合わせています。"
    )
    current = (
        "東海道新幹線: 運転見合わせのお知らせ "
        "徳山駅～新山口駅間での雨規制により運転を見合わせています。 "
        "過去１時間の雨量：４７ミリ"
    )

    assert classify_shinkansen_change(previous, current) == (
        False,
        "rain_amount_update",
    )


def test_shinkansen_notifies_new_suspension() -> None:
    previous = "東海道新幹線: 一部の上り列車に遅れが発生しています。"
    current = "東海道新幹線: 浜松駅～静岡駅間で運転を見合わせています。"

    assert classify_shinkansen_change(previous, current) == (
        True,
        "new_suspension",
    )


def test_shinkansen_notifies_tokaido_impact_start() -> None:
    previous = (
        "東海道新幹線: 徳山駅～新山口駅間での雨規制により、"
        "山陽新幹線の下り列車に遅れが発生しています。"
    )
    current = (
        "東海道新幹線: 徳山駅～新山口駅間での雨規制により、"
        "東海道新幹線の上り列車に遅れが発生しています。"
    )

    assert classify_shinkansen_change(previous, current) == (
        True,
        "tokaido_impact_started",
    )


def test_shinkansen_notifies_restart_estimate_major_change() -> None:
    previous = "東海道新幹線: 運転再開見込み時刻は１８時２５分頃です。"
    current = "東海道新幹線: 運転再開見込み時刻は１９時００分頃です。"

    assert classify_shinkansen_change(previous, current) == (
        True,
        "restart_estimate_major_change",
    )


def test_shinkansen_suppresses_ticket_update() -> None:
    current = "東海道新幹線: きっぷの払いもどしについてご案内します。"

    assert classify_shinkansen_change(None, current) == (
        False,
        "ticket_or_refund_update",
    )


def _zairai_event(**overrides):
    event = {
        "alert": "JR東海在来線 東海道線: 一部の列車に遅れがあります。",
        "incident_key": "東海道線\x1f非常ボタン\x1f南大高\x1f南大高\x1f上下線\x1f08:00",
        "status_id": "0006",
        "prospect_time": "",
        "resume_time": "",
        "trans_info_started": False,
        "message": "一部の列車に遅れがあります。",
        "recover_message": "",
        "has_supplement_info": False,
    }
    event.update(overrides)
    return event


def test_zairai_suppresses_delivery_message_only_change() -> None:
    previous = _zairai_event()
    current = _zairai_event(
        alert=(
            "JR東海在来線 東海道線: 一部の列車に遅れがあります。"
            "急病のお客様対応と判明しました。"
        ),
        message=(
            "一部の列車に遅れがあります。"
            "急病のお客様対応と判明しました。"
        ),
    )

    assert classify_zairai_change(
        current["alert"],
        [previous],
        [current],
    ) == (False, "delivery_message_only")


def test_zairai_notifies_status_worsening() -> None:
    previous = _zairai_event(status_id="0006")
    current = _zairai_event(
        alert="JR東海在来線 東海道線: 運転を見合わせています。",
        status_id="0001",
        message="運転を見合わせています。",
    )

    assert classify_zairai_change(
        current["alert"],
        [previous],
        [current],
    ) == (True, "status_worsened")


def test_zairai_notifies_first_prospect_time() -> None:
    previous = _zairai_event()
    current = _zairai_event(
        alert="JR東海在来線 東海道線: 運転再開は12時頃の見込みです。",
        prospect_time="12:00",
        message="運転再開は12時頃の見込みです。",
    )

    assert classify_zairai_change(
        current["alert"],
        [previous],
        [current],
    ) == (True, "prospect_time_first")


def test_railway_pre_llm_suppresses_animal_collision_only() -> None:
    alerts = ["JR東海在来線 東海道線(豊橋～米原): 醒ケ井駅付近で動物衝突のため、遅れが発生しています。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=[],
        current_alerts=alerts,
        current_official_hash="animal",
    ) == (False, "low_impact")


def test_railway_pre_llm_suppresses_turnback_delay_only() -> None:
    alerts = ["JR東海在来線 東海道線(豊橋～米原): 折り返し列車の遅れのため、遅れが発生しています。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=[],
        current_alerts=alerts,
        current_official_hash="turnback",
    ) == (False, "low_impact")


def test_railway_pre_llm_suppresses_animal_and_turnback_delay() -> None:
    alerts = [
        (
            "JR東海在来線 東海道線(豊橋～米原): 醒ケ井駅付近で動物衝突、"
            "折り返し列車の遅れにより、最大遅れ10分程度です。"
        )
    ]

    assert classify_railway_pre_llm_notification(
        previous_alerts=[],
        current_alerts=alerts,
        current_official_hash="animal-turnback",
    ) == (False, "low_impact")


def test_railway_pre_llm_suppresses_same_alerts_continuing() -> None:
    alerts = ["JR東海在来線 東海道線(豊橋～米原): 運転を見合わせています。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=alerts,
        current_alerts=alerts,
        previous_official_hash="same",
        current_official_hash="same",
    ) == (False, "no_official_change")


def test_railway_pre_llm_allows_suspension() -> None:
    alerts = ["JR東海在来線 東海道線(豊橋～米原): 運転見合わせが発生しています。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=[],
        current_alerts=alerts,
        current_official_hash="suspension",
    ) == (True, "major_incident")


def test_railway_pre_llm_allows_person_injury() -> None:
    alerts = ["名鉄 名古屋本線: 人身事故のため、運転を見合わせています。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=[],
        current_alerts=alerts,
        current_official_hash="person-injury",
    ) == (True, "major_incident")


def test_railway_pre_llm_silent_recovery_from_low_impact() -> None:
    previous = ["JR東海在来線 東海道線(豊橋～米原): 動物衝突のため、最大遅れ10分程度です。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=previous,
        current_alerts=[],
        previous_impact="low_impact",
    ) == (False, "recovered_silent")


def test_railway_pre_llm_allows_recovery_from_major() -> None:
    previous = ["JR東海在来線 東海道線(豊橋～米原): 運転見合わせが発生しています。"]

    assert classify_railway_pre_llm_notification(
        previous_alerts=previous,
        current_alerts=[],
        previous_impact="major",
    ) == (True, "major_recovered")
