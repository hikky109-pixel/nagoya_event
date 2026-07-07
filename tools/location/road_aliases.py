"""Local road-name aliases sourced from static reference data."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROAD_ALIASES_PATH = ROOT / "data" / "location" / "road_aliases.yml"
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


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


def infer_road_alias_from_result(result: dict[str, Any], *, path: Path = DEFAULT_ROAD_ALIASES_PATH) -> dict[str, Any]:
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    intersections = [_candidate_name(candidate) for candidate in candidates if isinstance(candidate, dict) and _is_yahoo_intersection(candidate)]

    road_matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for intersection in intersections:
        for match in match_road_aliases(intersection, path=path):
            key = (match["id"], match["matched_intersection"])
            if key in seen:
                continue
            seen.add(key)
            road_matches.append({**match, "yahoo_intersection": intersection})

    road_ids = {match["id"] for match in road_matches if match.get("id")}
    adopted = road_matches[0]["name"] if len(road_ids) == 1 and road_matches else ""
    if not road_matches:
        reason = "Yahoo交差点名がroad_aliases.ymlに未登録"
    elif len(road_ids) == 1:
        reason = "Yahoo交差点名がroad_aliases.ymlのintersectionsに一致"
    else:
        reason = "複数道路に一致したため採用通り名は未確定"

    return {
        "yahoo_roadname": _text(result.get("roadname")),
        "yahoo_intersections": intersections,
        "road_alias_candidates": road_matches,
        "adopted_roadname": adopted,
        "reason": reason,
    }
