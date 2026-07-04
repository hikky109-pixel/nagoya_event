import json
from pathlib import Path

from tools.location.get_yahoo_placeinfo import extract_candidates
from tools.location.place_labeler import build_taxi_place_label, normalize_short_address


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
