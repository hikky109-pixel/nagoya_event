import json
from pathlib import Path

from tools.location.get_yahoo_placeinfo import extract_candidates
from tools.location.place_labeler import build_placeinfo_display_lines, build_taxi_place_label, normalize_short_address


ROOT = Path(__file__).resolve().parents[1]


def _result_from_raw(path: str, lat: float, lon: float) -> dict:
    payload = json.loads((ROOT / path).read_text(encoding="utf-8"))
    result_set = payload.get("ResultSet", {})
    return {
        "lat": lat,
        "lon": lon,
        "address": result_set.get("Address") or [],
        "roadname": result_set.get("Roadname"),
        "place_area": result_set.get("Area") or [],
        "candidates": extract_candidates(payload),
    }


def test_override_labels_for_ikeda_park_and_nishiki_odori_otsu():
    ikeda = _result_from_raw(
        "data/location/placeinfo/20260703_050110_ikeda_park.json",
        35.166337,
        136.912610,
    )
    otsu = _result_from_raw(
        "data/location/placeinfo/20260703_050110_nishiki_odori_otsu.json",
        35.169973,
        136.906720,
    )

    assert build_taxi_place_label(ikeda)["label"] == "栄4丁目 池田公園付近"
    assert build_taxi_place_label(otsu)["label"] == "錦通大津（サンシャイン栄付近）"


def test_seeded_major_landmark_and_hotel_overrides():
    cases = [
        (35.1673355, 136.8970318, "伏見通（御園座付近）"),
        (35.1639900, 136.9099183, "矢場町通（TIAD付近）"),
        (35.185363, 136.895871, "名古屋キャッスル付近"),
        (35.167543, 136.894610, "広小路伏見（ヒルトン名古屋付近）"),
        (35.1704487, 136.8830090, "名古屋駅（マリオットアソシア付近）"),
        (35.1698452, 136.8852305, "名駅4丁目（ミッドランドスクエア付近）"),
        (35.1650308, 136.9076450, "大津通（松坂屋名古屋店付近）"),
    ]

    for lat, lon, expected in cases:
        result = {"lat": lat, "lon": lon, "address": [], "roadname": "", "candidates": []}
        assert build_taxi_place_label(result)["label"] == expected


def test_seeded_taxi_operation_overrides():
    cases = [
        (35.171361, 136.883249, "名古屋駅 桜通口タクシーのりば"),
        (35.170062, 136.880962, "名古屋駅 太閤通口タクシーのりば"),
        (35.1439454, 136.9005594, "アスナル金山タクシーのりば"),
        (35.142328, 136.901075, "金山駅南口タクシーのりば"),
    ]

    for lat, lon, expected in cases:
        result = {"lat": lat, "lon": lon, "address": [], "roadname": "", "candidates": []}
        assert build_taxi_place_label(result)["label"] == expected


def test_suburban_intersections_are_preferred():
    shinonome = _result_from_raw(
        "data/location/placeinfo/20260703_050110_shinonomebashi_west.json",
        35.146791,
        136.910315,
    )
    mukaida = _result_from_raw(
        "data/location/placeinfo/20260703_050111_mukaidabashi_west.json",
        35.148124,
        136.909713,
    )

    assert build_taxi_place_label(shinonome)["label"] == "東雲橋西交差点付近"
    assert build_taxi_place_label(mukaida)["label"] == "向田橋西交差点付近"


def test_hataedori_synthetic_intersection_is_preferred():
    result = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中村区", "沖田町"],
        "roadname": "畑江通",
        "candidates": [
            {"name": "ケーズデンキ岩塚店", "category": "家電量販店", "score": 80.0},
            {"name": "畑江通八交差点", "category": "地点名", "score": 50.0},
        ],
    }

    label = build_taxi_place_label(result)
    assert label["label"] == "畑江通八交差点付近"
    assert label["supplement"] == "ケーズデンキ岩塚店近く"


def test_placeinfo_display_lines_use_yahoo_address_and_intersection_without_auto_landmark():
    result = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "栄", "３丁目"],
        "short_address": "中区栄3丁目",
        "roadname": "",
        "candidates": [
            {"name": "三蔵通久屋西", "category": "地点名", "score": 50.0},
            {"name": "ラシック", "category": "ショッピングセンター・モール、複合商業施設", "score": 80.0},
            {"name": "ローソン栄三丁目店", "category": "ローソン", "score": 99.0},
        ],
    }

    display = build_placeinfo_display_lines(result)

    assert display["text"] == "📍 中区栄3丁目\n🚥 三蔵通久屋西\n座標: 35.000000, 136.000000"
    assert display["debug"]["yahoo_landmark_auto_disabled"] is True


def test_placeinfo_display_lines_omit_weak_landmark_row():
    result = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "錦", "３丁目"],
        "short_address": "中区錦3丁目",
        "roadname": "桜通",
        "candidates": [
            {"name": "ローソン錦三丁目店", "category": "ローソン", "score": 99.0},
        ],
    }

    display = build_placeinfo_display_lines(result)

    assert display["text"] == "📍 中区錦3丁目\n座標: 35.000000, 136.000000"


def test_placeinfo_display_lines_do_not_use_intersection_as_landmark():
    result = {
        "lat": 35.158786,
        "lon": 136.856260,
        "address": ["愛知県", "名古屋市中村区", "沖田町", ""],
        "short_address": "中村区沖田町",
        "roadname": "",
        "candidates": [
            {"name": "畑江通八交差点", "category": "地点名", "score": 90.0},
            {"name": "鈍池町3交差点", "category": "地点名", "score": 80.0},
            {"name": "ケーズデンキ岩塚店", "category": "大型専門店（電化・家電）", "score": 70.0},
        ],
    }

    display = build_placeinfo_display_lines(result)

    assert display["landmark"] == ""
    assert "🏢 畑江通八交差点" not in display["text"]
    assert "🏢 ケーズデンキ岩塚店" not in display["text"]


def test_placeinfo_display_lines_do_not_auto_promote_nearby_yahoo_landmark():
    result = {
        "lat": 35.158786,
        "lon": 136.856260,
        "address": ["愛知県", "名古屋市中村区", "沖田町", ""],
        "short_address": "中村区沖田町",
        "roadname": "",
        "candidates": [
            {"name": "遠い大型店", "category": "大型専門店", "score": 99.0, "lat": 35.160000, "lon": 136.856260},
            {"name": "畑江通八交差点", "category": "地点名", "score": 90.0, "lat": 35.158786, "lon": 136.856260},
            {"name": "近い大型店", "category": "大型専門店", "score": 50.0, "lat": 35.158900, "lon": 136.856260},
        ],
    }

    display = build_placeinfo_display_lines(result)

    assert display["landmark"] == ""
    assert "近い大型店" not in display["text"]


def test_placeinfo_display_lines_show_dictionary_landmark_only():
    result = {
        "lat": 35.185363,
        "lon": 136.895871,
        "address": ["愛知県", "名古屋市西区", "樋の口町", ""],
        "short_address": "西区樋の口町",
        "roadname": "",
        "candidates": [
            {"name": "城西二丁目交差点", "category": "地点名", "score": 80.0},
            {"name": "エスパシオナゴヤキャッスル", "category": "ホテル", "score": 70.0},
        ],
        "taxi_label": {
            "label": "名古屋キャッスル付近",
            "source": "override",
            "debug": {"override_source": "seeded_landmark"},
        },
    }

    display = build_placeinfo_display_lines(result)

    assert display["text"] == "📍 西区樋の口町\n🚥 城西二丁目交差点\n🏢 名古屋キャッスル付近\n座標: 35.185363, 136.895871"


def test_placeinfo_display_lines_show_road_alias_before_intersection():
    result = {
        "lat": 35.168277,
        "lon": 136.897676,
        "address": ["愛知県", "名古屋市中区", "栄", "２丁目"],
        "short_address": "中区栄2丁目",
        "roadname": "広小路通",
        "road_alias": {"adopted_roadname": "広小路通"},
        "candidates": [{"name": "広小路伏見交差点", "category": "地点名", "score": 80.0}],
    }

    display = build_placeinfo_display_lines(result)

    assert display["text"] == "📍 中区栄2丁目\n🛣️ 広小路通\n🚥 広小路伏見交差点\n座標: 35.168277, 136.897676"


def test_roadname_is_used_when_intersection_is_missing():
    result = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中村区", "沖田町"],
        "roadname": "畑江通",
        "candidates": [
            {"name": "ケーズデンキ岩塚店", "category": "家電量販店", "score": 80.0},
            {"name": "ローソン中村区沖田町店", "category": "ローソン", "score": 50.0},
        ],
    }

    label = build_taxi_place_label(result)
    assert label["label"] == "沖田町・畑江通"
    assert label["supplement"] == "ケーズデンキ岩塚店近く"


def test_highway_candidate_is_penalized_below_normal_road():
    result = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中村区", "岩塚町"],
        "roadname": "",
        "candidates": [
            {"name": "名古屋高速5号万場線", "kind": "road", "score": 99.0},
            {"name": "畑江通", "kind": "road", "score": 60.0},
        ],
    }

    label = build_taxi_place_label(result)

    assert label["label"] == "畑江通付近"
    assert label["debug"]["name"] == "畑江通"


def test_short_address_omits_prefecture_and_city():
    assert normalize_short_address(["愛知県", "名古屋市中区", "錦", "３丁目", "12"]) == "中区錦3丁目"
    assert normalize_short_address(["愛知県", "名古屋市熱田区", "金山町", "１丁目"]) == "熱田区金山町1丁目"
    assert normalize_short_address(["愛知県", "名古屋市中村区", "沖田町"]) == "中村区沖田町"


def test_underground_candidate_is_not_primary_label():
    result = {
        "lat": 35.0,
        "lon": 136.0,
        "address": ["愛知県", "名古屋市中区", "錦", "３丁目"],
        "roadname": None,
        "candidates": [
            {"name": "すき家サカエチカ店", "category": "すき家", "score": 99.0},
            {"name": "錦通大津交差点", "category": "地点名", "score": 50.0},
        ],
    }

    label = build_taxi_place_label(result)["label"]
    assert label == "錦通大津交差点付近"
    assert "サカエチカ" not in label
