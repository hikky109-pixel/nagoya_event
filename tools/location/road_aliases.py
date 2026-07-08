"""Local road-name aliases sourced from static reference data."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROAD_ALIASES_PATH = ROOT / "data" / "location" / "road_aliases.yml"
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
ROADNAME_FALLBACK_BLOCK_WORDS = ("県道", "国道", "市道", "名古屋高速", "高速", "IC", "ＩＣ", "JCT", "ＪＣＴ", "インター")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        body = value[1:-1].strip()
        if not body:
            return []
        return [item.strip().strip("'\"") for item in body.split(",") if item.strip()]
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    return value


def load_road_aliases(path: Path = DEFAULT_ROAD_ALIASES_PATH) -> list[dict[str, Any]]:
    """Read the project-local road alias YAML without adding a dependency."""

    if not path.exists():
        return []
    roads: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped in {"version: 1", "roads:"}:
            continue
        if stripped.startswith("- "):
            if current:
                roads.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if stripped:
                key, _, value = stripped.partition(":")
                current[key.strip()] = _parse_scalar(value)
            continue
        if current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = _parse_scalar(value)
    if current:
        roads.append(current)
    return roads


def normalize_intersection_name(name: str) -> str:
    normalized = _text(name).translate(FULLWIDTH_DIGITS)
    for char in (" ", "　", "・", "‐", "-", "－"):
        normalized = normalized.replace(char, "")
    if normalized.endswith("交差点"):
        normalized = normalized[: -len("交差点")]
    return normalized


def match_road_aliases(intersection_name: str, *, path: Path = DEFAULT_ROAD_ALIASES_PATH) -> list[dict[str, Any]]:
    normalized = normalize_intersection_name(intersection_name)
    if not normalized:
        return []

    matches: list[dict[str, Any]] = []
    for road in load_road_aliases(path):
        intersections = road.get("intersections") if isinstance(road.get("intersections"), list) else []
        for intersection in intersections:
            if normalize_intersection_name(_text(intersection)) != normalized:
                continue
            matches.append(
                {
                    "id": _text(road.get("id")),
                    "name": _text(road.get("name")),
                    "direction": _text(road.get("direction")),
                    "aliases": road.get("aliases") if isinstance(road.get("aliases"), list) else [],
                    "matched_intersection": _text(intersection),
                    "source_url": _text(road.get("source_url")),
                    "reason": "intersection_exact_match",
                }
            )
            break
    return matches


def _candidate_name(candidate: dict[str, Any]) -> str:
    return _text(candidate.get("name") or candidate.get("label"))


def _is_yahoo_intersection(candidate: dict[str, Any]) -> bool:
    category = _text(candidate.get("category"))
    name = _candidate_name(candidate)
    return category == "地点名" and bool(name)


def _matches_yahoo_roadname(match: dict[str, Any], yahoo_roadname: str) -> bool:
    normalized = normalize_intersection_name(yahoo_roadname)
    if not normalized:
        return False
    names = {normalize_intersection_name(_text(match.get("name")))}
    names.update(normalize_intersection_name(_text(alias)) for alias in match.get("aliases", []))
    return normalized in names


def _choose_direction_match(matches: list[dict[str, Any]], yahoo_roadname: str) -> tuple[dict[str, Any] | None, str]:
    if not matches:
        return None, "候補なし"
    road_ids = {match["id"] for match in matches if match.get("id")}
    if len(road_ids) == 1:
        return matches[0], "単一道路候補を採用"
    roadname_matches = [match for match in matches if _matches_yahoo_roadname(match, yahoo_roadname)]
    if len(roadname_matches) == 1:
        return roadname_matches[0], "同方向の複数道路候補からYahoo roadname一致を採用"
    return None, "同方向の複数道路候補があり未確定"


def _canonical_yahoo_roadname(roadname: str) -> str:
    normalized = _text(roadname)
    if normalized.endswith("通り"):
        normalized = normalized[:-1]
    return normalized


def _yahoo_roadname_fallback(roadname: str) -> str:
    normalized = _canonical_yahoo_roadname(roadname)
    if not normalized:
        return ""
    if any(word in normalized for word in ROADNAME_FALLBACK_BLOCK_WORDS):
        return ""
    if not any(token in normalized for token in ("通", "線", "筋")):
        return ""
    return normalized


def _road_display_name(east_west: dict[str, Any] | None, north_south: dict[str, Any] | None) -> str:
    if east_west is not None and north_south is not None:
        return f"{_text(east_west.get('name'))} × {_text(north_south.get('name'))}"
    if east_west is not None:
        return _text(east_west.get("name"))
    if north_south is not None:
        return _text(north_south.get("name"))
    return ""


def _build_direction_result(matches: list[dict[str, Any]], yahoo_roadname: str) -> dict[str, Any]:
    by_direction = {
        "east_west": [match for match in matches if match.get("direction") == "east_west"],
        "north_south": [match for match in matches if match.get("direction") == "north_south"],
        "unknown": [match for match in matches if match.get("direction") not in {"east_west", "north_south"}],
    }
    east_west, east_west_reason = _choose_direction_match(by_direction["east_west"], yahoo_roadname)
    north_south, north_south_reason = _choose_direction_match(by_direction["north_south"], yahoo_roadname)
    display_name = _road_display_name(east_west, north_south)
    if east_west is not None and north_south is not None:
        reason = "同一Yahoo交差点から東西道路と南北道路を1本ずつ採用"
    elif display_name:
        reason = "同一Yahoo交差点から片方向の道路候補を採用"
    else:
        reason = "同一Yahoo交差点内で同方向の複数道路候補があり未確定"
    return {
        "road_alias_by_direction": by_direction,
        "east_west_road": east_west or {},
        "north_south_road": north_south or {},
        "direction_reasons": {
            "east_west": east_west_reason,
            "north_south": north_south_reason,
        },
        "road_display_name": display_name,
        "adopted_roadname": display_name,
        "reason": reason,
    }


def infer_road_alias_from_result(
    result: dict[str, Any],
    *,
    path: Path = DEFAULT_ROAD_ALIASES_PATH,
    adopted_intersection: str = "",
) -> dict[str, Any]:
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    intersections = [_candidate_name(candidate) for candidate in candidates if isinstance(candidate, dict) and _is_yahoo_intersection(candidate)]
    display_intersection = _text(adopted_intersection or result.get("display_intersection") or result.get("selected_intersection"))
    if not display_intersection and intersections:
        display_intersection = intersections[0]

    yahoo_roadname = _text(result.get("roadname"))
    road_matches: list[dict[str, Any]] = []
    intersection_groups: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for intersection in intersections:
        group_matches: list[dict[str, Any]] = []
        for match in match_road_aliases(intersection, path=path):
            key = (match["id"], match["matched_intersection"])
            if key in seen:
                continue
            seen.add(key)
            matched = {**match, "yahoo_intersection": intersection}
            road_matches.append(matched)
            group_matches.append(matched)
        if group_matches:
            intersection_groups.append({"yahoo_intersection": intersection, "matches": group_matches})

    selected_group = {"yahoo_intersection": display_intersection, "matches": []} if display_intersection else {}
    for group in intersection_groups:
        if normalize_intersection_name(_text(group.get("yahoo_intersection"))) == normalize_intersection_name(display_intersection):
            selected_group = group
            break

    selected_matches = selected_group.get("matches", []) if isinstance(selected_group, dict) else []
    direction_result = _build_direction_result(selected_matches, yahoo_roadname) if selected_matches else {}

    fallback_roadname = _yahoo_roadname_fallback(yahoo_roadname)
    if not direction_result and fallback_roadname:
        reason = "表示用交差点がroad_aliases.ymlに未登録のためYahoo roadnameを採用"
        direction_result = {
            "road_alias_by_direction": {"east_west": [], "north_south": [], "unknown": []},
            "east_west_road": {},
            "north_south_road": {},
            "direction_reasons": {"east_west": "候補なし", "north_south": "候補なし"},
            "road_display_name": fallback_roadname,
            "adopted_roadname": fallback_roadname,
            "reason": reason,
        }
    elif direction_result and not direction_result["adopted_roadname"] and fallback_roadname:
        selected_matches = selected_group.get("matches", []) if isinstance(selected_group, dict) else []
        direction_result["road_display_name"] = fallback_roadname
        direction_result["adopted_roadname"] = fallback_roadname
        direction_result["reason"] = "road_alias未確定のためYahoo roadnameを採用"
    else:
        if not direction_result:
            direction_result = {
                "road_alias_by_direction": {"east_west": [], "north_south": [], "unknown": []},
                "east_west_road": {},
                "north_south_road": {},
                "direction_reasons": {"east_west": "候補なし", "north_south": "候補なし"},
                "road_display_name": "",
                "adopted_roadname": "",
                "reason": "表示用交差点がroad_aliases.ymlに未登録",
            }

    return {
        "yahoo_roadname": yahoo_roadname,
        "yahoo_intersections": intersections,
        "selected_yahoo_intersection": _text(selected_group.get("yahoo_intersection")) if isinstance(selected_group, dict) else "",
        "road_alias_candidates": selected_matches,
        "all_road_alias_candidates": road_matches,
        **direction_result,
    }
