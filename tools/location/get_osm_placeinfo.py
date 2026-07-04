#!/usr/bin/env python3
"""OSM Nominatim reverse geocoding for taxi-oriented place labels."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.location.place_labeler import build_taxi_place_label, normalize_short_address  # noqa: E402


NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
REQUEST_TIMEOUT_SECONDS = 15
JST = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = ROOT / "data" / "location" / "placeinfo"
USER_AGENT = "nagoya-event-osm-placeinfo/0.1 (https://github.com/hikky109-pixel/nagoya_event)"

ADDRESS_KEYS = (
    "road",
    "pedestrian",
    "neighbourhood",
    "suburb",
    "city_district",
    "quarter",
    "hamlet",
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "railway",
    "station",
    "building",
    "house_number",
)
KANJI_CHOME = {
    "一丁目": "1丁目",
    "二丁目": "2丁目",
    "三丁目": "3丁目",
    "四丁目": "4丁目",
    "五丁目": "5丁目",
    "六丁目": "6丁目",
    "七丁目": "7丁目",
    "八丁目": "8丁目",
    "九丁目": "9丁目",
}

LARGE_COMMERCIAL_NAMES = (
    "サンシャイン栄",
    "SUNSHINE SAKAE",
    "三越",
    "松坂屋",
    "ラシック",
    "LACHIC",
    "パルコ",
    "PARCO",
    "メルサ",
    "ミッドランドスクエア",
)
LANDMARK_NAMES = (
    "ザ・ランドマーク名古屋栄",
    "御園座",
    "IGアリーナ",
    "NGKスポーツアリーナ",
)
MAJOR_HOTEL_NAMES = (
    "ヒルトン名古屋",
    "名古屋観光ホテル",
    "名古屋東急ホテル",
    "名古屋キャッスル",
    "TIAD",
    "ホテルメルパルク名古屋",
    "コートヤード・バイ・マリオット名古屋",
    "名古屋マリオットアソシアホテル",
)
CONVENIENCE_WORDS = ("ローソン", "ファミリーマート", "セブン", "デイリーヤマザキ", "ミニストップ")


def now_jst() -> datetime:
    return datetime.now(JST)


def area_slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^0-9a-z_-]+", "_", text)
    return text.strip("_") or "point"


def save_raw_payload(payload: Any, *, area: str = "osm", saved_at: datetime | None = None) -> Path:
    saved_at = saved_at or now_jst()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{saved_at:%Y%m%d_%H%M%S}_{area_slug(area)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def fetch_osm_placeinfo(lat: float, lon: float) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "addressdetails": 1,
            "extratags": 1,
            "namedetails": 1,
            "zoom": 18,
            "accept-language": "ja",
        }
    )
    request = urllib.request.Request(
        f"{NOMINATIM_REVERSE_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {"raw": data}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_chome(value: str) -> str:
    for source, target in KANJI_CHOME.items():
        value = value.replace(source, target)
    return value


def _display_name(payload: dict[str, Any]) -> str:
    namedetails = payload.get("namedetails")
    if isinstance(namedetails, dict):
        for key in ("name:ja", "name", "official_name:ja", "official_name"):
            value = _text(namedetails.get(key))
            if value:
                return _normalize_chome(value)
    return _normalize_chome(_text(payload.get("name")) or _text(payload.get("display_name")).split(",", 1)[0].strip())


def _candidate_kind(name: str, osm_class: str, osm_type: str, address_key: str = "") -> str:
    text = f"{name} {osm_class} {osm_type} {address_key}"
    if "交差点" in name:
        return "intersection"
    if address_key in {"road", "pedestrian"} or osm_class == "highway":
        return "road"
    if any(word in text for word in LARGE_COMMERCIAL_NAMES):
        return "large_landmark"
    if any(word in text for word in LANDMARK_NAMES):
        return "large_landmark"
    if any(word in text for word in MAJOR_HOTEL_NAMES):
        return "major_hotel"
    if address_key in {"railway", "station"} or osm_class == "railway" or "駅" in name:
        return "station"
    if any(word in text for word in CONVENIENCE_WORDS):
        return "convenience"
    if address_key in {"shop", "amenity", "tourism", "leisure", "building"}:
        return "landmark"
    return "store"


def _candidate(
    *,
    name: str,
    kind: str,
    osm_class: str = "",
    osm_type: str = "",
    address_key: str = "",
    score: float = 0.0,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    return {
        "name": name,
        "label": name,
        "category": kind,
        "kind": kind,
        "where": address_key,
        "combined": _text(payload.get("display_name")),
        "score": score,
        "uid": f"{payload.get('osm_type', '')}:{payload.get('osm_id', '')}".strip(":"),
        "address": _text(payload.get("display_name")),
        "roadname": "",
        "area": [],
        "osm_class": osm_class,
        "osm_type": osm_type,
        "address_key": address_key,
    }


def extract_osm_address(payload: dict[str, Any]) -> dict[str, Any]:
    address = payload.get("address")
    return address if isinstance(address, dict) else {}


def osm_address_parts(address: dict[str, Any]) -> list[str]:
    city = _text(address.get("city")) or _text(address.get("town")) or _text(address.get("municipality"))
    ward = _text(address.get("city_district")) or _text(address.get("borough")) or _text(address.get("ward"))
    suburb = _text(address.get("suburb"))
    if not ward and suburb.endswith("区"):
        ward = suburb
    town = _text(address.get("neighbourhood")) or _text(address.get("quarter")) or (suburb if not suburb.endswith("区") else "") or _text(address.get("hamlet"))
    for source, target in KANJI_CHOME.items():
        town = town.replace(source, target)
    house_number = _text(address.get("house_number"))
    if city and ward and not ward.startswith(city):
        ward = f"{city}{ward}"
    parts = [_text(address.get("country")) or "日本", ward or city, town]
    if house_number:
        parts.append(house_number)
    return [part for part in parts if part]


def extract_candidates(payload: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    address = extract_osm_address(payload)
    osm_class = _text(payload.get("category"))
    osm_type = _text(payload.get("type"))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    main_name = _display_name(payload)
    if main_name:
        kind = _candidate_kind(main_name, osm_class, osm_type)
        candidates.append(_candidate(name=main_name, kind=kind, osm_class=osm_class, osm_type=osm_type, score=90.0, payload=payload))
        seen.add(main_name)

    for index, key in enumerate(ADDRESS_KEYS):
        value = _text(address.get(key))
        if not value:
            continue
        value = _normalize_chome(value)
        if value in seen:
            continue
        kind = _candidate_kind(value, "", "", key)
        candidates.append(_candidate(name=value, kind=kind, address_key=key, score=80.0 - index, payload=payload))
        seen.add(value)
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def build_placeinfo_result(
    lat: float,
    lon: float,
    payload: dict[str, Any],
    *,
    area: str = "osm",
    saved_at: datetime | None = None,
) -> dict[str, Any]:
    saved_at = saved_at or now_jst()
    raw_path = save_raw_payload(payload, area=area, saved_at=saved_at)
    address = extract_osm_address(payload)
    address_parts = osm_address_parts(address)
    roadname = _text(address.get("road")) or _text(address.get("pedestrian"))
    result = {
        "source": "OSMNominatim",
        "area": area,
        "lat": lat,
        "lon": lon,
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "address": address_parts,
        "short_address": normalize_short_address(address_parts),
        "roadname": roadname,
        "place_area": [],
        "candidates": extract_candidates(payload),
        "osm": {
            "place_id": payload.get("place_id"),
            "osm_type": payload.get("osm_type"),
            "osm_id": payload.get("osm_id"),
            "category": payload.get("category"),
            "type": payload.get("type"),
            "display_name": payload.get("display_name"),
            "address": address,
        },
        "error": payload.get("error", ""),
    }
    for candidate in result["candidates"]:
        if isinstance(candidate, dict):
            candidate["roadname"] = roadname
            candidate["area"] = result["place_area"]
    result["taxi_label"] = build_taxi_place_label(result)
    return result


def get_osm_placeinfo(lat: float, lon: float, *, area: str = "osm") -> dict[str, Any]:
    try:
        payload = fetch_osm_placeinfo(lat, lon)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        payload = {"error": type(exc).__name__}
    return build_placeinfo_result(lat, lon, payload, area=area)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OSM Nominatimから近隣候補を取得する。")
    parser.add_argument("--lat", type=float, required=True, help="緯度。")
    parser.add_argument("--lon", type=float, required=True, help="経度。")
    parser.add_argument("--area", default="osm", help="保存ファイル名に使う地点ラベル。")
    parser.add_argument("--raw", action="store_true", help="Nominatim raw JSONを標準出力する。")
    parser.add_argument("--pretty", action="store_true", help="整形済みJSONを標準出力する。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = get_osm_placeinfo(args.lat, args.lon, area=args.area)
    if args.raw:
        try:
            raw_payload = json.loads((ROOT / result["raw_path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, KeyError):
            raw_payload = {"error": "raw_read_failed"}
        print(json.dumps(raw_payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
