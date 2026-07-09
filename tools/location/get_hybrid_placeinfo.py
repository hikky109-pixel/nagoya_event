#!/usr/bin/env python3
"""Hybrid OSM + Yahoo PlaceInfo experiment."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.location.get_yahoo_placeinfo import get_yahoo_placeinfo  # noqa: E402
from tools.location.osm_road_geometry import build_final_road_alias, infer_osm_road_from_geometry  # noqa: E402
from tools.location.place_labeler import (  # noqa: E402
    build_placeinfo_display_lines,
    build_taxi_place_label,
    find_override,
    select_display_intersection_name,
)
from tools.location.road_aliases import infer_road_alias_from_result  # noqa: E402


LARGE_LANDMARK_NAMES = (
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
CHAIN_WORDS = ("ドン・キホーテ", "ドンキ", "アパホテル", "東横イン")
CONVENIENCE_WORDS = ("ローソン", "ファミリーマート", "セブン", "デイリーヤマザキ", "ミニストップ")
ROAD_WORDS = (
    "大津通",
    "伏見通",
    "広小路通",
    "錦通",
    "桜通",
    "若宮大通",
    "矢場町通",
    "畑江通",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _candidate_name(candidate: dict[str, Any]) -> str:
    return _text(candidate.get("name") or candidate.get("label"))


def _kind(candidate: dict[str, Any]) -> str:
    kind = _text(candidate.get("kind"))
    category = _text(candidate.get("category"))
    name = _candidate_name(candidate)
    text = f"{name} {category}"
    if kind:
        return kind
    if category == "地点名":
        return "intersection"
    if any(word in name for word in LARGE_LANDMARK_NAMES) and (
        any(name.startswith(word) for word in LARGE_LANDMARK_NAMES)
        or any(word in category for word in LARGE_LANDMARK_NAMES)
    ):
        return "large_landmark"
    if any(word in text for word in MAJOR_HOTEL_NAMES):
        return "major_hotel"
    if "駅" in name:
        return "station"
    if any(word in text for word in CHAIN_WORDS):
        return "chain"
    if category in {"ショッピングセンター・モール、複合商業施設", "タワー（テレビ塔）"}:
        return "large_landmark"
    if any(word in category for word in ("百貨店", "デパート", "複合商業施設", "ショッピングセンター")):
        return "large_landmark"
    if "ホテル" in category:
        return "hotel"
    if any(word in text for word in CONVENIENCE_WORDS):
        return "convenience"
    return "store"


def _candidate_score(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_rank(candidate: dict[str, Any]) -> float:
    name = _candidate_name(candidate)
    rank = _candidate_score(candidate)
    if any(name.startswith(word) for word in (*LARGE_LANDMARK_NAMES, *MAJOR_HOTEL_NAMES)):
        rank += 1000
    if "ビル" in name and not any(name.startswith(word) for word in (*LARGE_LANDMARK_NAMES, *MAJOR_HOTEL_NAMES)):
        rank -= 100
    return rank


def _with_source(candidate: dict[str, Any], source: str) -> dict[str, Any]:
    copied = dict(candidate)
    copied["source"] = source
    return copied


def _merge_candidates(osm: dict[str, Any], yahoo: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, result in (("OSM", osm), ("Yahoo", yahoo)):
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            name = _candidate_name(candidate)
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(_with_source(candidate, source))
            if len(merged) >= limit:
                return merged
    return merged


def _best_candidate(candidates: list[dict[str, Any]], kinds: set[str]) -> dict[str, Any] | None:
    matches = [candidate for candidate in candidates if _kind(candidate) in kinds]
    if not matches:
        return None
    matches.sort(key=_candidate_rank, reverse=True)
    return matches[0]


def _landmark_label(candidate: dict[str, Any] | None) -> str:
    if candidate is None:
        return ""
    return _candidate_name(candidate)


def _road_hint_from_candidates(candidates: list[dict[str, Any]]) -> str:
    for candidate in candidates:
        if _kind(candidate) == "intersection":
            continue
        text = " ".join(_text(candidate.get(key)) for key in ("name", "label", "combined", "address", "where"))
        for road in ROAD_WORDS:
            if road in text:
                return road
    return ""


def _hybrid_label(osm: dict[str, Any], yahoo: dict[str, Any], merged_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    lat = float(osm.get("lat") or yahoo.get("lat") or 0)
    lon = float(osm.get("lon") or yahoo.get("lon") or 0)
    override = find_override(lat, lon)
    if override:
        label = _text(override.get("label"))
        return {
            "label": label,
            "busy_label": f"{label}繁忙",
            "source": "override",
            "debug": {"override_id": override.get("id"), "override_source": override.get("source")},
        }

    osm_road = _text(osm.get("roadname"))
    yahoo_candidates = [_with_source(candidate, "Yahoo") for candidate in yahoo.get("candidates", []) if isinstance(candidate, dict)]
    yahoo_intersection = _best_candidate(yahoo_candidates, {"intersection"})
    if yahoo_intersection is not None:
        name = _candidate_name(yahoo_intersection)
        label = f"{name}付近" if name.endswith("交差点") else f"{name}交差点付近"
        return {
            "label": label,
            "busy_label": f"{label}繁忙",
            "source": "yahoo_intersection",
            "debug": {"candidate": name},
        }

    yahoo_landmark = _best_candidate(yahoo_candidates, {"large_landmark", "major_hotel"})
    if yahoo_landmark is not None:
        name = _candidate_name(yahoo_landmark)
        label = f"{name}付近"
        return {
            "label": label,
            "busy_label": f"{label}繁忙",
            "source": "yahoo_landmark",
            "debug": {"candidate": name},
        }

    yahoo_label = _text((yahoo.get("taxi_label") or {}).get("label"))
    if yahoo_label:
        return {"label": yahoo_label, "busy_label": f"{yahoo_label}繁忙", "source": "yahoo_label"}

    road_hint = _road_hint_from_candidates(yahoo_candidates)
    if road_hint:
        label = f"{road_hint}付近"
        return {"label": label, "busy_label": f"{label}繁忙", "source": "yahoo_road_hint"}

    if osm_road:
        label = f"{osm_road}付近"
        return {"label": label, "busy_label": f"{label}繁忙", "source": "osm_road_low_priority"}

    label = _text((osm.get("taxi_label") or {}).get("label")) or "現在地付近"
    return {"label": label, "busy_label": f"{label}繁忙", "source": "fallback"}


def build_hybrid_result(osm: dict[str, Any], yahoo: dict[str, Any]) -> dict[str, Any]:
    # Keep the legacy shape, but do not use OSM candidates for the user-facing display.
    merged_candidates = [_with_source(candidate, "Yahoo") for candidate in yahoo.get("candidates", []) if isinstance(candidate, dict)]
    result = {
        "source": "YahooPrimaryPlaceInfo",
        "lat": yahoo.get("lat", osm.get("lat")),
        "lon": yahoo.get("lon", osm.get("lon")),
        "area": "hybrid",
        "saved_at": yahoo.get("saved_at") or osm.get("saved_at"),
        "raw_path": yahoo.get("raw_path") or osm.get("raw_path", ""),
        "address": yahoo.get("address") or [],
        "short_address": yahoo.get("short_address") or osm.get("short_address") or "",
        "roadname": yahoo.get("roadname") or "",
        "place_area": yahoo.get("place_area") or [],
        "candidates": merged_candidates,
        "taxi_label": {},
        "display_lines": {},
        "osm_result": osm,
        "yahoo_result": yahoo,
        "comparison": {
            "osm_label": (osm.get("taxi_label") or {}).get("label", ""),
            "yahoo_label": (yahoo.get("taxi_label") or {}).get("label", ""),
        },
        "error": osm.get("error") or yahoo.get("error", ""),
    }
    result["display_intersection"] = select_display_intersection_name(result)
    try:
        result["osm_road_geometry"] = infer_osm_road_from_geometry(float(result["lat"]), float(result["lon"]))
    except (TypeError, ValueError):
        result["osm_road_geometry"] = {
            "source": "OSMRoadGeometry",
            "adopted_roadname": "",
            "reason": "Invalid coordinates",
            "adopted": False,
            "candidates": [],
        }
    result["fallback_road_alias"] = infer_road_alias_from_result(result, adopted_intersection=result["display_intersection"])
    result["road_alias"] = build_final_road_alias(result["osm_road_geometry"], result["fallback_road_alias"])
    result["taxi_label"] = _hybrid_label(osm, yahoo, merged_candidates)
    result["display_lines"] = build_placeinfo_display_lines(result)
    result["comparison"]["hybrid_label"] = result["taxi_label"].get("label", "")
    result["comparison"]["osm_geometry_road"] = result["osm_road_geometry"].get("adopted_roadname", "")
    result["comparison"]["final_road"] = result["road_alias"].get("adopted_roadname", "")
    result["comparison"]["final_road_source"] = result["road_alias"].get("adoption_source", "")
    # Keep the existing labeler output for comparison when all candidates are merged.
    result["comparison"]["merged_labeler_label"] = build_taxi_place_label(result).get("label", "")
    return result


def get_hybrid_placeinfo(lat: float, lon: float, *, area: str = "hybrid") -> dict[str, Any]:
    osm: dict[str, Any] = {
        "source": "OSMDisabled",
        "lat": lat,
        "lon": lon,
        "candidates": [],
        "taxi_label": {},
        "error": "",
    }
    yahoo = get_yahoo_placeinfo(lat, lon, area=f"{area}_yahoo")
    return build_hybrid_result(osm, yahoo)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OSM + Yahoo PlaceInfoハイブリッド検証。")
    parser.add_argument("--lat", type=float, required=True, help="緯度。")
    parser.add_argument("--lon", type=float, required=True, help="経度。")
    parser.add_argument("--area", default="hybrid", help="保存ファイル名に使う地点ラベル。")
    parser.add_argument("--pretty", action="store_true", help="整形済みJSONを標準出力する。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = get_hybrid_placeinfo(args.lat, args.lon, area=args.area)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
