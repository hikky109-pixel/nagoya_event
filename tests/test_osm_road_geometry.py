from tools.location.get_hybrid_placeinfo import build_hybrid_result
from tools.location.osm_road_geometry import infer_osm_road_from_geometry, osm_road_geometry_candidates


def test_osm_geometry_keeps_mitsukuradori_success_case():
    inferred = infer_osm_road_from_geometry(35.166229, 136.897967)

    assert inferred["adopted_roadname"] == "三蔵通"
    assert inferred["osm_name"] == "三蔵通"
    assert float(inferred["distance_m"]) <= 10.0


def test_osm_geometry_maps_osu_honmachi_case_without_monzencho_false_positive():
    inferred = infer_osm_road_from_geometry(35.160399, 136.901881)
    candidates = osm_road_geometry_candidates(35.160399, 136.901881, max_distance_m=200.0)

    assert inferred["adopted_roadname"] == "本町通"
    assert inferred["osm_name"] == "大須本通"
    assert float(inferred["distance_m"]) <= 5.0
    assert candidates[0]["name"] == "本町通"
    assert next(item for item in candidates if item["name"] == "門前町通")["distance_m"] > 100


def test_hybrid_result_exposes_osm_geometry_comparison_without_changing_display():
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

    assert result["road_alias"]["adopted_roadname"] == "門前町通"
    assert result["osm_road_geometry"]["adopted_roadname"] == "本町通"
    assert result["comparison"]["osm_geometry_road"] == "本町通"
    assert result["display_lines"]["text"] == "📍 中区大須3丁目\n🛣️ 門前町通\n🚥 赤門通本町交差点\n座標: 35.160399, 136.901881"
