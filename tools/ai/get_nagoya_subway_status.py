import hashlib
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

URL = "https://www.kotsu.city.nagoya.jp/datas/latest_traffic.json"
ROOT = Path(__file__).resolve().parents[2]
DEBUG_DIR = ROOT / "data" / "debug" / "railway" / "subway"
JST = timezone(timedelta(hours=9), "JST")

LINES = {
    "H_LINE": "東山線",
    "M_LINE": "名城線・名港線",
    "T_LINE": "鶴舞線",
    "S_LINE": "桜通線",
    "K_LINE": "上飯田線",
}


def _content_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _history_path(debug_dir, now):
    base = debug_dir / f"{now:%Y%m%d_%H%M%S}.json"
    if not base.exists():
        return base
    for index in range(1, 100):
        candidate = debug_dir / f"{now:%Y%m%d_%H%M%S}_{index}.json"
        if not candidate.exists():
            return candidate
    return debug_dir / f"{now:%Y%m%d_%H%M%S}_{now.microsecond}.json"


def save_subway_debug_dump(raw_status_dict, abnormal_records, debug_dir=DEBUG_DIR, now=None):
    now = now or datetime.now(JST)
    debug_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "saved_at": now.isoformat(timespec="seconds"),
        "source_url": URL,
        "raw_status_dict": raw_status_dict,
        "abnormal_records": abnormal_records,
        "hash": _content_hash(
            {
                "raw_status_dict": raw_status_dict,
                "abnormal_records": abnormal_records,
            }
        ),
    }
    latest_path = debug_dir / "latest.json"
    history_path = _history_path(debug_dir, now)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
    latest_path.write_text(payload + "\n", encoding="utf-8")
    history_path.write_text(payload + "\n", encoding="utf-8")
    print(f"subway_debug_saved: latest={latest_path} history={history_path}")
    return snapshot


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
    abnormal_records = {}

    for item in data:
        rosen_id = item.get("rosen_id")

        if rosen_id not in LINES:
            continue

        current_line_name = LINES[rosen_id]
        status = item.get("traffic_title", "")
        message = item.get("traffic_message", "")
        section = item.get("traffic_section", "")
        cause = item.get("traffic_cause", "")

        record = {
            "status": status,
            "message": message,
            "section": section,
            "cause": cause,
        }
        result[current_line_name] = record
        if status != "平常運行":
            abnormal_records[current_line_name] = record

    try:
        save_subway_debug_dump(result, abnormal_records)
    except Exception as exc:
        print(f"subway_debug_save_failed: {exc}")

    if abnormal_only:
        result = abnormal_records

    if line_name is not None:
        return result.get(line_name)

    return result


if __name__ == "__main__":
    print(get_nagoya_subway_status())
