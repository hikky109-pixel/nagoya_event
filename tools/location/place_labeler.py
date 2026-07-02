"""Taxi-driver oriented labels for Yahoo PlaceInfo results."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OVERRIDES_PATH = ROOT / "data" / "location" / "place_label_overrides.yml"

UNDERGROUND_WORDS = (
    "サカエチカ",
    "エスカ",
    "ユニモール",
    "地下",
    "地下街",
    "B1",
    "Ｂ１",
    "駅構内",
    "改札内",
    "階",
    "フロア",
    "館内",
    "ビル内",
    "店内",
    "石井スポーツ",
)

CONVENIENCE_CATEGORIES = {"ローソン", "ファミリーマート", "デイリーヤマザキ", "セブン-イレブン"}
LARGE_LANDMARK_WORDS = ("ショッピングセンター", "複合商業施設", "タワー", "百貨店")
STORE_PENALTY_CATEGORIES = {
    "その他のファミリーレストラン",
    "大型専門店（スポーツ・アウトドア）",
    "大型専門店（衣料品）",
}

NISHIKI_STREET_WORDS = (
    "袋町通",
    "七間町通",
    "伊勢町通",
    "伝馬町通",
    "住吉町通",
    "呉服町通",
    "木挽町通",
)

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_overrides(path: Path = DEFAULT_OVERRIDES_PATH) -> list[dict[str, Any]]:
    """Read the small project-local overrides YAML without adding a dependency."""

    if not path.exists():
        return []
    spots: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped in {"version: 1", "spots:"}:
            continue
        if stripped.startswith("- "):
            if current:
                spots.append(current)
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
        spots.append(current)
    return spots


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_override(lat: float, lon: float, *, path: Path = DEFAULT_OVERRIDES_PATH) -> dict[str, Any] | None:
    matches: list[tuple[float, dict[str, Any]]] = []
    for spot in load_overrides(path):
        spot_lat = _float(spot.get("lat"), default=999.0)
        spot_lon = _float(spot.get("lon"), default=999.0)
        radius = _float(spot.get("radius_m"), default=0.0)
        if radius <= 0:
            continue
        distance = distance_m(lat, lon, spot_lat, spot_lon)
        if distance <= radius:
            matches.append((distance, {**spot, "distance_m": round(distance, 1)}))
    if not matches:
        return None
    matches.sort(key=lambda item: (_float(item[1].get("priority"), 1000.0), item[0]))
    return matches[0][1]


def normalize_address(address_parts: Any) -> str:
    if not isinstance(address_parts, list):
        return ""
    parts = [_text(part) for part in address_parts]
    if len(parts) < 3:
        return ""
    town = parts[2]
    chome = parts[3].translate(FULLWIDTH_DIGITS) if len(parts) >= 4 else ""
    if town and "丁目" in chome:
        return f"{town}{chome}"
    return town


def candidate_kind(candidate: dict[str, Any]) -> str:
    name = _text(candidate.get("name"))
    category = _text(candidate.get("category"))
    if category == "地点名" and "交差点" in name:
        return "intersection"
    if category in CONVENIENCE_CATEGORIES:
        return "convenience"
    if "ホテル" in category:
        return "hotel"
    if any(word in category for word in LARGE_LANDMARK_WORDS):
        return "large_landmark"
    return "store"


def place_penalty(candidate: dict[str, Any]) -> float:
    text = " ".join(
        _text(candidate.get(key))
        for key in ("name", "label", "category", "where", "combined", "address")
    )
    penalty = 0.0
    if any(word in text for word in UNDERGROUND_WORDS):
        penalty += 80.0
    if _text(candidate.get("category")) in STORE_PENALTY_CATEGORIES:
        penalty += 20.0
    return penalty


def classify_zone(result: dict[str, Any], address_label: str) -> str:
    if address_label.startswith("錦3丁目"):
        return "nishiki_core"
    if address_label.startswith(("栄4丁目", "栄5丁目")):
        return "sakae_joshidai"
    if address_label.startswith(("金山5丁目", "平和2丁目")):
        return "suburban_intersection"
    return "default"


def rank_candidate(candidate: dict[str, Any], zone: str) -> float:
    kind = candidate_kind(candidate)
    if zone == "suburban_intersection":
        bonus = {
            "intersection": 120.0,
            "large_landmark": 60.0,
            "hotel": 25.0,
            "convenience": 10.0,
            "store": 0.0,
        }[kind]
    elif zone in {"nishiki_core", "sakae_joshidai"}:
        bonus = {
            "intersection": 70.0,
            "large_landmark": 65.0,
            "hotel": 35.0,
            "convenience": 25.0,
            "store": 0.0,
        }[kind]
    else:
        bonus = {
            "intersection": 80.0,
            "large_landmark": 60.0,
            "hotel": 40.0,
            "convenience": 30.0,
            "store": 10.0,
        }[kind]
    return _float(candidate.get("score")) + bonus - place_penalty(candidate)


def _intersection_label(name: str) -> str:
    name = _text(name)
    if not name:
        return ""
    if name.endswith("交差点"):
        return f"{name}付近"
    return f"{name}付近"


def _normalize_landmark(name: str) -> str:
    value = _text(name)
    if value == "SUNSHINE SAKAE":
        return "サンシャイン栄"
    return value


def _nishiki_street_from_candidate(candidate: dict[str, Any]) -> str:
    text = " ".join(_text(candidate.get(key)) for key in ("name", "label", "combined"))
    for street in NISHIKI_STREET_WORDS:
        if street in text:
            return street
    return ""


def _best_nishiki_convenience(candidates: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    matches: list[tuple[float, str, dict[str, Any]]] = []
    for candidate in candidates:
        if candidate_kind(candidate) != "convenience":
            continue
        street = _nishiki_street_from_candidate(candidate)
        if street:
            matches.append((_float(candidate.get("score")), street, candidate))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    _, street, candidate = matches[0]
    return street, candidate


def _label_result(label: str, source: str, zone: str, debug: dict[str, Any]) -> dict[str, Any]:
    label = _text(label) or "現在地付近"
    return {
        "label": label,
        "busy_label": f"{label}繁忙",
        "source": source,
        "zone": zone,
        "debug": debug,
    }


def build_taxi_place_label(result: dict[str, Any]) -> dict[str, Any]:
    lat = _float(result.get("lat"))
    lon = _float(result.get("lon"))
    address_parts = result.get("address") if isinstance(result.get("address"), list) else []
    address_label = normalize_address(address_parts)
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    candidates = [item for item in candidates if isinstance(item, dict)]
    zone = classify_zone(result, address_label)

    override = find_override(lat, lon)
    if override:
        return _label_result(
            _text(override.get("label")),
            "override",
            zone,
            {"override_id": override.get("id"), "distance_m": override.get("distance_m")},
        )

    roadname = _text(result.get("roadname"))
    if zone in {"nishiki_core", "sakae_joshidai"} and roadname:
        return _label_result(f"{address_label} {roadname}".strip(), "roadname", zone, {"roadname": roadname})

    if zone == "nishiki_core":
        nishiki_convenience = _best_nishiki_convenience(candidates)
        if nishiki_convenience is not None:
            street, convenience = nishiki_convenience
            return _label_result(
                f"{address_label} {street}（{_text(convenience.get('name'))}前）",
                "nishiki_convenience_street",
                zone,
                {"candidate": convenience.get("name"), "street": street},
            )

    ranked = sorted(
        candidates,
        key=lambda item: rank_candidate(item, zone),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    if best is None:
        return _label_result(address_label or "現在地付近", "address", zone, {})

    kind = candidate_kind(best)
    if kind == "intersection":
        return _label_result(_intersection_label(_text(best.get("name"))), "intersection", zone, _candidate_debug(best, zone))
    if kind == "large_landmark":
        label = _normalize_landmark(_text(best.get("name")))
        return _label_result(
            f"{address_label}（{label}付近）" if address_label else f"{label}付近",
            "large_landmark",
            zone,
            _candidate_debug(best, zone),
        )

    name = _text(best.get("name"))
    if address_label and name:
        label = f"{address_label} {name}付近"
    else:
        label = f"{name or '現在地'}付近"
    return _label_result(label, kind, zone, _candidate_debug(best, zone))


def _candidate_debug(candidate: dict[str, Any], zone: str) -> dict[str, Any]:
    return {
        "name": candidate.get("name"),
        "category": candidate.get("category"),
        "score": candidate.get("score"),
        "rank_score": round(rank_candidate(candidate, zone), 3),
        "penalty": place_penalty(candidate),
    }
