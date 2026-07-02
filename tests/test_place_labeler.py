import json
from pathlib import Path

from tools.location.get_yahoo_placeinfo import extract_candidates
from tools.location.place_labeler import build_taxi_place_label


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
