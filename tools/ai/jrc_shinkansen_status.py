import json
import urllib.request

BASE_URL = "https://traininfo.jr-central.co.jp/shinkansen/"
SERVICE_STOP_TEXT = "新幹線の運行情報のご提供を一時停止しております"


class ShinkansenServiceStop(Exception):
    pass


def _get_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ja,en-US;q=0.9",
            "Referer": "https://traininfo.jr-central.co.jp/shinkansen/pc/ja/index.html",
        },
    )
    text = urllib.request.urlopen(req, timeout=15).read().decode(
        "utf-8-sig", errors="replace"
    )
    stripped = text.lstrip("\ufeff").strip()
    if SERVICE_STOP_TEXT in text or stripped.startswith(("<!DOCTYPE html", "<html")):
        raise ShinkansenServiceStop
    return json.loads(stripped)


def get_jrc_shinkansen_status():
    try:
        service_json = _get_json(
            BASE_URL + "var/train_info/service_status.json"
        )
        page_fix_json = _get_json(
            BASE_URL + "common/data/ti01f_ja.json"
        )
        page_json = _get_json(
            BASE_URL + "var/train_info/ti01_ja.json"
        )
    except ShinkansenServiceStop:
        return {
            "status": "service_stop",
            "message": "新幹線運行情報提供停止",
        }

    info = service_json["serviceStatusInfo"]

    if info["serviceStatusIsEnabled"]:
        return {
            "status": "delay",
            "message": page_json["screen"].get("message"),
            "details": info["data"],
            "updated_at": info["datetime"],
        }

    return {
        "status": "normal",
        "message": page_fix_json["screen"]["normalStatusMessage"],
        "updated_at": info["datetime"],
    }


if __name__ == "__main__":
    print(get_jrc_shinkansen_status())
