import json
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

try:
    from jrc_zairai_targets import jrc_line_id_from_display, jrc_target_line_key_by_id
    from railway_debug_dump import save_railway_debug_dump
except ModuleNotFoundError:
    from tools.ai.jrc_zairai_targets import jrc_line_id_from_display, jrc_target_line_key_by_id
    from tools.ai.railway_debug_dump import save_railway_debug_dump

URL = (
    "https://traininfo.jr-central.co.jp/"
    "zairaisen/data/trainInfo/json/unkou.json"
)
# 暫定フック: JR側JSONに過去の台風起因イベントが残る場合だけ追加する。
# 2026-06-28確認時点では get_jrc_zairai_status_details_snapshot() は空で、
# 実台風イベントまで落とさないようデフォルトは空にしておく。
IGNORE_CAUSES: tuple[str, ...] = ()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _localized_value(
    values: Any,
    *,
    field: str = "name",
    language: str = "ja",
) -> str:
    if not isinstance(values, list):
        return ""
    for item in values:
        if isinstance(item, dict) and item.get("lang") == language:
            return _clean_text(item.get(field))
    return ""


def _incident_key(event: dict[str, Any]) -> str:
    parts = (
        _localized_value(event.get("imp_line")),
        _localized_value(event.get("cause")),
        _localized_value(event.get("imp_sec_from")),
        _localized_value(event.get("imp_sec_to")),
        _localized_value(event.get("direction")),
        _clean_text(event.get("accident_time")),
    )
    return "\x1f".join(parts)


def _is_ignored_cause(cause: str) -> bool:
    return any(pattern and pattern in cause for pattern in IGNORE_CAUSES)


def _structured_event(
    event: dict[str, Any],
    message_info: dict[str, Any],
    trans_info: list[Any],
    operation_no: str,
) -> dict[str, Any]:
    line = _localized_value(event.get("imp_line"))
    line_id = jrc_line_id_from_display(line)
    message = _localized_value(message_info.get("delivery_msg"), field="message")
    matching_trans_info = [
        item
        for item in trans_info
        if isinstance(item, dict) and str(item.get("eid") or "") == str(event.get("no") or "")
    ]
    alert = f"JR東海在来線 {line}: {message}" if line and message else ""
    return {
        "operation_no": operation_no,
        "event_no": _clean_text(event.get("no")),
        "incident_key": _incident_key(event),
        "line_id": line_id or "",
        "line": line,
        "status_id": _clean_text(event.get("status_id")),
        "status": _localized_value(event.get("status")),
        "cause": _localized_value(event.get("cause")),
        "section_from": _localized_value(event.get("imp_sec_from")),
        "section_to": _localized_value(event.get("imp_sec_to")),
        "direction": _localized_value(event.get("direction")),
        "accident_time": _clean_text(event.get("accident_time")),
        "prospect_time": _clean_text(event.get("prospect_time")),
        "resume_time": _clean_text(event.get("resume_time")),
        "recover_message": _clean_text(event.get("recover_message")),
        "has_supplement_info": bool(event.get("supplement_info")),
        "trans_info_started": bool(matching_trans_info),
        "message": message,
        "alert": alert,
    }


def _fetch_status_data() -> tuple[dict[str, Any], datetime | None]:
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        raw_text = response.read().decode("utf-8-sig")
        last_modified = response.headers.get("Last-Modified")
        final_url = response.geturl()
        status_code = response.status

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        save_railway_debug_dump(
            source="jr_central",
            request_url=URL,
            final_url=final_url,
            status_code=status_code,
            reason="parser_exception",
            html=raw_text,
            details={"error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    if not isinstance(data, dict) or "events" not in data or "message_info" not in data:
        save_railway_debug_dump(
            source="jr_central",
            request_url=URL,
            final_url=final_url,
            status_code=status_code,
            reason="unexpected_json_structure",
            html=raw_text,
            details={"top_level_keys": list(data) if isinstance(data, dict) else []},
        )

    updated_at = None
    if last_modified:
        try:
            updated_at = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            pass
    return data, updated_at


def get_jrc_zairai_status_details_snapshot(line_name=None):
    data, updated_at = _fetch_status_data()

    result = {}
    structured_events: list[dict[str, Any]] = []

    events = data.get("events") or []
    message_infos = data.get("message_info") or []
    trans_info = data.get("trans_info") or []
    operation_no = _clean_text(data.get("ono"))

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        message_info = (
            message_infos[index]
            if index < len(message_infos) and isinstance(message_infos[index], dict)
            else {}
        )
        current_line_name = _localized_value(event.get("imp_line"))

        if not current_line_name:
            continue
        line_id = jrc_line_id_from_display(current_line_name)
        if jrc_target_line_key_by_id(line_id) is None:
            continue

        structured = _structured_event(event, message_info, trans_info, operation_no)
        if _is_ignored_cause(str(structured.get("cause") or "")):
            continue
        structured_events.append(structured)
        message = structured["message"]

        if not message:
            continue

        messages = result.setdefault(current_line_name, [])
        if message not in messages:
            messages.append(message)

    if line_name is not None:
        filtered_events = [
            event for event in structured_events if event.get("line") == line_name
        ]
        return result.get(line_name), updated_at, filtered_events

    return result, updated_at, structured_events


def get_jrc_zairai_status_snapshot(line_name=None):
    result, updated_at, _structured_events = get_jrc_zairai_status_details_snapshot(line_name)
    return result, updated_at


def get_jrc_zairai_status(line_name=None):
    result, _updated_at = get_jrc_zairai_status_snapshot(line_name)
    return result


if __name__ == "__main__":
    print(get_jrc_zairai_status())
