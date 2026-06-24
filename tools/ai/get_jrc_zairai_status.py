import json
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

try:
    from jrc_zairai_targets import jrc_target_line_key
    from railway_debug_dump import save_railway_debug_dump
except ModuleNotFoundError:
    from tools.ai.jrc_zairai_targets import jrc_target_line_key
    from tools.ai.railway_debug_dump import save_railway_debug_dump

URL = (
    "https://traininfo.jr-central.co.jp/"
    "zairaisen/data/trainInfo/json/unkou.json"
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


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


def get_jrc_zairai_status_snapshot(line_name=None):
    data, updated_at = _fetch_status_data()

    result = {}

    events = data.get("events") or []
    message_infos = data.get("message_info") or []

    for event, message_info in zip(events, message_infos):
        current_line_name = next(
            (
                x["name"]
                for x in event.get("imp_line", []) or []
                if x["lang"] == "ja"
            ),
            None,
        )

        if not current_line_name:
            continue
        if jrc_target_line_key(current_line_name) is None:
            continue

        message = _clean_text(next(
            (
                x["message"]
                for x in message_info.get("delivery_msg", []) or []
                if x["lang"] == "ja"
            ),
            "",
        ))

        if not message:
            continue

        messages = result.setdefault(current_line_name, [])
        if message not in messages:
            messages.append(message)

    if line_name is not None:
        return result.get(line_name), updated_at

    return result, updated_at


def get_jrc_zairai_status(line_name=None):
    result, _updated_at = get_jrc_zairai_status_snapshot(line_name)
    return result


if __name__ == "__main__":
    print(get_jrc_zairai_status())
