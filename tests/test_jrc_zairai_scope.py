import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ai import get_jrc_zairai_status as jrc_status  # noqa: E402
from tools.ai.jrc_zairai_targets import (  # noqa: E402
    jrc_line_id_from_display,
    jrc_target_line_display,
    jrc_target_line_key_by_id,
)


def _localized(name: str) -> list[dict[str, str]]:
    return [{"lang": "ja", "name": name}]


def _message(text: str) -> list[dict[str, str]]:
    return [{"lang": "ja", "message": text}]


def _event(no: str, line_name: str) -> dict[str, Any]:
    return {
        "no": no,
        "imp_line": _localized(line_name),
        "status_id": "0006",
        "status": _localized("遅れ"),
        "imp_sec_from": _localized(""),
        "imp_sec_to": _localized(""),
        "direction": _localized("上下線"),
        "cause": _localized("確認"),
        "accident_time": "06:40",
    }


def test_tokaido_atami_to_toyohashi_id_is_out_of_scope() -> None:
    assert jrc_line_id_from_display("東海道線(熱海～豊橋)") == "10011"
    assert jrc_target_line_key_by_id("10011") is None


def test_tokaido_toyohashi_to_maibara_id_is_in_scope() -> None:
    assert jrc_line_id_from_display("東海道線(豊橋～米原)") == "10001"
    assert jrc_target_line_key_by_id("10001") == "東海道線"


def test_10011_event_is_not_notified(monkeypatch) -> None:
    def fake_fetch_status_data() -> tuple[dict[str, Any], None]:
        return {
            "ono": "op-1",
            "events": [_event("1", "東海道線(熱海～豊橋)")],
            "message_info": [
                {"delivery_msg": _message("一部の列車に遅れが発生しています。")}
            ],
            "trans_info": [],
        }, None

    monkeypatch.setattr(jrc_status, "_fetch_status_data", fake_fetch_status_data)

    result, _updated_at, structured_events = jrc_status.get_jrc_zairai_status_details_snapshot()

    assert result == {}
    assert structured_events == []


def test_10001_event_is_notified(monkeypatch) -> None:
    def fake_fetch_status_data() -> tuple[dict[str, Any], None]:
        return {
            "ono": "op-1",
            "events": [_event("1", "東海道線(豊橋～米原)")],
            "message_info": [
                {"delivery_msg": _message("一部の列車に遅れが発生しています。")}
            ],
            "trans_info": [],
        }, None

    monkeypatch.setattr(jrc_status, "_fetch_status_data", fake_fetch_status_data)

    result, _updated_at, structured_events = jrc_status.get_jrc_zairai_status_details_snapshot()

    assert result == {"東海道線(豊橋～米原)": ["一部の列車に遅れが発生しています。"]}
    assert [event["line_id"] for event in structured_events] == ["10001"]


def test_chuo_line_display_is_plain_line_name() -> None:
    assert jrc_target_line_display("中央線(名古屋～中津川)") == "中央線"
