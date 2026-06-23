import json
import urllib.request
from typing import Any

URL = (
    "https://traininfo.jr-central.co.jp/"
    "zairaisen/data/trainInfo/json/unkou.json"
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def get_jrc_zairai_status(line_name=None):
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    data = json.loads(
        urllib.request.urlopen(req, timeout=15)
        .read()
        .decode("utf-8-sig")
    )

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
        return result.get(line_name)

    return result


if __name__ == "__main__":
    print(get_jrc_zairai_status())
