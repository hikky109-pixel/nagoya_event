"""Experimental OSM geometry based road matching for Nagoya PlaceInfo."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from tools.location.road_aliases import load_road_aliases


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OSM_ROAD_GEOMETRIES_PATH = ROOT / "data" / "location" / "osm_road_geometries.yml"
DEFAULT_MAX_DISTANCE_M = 35.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_osm_road_geometries(path: Path = DEFAULT_OSM_ROAD_GEOMETRIES_PATH) -> list[dict[str, Any]]:
    """Load locally saved OSM way geometry records.

    This is intentionally static and offline. Fetching from Overpass/OSM API is a
    data preparation step, not part of GPS request handling.
    """

    return load_road_aliases(path)


def parse_osm_way_coordinates(geometry: str) -> list[dict[str, Any]]:
    """Parse the compact osm_way_coordinates=way:lat,lon;... format."""

    text = _text(geometry)
    prefix = "osm_way_coordinates="
    if text.startswith(prefix):
        text = text[len(prefix) :]
    ways: list[dict[str, Any]] = []
    for way_body in text.split("|"):
        way_body = way_body.strip()
        if not way_body or ":" not in way_body:
            continue
        way_id, _, coords_body = way_body.partition(":")
        points: list[tuple[float, float]] = []
        for pair in coords_body.split(";"):
            lat_text, _, lon_text = pair.partition(",")
            lat = _float(lat_text)
            lon = _float(lon_text)
            if lat is None or lon is None:
                continue
            points.append((lat, lon))
        if len(points) >= 2:
            ways.append({"way_id": way_id.strip(), "points": points})
    return ways


def _meters_per_degree(lat: float) -> tuple[float, float]:
    return 111_320.0, 111_320.0 * math.cos(math.radians(lat))


def distance_point_to_segment_m(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    """Approximate point-to-line-segment distance for city-scale geometry."""

    lat_m, lon_m = _meters_per_degree(point[0])
    px, py = point[1] * lon_m, point[0] * lat_m
    ax, ay = start[1] * lon_m, start[0] * lat_m
    bx, by = end[1] * lon_m, end[0] * lat_m
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    nearest_x = ax + t * dx
    nearest_y = ay + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def distance_to_osm_road_m(lat: float, lon: float, road: dict[str, Any]) -> tuple[float, str]:
    best_distance = float("inf")
    best_way_id = ""
    for way in parse_osm_way_coordinates(_text(road.get("geometry"))):
        points = way["points"]
        for start, end in zip(points, points[1:]):
            distance = distance_point_to_segment_m((lat, lon), start, end)
            if distance < best_distance:
                best_distance = distance
                best_way_id = _text(way.get("way_id"))
    return best_distance, best_way_id


def osm_road_geometry_candidates(
    lat: float,
    lon: float,
    *,
    path: Path = DEFAULT_OSM_ROAD_GEOMETRIES_PATH,
    max_distance_m: float | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for road in load_osm_road_geometries(path):
        distance, way_id = distance_to_osm_road_m(lat, lon, road)
        if not math.isfinite(distance):
            continue
        if max_distance_m is not None and distance > max_distance_m:
            continue
        rows.append(
            {
                "id": _text(road.get("id")),
                "name": _text(road.get("display_name") or road.get("name")),
                "osm_name": _text(road.get("osm_name") or road.get("name")),
                "distance_m": round(distance, 2),
                "way_id": way_id,
                "source": _text(road.get("source")),
                "source_url": _text(road.get("source_url")),
                "highway": _text(road.get("highway")),
                "note": _text(road.get("note")),
            }
        )
    rows.sort(key=lambda item: (float(item["distance_m"]), item["name"]))
    return rows


def infer_osm_road_from_geometry(
    lat: float,
    lon: float,
    *,
    path: Path = DEFAULT_OSM_ROAD_GEOMETRIES_PATH,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
) -> dict[str, Any]:
    candidates = osm_road_geometry_candidates(lat, lon, path=path, max_distance_m=max_distance_m)
    best = candidates[0] if candidates else {}
    return {
        "source": "OSMRoadGeometryExperiment",
        "adopted_roadname": _text(best.get("name")),
        "distance_m": best.get("distance_m", ""),
        "way_id": _text(best.get("way_id")),
        "osm_name": _text(best.get("osm_name")),
        "max_distance_m": max_distance_m,
        "candidates": candidates,
        "reason": "OSM geometry nearest road within threshold" if best else "No OSM road geometry within threshold",
    }
