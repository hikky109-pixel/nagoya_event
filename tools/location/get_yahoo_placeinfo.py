#!/usr/bin/env python3
"""Yahoo PlaceInfo APIで座標周辺のランドマーク候補を取得する。"""

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

from config import YAHOO_CLIENT_ID  # noqa: E402
from tools.location.place_labeler import build_placeinfo_display_lines, build_taxi_place_label, normalize_short_address  # noqa: E402


YAHOO_PLACEINFO_URL = "https://map.yahooapis.jp/placeinfo/V1/get"
REQUEST_TIMEOUT_SECONDS = 15
JST = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = ROOT / "data" / "location" / "placeinfo"


def now_jst() -> datetime:
    return datetime.now(JST)


def area_slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^0-9a-z_-]+", "_", text)
    return text.strip("_") or "point"


def save_raw_payload(payload: Any, *, area: str = "point", saved_at: datetime | None = None) -> Path:
    saved_at = saved_at or now_jst()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{saved_at:%Y%m%d_%H%M%S}_{area_slug(area)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def fetch_yahoo_placeinfo(lat: float, lon: float, client_id: str | None = None) -> dict[str, Any]:
    client_id = (client_id if client_id is not None else YAHOO_CLIENT_ID) or ""
    client_id = client_id.strip()
    if not client_id:
        return {"error": "missing_yahoo_client_id"}

    query = urllib.parse.urlencode(
        {
            "appid": client_id,
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "output": "json",
        }
    )
    request = urllib.request.Request(
        f"{YAHOO_PLACEINFO_URL}?{query}",
        headers={"User-Agent": "nagoya-event-placeinfo-alpha/1.0"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {"raw": data}


def _feature_name(feature: dict[str, Any]) -> str:
    for key in ("Name", "name", "Title", "title", "Label", "label"):
        value = feature.get(key)
        if str(value or "").strip():
            return str(value).strip()
    prop = feature.get("Property")
    if isinstance(prop, dict):
        for key in ("Name", "name", "Title", "title"):
            value = prop.get(key)
            if str(value or "").strip():
                return str(value).strip()
    return ""


def _feature_address(feature: dict[str, Any]) -> str:
    prop = feature.get("Property")
    candidates: list[Any] = []
    if isinstance(prop, dict):
        candidates.extend([prop.get("Address"), prop.get("address")])
    candidates.extend([feature.get("Address"), feature.get("address"), feature.get("Combined"), feature.get("Where")])
    for value in candidates:
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _feature_value(feature: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = feature.get(key)
        if value is not None:
            return value
    prop = feature.get("Property")
    if isinstance(prop, dict):
        for key in keys:
            value = prop.get(key)
            if value is not None:
                return value
    return None


def _feature_coordinates(feature: dict[str, Any]) -> tuple[float | None, float | None]:
    candidates = [
        feature.get("Geometry"),
        feature.get("geometry"),
        feature.get("Coordinates"),
        feature.get("coordinates"),
    ]
    prop = feature.get("Property")
    if isinstance(prop, dict):
        candidates.extend([prop.get("Geometry"), prop.get("geometry"), prop.get("Coordinates"), prop.get("coordinates")])
    for value in candidates:
        if isinstance(value, dict):
            value = value.get("Coordinates") or value.get("coordinates")
        if isinstance(value, str) and "," in value:
            first, second = [part.strip() for part in value.split(",", 1)]
            try:
                lon = float(first)
                lat = float(second)
            except ValueError:
                continue
            return lat, lon
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                lon = float(value[0])
                lat = float(value[1])
            except (TypeError, ValueError):
                continue
            return lat, lon
    return None, None


def _score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result_set(payload: dict[str, Any]) -> dict[str, Any]:
    result_set = payload.get("ResultSet")
    return result_set if isinstance(result_set, dict) else {}


def _area_list(result_set: dict[str, Any]) -> list[dict[str, Any]]:
    area = result_set.get("Area")
    if not isinstance(area, list):
        return []
    return [item for item in area if isinstance(item, dict)]


def extract_candidates(payload: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    result_set = _result_set(payload)
    address = result_set.get("Address") if isinstance(result_set.get("Address"), list) else []
    roadname = result_set.get("Roadname")
    area = _area_list(result_set)
    features = payload.get("Feature")
    if not isinstance(features, list):
        result = result_set.get("Result")
        features = []
        if isinstance(result, list):
            features.extend(result)
        if area:
            features.extend(area)

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        name = _feature_name(feature)
        if not name or name in seen:
            continue
        seen.add(name)
        label = str(_feature_value(feature, "Label", "label") or "").strip()
        category = str(_feature_value(feature, "Category", "category") or "").strip()
        where = str(_feature_value(feature, "Where", "where") or "").strip()
        combined = str(_feature_value(feature, "Combined", "combined") or "").strip()
        uid = str(_feature_value(feature, "Uid", "uid", "Id", "id") or "").strip()
        candidate_lat, candidate_lon = _feature_coordinates(feature)
        candidates.append(
            {
                "name": name,
                "label": label,
                "category": category,
                "where": where,
                "combined": combined,
                "score": _score(_feature_value(feature, "Score", "score")),
                "uid": uid,
                "address": _feature_address(feature),
                "lat": candidate_lat,
                "lon": candidate_lon,
                "roadname": roadname,
                "area": area,
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def build_placeinfo_result(
    lat: float,
    lon: float,
    payload: dict[str, Any],
    *,
    area: str = "point",
    saved_at: datetime | None = None,
) -> dict[str, Any]:
    saved_at = saved_at or now_jst()
    raw_path = save_raw_payload(payload, area=area, saved_at=saved_at)
    result_set = _result_set(payload)
    address = result_set.get("Address") if isinstance(result_set.get("Address"), list) else []
    result = {
        "source": "YahooPlaceInfo",
        "area": area,
        "lat": lat,
        "lon": lon,
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "address": address,
        "short_address": normalize_short_address(address),
        "roadname": result_set.get("Roadname"),
        "place_area": _area_list(result_set),
        "candidates": extract_candidates(payload),
        "error": payload.get("error", ""),
    }
    result["taxi_label"] = build_taxi_place_label(result)
    result["display_lines"] = build_placeinfo_display_lines(result)
    return result


def get_yahoo_placeinfo(lat: float, lon: float, *, area: str = "point") -> dict[str, Any]:
    try:
        payload = fetch_yahoo_placeinfo(lat, lon)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        payload = {"error": type(exc).__name__}
    return build_placeinfo_result(lat, lon, payload, area=area)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yahoo PlaceInfo APIから近隣候補を取得する。")
    parser.add_argument("--lat", type=float, required=True, help="緯度。")
    parser.add_argument("--lon", type=float, required=True, help="経度。")
    parser.add_argument("--area", default="point", help="保存ファイル名に使う地点ラベル。")
    parser.add_argument("--raw", action="store_true", help="Yahoo APIのraw JSONを標準出力する。")
    parser.add_argument("--pretty", action="store_true", help="整形済みJSONを標準出力する。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = get_yahoo_placeinfo(args.lat, args.lon, area=args.area)
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
