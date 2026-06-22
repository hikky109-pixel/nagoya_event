import json
import urllib.request

URL = "https://www.kotsu.city.nagoya.jp/datas/latest_traffic.json"

LINES = {
    "H_LINE": "東山線",
    "M_LINE": "名城線・名港線",
    "T_LINE": "鶴舞線",
    "S_LINE": "桜通線",
    "K_LINE": "上飯田線",
}


def get_nagoya_subway_status(line_name=None, abnormal_only=False):
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    data = json.loads(
        urllib.request.urlopen(req, timeout=15)
        .read()
        .decode("utf-8-sig")
    )

    result = {}

    for item in data:
        rosen_id = item.get("rosen_id")

        if rosen_id not in LINES:
            continue

        current_line_name = LINES[rosen_id]
        status = item.get("traffic_title", "")
        message = item.get("traffic_message", "")
        section = item.get("traffic_section", "")
        cause = item.get("traffic_cause", "")

        if abnormal_only and status == "平常運行":
            continue

        result[current_line_name] = {
            "status": status,
            "message": message,
            "section": section,
            "cause": cause,
        }

    if line_name is not None:
        return result.get(line_name)

    return result


if __name__ == "__main__":
    print(get_nagoya_subway_status())