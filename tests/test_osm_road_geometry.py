from tools.location.get_hybrid_placeinfo import build_hybrid_result
from tools.location.osm_road_geometry import DEFAULT_MAX_DISTANCE_M, infer_osm_road_from_geometry, osm_road_geometry_candidates


def test_osm_geometry_keeps_mitsukuradori_success_case():
    inferred = infer_osm_road_from_geometry(35.166229, 136.897967)

    assert inferred["adopted_roadname"] == "三蔵通"
    assert inferred["osm_name"] == "三蔵通"
    assert float(inferred["distance_m"]) <= 10.0
    assert inferred["max_distance_m"] == DEFAULT_MAX_DISTANCE_M
    assert inferred["adopted"] is True


def test_osm_geometry_maps_osu_honmachi_case_without_monzencho_false_positive():
    inferred = infer_osm_road_from_geometry(35.160399, 136.901881)
    candidates = osm_road_geometry_candidates(35.160399, 136.901881, max_distance_m=200.0)

    assert inferred["adopted_roadname"] == "本町通"
    assert inferred["osm_name"] == "大須本通"
    assert float(inferred["distance_m"]) <= 5.0
    assert candidates[0]["name"] == "本町通"
    assert next(item for item in candidates if item["name"] == "門前町通")["distance_m"] > 100


def test_osm_geometry_threshold_prevents_unbounded_adoption():
    inferred = infer_osm_road_from_geometry(35.160399, 136.901881, max_distance_m=0.1)

    assert inferred["adopted_roadname"] == ""
    assert inferred["adopted"] is False
    assert inferred["reason"] == "No OSM road geometry within threshold"


def test_osm_geometry_no_local_data_returns_empty():
    inferred = infer_osm_road_from_geometry(35.300000, 136.700000)

    assert inferred["adopted_roadname"] == ""
    assert inferred["adopted"] is False


def test_hybrid_result_uses_osm_geometry_for_production_display():
    osm = {
        "lat": 35.160399,
        "lon": 136.901881,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.160399,
        "lon": 136.901881,
        "address": ["愛知県", "名古屋市中区", "大須", "３丁目"],
        "short_address": "中区大須3丁目",
        "roadname": "門前町通",
        "candidates": [{"name": "赤門通本町交差点", "category": "地点名", "score": 80.0}],
        "taxi_label": {"label": "赤門通本町交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["fallback_road_alias"]["adopted_roadname"] == "門前町通"
    assert result["road_alias"]["adopted_roadname"] == "本町通"
    assert result["road_alias"]["adoption_source"] == "osm_geometry"
    assert result["osm_road_geometry"]["adopted_roadname"] == "本町通"
    assert result["osm_road_geometry"]["osm_name"] == "大須本通"
    assert result["comparison"]["osm_geometry_road"] == "本町通"
    assert result["comparison"]["final_road"] == "本町通"
    assert result["comparison"]["final_road_source"] == "osm_geometry"
    assert result["display_lines"]["text"] == "📍 中区大須3丁目\n🛣️ 本町通\n🚥 赤門通本町交差点\n座標: 35.160399, 136.901881"


def test_single_direction_yahoo_intersection_uses_osm_geometry_when_available():
    osm = {
        "lat": 35.166229,
        "lon": 136.897967,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.166229,
        "lon": 136.897967,
        "address": ["愛知県", "名古屋市中区", "栄", "２丁目"],
        "short_address": "中区栄2丁目",
        "roadname": "",
        "candidates": [{"name": "三蔵交差点", "category": "地点名", "score": 80.0}],
        "taxi_label": {"label": "三蔵交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["fallback_road_alias"]["adopted_roadname"] == "三蔵通"
    assert result["road_alias"]["adopted_roadname"] == "三蔵通"
    assert result["road_alias"]["adoption_source"] == "osm_geometry"
    assert result["display_lines"]["text"] == "📍 中区栄2丁目\n🛣️ 三蔵通\n🚥 三蔵交差点\n座標: 35.166229, 136.897967"


def test_cross_road_yahoo_intersection_beats_osm_geometry():
    osm = {
        "lat": 35.160399,
        "lon": 136.901881,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.160399,
        "lon": 136.901881,
        "address": ["愛知県", "名古屋市中区", "大須", "３丁目"],
        "short_address": "中区大須3丁目",
        "roadname": "",
        "candidates": [{"name": "錦通大津交差点", "category": "地点名", "score": 80.0}],
        "taxi_label": {"label": "錦通大津交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["osm_road_geometry"]["adopted_roadname"] == "本町通"
    assert result["road_alias"]["adopted_roadname"] == "錦通 × 大津通"
    assert result["road_alias"]["adoption_source"] == "adopted_yahoo_intersection"


def test_hybrid_result_falls_back_when_osm_geometry_has_no_match():
    osm = {
        "lat": 35.0,
        "lon": 136.0,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中村区", "太閤", "１丁目"],
        "short_address": "中村区太閤1丁目",
        "roadname": "",
        "candidates": [{"name": "笹島交差点", "category": "地点名", "score": 50.0}],
        "taxi_label": {"label": "笹島交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["osm_road_geometry"]["adopted_roadname"] == ""
    assert result["road_alias"]["adopted_roadname"] == "広小路通 × 名駅通"
    assert result["road_alias"]["adoption_source"] == "adopted_yahoo_intersection"


def test_hybrid_result_falls_back_to_yahoo_roadname_when_osm_and_alias_are_empty():
    osm = {
        "lat": 35.0,
        "lon": 136.0,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "錦", "３丁目"],
        "short_address": "中区錦3丁目",
        "roadname": "伊勢町通り",
        "candidates": [{"name": "未登録交差点", "category": "地点名", "score": 50.0}],
        "taxi_label": {"label": "未登録交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["osm_road_geometry"]["adopted_roadname"] == ""
    assert result["road_alias"]["adopted_roadname"] == "伊勢町通"
    assert result["road_alias"]["adoption_source"] == "yahoo_roadname_fallback"


def test_single_direction_yahoo_intersection_without_osm_uses_yahoo_roadname_fallback():
    osm = {
        "lat": 35.0,
        "lon": 136.0,
        "candidates": [],
        "taxi_label": {},
    }
    yahoo = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "錦", "３丁目"],
        "short_address": "中区錦3丁目",
        "roadname": "伊勢町通り",
        "candidates": [{"name": "錦三丁目交差点", "category": "地点名", "score": 50.0}],
        "taxi_label": {"label": "錦三丁目交差点付近"},
    }

    result = build_hybrid_result(osm, yahoo)

    assert result["fallback_road_alias"]["adopted_roadname"] == "大津通"
    assert result["road_alias"]["adopted_roadname"] == "伊勢町通"
    assert result["road_alias"]["adoption_source"] == "yahoo_roadname_fallback"
